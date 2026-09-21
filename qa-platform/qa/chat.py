"""Hermes 채팅창 — 사람이 Hermes 와 QA 를 이야기한다. docs/qa-platform-hermes.md §3.2.

플랫폼이 하는 일은 셋뿐이다. (1) 첫 턴에 시스템 프롬프트와 첨부(런·케이스·TC 요약)를 붙인다, (2) Hermes `/v1/responses` 를
동기로 한 번 부른다(previous_response_id 로 서버가 대화를 잇고, 밀려났으면 여기 기록으로 다시 잇는다), (3) 응답 본문·도구 호출
트레이스·그 턴에 생긴 초안 id 를 저장하고 감사 로그에 남긴다. 실행·발행·승인은 도구에 없으므로 채팅으로는 일어나지 않는다.
"""
from __future__ import annotations

import re
import time

from . import hermes
from .config import Config

DRAFT_ID = re.compile(r"\bd-[0-9a-f]{8}\b")
DRAFT_TOOLS = ("qa_draft_create", "qa_draft_update", "qa_manual_tc_propose")

SYSTEM = (
    "너는 이 팀(Spring 백엔드, dev 환경)의 QA 엔지니어다. QA 플랫폼 도구(qa_*)로 기준(TC)·케이스·런·커버리지·OpenAPI·PRD 를 읽고 한국어로 답한다.\n"
    "규칙:\n"
    "1. 기준(TC)은 SSOT·PRD·OpenAPI 에서 파생된 것이고 네가 만들거나 고치지 않는다. 기준을 바꾸려면 위키를 고쳐야 한다고 안내한다.\n"
    "2. 케이스를 쓰거나 고칠 때는 qa_draft_create / qa_draft_update 로 케이스 초안을 내고, 검증 사유가 돌아오면 고쳐서 다시 낸다. "
    "세 번 넘게 실패하면 사람에게 넘긴다. covers 는 qa_catalog_search 로 확인한 실재 TC id 만 쓴다.\n"
    "3. 실행·탐색기 전송·위키 발행·초안 승인은 사람이 화면 버튼으로 한다 — 요청받으면 어디서 누르는지 링크({public_url})로 안내한다.\n"
    "4. 답은 도구로 읽은 사실에 근거하고, 모르는 것은 모른다고 한다. 회원 UUID 같은 식별값은 답에 옮기지 않는다.\n"
    "5. 이 QA 대화에서는 위키를 쓰지 않는다(wiki_apply 금지). 위키 읽기 도구는 PRD·SSOT 확인에만 쓴다.\n"
    "6. 초안을 만들었으면 초안 id(d-…)와 링크를 답에 적는다."
)


def system_prompt(cfg: Config) -> str:
    return SYSTEM.replace("{public_url}", cfg.public_url)


# ---------------------------------------------------------------------------------------------
# 첨부 (컨텍스트) — 첫 메시지 앞에 붙는 요약. 나머지는 Hermes 가 도구로 읽는다.
# ---------------------------------------------------------------------------------------------
def context_block(app, ctx: dict) -> tuple[str, str | None]:
    """(첨부 텍스트, 제목 후보). ctx = {"run": id} | {"case": id} | {"tc": id} | {}."""
    if ctx.get("run"):
        run = app.store.get_run(ctx["run"])
        if not run:
            return "", None
        rcs = app.store.list_run_cases(run["id"])
        bad = [f"{rc['case_id']}({rc['verdict']}{(': ' + rc['error'][:80]) if rc.get('error') else ''})" for rc in rcs if rc["verdict"] in ("fail", "error")]
        text = (f"[첨부: 런 {run['id']}] 트리거 {run['trigger']} · 판정 {run.get('verdict') or run['status']} · 통과 {run['passed']} 실패 {run['failed']} "
                f"오류 {run['errored']} skip {run['skipped']} · sha {run.get('sha') or '-'}" + (f"\n실패한 케이스: {', '.join(bad[:8])}" if bad else "")
                + f"\n자세한 요청·응답은 qa_run_get(id=\"{run['id']}\", with_steps=true) 로 읽어라.")
        return text, f"런 {run['id']}"
    if ctx.get("case"):
        c = app.cases.get(ctx["case"])
        if not c:
            return "", None
        drift = app.drift_of(c)
        text = (f"[첨부: 케이스 {c.id}] {c.title} · suite {c.suite} · 덮는 TC {len(c.covers)}건 · 카탈로그 대조 {c.audit.get('status')}"
                + (f" · 근거가 바뀐 TC {len(drift)}건: {', '.join(d['id'] for d in drift[:6])}" if drift else "")
                + f"\nYAML 은 qa_case_get(id=\"{c.id}\") 로 읽어라.")
        return text, f"케이스 {c.id}"
    if ctx.get("tc"):
        cat = app.current_catalog()
        r = cat.records.get(ctx["tc"]) if cat else None
        if not r:
            return "", None
        cov = app.coverage(cat)["by_tc"].get(r["id"], [])
        text = (f"[첨부: TC {r['id']}] {r.get('title') or ''} · {r['layer']} · {r['domain']}"
                + (f" · 제외: {r['excluded']}" if r.get("excluded") else "") + f" · 덮는 케이스 {len(cov)}건"
                + f"\n레코드·PRD 절은 qa_tc_get(id=\"{r['id']}\") 로 읽어라.")
        return text, f"TC {r['id']}"
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


def send(app, chat: dict, text: str, *, operator: str, session_hash: str | None, ip: str | None) -> dict:
    """사람 메시지 하나를 보내고 Hermes 응답을 기록한다. 반환: 저장된 assistant 메시지(dict)."""
    cfg: Config = app.cfg
    store = app.store
    prior = store.list_chat_messages(chat["id"])
    first = not any(m["role"] == "user" for m in prior)
    user_text = text.strip()
    attach, _ = context_block(app, chat.get("context") or {}) if first else ("", None)
    sent = (attach + "\n\n" + user_text) if attach else user_text
    store.add_chat_message(chat["id"], role="user", content=user_text)
    t0 = time.monotonic()
    instructions = system_prompt(cfg) if first or not chat.get("last_response_id") else None
    err: str | None = None
    res: dict = {"id": None, "text": "", "tool_calls": [], "usage": {}}
    try:
        try:
            res = hermes.respond(cfg, sent, instructions=instructions, previous_response_id=chat.get("last_response_id"),
                                 session_key=chat["session_key"], timeout=cfg.chat_timeout)
        except hermes.HermesNotFound:
            # 서버 저장소(LRU)에서 밀려남 — 우리 기록으로 다시 잇는다. 이때는 시스템 프롬프트도 다시 넣는다
            res = hermes.respond(cfg, sent, instructions=system_prompt(cfg), history=_history(prior), session_key=chat["session_key"], timeout=cfg.chat_timeout)
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
    return {"id": mid, "content": content, "tool_calls": res["tool_calls"], "draft_ids": drafts, "ms": ms, "error": err}
