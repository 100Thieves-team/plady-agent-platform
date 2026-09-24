"""결정론 러너. 사람이 만든 런을 큐에서 하나씩 꺼내 실행한다. docs/qa-platform.md §4 3.x.

- 런은 직렬(worker 1개): dev 데이터 충돌을 막는다.
- 스크립트는 순차, 단계 실패 시 그 스크립트 중단.
- 테스트 계정/픽스처 부재 → 스크립트 skipped (설정 문제), 그 외 예외 → error, 단언 불일치 → failed.
- 요청 기록은 Authorization 을 마스킹하고 응답 본문은 8 KB 로 자른다.
"""
from __future__ import annotations

import queue
import threading
import traceback

from . import httpx
from .cases import Case
from .config import Config
from .store import Store, now_iso
from .templating import Context, TemplateError, get_path

BODY_LIMIT = 8 * 1024


class ActorPool:
    """dev-sessions 로 테스트 계정 토큰을 얻어 캐시한다. 토큰은 만료가 없으니 프로세스 수명 동안 유지."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._tokens: dict[str, str] = {}
        self._lock = threading.Lock()
        self.extra = None      # () -> {name: memberId} — 플랫폼이 만든 QA 테스트 회원(store.qa_members). App 이 꽂는다

    def mapping(self) -> dict:
        """이름 → 회원 UUID. SSM 의 고정 테스트 계정 + 플랫폼이 만든 QA 회원."""
        out = dict(self.cfg.actors)
        if self.extra:
            try:
                out.update(self.extra())
            except Exception:
                pass
        return out

    def member_id(self, name: str) -> str | None:
        return self.mapping().get(name)

    def token(self, name: str, base_url: str | None = None) -> str:
        mid = self.member_id(name)
        if not mid:
            raise TemplateError(f"actor.{name}", "actor")
        with self._lock:
            if name in self._tokens:
                return self._tokens[name]
        r = httpx.request("POST", f"{base_url or self.cfg.target_base_url}/v1/auth/dev-sessions", body={"memberId": mid},
                          timeout=self.cfg.request_timeout)
        tok = get_path(r.json, "data.accessToken") if r.json else None
        if r.status != 200 or not tok:
            raise RuntimeError(f"테스트 계정 '{name}' 토큰 발급 실패: status={r.status} {r.error or (r.text or '')[:200]}")
        with self._lock:
            self._tokens[name] = tok
        return tok

    def invalidate(self, name: str):
        with self._lock:
            self._tokens.pop(name, None)


def evaluate(expect: dict, status: int, body) -> list[dict]:
    """기대 5종을 평가한다. 각 항목: {check, path?, expected, actual, ok}."""
    out = []
    if "status" in expect:
        out.append({"check": "status", "expected": expect["status"], "actual": status, "ok": status == int(expect["status"])})
    if "result" in expect:
        a = get_path(body, "result") if isinstance(body, dict) else None
        out.append({"check": "result", "expected": expect["result"], "actual": a, "ok": a == expect["result"]})
    if "error_code" in expect:
        a = get_path(body, "error.code") if isinstance(body, dict) else None
        out.append({"check": "error_code", "expected": expect["error_code"], "actual": a, "ok": a == expect["error_code"]})
    for path, exp in (expect.get("json") or {}).items():
        a = get_path(body, path)
        ok = a == exp or (a is not None and exp is not None and type(a) is not type(exp) and str(a) == str(exp))
        out.append({"check": "json", "path": path, "expected": exp, "actual": a, "ok": ok})
    for path in expect.get("exists") or []:
        a = get_path(body, path)
        out.append({"check": "exists", "path": path, "expected": "존재", "actual": _brief(a), "ok": a is not None})
    return out


def _brief(v, limit: int = 120):
    if v is None:
        return None
    s = v if isinstance(v, str) else str(v)
    return s if len(s) <= limit else s[:limit] + "…"


_SECRET_KEYS = ("accessToken", "refreshToken", "token")


def _mask_secrets(v, depth: int = 0):
    """응답 본문의 토큰 값은 기록하지 않는다 (dev 전용 회원 생성 API 가 accessToken 을 돌려준다)."""
    if isinstance(v, dict):
        return {k: ("***" if k in _SECRET_KEYS and isinstance(val, str) else _mask_secrets(val, depth + 1)) for k, val in v.items()} if depth < 4 else v
    if isinstance(v, list) and depth < 4:
        return [_mask_secrets(x, depth + 1) for x in v]
    return v


def _truncate_text(t: str | None) -> str | None:
    if t is None:
        return None
    return t if len(t) <= BODY_LIMIT else t[:BODY_LIMIT] + f"\n…(잘림, 총 {len(t)} bytes)"


class Runner:
    def __init__(self, cfg: Config, store: Store, cases: dict[str, Case], on_finish=None, op_resolver=None):
        # op_resolver(method, path) -> operationId|None. 단계 기록에 op id 를 박는다 (docs/qa-platform-api.md §6). 없으면 NULL
        self.op_resolver = op_resolver
        self.cfg = cfg
        self.store = store
        self.cases = cases
        self.on_finish = on_finish
        self.actors = ActorPool(cfg)
        self._q: queue.Queue[str] = queue.Queue()
        self._cancel: set[str] = set()
        self._lock = threading.Lock()
        self._exec = threading.Lock()      # 런 실행은 언제나 하나씩 — 큐 워커와 탐색기 동기 실행이 이 락을 나눠 쓴다
        self.current: str | None = None
        self._thread = threading.Thread(target=self._loop, name="qa-runner", daemon=True)

    # ---- 생명주기 ------------------------------------------------------------------
    def start(self):
        for rid in self.store.queued_runs():   # 재시작 전 남은 큐 복구
            self._q.put(rid)
        self._thread.start()

    def submit(self, rid: str):
        self._q.put(rid)

    def cancel(self, rid: str):
        with self._lock:
            self._cancel.add(rid)

    def _canceled(self, rid: str) -> bool:
        with self._lock:
            return rid in self._cancel

    def _loop(self):
        while True:
            rid = self._q.get()
            try:
                with self._exec:
                    self.execute(rid)
            except Exception:
                traceback.print_exc()
                try:
                    self.store.update_run(rid, status="finished", verdict="error", finished_at=now_iso())
                except Exception:
                    traceback.print_exc()
            finally:
                self.current = None
                with self._lock:
                    self._cancel.discard(rid)

    def execute_now(self, rid: str):
        """큐를 거치지 않고 지금 실행한다 (탐색기 전송). 진행 중인 런이 있으면 끝날 때까지 기다린다."""
        with self._exec:
            self.execute(rid)

    # ---- 실행 ----------------------------------------------------------------------
    def execute(self, rid: str):
        run = self.store.get_run(rid)
        if not run or run["status"] != "queued":
            return
        self.current = rid
        self.store.update_run(rid, status="running", started_at=now_iso())
        counts = {"passed": 0, "failed": 0, "errored": 0, "skipped": 0}
        for rc in self.store.list_run_cases(rid):
            if self._canceled(rid):
                self.store.update_run_case(rc["id"], verdict="canceled")
                continue
            verdict, dur, err = self.run_case(rc, run)
            key = {"pass": "passed", "fail": "failed", "error": "errored", "skipped": "skipped"}[verdict]
            counts[key] += 1
        if self._canceled(rid):
            verdict = "canceled"
        elif counts["failed"]:
            verdict = "fail"
        elif counts["errored"]:
            verdict = "error"
        elif counts["passed"]:
            verdict = "pass"
        else:
            verdict = "skipped"
        self.store.update_run(rid, status="finished", finished_at=now_iso(), verdict=verdict, **counts)
        if self.on_finish:
            try:
                self.on_finish(self.store.get_run(rid))
            except Exception:
                traceback.print_exc()

    def run_case(self, rc: dict, run: dict) -> tuple[str, int, str | None]:
        """run_cases 행 하나를 실행하고 (verdict, duration_ms, error) 를 돌려준다."""
        from .cases import parse_one
        rcid = rc["id"]
        self.store.update_run_case(rcid, verdict="running")
        try:
            case = parse_one(rc["case_yaml"], f"run:{rc['case_id']}")
        except Exception as e:
            self.store.update_run_case(rcid, verdict="error", error=f"스크립트 스냅샷 파싱 실패: {e}")
            return "error", 0, str(e)
        ctx = Context(actors=self.actors.mapping(), fixtures=self.cfg.fixtures)
        total_ms = 0
        verdict, err = "pass", None
        for i, step in enumerate(case.steps):
            sv, ms, serr = self._run_step(case, step, i, rcid, ctx, run["base_url"] or self.cfg.target_base_url)
            total_ms += ms
            if sv != "pass":
                verdict, err = sv, serr
                if step.get("given") and sv == "fail":
                    # 전제 카드(uses) 단계가 틀리면 확인하려던 규칙까지 가지 못한 것 — fail 이 아니라 error (docs/qa-platform-scenarios.md §8.3)
                    verdict = "error"
                if step.get("given") and sv != "skipped":
                    err = f"전제 준비 실패({step['given']}): {serr}"
                break
        self.store.update_run_case(rcid, verdict=verdict, duration_ms=total_ms, error=err)
        return verdict, total_ms, err

    def _run_step(self, case: Case, step: dict, i: int, rcid: int, ctx: Context, base_url: str) -> tuple[str, int, str | None]:
        """런에 기록된 base_url 로 요청한다 — 런은 생성 시점의 대상을 고정한다."""
        name = step.get("name") or f"step {i + 1}"
        actor = step.get("actor", case.actor)
        record = {"method": step["request"]["method"], "path": step["request"].get("path"), "actor": actor}
        if step.get("given"):
            record["given"] = step["given"]        # 결과 화면이 전제 단계를 접어 보인다
        op_id = self._op_of(record["method"], record["path"])
        try:
            req = ctx.render(step["request"])
            expect = ctx.render(step.get("expect") or {})
            headers = {"Accept": "application/json"}
            headers.update({str(k): str(v) for k, v in (req.get("headers") or {}).items()})
            if actor:
                headers["Authorization"] = "Bearer " + self.actors.token(actor, base_url)
            url = base_url + req["path"]
            if req.get("query"):
                from urllib.parse import urlencode
                url += ("&" if "?" in url else "?") + urlencode({k: v for k, v in req["query"].items() if v is not None})
            record.update({"url": url, "query": req.get("query"), "body": req.get("body"),
                           "headers": {k: ("Bearer ***" if k == "Authorization" else v) for k, v in headers.items()}})
        except TemplateError as e:
            verdict = "skipped" if e.kind in ("actor", "fixture") else "error"
            msg = (f"{'테스트 계정' if e.kind == 'actor' else '픽스처'} 미설정: {e}" if verdict == "skipped" else str(e))
            self.store.add_step(rcid, i, name, record, None, [], verdict, 0, msg, op_id=op_id)
            return verdict, 0, msg
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.store.add_step(rcid, i, name, record, None, [], "error", 0, msg, op_id=op_id)
            return "error", 0, msg
        op_id = self._op_of(req["method"], req.get("path")) or op_id   # 치환된 경로가 더 정확하다

        r = httpx.request(req["method"], url, headers=headers, body=req.get("body"), timeout=self.cfg.request_timeout)
        response = {"status": r.status, "elapsed_ms": r.elapsed_ms, "json": _mask_secrets(r.json) if r.json is not None else None,
                    "text": None if r.json is not None else _truncate_text(r.text), "error": r.error}
        if r.json is not None and len(r.text) > BODY_LIMIT:
            response["json"] = None
            response["text"] = _truncate_text(r.text)
        if r.error:
            self.store.add_step(rcid, i, name, record, response, [], "error", r.elapsed_ms, r.error, op_id=op_id)
            return "error", r.elapsed_ms, f"{name}: {r.error}"
        checks = evaluate(expect, r.status, r.json)
        ok = all(c["ok"] for c in checks)
        err = None
        if not ok:
            bad = [c for c in checks if not c["ok"]]
            err = f"{name}: " + "; ".join(
                f"{c['check']}{'(' + c['path'] + ')' if c.get('path') else ''} 기대 {c['expected']!r} 실제 {c['actual']!r}" for c in bad)
        if ok:
            for var, path in (step.get("save") or {}).items():
                ctx.vars[var] = get_path(r.json, path)
        self.store.add_step(rcid, i, name, record, response, checks, "pass" if ok else "fail", r.elapsed_ms, err, op_id=op_id)
        return ("pass" if ok else "fail"), r.elapsed_ms, err

    def _op_of(self, method: str | None, path: str | None) -> str | None:
        if not self.op_resolver or not method or not path:
            return None
        try:
            return self.op_resolver(method, path)
        except Exception:
            return None
