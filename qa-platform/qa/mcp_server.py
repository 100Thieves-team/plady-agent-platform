"""QA MCP 서버 — Hermes 가 부르는 QA 도구. docs/qa-platform-hermes.md §3.1.

streamable HTTP 의 서버 쪽 최소 구현: JSON-RPC 2.0 over POST, 상태 없음(세션 id 없음), 표준 라이브러리만.
메서드는 initialize · ping · tools/list · tools/call 네 개. 알림(id 없음)은 202 로 받고 버린다.

도구는 읽기 + 저장 2. **실행·전송·발행 도구는 없다** — 사용자 결정 ①(실행은 사람 버튼)을 도구 목록 자체로 막는다.
저장 도구(qa_case_save · qa_manual_tc_save)는 폼과 같은 결정론 검증을 통과한 것만 main 에 바로 커밋한다
(초안·승인 없음, docs/qa-platform-scenarios.md §9). 저장한 항목에는 written_by: hermes 가 붙는다. 삭제 도구는 없다.

인증: `Authorization: Bearer QA_MCP_TOKEN` (내부 네트워크 전용. Caddy @qa 는 /mcp 를 403 으로 막는다).
모든 tools/call 은 events `mcp.call` 로 남는다 (operator "hermes" — 사람이 아니라 에이전트가 부른 것임을 그대로 적는다).
"""
from __future__ import annotations

import hmac
import json
import sys
import time
import traceback

import yaml

from . import drafts as draftsmod
from .cases import _TC
from .mcp import mask_ids
from .store import now_iso

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
AGENT = "hermes"          # 도구를 부르는 쪽. 감사 로그 operator 열에 그대로 남긴다
MAX_LIMIT = 200

INSTRUCTIONS = (
    "plady QA 플랫폼의 도구다. 테스트 케이스(TC)는 SSOT·PRD·OpenAPI 에서 파생된 것이라 여기서 만들거나 고칠 수 없다. "
    "스크립트를 새로 쓰거나 고칠 때는 qa_case_save 로 저장한다. 검증을 통과하면 main 에 바로 들어가고, 사유가 돌아오면 고쳐서 다시 부른다. "
    "실행·전송·발행은 사람이 화면 버튼으로 한다 — 요청받으면 어디서 누르는지 링크로 안내한다. "
    "회원 UUID 같은 식별값은 답에 옮기지 않는다."
)


class ToolError(Exception):
    """도구가 사용자(Hermes)에게 돌려주는 실패. isError=true 로 나가고, 사유를 그대로 읽게 한다."""


def _s(obj, limit: int = 3000) -> str:
    """JSON 문자열(한글 유지). 길면 자른다 — Hermes 컨텍스트를 아끼려고."""
    text = json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + f"…(+{len(text) - limit})"


def _slim_record(r: dict) -> dict:
    out = {k: r.get(k) for k in ("id", "layer", "kind", "domain", "title", "gate", "command", "actor", "binding", "source", "prd", "excluded")
           if r.get(k) not in (None, [], {}, "")}
    hint = r.get("expect_hint")
    if isinstance(hint, dict):
        out["expect_hint"] = {k: v for k, v in hint.items() if k != "example"}
    elif hint:
        out["expect_hint"] = hint
    return out


def _arg_summary(args: dict) -> dict:
    """감사 로그용 인자 요약 — 긴 문자열(YAML 등)은 길이만, 목록은 개수만."""
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str):
            out[k] = v if len(v) <= 80 else f"<{len(v)} chars>"
        elif isinstance(v, list):
            out[k] = f"<{len(v)} items>"
        elif isinstance(v, dict):
            out[k] = f"<{len(v)} keys>"
        else:
            out[k] = v
    return out


def _schema(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


_STR = {"type": "string"}
_INT = {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT}

TOOLS: list[dict] = [
    {"name": "qa_catalog_search", "description": "테스트 케이스(TC) 목록 검색. 비즈니스 규칙(policy: SSOT 에서 파생)·API 계약(contract: OpenAPI)·수동 작성(manual) 세 층. "
     "only=uncovered 면 아직 어떤 스크립트도 덮지 않는 TC 만. 결과의 covered_by 가 그 TC 를 검증하는 스크립트와 마지막 결과.",
     "inputSchema": _schema({"domain": _STR, "layer": {"type": "string", "enum": ["policy", "contract", "manual"]},
                             "only": {"type": "string", "enum": ["uncovered", "covered", "excluded", "warn"]},
                             "q": {"type": "string", "description": "id·제목·API 매핑에 대한 부분 문자열"}, "limit": _INT})},
    {"name": "qa_tc_get", "description": "TC 하나의 레코드 전문 + 근거 PRD 절 본문 + 검증하는 스크립트 + 최근 변경 여부.",
     "inputSchema": _schema({"id": {"type": "string", "description": "예: G.room.create#duplicate-slot-left, op.createRoom:E1402, PRD.룸-탐색.4.1#1"}}, ["id"])},
    {"name": "qa_coverage", "description": "도메인×층 커버리지 매트릭스, 제외 수, TC 소스 버전(SSOT·OpenAPI 해시), 스펙 불일치 경고.", "inputSchema": _schema({})},
    {"name": "qa_changes", "description": "최근 바뀐(추가·변경·삭제된) TC 와 영향받는 스크립트. since 는 ISO 시각(그 이후만).",
     "inputSchema": _schema({"since": _STR, "limit": _INT})},
    {"name": "qa_case_list", "description": "스크립트(원본 YAML, git) 목록: suite·검증하는 TC 수·TC 정합성 검사 상태·마지막 결과·TC 변경 수.",
     "inputSchema": _schema({"domain": _STR, "suite": {"type": "string", "enum": ["smoke", "sanity", "manual"]}})},
    {"name": "qa_case_get", "description": "스크립트 하나: YAML 전문, covers, TC 정합성 검사 결과, TC 변경(드리프트), 최근 실행 이력.",
     "inputSchema": _schema({"id": _STR}, ["id"])},
    {"name": "qa_run_list", "description": "테스트 실행 목록(최신순). trigger: deploy-sanity | sprint-smoke | release | manual | draft-check | explorer.",
     "inputSchema": _schema({"trigger": _STR, "limit": _INT})},
    {"name": "qa_run_get", "description": "실행 상세: 스크립트별 판정·오류·진단. with_steps=true 면 단계마다 요청·응답·검증 항목(assertion)까지(마스킹된 그대로, 응답은 절단).",
     "inputSchema": _schema({"id": _STR, "with_steps": {"type": "boolean"}}, ["id"])},
    {"name": "qa_spec_op", "description": "OpenAPI(dev 브랜치 계약) 발췌: method·path·파라미터·요청 예시·성공 응답·문서화된 에러 코드.",
     "inputSchema": _schema({"operationId": _STR}, ["operationId"])},
    {"name": "qa_api_get", "description": "API 하나를 축으로 모아 보기: OpenAPI 발췌(파라미터·요청 예시·응답·에러 코드) + 그 API 에 걸린 TC(층별, 자동화 여부, 검증하는 스크립트) "
                                          "+ 그 API 를 부르는 스크립트(단계 이름) + 최근 호출 20건(실행 기록·판정·status·소요). \"이 API 지난번에 어땠나\" 에 답할 때.",
     "inputSchema": _schema({"operationId": _STR}, ["operationId"])},
    {"name": "qa_prd_section", "description": "PRD 절 본문(위키 체크아웃에서). doc 은 문서 이름(예: 룸 생성), section 은 절 번호(예: 4.7).",
     "inputSchema": _schema({"doc": _STR, "section": _STR}, ["doc", "section"])},
    {"name": "qa_case_save", "description": "스크립트 YAML 을 결정론 검증(형식·covers 가 TC 목록에 실재·method/path/코드 일치·테스트 계정·픽스처)에 넣고, "
     "통과하면 main 에 바로 저장한다(Hermes 작성 표시가 붙는다). 실패하면 사유를 돌려준다 — 고쳐서 다시 부른다. "
     "기존 스크립트를 고치려면 update=true 로 같은 id 를 낸다(qa_case_get 으로 읽은 YAML 을 고쳐서). update=false 인데 id 가 겹치면 -2 처럼 새 id 로 만든다. "
     "YAML 은 스크립트 맵 하나 또는 `cases:` 목록(최대 5). 실행은 하지 않는다 — 사람이 화면에서 누른다.",
     "inputSchema": _schema({"yaml": _STR, "update": {"type": "boolean", "description": "true 면 같은 id 의 기존 스크립트를 이 YAML 로 바꾼다"},
                             "reason": {"type": "string", "description": "왜 이 스크립트인지 한 줄 (커밋 메시지와 변경 기록에 남는다)"}}, ["yaml"])},
    {"name": "qa_manual_tc_save", "description": "PRD 절에서 뽑은 수동 작성 TC(규칙표에 없는 확인 항목)를 catalog/manual-tc.yaml 에 바로 저장한다(Hermes 작성 표시). "
     "id 는 PRD.문서.절#번호 로 자동으로 붙는다. items 의 각 항목은 title·when·then 필수, given·operations 선택.",
     "inputSchema": _schema({"doc": _STR, "section": _STR, "domain": {"type": "string", "description": "room·participation 등. 없으면 같은 문서의 기존 수동 작성 TC 에서 가져온다"},
                             "items": {"type": "array", "minItems": 1, "maxItems": 10,
                                       "items": _schema({"title": _STR, "given": _STR, "when": _STR, "then": _STR,
                                                         "operations": {"type": "array", "items": _STR}}, ["title", "when", "then"])}},
                            ["doc", "section", "items"])},
]


class McpServer:
    def __init__(self, app, hidden_triggers: tuple = ("explorer",)):
        self.app = app
        self.hidden_triggers = hidden_triggers
        self._impl = {t["name"]: getattr(self, "t_" + t["name"][3:]) for t in TOOLS}

    # ---- 인증 ---------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.app.cfg.qa_mcp_token)

    def authorized(self, authorization: str | None) -> bool:
        if not self.enabled or not authorization:
            return False
        parts = authorization.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return False
        return hmac.compare_digest(parts[1].strip(), self.app.cfg.qa_mcp_token)

    # ---- JSON-RPC ----------------------------------------------------------------
    def handle(self, raw: bytes, *, ip: str | None = None) -> tuple[int, object | None]:
        """(HTTP status, 응답 객체|None). None 이면 본문 없이 202."""
        try:
            msg = json.loads(raw or b"")
        except ValueError:
            return 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "본문이 JSON 이 아니다"}}
        batch = isinstance(msg, list)
        out = []
        for m in (msg if batch else [msg]):
            r = self._one(m, ip)
            if r is not None:
                out.append(r)
        if not out:
            return 202, None
        return 200, (out if batch else out[0])

    def _one(self, m, ip) -> dict | None:
        if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or not isinstance(m.get("method"), str):
            return {"jsonrpc": "2.0", "id": (m.get("id") if isinstance(m, dict) else None), "error": {"code": -32600, "message": "JSON-RPC 2.0 요청이 아니다"}}
        mid, method, params = m.get("id"), m["method"], (m.get("params") or {})
        if mid is None:
            return None          # 알림 (notifications/initialized 등) — 응답 없음
        try:
            if method == "initialize":
                want = str(params.get("protocolVersion") or "")
                result = {"protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[1],
                          "capabilities": {"tools": {"listChanged": False}},
                          "serverInfo": {"name": "plady-qa-platform", "version": "0.4"}, "instructions": INSTRUCTIONS}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call(str(params.get("name") or ""), params.get("arguments") or {}, ip)
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"지원하지 않는 메서드: {method}"}}
        except Exception as ex:   # 도구 밖의 예외 — 프로토콜 오류로
            traceback.print_exc()
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": f"내부 오류: {ex}"[:300]}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _call(self, name: str, args, ip) -> dict:
        impl = self._impl.get(name)
        if not impl:
            return {"content": [{"type": "text", "text": f"없는 도구: {name}. 있는 도구: {', '.join(self._impl)}"}], "isError": True}
        if not isinstance(args, dict):
            args = {}
        t0 = time.monotonic()
        ok, text, hint = True, "", None
        try:
            result = impl(**args)
            hint = result.pop("_hint", None) if isinstance(result, dict) else None
            text = json.dumps(result, ensure_ascii=False, indent=1, default=str)
        except TypeError as ex:      # 스키마 밖 인자
            ok, text = False, f"인자 오류: {ex}"
        except ToolError as ex:
            ok, text = False, str(ex)
        except Exception as ex:
            traceback.print_exc()
            ok, text = False, f"도구 실패: {ex}"[:600]
        ms = int((time.monotonic() - t0) * 1000)
        detail = {"tool": name, "args": _arg_summary(args), "ok": ok, "ms": ms, "chars": len(text)}
        if hint:
            detail["result"] = hint
        if not ok:
            detail["error"] = text[:300]
        self.app.store.add_event(operator=AGENT, action="mcp.call", target=name, ip=ip, detail=detail)
        sys.stderr.write(f"mcp.call {name} ok={ok} {ms}ms {len(text)}B\n")
        return {"content": [{"type": "text", "text": text}], "isError": not ok}

    # ---- 공통 ----------------------------------------------------------------------
    def _catalog(self):
        cat = self.app.current_catalog()
        if cat is None:
            raise ToolError("TC 목록이 없다: " + (self.app.catalog.last_error or "원인 미상"))
        return cat

    def _url(self, path: str) -> str:
        return f"{self.app.cfg.public_url}{path}"

    @staticmethod
    def _limit(limit, default: int) -> int:
        try:
            n = int(limit) if limit is not None else default
        except (TypeError, ValueError):
            n = default
        return max(1, min(n, MAX_LIMIT))

    def _last_verdicts(self) -> dict:
        return self.app.store.last_verdicts()

    @staticmethod
    def _verdict(last: dict, case_id: str) -> dict | None:
        v = last.get(case_id)
        return {"verdict": v["verdict"], "run_id": v["run_id"], "at": v["created_at"]} if v else None

    # ---- 읽기 도구 -----------------------------------------------------------------
    def t_catalog_search(self, domain=None, layer=None, only=None, q=None, limit=None) -> dict:
        cat = self._catalog()
        cov = self.app.coverage(cat)["by_tc"]
        last = self._last_verdicts()
        warn_ids = {w.split(":")[0] for w in cat.warnings if ":" in w}
        ql = (q or "").strip().lower()
        n = self._limit(limit, 50)
        items, total = [], 0
        for r in sorted(cat.records.values(), key=lambda r: (r["domain"], r["layer"], r["id"])):
            if domain and r["domain"] != domain:
                continue
            if layer and r["layer"] != layer:
                continue
            state = "excluded" if r.get("excluded") else ("covered" if cov.get(r["id"]) else "uncovered")
            if only in ("uncovered", "covered", "excluded") and state != only:
                continue
            if only == "warn" and r["id"] not in warn_ids:
                continue
            if ql and ql not in (r["id"] + " " + str(r.get("title") or "") + " " + json.dumps(r.get("binding") or {}, ensure_ascii=False)).lower():
                continue
            total += 1
            if len(items) >= n:
                continue
            item = _slim_record(r)
            item["state"] = state
            item["covered_by"] = [{"case_id": c, "last": self._verdict(last, c)} for c in cov.get(r["id"], [])]
            if r["id"] in warn_ids:
                item["warnings"] = [w for w in cat.warnings if w.startswith(r["id"] + ":")]
            items.append(item)
        return {"total": total, "returned": len(items), "domains": cat.domains(), "items": items,
                "note": "스크립트로 쓰려면 qa_case_save 에 YAML 을 낸다. covers 는 여기 있는 id 만 쓸 수 있다."}

    def t_tc_get(self, id: str) -> dict:  # noqa: A002
        cat = self._catalog()
        r = cat.records.get(id)
        if not r:
            near = [i for i in cat.records if id.lower() in i.lower()][:10]
            raise ToolError(f"TC 목록에 없는 TC: {id}" + (f". 비슷한 id: {', '.join(near)}" if near else ""))
        cov = self.app.coverage(cat)["by_tc"].get(id, [])
        last = self._last_verdicts()
        prd = []
        for ref in r.get("prd") or []:
            text = self.app.wiki.prd_section(ref["doc"], ref["section"], max_lines=80) if self.app.wiki.available else None
            prd.append({"doc": ref["doc"], "section": ref["section"], "url": ref.get("url"), "text": text})
        return {"record": r, "prd": prd, "url": self._url(f"/catalog/tc?id={id}"),
                "covered_by": [{"case_id": c, "title": self.app.cases[c].title, "suite": self.app.cases[c].suite, "last": self._verdict(last, c)}
                               for c in cov if c in self.app.cases],
                "change": self.app.catalog.changes.get(id), "warnings": [w for w in cat.warnings if w.startswith(id + ":")]}

    def t_coverage(self) -> dict:
        cat = self._catalog()
        cov = self.app.coverage(cat)
        return {"versions": cat.versions, "built_at": cat.built_at, "counts": cat.counts(), "matrix": cov["matrix"],
                "cases": {"total": len(self.app.cases), "blocked": [c.id for c in self.app.cases.values() if c.blocked],
                          "load_errors": len(self.app.case_errors)},
                "warnings": cat.warnings[:30], "warning_count": len(cat.warnings), "url": self._url("/catalog")}

    def t_changes(self, since=None, limit=None) -> dict:
        n = self._limit(limit, 50)
        by_tc: dict[str, list[str]] = {}
        for c in self.app.cases.values():
            for t in c.covers:
                by_tc.setdefault(t, []).append(c.id)
        rows = []
        for tid, ch in self.app.catalog.changes.items():
            if since and ch.get("at", "") <= str(since):
                continue
            rows.append(dict(ch, id=tid, affected_cases=by_tc.get(tid, [])))
        rows.sort(key=lambda x: (x.get("at") or "", x["id"]), reverse=True)
        return {"total": len(rows), "items": rows[:n],
                "note": "영향 스크립트는 스크립트 화면의 TC 변경 배지와 같다. 고치려면 qa_case_get 으로 YAML 을 읽고 qa_case_save(update=true) 로 고친 판을 저장한다."}

    def t_case_list(self, domain=None, suite=None) -> dict:
        self.app.current_catalog()
        last = self._last_verdicts()
        items = []
        for c in sorted(self.app.cases.values(), key=lambda c: c.id):
            if domain and domain not in c.domains:
                continue
            if suite and c.suite != suite:
                continue
            items.append({"id": c.id, "title": c.title, "suite": c.suite, "domains": c.domains, "covers": len(c.covers),
                          "audit": c.audit.get("status"), "blocked": c.blocked, "drift": len(self.app.drift_of(c)),
                          "last": self._verdict(last, c.id), "file": c.file})
        return {"total": len(items), "items": items, "load_errors": self.app.case_errors[:10]}

    def t_case_get(self, id: str) -> dict:  # noqa: A002
        c = self.app.cases.get(id)
        if not c:
            near = [i for i in self.app.cases if id.lower() in i.lower()][:10]
            raise ToolError(f"없는 스크립트: {id}" + (f". 비슷한 id: {', '.join(near)}" if near else ""))
        self.app.current_catalog()
        return {"id": c.id, "title": c.title, "suite": c.suite, "domains": c.domains, "operations": c.operations, "actor": c.actor,
                "covers": c.covers, "reviewed": c.reviewed, "audit": c.audit, "blocked": c.blocked, "drift": self.app.drift_of(c),
                "yaml": c.to_yaml(), "file": c.file, "history": self.app.store.case_history(c.id, 10), "url": self._url(f"/cases/{c.id}")}

    def t_run_list(self, trigger=None, limit=None) -> dict:
        n = self._limit(limit, 20)
        runs = self.app.store.list_runs(n, trigger or None, exclude=() if trigger else self.hidden_triggers)
        keep = ("id", "created_at", "started_at", "finished_at", "trigger", "operator", "suite", "status", "verdict",
                "total", "passed", "failed", "errored", "skipped", "sha", "pr_number")
        items = []
        for r in runs:
            item = {k: r.get(k) for k in keep}
            item["basis"] = r["meta"].get("basis")
            item["reason"] = r["meta"].get("reason")
            item["url"] = self._url(f"/runs/{r['id']}")
            items.append(item)
        return {"returned": len(items), "items": items}

    def t_run_get(self, id: str, with_steps=False) -> dict:  # noqa: A002
        run = self.app.store.get_run(id)
        if not run:
            raise ToolError(f"없는 실행 기록: {id}")
        meta = {k: v for k, v in run["meta"].items() if not k.startswith("_")}
        rcs = self.app.store.list_run_cases(id)
        cases = []
        for rc in rcs:
            item = {"run_case_id": rc["id"], "case_id": rc["case_id"], "title": rc["case_title"], "suite": rc["case_suite"],
                    "verdict": rc["verdict"], "duration_ms": rc["duration_ms"], "error": rc.get("error"), "triage": rc.get("triage")}
            if with_steps:
                steps = []
                for s in self.app.store.list_steps(rc["id"]):
                    req = dict(s["request"])
                    req.pop("headers", None)
                    resp = s.get("response") or {}
                    body = resp.get("json") if resp.get("json") is not None else resp.get("text")
                    steps.append({"ord": s["ord"], "name": s["name"], "verdict": s["verdict"], "duration_ms": s["duration_ms"],
                                  "request": mask_ids(_s(req, 1500)),
                                  "response": {"status": resp.get("status"), "body": mask_ids(_s(body, 2000)) if body is not None else None},
                                  "checks": s["checks"], "error": s.get("error")})
                item["steps"] = steps
            cases.append(item)
        run = {k: v for k, v in run.items() if k != "meta"}
        return {"run": run, "meta": meta, "cases": cases, "url": self._url(f"/runs/{id}")}

    def t_spec_op(self, operationId: str) -> dict:  # noqa: N803
        spec = self.app.spec.get()
        if not spec:
            raise ToolError("OpenAPI 를 읽지 못했다: " + (self.app.spec.last_error or ""))
        op = spec.ops.get(operationId)
        if not op:
            ql = operationId.lower()
            near = [o.id for o in spec.ops.values() if ql in (o.id + o.path).lower()][:10]
            raise ToolError(f"OpenAPI 에 없는 operationId: {operationId}" + (f". 비슷한 것: {', '.join(near)}" if near else ""))
        return {"operationId": op.id, "method": op.method, "path": op.path, "summary": op.summary, "tags": op.tags, "params": op.params,
                "request_example": op.request_example, "success": op.success,
                "errors": {code: {"status": i.get("status"), "message": i.get("message"), "example": i.get("example")} for code, i in op.errors.items()},
                "tc_ids": [f"op.{op.id}:{st}" for st in op.success] + [f"op.{op.id}:{code}" for code in op.errors], "spec_hash": spec.hash}

    def t_api_get(self, operationId: str) -> dict:  # noqa: N803
        d = self.app.api_detail(operationId)
        if not d:
            spec = self.app.spec.get()
            ql = operationId.lower()
            near = [o.id for o in spec.ops.values() if ql in (o.id + o.path).lower()][:10] if spec else []
            raise ToolError(f"OpenAPI 에 없는 operationId: {operationId}" + (f". 비슷한 것: {', '.join(near)}" if near else ""))
        calls = [{k: v for k, v in c.items() if k not in ("url", "body", "query", "checks")} for c in d["recent_calls"]]
        out = {"op": d["op"], "qa": {k: v for k, v in d["qa"].items() if k != "ids"}, "tcs": d["tcs"], "scripts": d["scripts"], "recent_calls": calls,
               "docs_url": d["docs_url"], "spec_hash": d["spec_hash"], "url": f"{self.app.cfg.public_url}/apis/{d['op']['id']}"}
        return json.loads(mask_ids(json.dumps(out, ensure_ascii=False, default=str)))

    def t_prd_section(self, doc: str, section: str) -> dict:
        wiki = self.app.wiki
        if not wiki.available:
            raise ToolError("위키 체크아웃이 없다 (QA_WIKI_DIR) — PRD 를 읽을 수 없다")
        if not wiki.prd_path(doc):
            raise ToolError(f"PRD 문서를 찾지 못했다: {doc} (문서 이름은 SSOT meta.문서_링크 의 이름과 같게, 예: 룸 생성)")
        text = wiki.prd_section(doc, str(section), max_lines=150)
        if text is None:
            raise ToolError(f"PRD/{doc} 에 §{section} 헤딩이 없다")
        return {"doc": doc, "section": str(section), "url": wiki.prd_url(doc), "text": text, "wiki_head": wiki.head()}

    # ---- 저장 도구 (검증을 통과하면 main 에 바로) ------------------------------------------
    def t_case_save(self, yaml: str, update=False, reason=None) -> dict:  # noqa: A002
        cat = self._catalog()
        raws = draftsmod.parse_output(str(yaml))
        if not raws:
            raise ToolError("YAML 에서 스크립트를 찾지 못했다 — 스크립트 맵 하나 또는 `cases:` 목록이어야 한다")
        if len(raws) > 5:
            raise ToolError("한 번에 5건까지")
        saved, rejected = [], []
        for raw in raws:
            rid = str(raw.get("id") or "?")
            if update and rid not in self.app.cases:
                rejected.append({"case_id": rid, "errors": ["update=true 인데 그 id 의 스크립트가 없다 — qa_case_list 로 id 를 확인한다"], "warnings": []})
                continue
            requested = list(raw.get("covers") or []) + [t for s in (raw.get("steps") or []) if isinstance(s, dict) for t in (s.get("covers") or [])]
            existing = set(self.app.cases) - ({rid} if update else set())
            case, errors, warnings = draftsmod.validate(raw, requested=requested, catalog=cat, cfg=self.app.cfg, existing_ids=existing, actors=self.app.all_actors())
            if not case:
                rejected.append({"case_id": rid, "errors": errors, "warnings": warnings})
                continue
            try:
                out = self.app.save_change(kind="case", source="hermes-chat", yaml_text=case.to_yaml(), operator=AGENT, domain=(case.domains[0] if case.domains else None),
                                           note=(str(reason).strip()[:300] if reason else None), case_id=case.id, tc_ids=case.covers,
                                           validation={"status": case.audit["status"], "warnings": warnings})
            except Exception as ex:      # main 커밋 실패 (그사이 바뀜 등)
                rejected.append({"case_id": case.id, "errors": [str(ex)], "warnings": warnings})
                continue
            saved.append({"id": out["id"], "case_id": case.id, "updated": bool(update), "committed": bool(out["commit"]), "warnings": warnings,
                          "url": self._url(self.app.change_link(out)["href"])})
        return {"saved": saved, "rejected": rejected, "_hint": {"saved": [c["id"] for c in saved], "rejected": len(rejected)},
                "next": ("저장했다. 실행은 사람이 스크립트 화면에서 누른다 — 링크를 안내하라." if saved else "사유를 고쳐 다시 qa_case_save 를 부른다.")}

    def t_manual_tc_save(self, doc: str, section: str, items: list, domain=None) -> dict:
        cat = self._catalog()
        if not isinstance(items, list) or not items:
            raise ToolError("items 는 비어 있지 않은 목록")
        if len(items) > 10:
            raise ToolError("한 번에 10건까지")
        try:
            out, warnings, domain = draftsmod.build_manual_tc(catalog=cat, doc=doc, section=section, items=items, domain=domain, wiki=self.app.wiki)
        except ValueError as ex:
            raise ToolError(str(ex))
        sec = str(section).strip().rstrip(".")
        text = yaml_dump({"cases": out})
        try:
            res = self.app.save_change(kind="tc", source="hermes-chat", yaml_text=text, operator=AGENT, domain=str(domain),
                                       note=f"PRD/{doc} §{sec} 에서 Hermes 가 뽑은 수동 작성 TC", tc_ids=[r["id"] for r in out],
                                       validation={"status": "warn" if warnings else "ok", "warnings": warnings})
        except Exception as ex:
            raise ToolError(f"저장하지 못했다: {ex}")
        return {"id": res["id"], "kind": "tc", "tc_ids": res["tc_ids"], "yaml": text, "warnings": warnings, "committed": bool(res["commit"]),
                "url": self._url(self.app.change_link(res)["href"]), "_hint": {"saved": [res["id"]], "tc": len(out)},
                "next": "저장했다. 틀린 항목은 사람이 TC 상세에서 폼으로 고치거나 지운다."}


def yaml_dump(obj) -> str:
    return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False)
