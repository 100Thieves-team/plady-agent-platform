"""결정론 러너. 사람이 만든 런을 큐에서 하나씩 꺼내 실행한다. docs/qa-platform.md §4 3.x.

- 런은 직렬(worker 1개): dev 데이터 충돌을 막는다.
- 스크립트는 순차, 단계 실패 시 그 스크립트 중단.
- 테스트 계정/픽스처 부재 → 스크립트 skipped (설정 문제), 그 외 예외 → error, 단언 불일치 → failed.
- 요청 기록은 Authorization 을 마스킹하고 응답 본문은 8 KB 로 자른다.
"""
from __future__ import annotations

import inspect
import queue
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

from . import httpx
from . import inbox as inboxmod
from . import multipart as multipartmod
from urllib.parse import quote

from .cases import Case, withdraws_shared_account
from .config import Config
from .store import Store, now_iso
from .templating import Context, TemplateError, get_path

BODY_LIMIT = 8 * 1024


class ActorPool:
    """dev-sessions 로 테스트 계정 토큰을 얻어 캐시한다. 토큰은 만료가 없으니 프로세스 수명 동안 유지."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._tokens: dict[tuple, str] = {}     # (대상 주소, 회원 id) → 토큰 — 대상마다 회원이 다르다 (docs/qa-platform-v2.md §13)
        self._lock = threading.Lock()
        self.extra = None      # () -> {name: memberId} — 플랫폼이 만든 QA 테스트 회원(store.qa_members). App 이 꽂는다
        self.by_base = None    # (base_url) -> {name: memberId} — 등록한 대상 서버의 테스트 계정. App 이 꽂는다

    def mapping(self) -> dict:
        """이름 → 회원 UUID. SSM 의 고정 테스트 계정 + 플랫폼이 만든 QA 회원."""
        out = dict(self.cfg.actors)
        if self.extra:
            try:
                out.update(self.extra())
            except Exception:
                pass
        return out

    def member_id(self, name: str, base_url: str | None = None) -> str | None:
        """그 대상에 따로 적은 회원 id 가 있으면 그것, 없으면 dev 와 같은 id."""
        if base_url and self.by_base:
            try:
                mid = (self.by_base(base_url) or {}).get(name)
            except Exception:
                mid = None
            if mid:
                return mid
        return self.mapping().get(name)

    def token(self, name: str, base_url: str | None = None) -> str:
        base = base_url or self.cfg.target_base_url
        mid = self.member_id(name, base)
        if not mid:
            raise TemplateError(f"actor.{name}", "actor")
        return self.token_for_member(mid, base, name=name)

    def token_for_member(self, member_id: str, base_url: str | None = None, *, name: str | None = None) -> str:
        """회원 id 로 dev-sessions 토큰. 테스트 계정 이름이 없는 QA 회원도 정리 표에서 토큰을 볼 수 있게."""
        base = base_url or self.cfg.target_base_url
        with self._lock:
            if (base, member_id) in self._tokens:
                return self._tokens[(base, member_id)]
        r = httpx.request("POST", f"{base}/v1/auth/dev-sessions", body={"memberId": member_id},
                          timeout=self.cfg.request_timeout)
        tok = get_path(r.json, "data.accessToken") if r.json else None
        if r.status != 200 or not tok:
            raise RuntimeError(f"테스트 계정 '{name or member_id}' 토큰 발급 실패: status={r.status} {r.error or (r.text or '')[:200]}")
        self.remember(member_id, base, tok)
        return tok

    def remember(self, member_id: str, base_url: str, token: str) -> None:
        """회원 생성 응답의 토큰을 캐시에 넣는다 — 바로 보여 줄 때 dev-sessions 를 한 번 더 부르지 않게. 메모리에만."""
        with self._lock:
            self._tokens[(base_url, member_id)] = token

    def invalidate(self, name: str):
        mid = self.mapping().get(name) or name
        with self._lock:
            for k in [k for k in self._tokens if k[1] == mid]:
                self._tokens.pop(k, None)


COOKIE_STATES = ("set", "cleared", "absent")


def parse_set_cookie(line: str) -> dict:
    """Set-Cookie 한 줄 → {name, value, path, cleared}. 값이 비었거나 Max-Age=0 이면 지우는 쿠키다."""
    parts = [x.strip() for x in str(line).split(";")]
    name, _, value = parts[0].partition("=")
    attrs = {}
    for a in parts[1:]:
        k, _, v = a.partition("=")
        attrs[k.strip().lower()] = v.strip()
    cleared = value == "" or attrs.get("max-age") == "0"
    return {"name": name.strip(), "value": value, "path": attrs.get("path") or "/", "cleared": cleared}


def cookie_state(set_cookies: list, name: str) -> str:
    hit = [c for c in (parse_set_cookie(x) for x in set_cookies or []) if c["name"] == name]
    if not hit:
        return "absent"
    return "cleared" if hit[-1]["cleared"] else "set"


def evaluate(expect: dict, status: int, body, set_cookies: list | None = None) -> list[dict]:
    """기대 6종을 평가한다. 각 항목: {check, path?, expected, actual, ok}."""
    out = []
    if "status" in expect:
        want = str(expect["status"]).strip().lower()
        if len(want) == 3 and want.endswith("xx") and want[0].isdigit():      # 4xx — 거절됨까지만 확인 (에러 코드를 모를 때, §16.6-2)
            ok = status is not None and status // 100 == int(want[0])
        else:
            ok = status == int(want)
        out.append({"check": "status", "expected": expect["status"], "actual": status, "ok": ok})
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
    for name, want in (expect.get("cookies") or {}).items():
        # 응답 Set-Cookie 로 판정한다: set 은 값을 심었다, cleared 는 만료시켰다, absent 는 건드리지 않았다
        a = cookie_state(set_cookies or [], name)
        out.append({"check": "cookie", "path": name, "expected": want, "actual": a, "ok": a == want})
    return out


def _send(method, url, **kw):
    """스크립트 요청은 리다이렉트를 따라가지 않는다 — 3xx 와 그 응답의 Set-Cookie 를 그대로 확인하려고 (OAuth 시작 등).
    테스트가 httpx.request 를 바꿔 끼우면 그 함수가 follow_redirects 를 모를 수 있어 시그니처를 본다."""
    fn = httpx.request
    try:
        params = inspect.signature(fn).parameters
        ok = "follow_redirects" in params or any(p.kind == p.VAR_KEYWORD for p in params.values())
    except (TypeError, ValueError):
        ok = False
    return fn(method, url, **kw, **({"follow_redirects": False} if ok else {}))


def _mask_header(k: str, v: str) -> str:
    if k == "Authorization":
        return "Bearer ***"
    if k == "Cookie":
        return "; ".join(x.split("=", 1)[0].strip() + "=***" for x in v.split(";"))
    return v


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
        self.notify = None          # 알림 기다리기 단계용 (App): notify_ready(actor, channel, base) → 못 받는 이유, poll_mail() (§15.4)
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
        base0 = run["base_url"] or self.cfg.target_base_url
        ctx = Context(actors=self.actors.mapping(), fixtures=self.cfg.fixtures,
                      webpush=self.notify.webpush_tokens(base0) if self.notify else {})
        total_ms = 0
        verdict, err = "pass", None
        push_to = {s["notify"]["to"] for s in case.steps if s.get("notify") and "web_push" in s["notify"]["channels"]}
        if push_to and self.notify:
            try:
                self.notify.notify_prepare(push_to, base0)      # 웹 푸시 기기 등록 갱신 — 알림을 일으킬 API 단계보다 먼저
            except Exception:
                traceback.print_exc()
        action_at = datetime.now(timezone.utc)      # 알림 기다리기는 바로 앞 API 단계를 시작한 때부터 센다
        skipped_notes = []
        for i, step in enumerate(case.steps):
            if verdict != "pass" and not step.get("always"):
                continue            # 앞 단계가 실패했다 — always 표시가 있는 정리 단계만 돈다 (2026-09-25)
            base = run["base_url"] or self.cfg.target_base_url
            if step.get("notify"):
                sv, ms, serr = self._run_notify(step, i, rcid, ctx, base, action_at, run["id"])
                total_ms += ms
                if sv == "skipped":
                    skipped_notes.append(serr)      # 받을 준비가 안 된 알림 확인은 건너뛰고 다음 단계를 이어 간다
                    continue
            else:
                action_at = datetime.now(timezone.utc)
                sv, ms, serr = self._run_step(case, step, i, rcid, ctx, base, after_failure=verdict != "pass")
            total_ms += ms
            if verdict != "pass":
                continue            # 실패 뒤 정리 단계의 결과는 기록만 한다. 판정은 처음 실패가 정한다
            if sv != "pass":
                verdict, err = sv, serr
                if step.get("given") and sv == "fail":
                    # 테스트 데이터 만들기 카드(uses) 단계가 틀리면 확인하려던 규칙까지 가지 못한 것 — fail 이 아니라 error (docs/qa-platform-scenarios.md §8.3)
                    verdict = "error"
                if step.get("given") and sv != "skipped":
                    err = f"전제 준비 실패({step['given']}): {serr}"
        if verdict == "pass" and skipped_notes:
            err = "알림 확인을 건너뛰었다: " + "; ".join(dict.fromkeys(skipped_notes))
        self.store.update_run_case(rcid, verdict=verdict, duration_ms=total_ms, error=err)
        return verdict, total_ms, err

    def _run_notify(self, step: dict, i: int, rcid: int, ctx: Context, base_url: str, since: datetime, rid: str) -> tuple[str, int, str | None]:
        """알림 기다리기 단계 (docs/qa-platform-v2.md §15.4). 바로 앞 API 단계를 시작한 때부터 within 초 안에 그 회원에게 온 알림을 본다.
        받을 준비가 안 됐으면(수신기 꺼짐, 메일함 없음) skipped — 스크립트의 다른 단계는 이어 간다."""
        name = step.get("name") or f"step {i + 1}"
        t0 = time.monotonic()
        try:
            spec = ctx.render(step["notify"])
        except TemplateError as e:
            msg = str(e)
            self.store.add_step(rcid, i, name, {"method": "NOTIFY", "path": "", "notify": step["notify"]}, None, [], "error", 0, msg)
            return "error", 0, msg
        record = {"method": "NOTIFY", "path": inboxmod.describe(spec), "actor": spec["to"], "notify": spec}
        missing = []
        for ch in spec["channels"]:
            why = self.notify.notify_ready(spec["to"], ch, base_url) if self.notify else "알림 수신이 설정되지 않았다"
            if why:
                missing.append(f"{inboxmod.CHANNEL_KO[ch]}: {why}")
        if missing:
            msg = f"{name}: " + "; ".join(missing)
            self.store.add_step(rcid, i, name, record, None, [], "skipped", 0, msg)
            return "skipped", 0, msg
        start = {"web_push": since, "email": since - timedelta(seconds=5)}     # 메일 Date 는 보내는 서버 시계라 조금 넉넉히
        iso = lambda d: d.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")  # noqa: E731
        deadline = since.timestamp() + spec["within"]
        while True:
            if "email" in spec["channels"]:
                self.notify.poll_mail()
            got = {ch: self.notify.inbox_for(spec["to"], ch, base_url, iso(start[ch])) for ch in spec["channels"]}
            ok, checks = inboxmod.judge(spec, got)
            if ok != bool(spec.get("none")) or time.time() >= deadline or self._canceled(rid):      # 왔으면 바로 끝, none 은 오면 바로 실패
                break
            time.sleep(2)
        ids = [x for c in checks for x in c.pop("ids", [])]
        if ids:
            self.store.link_inbox(ids, rcid, i)
        seen = sorted({x["id"] for v in got.values() for x in v})
        ms = int((time.monotonic() - t0) * 1000)
        err = None if ok else f"{name}: " + "; ".join(f"{c['check']} 기대 {c['expected']} 실제 {c['actual']}" for c in checks if not c["ok"])
        self.store.add_step(rcid, i, name, record, {"inbox_ids": ids, "seen_ids": seen[-10:]}, checks, "pass" if ok else "fail", ms, err)
        return ("pass" if ok else "fail"), ms, err

    def _run_step(self, case: Case, step: dict, i: int, rcid: int, ctx: Context, base_url: str, after_failure: bool = False) -> tuple[str, int, str | None]:
        """런에 기록된 base_url 로 요청한다 — 런은 생성 시점의 대상을 고정한다."""
        name = step.get("name") or f"step {i + 1}"
        actor = step.get("actor", case.actor)
        path0 = str(step["request"].get("path") or "")
        has_auth = any(str(k).lower() == "authorization" for k in (step["request"].get("headers") or {}))
        if not actor and path0.startswith("/v1/dev/") and not has_auth and not step.get("cookie_jar") and self.cfg.actors:
            actor = next(iter(self.cfg.actors))     # dev 도구는 검증 대상이 아니다 — 인증이 없으면 기본 테스트 계정으로 (정리 단계 401 방지)
        record = {"method": step["request"]["method"], "path": step["request"].get("path"), "actor": actor}
        if withdraws_shared_account(step, case.actor):
            msg = "공용 테스트 계정으로 회원 탈퇴를 부르는 단계라 보내지 않았다 — 새 QA 회원의 토큰으로만 부른다"
            self.store.add_step(rcid, i, name, record, None, [], "error", 0, msg)
            return "error", 0, msg
        if step.get("given"):
            record["given"] = step["given"]        # 결과 화면이 전제 단계를 접어 보인다
        if after_failure:
            record["after_failure"] = True        # 앞 단계가 실패한 뒤 always 로 돈 정리 단계
        op_id = self._op_of(record["method"], record["path"])
        try:
            req = ctx.render(step["request"])
            expect = ctx.render(step.get("expect") or {})
            headers = {"Accept": "application/json"}
            headers.update({str(k): str(v) for k, v in (req.get("headers") or {}).items()})
            if actor:
                headers["Authorization"] = "Bearer " + self.actors.token(actor, base_url)
            jar_name = step.get("cookie_jar")
            if jar_name:
                # 그 이름의 쿠키 저장소에 든 쿠키를 붙인다. 쿠키 경로가 요청 경로의 앞부분일 때만 (브라우저와 같게)
                jar = ctx.jars.setdefault(jar_name, {})
                sent = [(n, c["value"]) for n, c in jar.items() if req["path"].split("?")[0].startswith(c["path"])]
                if sent:
                    headers["Cookie"] = "; ".join(f"{n}={v}" for n, v in sent)
                record["cookie_jar"] = jar_name
            url = base_url + quote(req["path"], safe="/:@!$&'()*+,;=%-._~")     # 경로에 한글 등이 섞여도 요청이 깨지지 않게
            if req.get("query"):
                from urllib.parse import urlencode
                url += ("&" if "?" in url else "?") + urlencode({k: v for k, v in req["query"].items() if v is not None})
            send_body = req.get("body")
            if req.get("multipart"):
                ctype, send_body, mp_summary = multipartmod.encode(req["multipart"])
                headers["Content-Type"] = ctype
                record["multipart"] = mp_summary          # 파일 내용은 기록하지 않는다
            record.update({"url": url, "query": req.get("query"), "body": req.get("body"),
                           "headers": {k: _mask_header(k, v) for k, v in headers.items()}})
        except TemplateError as e:
            verdict = "skipped" if (e.kind in ("actor", "fixture", "webpush") or after_failure) else "error"
            msg = (f"{ {'actor': '테스트 계정', 'fixture': '픽스처', 'webpush': '웹 푸시 수신기'}[e.kind]} 미설정: {e}" if e.kind in ("actor", "fixture", "webpush") else
                   (f"앞 단계가 실패해 값이 없어 이 정리 단계를 건너뛰었다: {e}" if after_failure else str(e)))
            self.store.add_step(rcid, i, name, record, None, [], verdict, 0, msg, op_id=op_id)
            return verdict, 0, msg
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.store.add_step(rcid, i, name, record, None, [], "error", 0, msg, op_id=op_id)
            return "error", 0, msg
        op_id = self._op_of(req["method"], req.get("path")) or op_id   # 치환된 경로가 더 정확하다

        r = _send(req["method"], url, headers=headers, body=send_body, timeout=self.cfg.request_timeout)
        response = {"status": r.status, "elapsed_ms": r.elapsed_ms, "json": _mask_secrets(r.json) if r.json is not None else None,
                    "text": None if r.json is not None else _truncate_text(r.text), "error": r.error}
        if r.json is not None and len(r.text) > BODY_LIMIT:
            response["json"] = None
            response["text"] = _truncate_text(r.text)
        set_cookies = getattr(r, "set_cookies", None) or []
        if set_cookies:
            # 쿠키 값은 기록하지 않는다. 이름·경로·만료 여부만
            response["set_cookies"] = [{k: c[k] for k in ("name", "path", "cleared")} for c in map(parse_set_cookie, set_cookies)]
        if step.get("cookie_jar"):
            jar = ctx.jars.setdefault(step["cookie_jar"], {})
            for c in map(parse_set_cookie, set_cookies):
                if c["cleared"]:
                    jar.pop(c["name"], None)
                else:
                    jar[c["name"]] = {"value": c["value"], "path": c["path"]}
        if r.error:
            self.store.add_step(rcid, i, name, record, response, [], "error", r.elapsed_ms, r.error, op_id=op_id)
            return "error", r.elapsed_ms, f"{name}: {r.error}"
        checks = evaluate(expect, r.status, r.json, set_cookies)
        ok = all(c["ok"] for c in checks)
        err = None
        if not ok:
            bad = [c for c in checks if not c["ok"]]
            err = f"{name}: " + "; ".join(
                f"{c['check']}{'(' + c['path'] + ')' if c.get('path') else ''} 기대 {c['expected']!r} 실제 {c['actual']!r}" for c in bad)
        for var, path in (step.get("save") or {}).items():
            val = get_path(r.json, path)
            if ok or val is not None:
                # 검증이 틀려도 응답에 값이 있으면 저장한다 — 뒤의 정리 단계(always)가 만든 데이터를 지울 수 있게 (2026-09-25:
                # 룸 생성이 기존 확정 룸을 돌려줘 상태 검증이 실패했고, roomId 가 없어 정리를 못 했다)
                ctx.vars[var] = val
        self.store.add_step(rcid, i, name, record, response, checks, "pass" if ok else "fail", r.elapsed_ms, err, op_id=op_id)
        return ("pass" if ok else "fail"), r.elapsed_ms, err

    def _op_of(self, method: str | None, path: str | None) -> str | None:
        if not self.op_resolver or not method or not path:
            return None
        try:
            return self.op_resolver(method, path)
        except Exception:
            return None
