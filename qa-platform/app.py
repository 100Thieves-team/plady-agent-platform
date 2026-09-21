#!/usr/bin/env python3
"""qa-platform HTTP 서버. 설계: docs/qa-platform.md.

inbound 은 브라우저(팀 세션 뒤)뿐이다. 외부에서 런을 시작시키는 경로는 없다.
모든 변경 행위는 운영자 필드가 필수이고 감사 로그(events)에 남는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import traceback
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa import ui  # noqa: E402
from qa.cases import audit as audit_cases, load_dir, select  # noqa: E402
from qa.catalog import CatalogService  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.github import GitHub, domains_from_files  # noqa: E402
from qa.hermes import triage as hermes_triage  # noqa: E402
from qa.notify import slack  # noqa: E402
from qa.runner import Runner  # noqa: E402
from qa.spec import Spec  # noqa: E402
from qa.store import Store, now_iso  # noqa: E402
from qa.wiki import Wiki  # noqa: E402

TRIGGERS = ("deploy-sanity", "sprint-smoke", "release", "manual")


class BadRequest(Exception):
    pass


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.github = GitHub(cfg)
        # 기준 문서 (docs/qa-platform-tc.md): 위키 볼륨 + OpenAPI → TC 카탈로그. 읽기이므로 요청 시 갱신.
        self.wiki = Wiki(cfg.wiki_dir, cfg.wiki_branch, cfg.wiki_public_url)
        self.spec = Spec(cfg.spec_url, cfg.data_dir / "catalog", file=cfg.spec_file)
        self.catalog = CatalogService(wiki=self.wiki, spec=self.spec, catalog_dir=cfg.catalog_dir, data_dir=cfg.data_dir)
        self.cases, self.case_errors = {}, []
        self.reload_cases()
        self.runner = Runner(cfg, self.store, self.cases, on_finish=self._on_finish)

    def start(self):
        self.runner.start()

    # ---- 케이스 -----------------------------------------------------------------
    def reload_cases(self) -> tuple[int, list[str]]:
        self.cases, self.case_errors = load_dir(self.cfg.cases_dir)
        audit_cases(self.cases, self.catalog.get())
        if hasattr(self, "runner"):
            self.runner.cases = self.cases
        return len(self.cases), self.case_errors

    def current_catalog(self):
        """카탈로그를 돌려주고, 입력이 바뀌어 다시 계산됐으면 케이스 대조도 다시 한다."""
        before = self.catalog.current
        cat = self.catalog.get()
        if cat is not None and (before is None or cat.key != before.key):
            audit_cases(self.cases, cat)
        return cat

    def coverage(self, cat) -> dict:
        """TC id → 덮는 케이스 id 목록, 도메인×층 매트릭스. 분모는 전체 TC, 제외는 따로 센다 (§6.2)."""
        by_tc: dict[str, list[str]] = {}
        for c in self.cases.values():
            for t in c.covers:
                by_tc.setdefault(t, []).append(c.id)
        matrix: dict[str, dict[str, dict]] = {}
        for r in cat.records.values():
            cell = matrix.setdefault(r["domain"], {}).setdefault(r["layer"], {"total": 0, "covered": 0, "excluded": 0})
            cell["total"] += 1
            if r.get("excluded"):
                cell["excluded"] += 1
            elif r["id"] in by_tc:
                cell["covered"] += 1
        return {"by_tc": by_tc, "matrix": matrix}

    def drift_of(self, case) -> list[dict]:
        return self.catalog.drift_for(case.covers, (case.reviewed or {}).get("at"))

    # ---- 트리거 준비: 사람에게 보여줄 제안 ------------------------------------------
    def suggest(self, trigger: str, sha: str | None, pr: int | None) -> tuple[list, str, dict]:
        """반환: (제안 케이스, 근거 문장, 대상 정보)."""
        info: dict = {}
        if trigger == "deploy-sanity":
            if not sha:
                raise BadRequest("배포 검증에는 sha 가 필요하다")
            prinfo = self.github.pr_for_sha(sha) if not pr else None
            if prinfo:
                pr = prinfo["number"]
                info.update(pr_title=prinfo["title"], pr_url=prinfo["url"])
            elif pr:
                info.update(pr_url=f"https://github.com/{self.cfg.backend_repo}/pull/{pr}")
            files = self.github.pr_files(pr) if pr else []
            domains = sorted(domains_from_files(files))
            info.update(pr_number=pr, changed_files=len(files), domains=domains)
            if domains:
                cases = select(self.cases, suite="sanity", domains=domains)
                if cases:
                    return cases, f"PR #{pr} 변경 파일 {len(files)}개 → 도메인 {', '.join(domains)} → sanity {len(cases)}개", info
                return select(self.cases, suite="sanity"), f"PR #{pr} 도메인 {', '.join(domains)} 에 맞는 케이스가 없어 sanity 전체", info
            why = "PR 을 찾지 못함" if not pr else "변경 파일에서 도메인을 못 읽음"
            return select(self.cases, suite="sanity"), f"{why} → sanity 전체 (보수 폴백)", info
        if trigger in ("sprint-smoke", "release"):
            cs = select(self.cases, suite="smoke")
            return cs, f"smoke 스위트 전체 {len(cs)}개", info
        if trigger == "manual":
            return [], "직접 고른다", info
        raise BadRequest(f"모르는 트리거: {trigger}")

    # ---- 런 생성 (form / API 공용) --------------------------------------------------
    def create_run(self, *, trigger: str, operator: str, case_ids: list[str], sha: str | None, ref: str | None,
                   pr_number: int | None, deploy_run_id: str | None, reason: str, basis: str, extra: dict,
                   session_hash: str | None, ip: str | None) -> str:
        if trigger not in TRIGGERS:
            raise BadRequest(f"모르는 트리거: {trigger}")
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("운영자를 목록에서 골라야 한다")
        chosen = [self.cases[c] for c in case_ids if c in self.cases]
        if not chosen:
            raise BadRequest("케이스를 하나 이상 골라야 한다")
        suite = chosen[0].suite if len({c.suite for c in chosen}) == 1 else None
        cat = self.catalog.current
        meta = {"basis": basis, "reason": reason, "deploy_run_id": deploy_run_id, "case_ids": [c.id for c in chosen],
                "catalog": (cat.versions if cat else None),   # 이 런의 기준 버전 (§6.3). 과거 런은 다시 해석하지 않는다
                "covers": sorted({t for c in chosen for t in c.covers})}
        meta.update({k: v for k, v in extra.items() if v not in (None, "")})
        rid = self.store.create_run(trigger=trigger, operator=operator, suite=suite, env=self.cfg.target_env,
                                    base_url=self.cfg.target_base_url, ref=ref or self.cfg.backend_branch, sha=sha,
                                    pr_number=pr_number, meta=meta, cases=chosen)
        self.store.add_event(operator=operator, action="run.create", target=rid, session_hash=session_hash, ip=ip,
                             detail={"trigger": trigger, "sha": sha, "pr": pr_number, "cases": len(chosen), "basis": basis, "reason": reason})
        self.runner.submit(rid)
        tgt = f"sha {sha[:8]}" + (f" PR #{pr_number}" if pr_number else "") if sha else self.cfg.target_env
        slack(self.cfg.slack_webhook_url, f"[QA] {operator} 가 {ui.TRIGGER_KO.get(trigger, trigger)} 실행 — {tgt}, {len(chosen)}건 · {self.cfg.public_url}/runs/{rid}")
        return rid

    def _on_finish(self, run: dict):
        rcs = self.store.list_run_cases(run["id"])
        bad = [f"{rc['case_id']}" for rc in rcs if rc["verdict"] in ("fail", "error")]
        icon = {"pass": "✅", "fail": "❌", "error": "⚠️", "skipped": "⏭", "canceled": "⏹"}.get(run["verdict"], "")
        msg = (f"[QA] {icon} {ui.TRIGGER_KO.get(run['trigger'], run['trigger'])} {run['verdict']} — 통과 {run['passed']} 실패 {run['failed']} 오류 {run['errored']} skip {run['skipped']}"
               + (f"\n실패: {', '.join(bad[:8])}" if bad else "") + f"\n{self.cfg.public_url}/runs/{run['id']}")
        slack(self.cfg.slack_webhook_url, msg)

    # ---- 대시보드 데이터 ------------------------------------------------------------
    def deploys_with_status(self) -> list[dict]:
        out = []
        for d in self.github.list_deploys():
            d = dict(d)
            d["pr"] = self.github.pr_for_sha(d["sha"]) if d.get("sha") else None
            d["runs"] = [r for r in self.store.runs_for_sha(d["sha"]) if r["trigger"] == "deploy-sanity"] if d.get("sha") else []
            out.append(d)
        return out


# ---- HTTP -------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "qa-platform/0.1"

    def log_message(self, fmt, *args):  # 조용히: 요청 로그에 쿼리(운영자 등)가 섞이지 않게 경로만
        sys.stderr.write(f"{self.address_string()} {self.command} {urlsplit(self.path).path} {args[1] if len(args) > 1 else ''}\n")

    # -- 유틸 --
    def _cookies(self) -> SimpleCookie:
        c = SimpleCookie()
        if self.headers.get("Cookie"):
            try:
                c.load(self.headers["Cookie"])
            except Exception:
                pass
        return c

    def _operator(self) -> str:
        c = self._cookies()
        return c["qa_operator"].value if "qa_operator" in c else ""

    def _session_hash(self) -> str | None:
        c = self._cookies()
        if "wiki_session" in c:
            return hashlib.sha256(c["wiki_session"].value.encode()).hexdigest()[:12]
        return None

    def _ip(self) -> str:
        xff = self.headers.get("X-Forwarded-For")
        return (xff.split(",")[0].strip() if xff else self.client_address[0])

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _form(self) -> dict:
        ct = self.headers.get("Content-Type", "")
        raw = self._body()
        if ct.startswith("application/json"):
            try:
                d = json.loads(raw or b"{}")
            except ValueError:
                raise BadRequest("JSON 본문이 아니다")
            return {k: (v if isinstance(v, list) else [v]) for k, v in d.items()} if isinstance(d, dict) else {}
        return parse_qs(raw.decode("utf-8"), keep_blank_values=True)

    def _send(self, status: int, body: str | bytes, ctype: str = "text/html; charset=utf-8", headers: dict | None = None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False, indent=1), "application/json; charset=utf-8")

    def _redirect(self, loc: str, set_operator: str | None = None):
        h = {"Location": loc}
        if set_operator:
            h["Set-Cookie"] = f"qa_operator={set_operator}; Path=/; Max-Age=31536000; SameSite=Lax"
        self._send(HTTPStatus.SEE_OTHER, "", headers=h)

    def _page(self, title, body, active="", flash=None, status=200):
        self._send(status, ui.page(title, body, active=active, operator=self._operator(), flash=flash))

    def _wants_json(self) -> bool:
        return self.path.startswith("/api/") or "application/json" in self.headers.get("Accept", "")

    # -- 라우팅 --
    def do_GET(self):
        try:
            self._route("GET")
        except BadRequest as e:
            self._error(400, str(e))
        except Exception:
            traceback.print_exc()
            self._error(500, "내부 오류 (서버 로그 참고)")

    def do_POST(self):
        try:
            self._route("POST")
        except BadRequest as e:
            self._error(400, str(e))
        except Exception:
            traceback.print_exc()
            self._error(500, "내부 오류 (서버 로그 참고)")

    def _error(self, status: int, msg: str):
        if self._wants_json():
            self._json(status, {"error": msg})
        else:
            self._page("오류", f"<h1>오류</h1><div class='flash err'>{ui.e(msg)}</div><a href='/'>대시보드로</a>", status=status)

    def _route(self, method: str):
        app = self.app
        u = urlsplit(self.path)
        path, q = u.path.rstrip("/") or "/", parse_qs(u.query)
        g = lambda k, d="": (q.get(k) or [d])[0]  # noqa: E731

        if path == "/health":
            return self._json(200, {"status": "ok", "cases": len(app.cases), "case_errors": len(app.case_errors),
                                    "case_audit": {k: sum(1 for c in app.cases.values() if c.audit["status"] == k) for k in ("ok", "warn", "error", "unchecked")},
                                    "runner": app.runner.current or "idle", "catalog": app.catalog.summary(),
                                    "wiki": {"available": app.wiki.available, "head": app.wiki.head()}, "config": app.cfg.summary()})

        # ---------- 대시보드 ----------
        if path == "/" and method == "GET":
            sprint = app.cfg.current_sprint()
            since = sprint["starts_at"].isoformat().replace("+00:00", "Z")
            cat = app.current_catalog()
            body = ui.dashboard(deploys=app.deploys_with_status(), sprint=sprint, sprint_runs=app.store.runs_since(since, "sprint-smoke"),
                                recent=app.store.list_runs(10), cfg_summary=app.cfg.summary(), case_count=len(app.cases),
                                case_errors=app.case_errors, gh_error=app.github.last_error, runner_current=app.runner.current,
                                catalog=cat, coverage=app.coverage(cat) if cat else None, catalog_error=app.catalog.last_error)
            return self._page("대시보드", body, "dash")

        # ---------- 런 ----------
        if path == "/runs" and method == "GET":
            return self._page("런", ui.runs_list(app.store.list_runs(100)), "runs")

        if path == "/runs/new" and method == "GET":
            trigger = g("trigger", "manual")
            if trigger not in TRIGGERS:
                raise BadRequest(f"모르는 트리거: {trigger}")
            sha, pr = g("sha") or None, (int(g("pr")) if g("pr").isdigit() else None)
            suggested, basis, info = app.suggest(trigger, sha, pr)
            pr = info.get("pr_number", pr)
            target = {"환경": f'<span class="mono">{ui.e(app.cfg.target_base_url)}</span>'}
            if sha:
                target["SHA"] = f'<span class="mono">{ui.e(sha)}</span>'
            if pr:
                target["PR"] = f'<a href="{ui.e(info.get("pr_url"))}">#{pr}</a> {ui.e(info.get("pr_title") or "")}'
            if info.get("domains") is not None:
                target["변경 도메인"] = ui.e(", ".join(info["domains"]) or "–")
            warnings = []
            if any(c.needs_actor() for c in suggested) and not app.cfg.actors:
                warnings.append("테스트 계정(QA_ACTORS)이 설정되지 않았다 — 테스트 계정이 필요한 케이스는 skipped 로 기록된다.")
            if app.github.last_error and trigger == "deploy-sanity":
                warnings.append(app.github.last_error)
            app.current_catalog()
            drifted = [c.id for c in suggested if app.drift_of(c)]
            if drifted:
                warnings.append("근거가 바뀐 케이스가 있다 (케이스 화면에서 확인): " + ", ".join(drifted[:6]) + (" …" if len(drifted) > 6 else ""))
            blocked = [c.id for c in app.cases.values() if c.blocked]
            if blocked:
                warnings.append("카탈로그 대조 오류로 스위트에서 빠진 케이스: " + ", ".join(blocked[:6]))
            hidden = {"sha": sha, "pr": pr, "deploy_run_id": g("deploy_run_id"), "basis": basis,
                      "pr_title": info.get("pr_title"), "pr_url": info.get("pr_url"), "domains": ",".join(info.get("domains") or [])}
            body = ui.run_new(trigger=trigger, target=target, suggested=suggested, all_cases=sorted(app.cases.values(), key=lambda c: c.id),
                              basis=basis, operators=app.cfg.operators, operator=self._operator(), hidden=hidden, warnings=warnings)
            return self._page("실행 전 확인", body, "runs")

        if path in ("/runs", "/api/runs") and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            pr = fv("pr") or fv("pr_number")
            rid = app.create_run(
                trigger=str(fv("trigger", "manual")), operator=operator, case_ids=[str(x) for x in f.get("case_ids") or []],
                sha=str(fv("sha")) or None, ref=str(fv("ref")) or None, pr_number=int(pr) if str(pr).isdigit() else None,
                deploy_run_id=str(fv("deploy_run_id")) or None, reason=str(fv("reason")).strip(), basis=str(fv("basis")),
                extra={"pr_title": fv("pr_title"), "pr_url": fv("pr_url"), "domains": fv("domains")},
                session_hash=self._session_hash(), ip=self._ip())
            if path.startswith("/api/"):
                return self._json(202, {"id": rid, "url": f"{app.cfg.public_url}/runs/{rid}"})
            return self._redirect(f"/runs/{rid}", set_operator=operator)

        m = re.match(r"^/(api/)?runs/(r-[0-9a-f\-]+)$", path)
        if m and method == "GET":
            rid = m.group(2)
            run = app.store.get_run(rid)
            if not run:
                return self._error(404, "런이 없다")
            rcs = app.store.list_run_cases(rid)
            steps = {rc["id"]: app.store.list_steps(rc["id"]) for rc in rcs}
            if m.group(1):
                return self._json(200, {"run": run, "cases": [dict(rc, steps=steps[rc["id"]]) for rc in rcs]})
            checklist = app.github.release_checklist() if run["trigger"] == "release" else []
            return self._page(f"런 {rid}", ui.run_detail(run, rcs, steps, operators=app.cfg.operators, operator=self._operator(),
                                                        checklist=checklist, public_url=app.cfg.public_url), "runs")

        m = re.match(r"^/(api/)?runs/(r-[0-9a-f\-]+)/(cancel|triage|decide)$", path)
        if m and method == "POST":
            rid, action = m.group(2), m.group(3)
            run = app.store.get_run(rid)
            if not run:
                return self._error(404, "런이 없다")
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("운영자를 목록에서 골라야 한다")
            sh, ip = self._session_hash(), self._ip()
            if action == "cancel":
                app.runner.cancel(rid)
                if run["status"] == "queued":
                    app.store.update_run(rid, status="finished", verdict="canceled", finished_at=now_iso())
                app.store.add_event(operator=operator, action="run.cancel", target=rid, session_hash=sh, ip=ip, detail={"status": run["status"]})
                return self._json(200, {"ok": True}) if m.group(1) else self._redirect(f"/runs/{rid}", operator)
            if action == "triage":
                rcid = fv("run_case_id")
                rc = app.store.get_run_case(int(rcid)) if str(rcid).isdigit() else None
                if not rc or rc["run_id"] != rid:
                    raise BadRequest("run_case_id 가 이 런의 것이 아니다")
                try:
                    text = hermes_triage(app.cfg, run, rc, app.store.list_steps(rc["id"]))
                    app.store.update_run_case(rc["id"], triage=text, triaged_at=now_iso())
                    app.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=sh, ip=ip,
                                        detail={"case": rc["case_id"], "chars": len(text)})
                    flash = ("ok", f"Hermes 진단을 {rc['case_id']} 에 기록했다")
                except Exception as ex:
                    app.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=sh, ip=ip,
                                        detail={"case": rc["case_id"], "error": str(ex)[:300]})
                    flash = ("err", f"Hermes 진단 실패: {ex}")
                if m.group(1):
                    return self._json(200 if flash[0] == "ok" else 502, {"ok": flash[0] == "ok", "message": flash[1]})
                self._send(HTTPStatus.SEE_OTHER, "", headers={"Location": f"/runs/{rid}", "Set-Cookie": f"qa_operator={operator}; Path=/; Max-Age=31536000; SameSite=Lax"})
                return
            if action == "decide":
                if run["trigger"] != "release":
                    raise BadRequest("릴리스 런에만 판단을 기록한다")
                if run["status"] != "finished":
                    raise BadRequest("런이 끝난 뒤에 판단한다")
                decision = str(fv("decision"))
                if decision not in ("go", "no-go"):
                    raise BadRequest("decision 은 go | no-go")
                rec = {"decision": decision, "operator": operator, "at": now_iso(), "reason": str(fv("reason")).strip(),
                       "items": app.github.release_checklist(), "checked": [str(x) for x in f.get("checked") or []]}
                app.store.merge_run_meta(rid, {"release": rec})
                app.store.add_event(operator=operator, action="release.decide", target=rid, session_hash=sh, ip=ip,
                                    detail={"decision": decision, "checked": len(rec["checked"]), "of": len(rec["items"]), "reason": rec["reason"][:200]})
                slack(app.cfg.slack_webhook_url, f"[QA] 릴리스 판단 {decision.upper()} — {operator}: {rec['reason'] or '(사유 없음)'} · {app.cfg.public_url}/runs/{rid}")
                return self._json(200, {"ok": True}) if m.group(1) else self._redirect(f"/runs/{rid}", operator)

        # ---------- 기준 (TC 카탈로그) ----------
        if path == "/catalog" and method == "GET":
            cat = app.current_catalog()
            if cat is None:
                return self._page("기준", f'<h1>기준</h1><div class="flash err">카탈로그를 계산하지 못했다: {ui.e(app.catalog.last_error or "원인 미상")}</div>', "catalog")
            cov = app.coverage(cat)
            domain = g("domain") or (cat.domains()[0] if cat.domains() else "")
            body = ui.catalog_list(cat, cov, app.store.last_verdicts(), domain=domain, layer=g("layer"), only=g("only"),
                                   changes=app.catalog.changes, wiki_available=app.wiki.available)
            return self._page("기준", body, "catalog")
        if path == "/catalog/tc" and method == "GET":
            cat = app.current_catalog()
            rec = cat.records.get(g("id")) if cat else None
            if not rec:
                return self._error(404, "그 TC 가 카탈로그에 없다")
            cov = app.coverage(cat)
            covering = [app.cases[i] for i in cov["by_tc"].get(rec["id"], []) if i in app.cases]
            excerpts = []
            for ref in rec.get("prd") or []:
                text = app.wiki.prd_section(ref["doc"], ref["section"], max_lines=40) if app.wiki.available else None
                excerpts.append((ref, text))
            return self._page(rec["id"], ui.catalog_detail(rec, covering, app.store.last_verdicts(), excerpts, app.catalog.changes.get(rec["id"])), "catalog")
        if path == "/api/catalog" and method == "GET":
            cat = app.current_catalog()
            return self._json(200, cat.to_json() if cat else {"error": app.catalog.last_error})

        # ---------- 케이스 ----------
        if path == "/cases" and method == "GET":
            app.current_catalog()
            cs = sorted(app.cases.values(), key=lambda c: c.id)
            drift = {c.id: app.drift_of(c) for c in cs}
            return self._page("케이스", ui.cases_list(cs, app.store.last_verdicts(), app.case_errors, drift=drift), "cases")
        if path == "/cases/reload" and method == "POST":
            n, errs = app.reload_cases()
            app.store.add_event(operator=self._operator() or "(미선택)", action="cases.reload", target=None, detail={"cases": n, "errors": len(errs)})
            return self._redirect("/cases")
        m = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)$", path)
        if m and method == "GET":
            c = app.cases.get(m.group(1))
            if not c:
                return self._error(404, "케이스가 없다")
            cat = app.current_catalog()
            recs = {t: (cat.records.get(t) if cat else None) for t in c.covers}
            return self._page(c.id, ui.case_detail(c, app.store.case_history(c.id), tc_records=recs, drift=app.drift_of(c)), "cases")

        # ---------- 활동 ----------
        if path == "/activity" and method == "GET":
            f_op, f_act = g("operator"), g("action")
            evs = app.store.list_events(200, f_op or None, f_act or None)
            return self._page("활동", ui.activity(evs, app.cfg.operators, app.store.event_actions(), f_op, f_act), "activity")
        if path == "/api/activity" and method == "GET":
            return self._json(200, app.store.list_events(200, g("operator") or None, g("action") or None))

        return self._error(404, "없는 경로")


def main():
    cfg = Config()
    app = App(cfg)
    app.start()
    Handler.app = app
    print(f"qa-platform listening on :{cfg.port} — {json.dumps(cfg.summary(), ensure_ascii=False)}", flush=True)
    if app.case_errors:
        print("case load errors:\n  " + "\n  ".join(app.case_errors), flush=True)
    ThreadingHTTPServer(("0.0.0.0", cfg.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
