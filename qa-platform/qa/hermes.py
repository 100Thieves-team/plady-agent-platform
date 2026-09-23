"""Hermes 호출 — UI 의 AI 는 전부 여기로. 플랫폼은 모델 키를 갖지 않는다.

- `chat()`: chat completions 한 번. 실패 진단(triage)과 초안 생성(qa/drafts.py)이 쓴다. 도구 호출은 기대하지 않는다.
- `ask_stream()`: 한 번 묻고 답을 받되, `/v1/responses` 스트리밍으로 받으며 조각·도구 호출을 콜백으로 알린다. Hermes 작업
  (qa/jobs.py — 초안 생성·TC 제안·고치기·실패 분석)이 쓴다. 그만두기·시간 한도를 이벤트마다 확인한다.
- `stream_respond()`: `/v1/responses` 한 턴을 SSE 로 받는다. 채팅 위젯(qa/chat.py)이 쓴다. 본문 델타·도구 호출·도구 결과가
  이벤트로 오고 마지막 `response.completed` 에 전체 응답이 온다. previous_response_id 로 서버가 대화를 잇는다
  (hermes-agent v2026.6.19 api_server.py `_write_sse_responses` 확인).
"""
from __future__ import annotations

import json
import secrets
import socket
import time

from . import httpx
from .config import Config

TRIAGE_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 자동 API 스크립트가 dev 서버에서 실패했다. "
    "주어진 스크립트·단계·요청·응답만 근거로 삼고, 모르는 것은 모른다고 말한다. 한국어로 답한다.\n"
    "출력 형식(그대로):\n"
    "분류: 버그 | 스크립트 노후 | 환경\n"
    "근거: 두세 문장. 어느 단계의 무엇이 기대와 어긋났는지, 응답 코드·에러 코드를 인용.\n"
    "다음 행동: 한 줄씩 최대 3개. 버그면 확인할 코드 영역, 스크립트 노후면 고칠 기대값, 환경이면 확인할 설정."
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


class Canceled(RuntimeError):
    """사람이 [그만두기] 를 눌렀다."""


def ask_stream(cfg: Config, system: str, prompt: str, *, session_prefix: str, on_event=None, cancel=None,
               deadline: float | None = None, stall: int | None = None) -> str:
    """system·prompt 한 번 → 전체 답 텍스트. on_event(kind, data): delta · tool · tool_result · keepalive.
    cancel(threading.Event)이 서면 Canceled, deadline(time.monotonic 기준)을 넘으면 RuntimeError.
    stall 초 동안 아무것도 안 오면(Hermes 는 10초마다 keepalive) 멈춘 것으로 보고 RuntimeError."""
    stall = stall or cfg.job_stall
    gen = stream_respond(cfg, prompt, instructions=system, session_key=f"{session_prefix}-{secrets.token_hex(3)}", timeout=stall)
    parts: list[str] = []
    final = None
    try:
        for kind, data in gen:
            if cancel is not None and cancel.is_set():
                raise Canceled("그만둠")
            if deadline is not None and time.monotonic() > deadline:
                raise RuntimeError(f"시간 한도({cfg.job_timeout}초)를 넘었다")
            if kind == "delta":
                parts.append(data)
            elif kind == "done":
                final = data
                break
            elif kind == "failed":
                raise RuntimeError(f"Hermes 실패: {data}")
            if on_event is not None:
                on_event(kind, data)
    except (socket.timeout, TimeoutError):
        raise RuntimeError(f"Hermes 가 {stall}초 동안 아무것도 보내지 않았다") from None
    finally:
        gen.close()
    text = ((final or {}).get("text") or "".join(parts)).strip()
    if not text:
        raise RuntimeError("Hermes 응답이 비어 있다")
    return text


class HermesNotFound(RuntimeError):
    """previous_response_id 가 서버 저장소(LRU 100건)에서 밀려났다 — 호출 쪽이 기록으로 다시 잇는다."""


def _text_of(output) -> str:
    """function_call_output.output — 비스트리밍은 문자열, 스트리밍은 [{type: input_text, text}] 목록."""
    if isinstance(output, list):
        return "".join(str(p.get("text") or "") for p in output if isinstance(p, dict))
    return "" if output is None else str(output)


def stream_respond(cfg: Config, text: str, *, instructions: str | None = None, previous_response_id: str | None = None,
                   history: list[dict] | None = None, session_key: str | None = None, timeout: int | None = None):
    """/v1/responses 한 턴을 SSE 로. 제너레이터가 (kind, data) 를 낸다:
      ("delta", str) · ("tool", {call_id, name, arguments}) · ("tool_result", {call_id, output}) · ("keepalive", None) ·
      ("done", parse_response(전체 응답)) · ("failed", 메시지)

    history 가 있으면 그것으로(서버 저장소 대신), 없으면 previous_response_id 로 잇는다. instructions 는 첫 턴에 넣으면
    서버가 체인을 따라 이어 준다; history 로 이을 때는 다시 넣어야 한다. 밀려난 previous_response_id 는 HermesNotFound."""
    if not cfg.hermes_key:
        raise RuntimeError("HERMES_API_KEY 가 없어 Hermes 를 호출할 수 없다")
    body: dict = {"model": cfg.hermes_model, "input": text, "store": True, "stream": True}
    if instructions:
        body["instructions"] = instructions
    if history:
        body["conversation_history"] = history
    elif previous_response_id:
        body["previous_response_id"] = previous_response_id
    headers = {"Authorization": "Bearer " + cfg.hermes_key, "Accept": "text/event-stream"}
    if session_key:
        headers["X-Hermes-Session-Key"] = session_key
    try:
        lines = httpx.stream("POST", f"{cfg.hermes_url}/v1/responses", headers=headers, body=body, timeout=timeout or cfg.hermes_timeout)
        yield from _parse_sse(lines)
    except httpx.HttpError as e:
        if e.status == 404 and previous_response_id and not history:
            raise HermesNotFound(f"이전 응답 {previous_response_id} 을 Hermes 가 더는 갖고 있지 않다") from None
        raise RuntimeError(f"Hermes 응답 오류: {e}") from None


def _parse_sse(lines):
    """SSE 프레임(event:/data:/빈 줄) → (kind, data). 서버 이벤트 이름은 OpenAI Responses 규격."""
    event, data = None, []
    for line in lines:
        if line.startswith(":"):
            yield "keepalive", None
            continue
        if line == "":
            if data:
                yield from _sse_frame(event, "\n".join(data))
            event, data = None, []
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield from _sse_frame(event, "\n".join(data))


def _sse_frame(event, payload: str):
    try:
        d = json.loads(payload)
    except ValueError:
        return
    if not isinstance(d, dict):
        return
    t = d.get("type") or event or ""
    if t == "response.output_text.delta":
        yield "delta", str(d.get("delta") or "")
    elif t == "response.output_item.added":
        item = d.get("item") or {}
        if item.get("type") == "function_call":
            yield "tool", {"call_id": str(item.get("call_id") or ""), "name": str(item.get("name") or ""), "arguments": item.get("arguments")}
        elif item.get("type") == "function_call_output":
            yield "tool_result", {"call_id": str(item.get("call_id") or ""), "output": _text_of(item.get("output"))}
    elif t == "response.completed":
        yield "done", parse_response(d.get("response") or {})
    elif t == "response.failed":
        err = (d.get("response") or {}).get("error") or {}
        yield "failed", str(err.get("message") if isinstance(err, dict) else err) or "Hermes 실패"


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
            c["output"] = _text_of(item.get("output"))
        elif t == "message":
            for part in item.get("content") or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text") and part.get("text"):
                    texts.append(str(part["text"]))
    return {"id": data.get("id"), "text": "\n".join(texts).strip(), "tool_calls": calls, "usage": data.get("usage") or {}}


def triage(cfg: Config, run: dict, rc: dict, steps: list[dict], ask=None) -> str:
    parts = [f"## 런\n트리거 {run['trigger']} · 대상 {run['base_url']} · sha {run.get('sha') or '-'} · PR {run.get('pr_number') or '-'}",
             f"## 스크립트 {rc['case_id']} — {rc['case_title']}\n판정 {rc['verdict']} · 오류 {rc.get('error') or '-'}",
             "## 스크립트 정의\n```yaml\n" + rc["case_yaml"] + "\n```", "## 단계 결과"]
    for s in steps:
        req = dict(s["request"]); req.pop("headers", None)
        resp = s.get("response") or {}
        body = resp.get("json") if resp.get("json") is not None else resp.get("text")
        parts.append(
            f"### {s['ord'] + 1}. {s['name']} → {s['verdict']}\n요청: {json.dumps(req, ensure_ascii=False)[:1500]}\n"
            f"응답 status={resp.get('status')} body={json.dumps(body, ensure_ascii=False)[:1500] if body is not None else '-'}\n"
            f"검증 항목(assertion): {json.dumps(s['checks'], ensure_ascii=False)[:1200]}\n오류: {s.get('error') or '-'}")
    if ask is not None:
        return ask(TRIAGE_SYSTEM, "\n\n".join(parts), "qa-triage")
    return chat(cfg, TRIAGE_SYSTEM, "\n\n".join(parts), session_prefix="qa-triage")
