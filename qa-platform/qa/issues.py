"""백엔드 구현 실수를 Linear 이슈 초안으로 (docs/qa-platform-v2.md §17).

근거는 플랫폼이 모은 사실만 쓴다: 실패 단계의 요청·응답, API 문서, 규칙표(SSOT) 검사, PRD 출처.
Hermes 는 그 사실로 팀 이슈 형식의 문장을 쓰고 분류를 제안한다. 근거 칸은 플랫폼이 붙인다(Hermes 가 바꾸지 못한다).
"""
from __future__ import annotations

import json
import re

ISSUE_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 자동 API 스크립트가 dev 서버에서 실패했다. 이 실패를 백엔드 이슈로 올릴지 판단하고 초안을 쓴다. 한국어로 쓴다.\n\n"
    "규칙:\n"
    "1. 주어진 근거(요청 · 실제 응답 · API 문서 · 규칙표 · PRD 출처)만 쓴다. 근거에 없는 원인(코드 위치 · 클래스 이름)은 지어내지 않는다. 모르면 '확인 필요' 로 적는다.\n"
    "2. 분류(kind):\n"
    "   - bug: 실제 응답이 API 문서나 규칙표와 다르고, 문서와 규칙표는 서로 맞다. 백엔드가 고칠 일이다.\n"
    "   - decision: 규칙표와 API 문서(또는 백엔드가 일부러 그렇게 만든 동작)가 서로 달라 어느 쪽이 맞는지 근거가 없다. 기획과 백엔드가 정할 일이다.\n"
    "   - not_backend: 스크립트의 기대가 API 문서와 다르다(문서에 실제 응답대로 적혀 있음), 준비 상태를 못 만들었다, 환경 문제다. 이슈로 올리지 않는다.\n"
    "3. 출력은 ```json 블록 하나: {\"kind\": \"bug|decision|not_backend\", \"reason\": \"분류 이유 한두 문장\", \"title\": \"[QA] …\", \"body\": \"마크다운\"}.\n"
    "4. title 은 '[QA] ' 로 시작하고, 무엇이 어떻게 다른지 한 줄로 쓴다(예: '[QA] 이용 제한 회원이 이력서를 등록할 수 있음').\n"
    "5. body 는 다음 절을 이 순서로 쓴다: ## Context · ## Problem · ## Proposal · ## Acceptance Criteria(체크박스 '- [ ]' 두 개 이상, 확인할 수 있는 결과) · "
    "## Verification · ## Out of Scope. Context 에는 실행 id 와 스크립트 id, 어긋난 규칙표 검사 id 를 적는다. decision 이면 Proposal 에 고를 수 있는 길을 번호로 적는다.\n"
    "6. 짧은 문장으로 쓴다. 요청·응답 원문과 근거 표는 플랫폼이 이슈 끝에 붙이니 body 에 다시 옮기지 않는다.\n"
    "7. not_backend 면 title · body 는 비워도 된다. reason 에 무엇을 고쳐야 하는지 적는다."
)


def failing_step(steps: list[dict]) -> dict | None:
    """처음 실패한 단계. 실패 뒤 정리 단계는 뺀다."""
    for s in steps:
        if s.get("verdict") == "fail" and not (s.get("request") or {}).get("after_failure"):
            return s
    return None


def _code(step: dict | None) -> tuple:
    if not step:
        return (None, None)
    resp = step.get("response") or {}
    j = resp.get("json") if isinstance(resp.get("json"), dict) else {}
    return (resp.get("status"), ((j.get("error") or {}) if isinstance(j.get("error"), dict) else {}).get("code"))


def spread(rc_id: int, failing_by_rc: dict[int, dict | None]) -> int:
    """같은 실행에서 같은 응답(status · 에러 코드)으로 실패한 다른 스크립트 수. 공용 데이터·환경 문제를 거른다."""
    me = _code(failing_by_rc.get(rc_id))
    if me == (None, None):
        return 0
    return sum(1 for k, s in failing_by_rc.items() if k != rc_id and s and _code(s) == me)


def eligibility(rc: dict, step: dict | None, case, spread_n: int) -> list[str]:
    """백엔드 잘못으로 볼 수 없는 이유 목록. 비어 있으면 초안을 만든다 (§17.3)."""
    out = []
    if rc.get("verdict") != "fail":
        out.append(f"판정이 {rc.get('verdict')} 다. 기대와 다른 응답(fail)만 본다. 오류·건너뜀은 스크립트·환경부터 본다")
        return out
    if case is None:
        out.append("레포에 이 스크립트가 없다(지워지거나 id 가 바뀜)")
        return out
    audit = getattr(case, "audit", None) or {}
    if audit.get("status") == "error":
        out.append("스크립트가 지금 검사에 걸린다: " + "; ".join((audit.get("errors") or [])[:2]) + ". 스크립트부터 고친다")
    if step is None:
        out.append("실패한 단계를 찾지 못했다")
    if spread_n >= 4:
        out.append(f"같은 실행에서 같은 응답(status · 에러 코드)으로 실패한 스크립트가 {spread_n}개 더 있다. 공용 데이터·환경 문제일 수 있어 먼저 본다")
    return out


def _tc(rec: dict) -> dict:
    hint = rec.get("expect_hint") or {}
    b = rec.get("binding") or {}
    return {k: v for k, v in {
        "id": rec.get("id"), "title": rec.get("title"), "gate": rec.get("gate"), "check": hint.get("check"), "message": hint.get("message"),
        "error_code": b.get("error_code"), "operations": b.get("operations"), "source": rec.get("source"),
        "prd": [f"{p.get('doc')} {p.get('section')}" for p in (rec.get("prd") or []) if isinstance(p, dict)] or None,
    }.items() if v}


def evidence(*, run: dict, rc: dict, step: dict, case, spec, catalog, public_url: str = "") -> dict:
    """이슈에 붙일 사실. 모두 실행 기록 · API 문서 · 규칙표에서 그대로 옮긴다."""
    req = step.get("request") or {}
    resp = step.get("response") or {}
    body = resp.get("json") if resp.get("json") is not None else resp.get("text")
    st, code = _code(step)
    op = None
    if spec and req.get("method") and req.get("path") and req.get("method") != "NOTIFY":
        try:
            op = spec.op_for(str(req["method"]), str(req.get("path") or "").split("?")[0])
        except Exception:
            op = None
    expected = None
    if case is not None and 0 <= step.get("ord", -1) < len(case.steps):
        expected = case.steps[step["ord"]].get("expect")
    want_code = (expected or {}).get("error_code")
    doc = None
    if op is not None:
        codes = [c for c in (code, want_code) if c]
        doc = {"operationId": op.id, "method": op.method, "path": op.path, "summary": op.summary,
               "success_status": [k for k in op.success], "errors": {c: {k: op.errors[c].get(k) for k in ("status", "message")} for c in codes if c in op.errors},
               "params": [p for p in op.params if p.get("in") == "query" and p.get("description")]}
    tc_ids = list(dict.fromkeys((case.covers if case else []) + ((case.steps[step["ord"]].get("covers") or []) if case is not None and 0 <= step.get("ord", -1) < len(case.steps) else [])))
    recs = (catalog.records if catalog is not None else {})
    base = public_url.rstrip("/")
    return {
        "run_id": run["id"], "run_url": f"{base}/runs/{run['id']}" if base else f"/runs/{run['id']}", "trigger": run.get("trigger"),
        "target": run.get("base_url"), "case_id": rc["case_id"], "case_title": rc.get("case_title"), "variant": getattr(case, "variant", None),
        "step": {"ord": step.get("ord"), "name": step.get("name"), "actor": req.get("actor")},
        "request": {k: req.get(k) for k in ("method", "path", "url", "query", "body", "multipart") if req.get(k) not in (None, {}, [])},
        "response": {"status": st, "error_code": code, "body": body},
        "expected": expected, "failed_checks": [c for c in (step.get("checks") or []) if c.get("ok") is False],
        "doc": doc, "tc_ids": tc_ids, "rules": [_tc(recs[t]) for t in tc_ids if t in recs],
        "triage": rc.get("triage"),
    }


def prompt(ev: dict) -> str:
    j = lambda x: json.dumps(x, ensure_ascii=False, indent=1)[:3000]  # noqa: E731
    parts = [f"## 실행\n{ev['run_id']} ({ev.get('trigger')}) · 대상 {ev.get('target')}",
             f"## 스크립트\n{ev['case_id']} — {ev.get('case_title') or ''} · 케이스 {ev.get('variant') or '-'}",
             f"## 실패한 단계\n{ev['step'].get('name')} · 테스트 계정 {ev['step'].get('actor') or '-'}",
             "## 요청\n```json\n" + j(ev["request"]) + "\n```",
             "## 실제 응답\n```json\n" + j(ev["response"]) + "\n```",
             "## 스크립트가 기대한 것\n```json\n" + j(ev.get("expected")) + "\n```\n어긋난 검증 항목: " + j(ev.get("failed_checks"))]
    if ev.get("doc"):
        parts.append("## API 문서 (OpenAPI, dev)\n```json\n" + j(ev["doc"]) + "\n```")
    else:
        parts.append("## API 문서\n이 요청은 API 문서에서 찾지 못했다.")
    if ev.get("rules"):
        parts.append("## 규칙표 (상태 SSOT 검사 · PRD 출처)\n```json\n" + j(ev["rules"]) + "\n```")
    if ev.get("triage"):
        parts.append("## 앞서 한 실패 분석 (참고)\n" + str(ev["triage"])[:1500])
    parts.append("## 출력\n규칙 3 의 ```json 블록 하나.")
    return "\n\n".join(parts)


def parse(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)
    raw = m.group(1) if m else (text or "")
    if not m:
        a, b = raw.find("{"), raw.rfind("}")
        raw = raw[a:b + 1] if a >= 0 and b > a else raw
    try:
        d = json.loads(raw)
    except ValueError:
        raise ValueError("Hermes 출력에서 JSON 을 찾지 못했다")
    kind = str(d.get("kind") or "").strip()
    if kind not in ("bug", "decision", "not_backend"):
        raise ValueError(f"분류가 bug · decision · not_backend 가 아니다: {kind!r}")
    title = str(d.get("title") or "").strip()
    if kind != "not_backend":
        if not title:
            raise ValueError("제목이 비었다")
        if not title.startswith("[QA]"):
            title = "[QA] " + title
        if "## Acceptance Criteria" not in str(d.get("body") or ""):
            raise ValueError("본문에 Acceptance Criteria 절이 없다")
    return {"kind": kind, "reason": str(d.get("reason") or "").strip(), "title": title, "body": str(d.get("body") or "").strip()}


def full_body(body: str, ev: dict, operator: str) -> str:
    """Hermes 본문 + 플랫폼이 모은 근거 + 누가 만들었는지. 근거는 실행 기록 그대로다."""
    j = lambda x: json.dumps(x, ensure_ascii=False, indent=1)[:2500]  # noqa: E731
    out = [body.strip(), "", "## QA 근거 (플랫폼이 실행 기록 · API 문서 · 규칙표에서 옮김)", "",
           f"* 실행: [{ev['run_id']}]({ev['run_url']}) · 스크립트 `{ev['case_id']}` · 단계 {ev['step'].get('name')}",
           f"* 요청: `{(ev['request'].get('method') or '')} {ev['request'].get('path') or ''}` · 테스트 계정 {ev['step'].get('actor') or '-'}",
           f"* 실제 응답: {ev['response'].get('status')} {ev['response'].get('error_code') or ''}".rstrip()]
    if ev.get("tc_ids"):
        out.append("* 테스트 조건: " + ", ".join(f"`{t}`" for t in ev["tc_ids"]))
    out += ["", "<details><summary>요청 · 응답 · 기대 원문</summary>", "", "```json",
            j({"request": ev["request"], "response": ev["response"], "expected": ev.get("expected")}), "```", "", "</details>"]
    if ev.get("rules"):
        out += ["", "<details><summary>규칙표 검사</summary>", "", "```json", j(ev["rules"]), "```", "", "</details>"]
    out += ["", f"_QA 플랫폼에서 {operator} 가 만들었다._"]
    return "\n".join(out)
