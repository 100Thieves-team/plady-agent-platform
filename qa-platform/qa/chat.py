"""Hermes 채팅 — 어느 화면에서나 뜨는 위젯(채널톡처럼)과 Hermes 사이. docs/qa-platform-hermes.md §3.2.

플랫폼이 하는 일은 셋뿐이다. (1) 첫 턴에 시스템 프롬프트와 첨부(실행·스크립트·테스트 조건 요약)를 붙인다, (2) Hermes `/v1/responses` 를
SSE 로 한 번 부르며 델타·도구 호출·도구 결과를 그대로 브라우저로 흘린다(previous_response_id 로 서버가 대화를 잇고, 밀려났으면
여기 기록으로 다시 잇는다), (3) 끝나면 응답 본문·도구 호출·그 턴에 저장한 변경 id(d-…)를 기록하고 감사 로그에 남긴다.
실행·발행은 도구에 없으므로 채팅으로는 일어나지 않는다. 스크립트·수동 작성 테스트 조건 저장은 검증을 통과하면 바로 된다.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from . import hermes
from .config import Config

DRAFT_ID = re.compile(r"\bd-[0-9a-f]{8}\b")
DRAFT_TOOLS = ("qa_case_save", "qa_manual_tc_save", "qa_draft_create", "qa_draft_update", "qa_manual_tc_propose")   # 뒤 셋은 예전 대화 기록을 읽으려고
Emit = Callable[[str, object], None]

SYSTEM = (
    "너는 이 팀(Spring 백엔드, dev 환경)의 QA 엔지니어다. QA 플랫폼 도구(qa_*)로 테스트 조건·스크립트·실행 기록·커버리지·OpenAPI·PRD 를 읽고 한국어로 답한다.\n"
    "규칙:\n"
    "1. 테스트 조건은 SSOT·PRD·OpenAPI 에서 파생된 것이고 네가 만들거나 고치지 않는다. 테스트 조건을 바꾸려면 위키를 고쳐야 한다고 안내한다.\n"
    "2. 스크립트를 쓰거나 고칠 때는 qa_case_save 로 저장한다(고칠 때는 update=true). 검증을 통과하면 main 에 바로 들어가니, 사람이 부탁한 것만 저장한다. "
    "검증 사유가 돌아오면 고쳐서 다시 부르고, 세 번 넘게 실패하면 사람에게 넘긴다. covers 는 qa_catalog_search 로 확인한 실재 테스트 조건 id 만 쓴다.\n"
    "3. 실행·API 직접 호출·위키 보고서 게시는 사람이 화면 버튼으로 한다 — 요청받으면 어디서 누르는지 링크({public_url})로 안내한다.\n"
    "4. 답은 도구로 읽은 사실에 근거하고, 모르는 것은 모른다고 한다. 회원 UUID 같은 식별값은 답에 옮기지 않는다.\n"
    "5. 이 QA 대화에서는 위키를 쓰지 않는다(wiki_apply 금지). 위키 읽기 도구는 PRD·SSOT 확인에만 쓴다.\n"
    "6. 저장했으면 스크립트 id 와 링크를 답에 적는다. 답은 짧게, 마크다운 없이 평문으로."
)


def system_prompt(cfg: Config) -> str:
    return SYSTEM.replace("{public_url}", cfg.public_url)


# ---------------------------------------------------------------------------------------------
# 첨부 (컨텍스트) — 첫 메시지 앞에 붙는 요약. 나머지는 Hermes 가 도구로 읽는다.
# ---------------------------------------------------------------------------------------------
def context_block(app, ctx: dict) -> tuple[str, str | None]:
    """(첨부 텍스트, 제목 후보). ctx = {"run": id} | {"case": id} | {"tc": id} | {"op": operationId} | {}."""
    if ctx.get("op"):
        d = app.api_detail(ctx["op"])
        if not d:
            return "", None
        o = d["op"]
        qa = d["qa"]
        text = (f"[첨부: API {o['method']} {o['path']} ({o['id']})] {o['summary']} · 테스트 조건 {qa['tc']}건(자동화 {qa['covered']}, 제외 {qa['excluded']}) "
                f"· 부르는 스크립트 {len(d['scripts'])}건 · 최근 호출 {len(d['recent_calls'])}건"
                + (f" · 마지막 {d['recent_calls'][0]['verdict']} {d['recent_calls'][0]['created_at']}" if d["recent_calls"] else "")
                + f"\n스펙·테스트 조건·최근 호출은 qa_api_get(operationId=\"{o['id']}\") 로 읽어라.")
        return text, f"API {o['id']}"
    if ctx.get("run"):
        run = app.store.get_run(ctx["run"])
        if not run:
            return "", None
        rcs = app.store.list_run_cases(run["id"])
        bad = [f"{rc['case_id']}({rc['verdict']}{(': ' + rc['error'][:80]) if rc.get('error') else ''})" for rc in rcs if rc["verdict"] in ("fail", "error")]
        text = (f"[첨부: 테스트 실행 {run['id']}] 트리거 {run['trigger']} · 판정 {run.get('verdict') or run['status']} · 통과 {run['passed']} 실패 {run['failed']} "
                f"오류 {run['errored']} skip {run['skipped']} · sha {run.get('sha') or '-'}" + (f"\n실패한 스크립트: {', '.join(bad[:8])}" if bad else "")
                + f"\n자세한 요청·응답은 qa_run_get(id=\"{run['id']}\", with_steps=true) 로 읽어라.")
        return text, f"실행 {run['id']}"
    if ctx.get("case"):
        c = app.cases.get(ctx["case"])
        if not c:
            return "", None
        drift = app.drift_of(c)
        text = (f"[첨부: 스크립트 {c.id}] {c.title} · suite {c.suite} · 검증하는 테스트 조건 {len(c.covers)}건 · 테스트 조건 정합성 검사 {c.audit.get('status')}"
                + (f" · 바뀐 테스트 조건 {len(drift)}건: {', '.join(d['id'] for d in drift[:6])}" if drift else "")
                + f"\nYAML 은 qa_case_get(id=\"{c.id}\") 로 읽어라.")
        return text, f"스크립트 {c.id}"
    if ctx.get("tc"):
        cat = app.current_catalog()
        r = cat.records.get(ctx["tc"]) if cat else None
        if not r:
            return "", None
        cov = app.coverage(cat)["by_tc"].get(r["id"], [])
        text = (f"[첨부: 테스트 조건 {r['id']}] {r.get('title') or ''} · {r['layer']} · {r['domain']}"
                + (f" · 제외: {r['excluded']}" if r.get("excluded") else "") + f" · 검증하는 스크립트 {len(cov)}건"
                + f"\n레코드·PRD 절은 qa_tc_get(id=\"{r['id']}\") 로 읽어라.")
        return text, f"테스트 조건 {r['id']}"
    return "", None


# ---------------------------------------------------------------------------------------------
# 한 턴
# ---------------------------------------------------------------------------------------------
def draft_ids_from(tool_calls: list[dict]) -> list[str]:
    out: list[str] = []
    for c in tool_calls:
        name = str(c.get("name") or "")
        if not any(name.endswith(t) for t in DRAFT_TOOLS):
            continue
        for m in DRAFT_ID.findall(str(c.get("output") or "")):
            if m not in out:
                out.append(m)
    return out


def _history(messages: list[dict]) -> list[dict]:
    """서버 저장소가 밀렸을 때 보낼 기록 — 사람·Hermes 본문만(도구 호출은 뺀다). 실패한 턴은 뺀다."""
    return [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] in ("user", "assistant") and not m.get("error") and m["content"]]


def _run(cfg: Config, sent: str, chat: dict, prior: list[dict], first: bool, emit: Emit) -> dict:
    """스트림을 끝까지 소비하며 emit 으로 흘리고, 모은 결과를 돌려준다. 404 면 기록으로 한 번 다시 잇는다."""
    def consume(gen) -> dict:
        text_parts: list[str] = []
        calls: list[dict] = []
        by_id: dict[str, dict] = {}
        final: dict | None = None
        failed: str | None = None
        for kind, data in gen:
            if kind == "delta":
                text_parts.append(data)
                emit("delta", {"text": data})
            elif kind == "tool":
                c = dict(data, output=None)
                calls.append(c)
                if c["call_id"]:
                    by_id[c["call_id"]] = c
                emit("tool", {"name": c["name"], "arguments": c.get("arguments"), "call_id": c["call_id"]})
            elif kind == "tool_result":
                c = by_id.get(data["call_id"])
                if c is None:
                    c = {"call_id": data["call_id"], "name": "?", "arguments": None, "output": None}
                    calls.append(c)
                c["output"] = data["output"]
                emit("tool_result", {"call_id": data["call_id"], "output": (data["output"] or "")[:2500]})
            elif kind == "keepalive":
                emit("keepalive", None)
            elif kind == "done":
                final = data
            elif kind == "failed":
                failed = data
        if failed:
            raise RuntimeError(failed)
        if final is None:
            raise RuntimeError("Hermes 스트림이 response.completed 없이 끝났다")
        # 도구 호출 목록은 스트림에서 모은 것을 우선(결과 본문이 안 잘려 있다). 본문은 델타를 모은 것, 없으면 최종 응답의 것
        text = "".join(text_parts).strip() or final.get("text") or ""
        return {"id": final.get("id"), "text": text, "tool_calls": calls or final.get("tool_calls") or [], "usage": final.get("usage") or {}}

    instructions = system_prompt(cfg) if first or not chat.get("last_response_id") else None
    try:
        return consume(hermes.stream_respond(cfg, sent, instructions=instructions, previous_response_id=chat.get("last_response_id"),
                                             session_key=chat["session_key"], timeout=cfg.chat_timeout))
    except hermes.HermesNotFound:
        # 서버 저장소(LRU)에서 밀려남 — 우리 기록으로 다시 잇는다. 이때는 시스템 프롬프트도 다시 넣는다
        return consume(hermes.stream_respond(cfg, sent, instructions=system_prompt(cfg), history=_history(prior),
                                             session_key=chat["session_key"], timeout=cfg.chat_timeout))


def send(app, chat: dict, text: str, *, operator: str, session_hash: str | None, ip: str | None, emit: Emit | None = None) -> dict:
    """사람 메시지 하나를 보내고 Hermes 응답을 기록한다. emit 이 있으면 진행 이벤트를 흘린다. 반환: 저장된 assistant 메시지."""
    cfg: Config = app.cfg
    store = app.store
    emit = emit or (lambda kind, data: None)
    prior = store.list_chat_messages(chat["id"])
    first = not any(m["role"] == "user" for m in prior)
    user_text = text.strip()
    attach, _ = context_block(app, chat.get("context") or {}) if first else ("", None)
    sent = (attach + "\n\n" + user_text) if attach else user_text
    umid = store.add_chat_message(chat["id"], role="user", content=user_text)
    emit("user", {"id": umid, "content": user_text})
    t0 = time.monotonic()
    err: str | None = None
    res: dict = {"id": None, "text": "", "tool_calls": [], "usage": {}}
    try:
        res = _run(cfg, sent, chat, prior, first, emit)
    except Exception as ex:
        err = str(ex)[:500]
    ms = int((time.monotonic() - t0) * 1000)
    drafts = [d for d in draft_ids_from(res["tool_calls"]) if store.get_draft(d)]
    content = res["text"] if not err else f"Hermes 호출 실패: {err}"
    mid = store.add_chat_message(chat["id"], role="assistant", content=content, tool_calls=res["tool_calls"], draft_ids=drafts, ms=ms, error=err)
    fields = {"turns": chat["turns"] + 1, "drafts": chat["drafts"] + len(drafts)}
    if res.get("id"):
        fields["last_response_id"] = res["id"]
    if not chat.get("title"):
        fields["title"] = (user_text[:60] + ("…" if len(user_text) > 60 else "")) or None
    store.update_chat(chat["id"], **fields)
    store.add_event(operator=operator, action="chat.send", target=chat["id"], session_hash=session_hash, ip=ip,
                    detail={"chars": len(user_text), "reply_chars": len(res["text"]), "tools": [c["name"] for c in res["tool_calls"]][:20],
                            "drafts": drafts, "ms": ms, "usage": res.get("usage") or {}, "attached": bool(attach), **({"error": err} if err else {})})
    reply = {"id": mid, "content": content, "tool_calls": res["tool_calls"], "draft_ids": drafts, "ms": ms, "error": err,
             "turns": fields["turns"], "title": fields.get("title") or chat.get("title")}
    emit("done", reply)
    return reply
