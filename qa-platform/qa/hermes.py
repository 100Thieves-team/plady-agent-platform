"""Hermes 호출 — UI 의 AI 는 전부 여기로. 플랫폼은 모델 키를 갖지 않는다.

- `chat()`: chat completions 한 번. 실패 진단(triage)과 초안 생성(qa/drafts.py)이 쓴다. 도구 호출은 기대하지 않는다.
- `respond()`: `/v1/responses` 한 턴. 채팅창(qa/chat.py)이 쓴다. 응답 output 에 도구 호출 트레이스(function_call ·
  function_call_output)가 그대로 오고, previous_response_id 로 서버가 대화를 잇는다 (hermes-agent v2026.6.19 api_server.py 확인).
"""
from __future__ import annotations

import json
import secrets

from . import httpx
from .config import Config

TRIAGE_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 자동 API 케이스가 dev 서버에서 실패했다. "
    "주어진 케이스·단계·요청·응답만 근거로 삼고, 모르는 것은 모른다고 말한다. 한국어로 답한다.\n"
    "출력 형식(그대로):\n"
    "분류: 버그 | 케이스 노후 | 환경\n"
    "근거: 두세 문장. 어느 단계의 무엇이 기대와 어긋났는지, 응답 코드·에러 코드를 인용.\n"
    "다음 행동: 한 줄씩 최대 3개. 버그면 확인할 코드 영역, 케이스 노후면 고칠 기대값, 환경이면 확인할 설정."
)


def chat(cfg: Config, system: str, user: str, *, session_prefix: str, timeout: int | None = None) -> str:
    """chat completions 한 번. 응답 본문 텍스트를 돌려준다. 실패는 RuntimeError."""
    if not cfg.hermes_key:
        raise RuntimeError("HERMES_API_KEY 가 없어 Hermes 를 호출할 수 없다")
    r = httpx.request(
        "POST", f"{cfg.hermes_url}/v1/chat/completions",
        headers={"Authorization": "Bearer " + cfg.hermes_key, "X-Hermes-Session-Key": f"{session_prefix}-{secrets.token_hex(3)}"},
        body={"model": cfg.hermes_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "stream": False},
        timeout=timeout or cfg.hermes_timeout,
    )
    if r.status != 200 or not r.json:
        raise RuntimeError(f"Hermes 응답 오류: status={r.status} {r.error or (r.text or '')[:300]}")
    try:
        return str(r.json["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Hermes 응답에 message.content 가 없다") from None


class HermesNotFound(RuntimeError):
    """previous_response_id 가 서버 저장소(LRU 100건)에서 밀려났다 — 호출 쪽이 기록으로 다시 잇는다."""


def respond(cfg: Config, text: str, *, instructions: str | None = None, previous_response_id: str | None = None,
            history: list[dict] | None = None, session_key: str | None = None, timeout: int | None = None) -> dict:
    """/v1/responses 한 턴. 반환 {id, text, tool_calls: [{call_id, name, arguments, output}], usage}.

    history 가 있으면 그것으로(서버 저장소 대신), 없으면 previous_response_id 로 잇는다. 둘 다 없으면 새 대화.
    instructions 는 첫 턴에 넣으면 서버가 previous_response_id 체인을 따라 이어 준다; history 로 이을 때는 다시 넣어야 한다."""
    if not cfg.hermes_key:
        raise RuntimeError("HERMES_API_KEY 가 없어 Hermes 를 호출할 수 없다")
    body: dict = {"model": cfg.hermes_model, "input": text, "store": True, "stream": False}
    if instructions:
        body["instructions"] = instructions
    if history:
        body["conversation_history"] = history
    elif previous_response_id:
        body["previous_response_id"] = previous_response_id
    headers = {"Authorization": "Bearer " + cfg.hermes_key}
    if session_key:
        headers["X-Hermes-Session-Key"] = session_key
    r = httpx.request("POST", f"{cfg.hermes_url}/v1/responses", headers=headers, body=body, timeout=timeout or cfg.hermes_timeout)
    if r.status == 404 and previous_response_id and not history:
        raise HermesNotFound(f"이전 응답 {previous_response_id} 을 Hermes 가 더는 갖고 있지 않다")
    if r.status != 200 or not isinstance(r.json, dict):
        raise RuntimeError(f"Hermes 응답 오류: status={r.status} {r.error or (r.text or '')[:300]}")
    return parse_response(r.json)


def parse_response(data: dict) -> dict:
    """Responses API output → 본문 텍스트 + 도구 호출(호출과 결과를 call_id 로 짝지음)."""
    calls: list[dict] = []
    by_id: dict[str, dict] = {}
    texts: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "function_call":
            c = {"call_id": str(item.get("call_id") or ""), "name": str(item.get("name") or ""), "arguments": item.get("arguments"), "output": None}
            calls.append(c)
            if c["call_id"]:
                by_id[c["call_id"]] = c
        elif t == "function_call_output":
            c = by_id.get(str(item.get("call_id") or ""))
            if c is None:
                c = {"call_id": str(item.get("call_id") or ""), "name": "?", "arguments": None, "output": None}
                calls.append(c)
            c["output"] = item.get("output")
        elif t == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text") and part.get("text"):
                    texts.append(str(part["text"]))
    return {"id": data.get("id"), "text": "\n".join(texts).strip(), "tool_calls": calls, "usage": data.get("usage") or {}}


def triage(cfg: Config, run: dict, rc: dict, steps: list[dict]) -> str:
    parts = [f"## 런\n트리거 {run['trigger']} · 대상 {run['base_url']} · sha {run.get('sha') or '-'} · PR {run.get('pr_number') or '-'}",
             f"## 케이스 {rc['case_id']} — {rc['case_title']}\n판정 {rc['verdict']} · 오류 {rc.get('error') or '-'}",
             "## 케이스 정의\n```yaml\n" + rc["case_yaml"] + "\n```", "## 단계 결과"]
    for s in steps:
        req = dict(s["request"]); req.pop("headers", None)
        resp = s.get("response") or {}
        body = resp.get("json") if resp.get("json") is not None else resp.get("text")
        parts.append(
            f"### {s['ord'] + 1}. {s['name']} → {s['verdict']}\n요청: {json.dumps(req, ensure_ascii=False)[:1500]}\n"
            f"응답 status={resp.get('status')} body={json.dumps(body, ensure_ascii=False)[:1500] if body is not None else '-'}\n"
            f"단언: {json.dumps(s['checks'], ensure_ascii=False)[:1200]}\n오류: {s.get('error') or '-'}")
    return chat(cfg, TRIAGE_SYSTEM, "\n\n".join(parts), session_prefix="qa-triage")
