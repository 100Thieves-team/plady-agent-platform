"""Hermes 호출 — UI 의 AI 는 전부 여기로. 플랫폼은 모델 키를 갖지 않는다.

실패 진단(triage)과 초안 생성(qa/drafts.py)이 `chat()` 하나를 쓴다. 도구 호출은 시키지 않는다.
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
