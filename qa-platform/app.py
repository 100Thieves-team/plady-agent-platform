#!/usr/bin/env python3
"""qa-platform HTTP 서버. 설계: docs/qa-platform.md.

inbound 은 브라우저(팀 세션 뒤)뿐이다. 외부에서 실행을 시작시키는 경로는 없다.
모든 변경 행위는 담당자 필드가 필수이고 감사 로그(events)에 남는다.
"""
from __future__ import annotations

import hashlib
import json
import yaml
import re
import sys
import traceback
from datetime import datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit
_urlq = quote          # _route 안에서 quote 를 지역으로 다시 import 하는 곳이 있어 이름을 따로 둔다

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qa import help as helpmod  # noqa: E402
from qa.qadata import QaData  # noqa: E402
from qa import ui  # noqa: E402
from qa import ui_sanity  # noqa: E402
from qa.cases import CaseError, bake_inputs, audit as audit_cases, load_dir, select  # noqa: E402
from qa.catalog import domain_of_path, CatalogService  # noqa: E402
from qa.config import Config  # noqa: E402
from qa import chat as chatmod  # noqa: E402
from qa import drafts as draftsmod  # noqa: E402
from qa import editor as editormod  # noqa: E402
from qa.jobs import Jobs  # noqa: E402
from qa import scenarios as scenariosmod  # noqa: E402
from qa.repo import Repo, RepoError  # noqa: E402
from qa.github import GitHub, domains_from_files  # noqa: E402
from qa.hermes import triage as hermes_triage  # noqa: E402
from qa.mcp import McpClient, McpError, wiki_apply  # noqa: E402
from qa.mcp_server import McpServer  # noqa: E402
from qa import report as reportmod  # noqa: E402
from qa import sanity as sanitymod  # noqa: E402
from qa import targets as targetsmod  # noqa: E402
from qa import specfix as specfixmod  # noqa: E402
from qa import httpx  # noqa: E402
from qa import inbox as inboxmod  # noqa: E402,F401
from qa import ui_inbox  # noqa: E402
from qa.mailrecv import MailReader  # noqa: E402
from qa.pushrecv import PushError, PushReceivers  # noqa: E402
from qa.notify import slack  # noqa: E402
from qa.reminder import Reminder  # noqa: E402
from qa.runner import Runner  # noqa: E402
from qa.spec import Spec  # noqa: E402
from qa.store import Store, now_iso  # noqa: E402
from qa.wiki import Wiki  # noqa: E402

TRIGGERS = ("deploy-sanity", "sprint-smoke", "release", "manual", "draft-check", "explorer", "setup")
HIDDEN_TRIGGERS = ("explorer",)          # 테스트 실행 목록 기본 숨김 (API 직접 호출은 건수가 많다)


def _crash_summary(e: BaseException) -> str:
    """500 화면에 보일 한 줄 — 예외 종류·메시지·이 레포 안의 마지막 위치. 팀 세션 뒤의 내부 도구라 서버 로그 없이도 원인을 알 수 있게."""
    where = ""
    for fr in reversed(traceback.extract_tb(e.__traceback__)):
        if "qa-platform" in fr.filename or fr.filename.endswith(("app.py",)) or "/qa/" in fr.filename:
            where = f" ({fr.filename.rsplit('/', 2)[-2]}/{fr.filename.rsplit('/', 1)[-1]}:{fr.lineno} in {fr.name})"
            break
    return f"내부 오류 — {type(e).__name__}: {str(e)[:300]}{where}"


class BadRequest(Exception):
    pass


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.github = GitHub(cfg)
        # 기준 문서 (docs/qa-platform-tc.md): 위키 볼륨 + OpenAPI → TC 카탈로그. 읽기이므로 요청 시 갱신.
        self.wiki = Wiki(cfg.wiki_dir, cfg.wiki_branch, cfg.wiki_public_url)
        self.spec = Spec(cfg.spec_url, cfg.data_dir / "catalog", file=cfg.spec_file, ttl=cfg.spec_ttl)
        # 스크립트·TC 입력 파일의 원본은 레포 main. 쓰기 토큰이 있으면 main 판을 <data>/repo 로 받아 읽는다 (docs/qa-platform-editor.md §6)
        self.repo = Repo(cfg)
        self.cases_dir, catalog_dir, self.scenarios_dir = cfg.cases_dir, cfg.catalog_dir, cfg.scenarios_dir
        if self.repo.enabled and (self.repo.sync() or self.repo.synced):
            self.cases_dir, catalog_dir, self.scenarios_dir = self.repo.local / "cases", self.repo.local / "catalog", self.repo.local / "scenarios"
        self.catalog = CatalogService(wiki=self.wiki, spec=self.spec, catalog_dir=catalog_dir, data_dir=cfg.data_dir)
        self.cases, self.case_errors = {}, []
        self.features, self.scenario_errors = {}, []      # 시나리오 파일 (docs/qa-platform-scenarios.md)
        self.reload_cases()
        self.jobs = Jobs(cfg, self.store)     # Hermes 작업 (docs/qa-platform-progress.md)
        self.runner = Runner(cfg, self.store, self.cases, on_finish=self._on_finish, op_resolver=self.op_of)
        self.reminder = Reminder(cfg, self.store, lambda text: slack(cfg.slack_webhook_url, text))
        # QA MCP 서버 (docs/qa-platform-hermes.md §3.1): Hermes 가 부르는 읽기·제안 도구. 실행 도구는 없다
        self.mcp = McpServer(self, hidden_triggers=HIDDEN_TRIGGERS)
        self.qadata = QaData(self)     # dev 전용 QA 데이터 API(삭제·초기화·회원 생성) 클라이언트
        self.runner.actors.extra = self.store.qa_member_map   # 플랫폼이 만든 QA 회원도 테스트 계정 이름으로
        self.store.interrupt_sanity()     # 재시작 전에 돌던 Sanity 는 멈춤으로 (docs/qa-platform-v2.md §9.1)
        self._qa_snap: dict[str, tuple[float, dict]] = {}     # 대상 주소 → 남은 QA 데이터 (QA 데이터 화면을 열 때 갱신)
        self.runner.actors.by_base = self.target_actors      # 대상 서버마다 따로 적은 테스트 계정
        self._sanity_todo: int | None = None                  # 왼쪽 메뉴의 Sanity 숫자 (PR 목록을 읽을 때 갱신)
        import threading as _th
        self._finding_lock = _th.Lock()     # 스펙 확인 항목을 화면과 뒤에서 도는 수정안 작업이 함께 고친다
        self.blobs = specfixmod.Blobs(cfg.data_dir / "specfix")    # 수정안의 원래 파일·고친 파일 (반영 때 3-way merge)
        # 알림 QA (docs/qa-platform-v2.md §15): 플랫폼이 테스트 계정의 웹 푸시 기기와 메일함이 된다. 받기만 한다
        self.push = PushReceivers(cfg, self.store, self.runner.actors)
        self.mail = MailReader(cfg, self.store, self._mail_actor)
        self.runner.notify = self
        self._email_refresh_at = 0.0

    def start(self):
        self.runner.start()
        self.reminder.start()      # 알림만. 실행은 여전히 사람 버튼
        self.push.start()          # 켜 두었던 웹 푸시 수신기를 다시 연다
        self.mail.start()          # 메일함을 15초마다 읽는다 (받기만)
        self._prune_inbox()

    # ---- 알림 QA (docs/qa-platform-v2.md §15) -------------------------------------------
    def _prune_inbox(self) -> None:
        from datetime import timedelta, timezone
        before = (datetime.now(timezone.utc) - timedelta(days=self.cfg.inbox_keep_days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.store.prune_inbox(before)

    def notify_actors(self) -> list[str]:
        """알림함에 보이는 테스트 계정 — SSM 고정 계정 + 플랫폼이 만든 QA 회원."""
        return sorted(self.runner.actors.mapping())

    def _actor_email(self, actor: str, *, refresh: bool = False) -> str | None:
        """테스트 계정의 메일 주소. 모르면 GET /v1/members/me 로 읽어 receivers 에 적는다."""
        base = self.cfg.target_base_url
        r = self.store.get_receiver(base, actor) or {}
        if r.get("email") and not refresh:
            return r["email"]
        try:
            res = httpx.request("GET", base + "/v1/members/me", headers={"Authorization": "Bearer " + self.runner.actors.token(actor, base),
                                                                       "Accept": "application/json"}, timeout=self.cfg.request_timeout)
            me = ((res.json or {}).get("data") or {}) if res.status == 200 else {}
        except Exception:
            me = {}
        if me.get("email"):
            self.store.save_receiver(base, actor, email=me["email"].lower(), member_id=me.get("memberId"))
            return me["email"].lower()
        return r.get("email")

    def _mail_actor(self, address: str):
        """메일 주소 → (대상, 테스트 계정). 모르는 주소면 5분에 한 번 계정 주소를 다시 읽는다."""
        import time as _t
        address = (address or "").lower()
        for r in self.store.list_receivers(self.cfg.target_base_url):
            if r.get("email") == address:
                return r["base_url"], r["actor"]
        if _t.monotonic() - self._email_refresh_at > 300:
            self._email_refresh_at = _t.monotonic()
            for a in self.notify_actors():
                if self._actor_email(a, refresh=True) == address:
                    return self.cfg.target_base_url, a
        return None

    def notify_ready(self, actor: str, channel: str, base_url: str) -> str | None:
        """알림 기다리기 단계가 이 계정의 이 채널을 볼 수 있나. None 이면 볼 수 있다."""
        if base_url.rstrip("/") != self.cfg.target_base_url:
            return "알림 수신은 기본 대상(dev)만 지원한다"
        if actor not in self.runner.actors.mapping():
            return f"테스트 계정 {actor} 가 없다"
        if channel == "web_push":
            return self.push.ready(actor, base_url)
        why = self.mail.unavailable()
        if why:
            return why
        em = self._actor_email(actor)
        if not em:
            return f"{actor} 의 메일 주소를 읽지 못했다"
        if not self.mail.mine(em):
            return f"{actor} 의 메일 주소({em})가 플랫폼 메일함 주소가 아니다. QA 데이터 화면에서 QA 회원을 다시 만든다"
        return None

    def notify_prepare(self, actors: set[str], base_url: str) -> None:
        """스크립트를 시작하기 전에 알림을 기다릴 계정의 백엔드 기기 등록을 다시 보낸다. 알림은 앞 API 단계에서 나가므로 시작할 때 해야 한다.
        백엔드가 그사이 등록을 지웠을 수 있다(FCM UNREGISTERED)."""
        if base_url.rstrip("/") != self.cfg.target_base_url:
            return
        for a in actors:
            if self.push.ready(a, base_url) is None:
                self.push.refresh(a)

    def inbox_for(self, actor: str, channel: str, base_url: str, since: str) -> list[dict]:
        rows = self.store.list_inbox(base_url=base_url, actor=actor, channel=channel, since=since)
        if channel == "email":
            em = self._actor_email(actor)
            if em:                                  # 주소를 알기 전에 들어온 메일도 본다
                seen = {x["id"] for x in rows}
                rows += [x for x in self.store.list_inbox(channel="email", address=em, since=since) if x["id"] not in seen]
        return sorted(rows, key=lambda x: x["id"])

    def webpush_tokens(self, base_url: str) -> dict:
        """{{webpush.X}} — 켜 둔 수신기의 FCM 토큰. 스크립트가 알림 수신 설정을 다시 켤 때 쓴다(PATCH notification-setting)."""
        if base_url.rstrip("/") != self.cfg.target_base_url:
            return {}
        return {r["actor"]: r["push_token"] for r in self.store.list_receivers(self.cfg.target_base_url) if r["enabled"] and r["push_token"]}

    def poll_mail(self) -> None:
        self.mail.poll(min_gap=3)

    def inbox_items(self, filters: dict, after_id: int = 0) -> list[dict]:
        from datetime import timedelta, timezone
        now = datetime.now(timezone.utc)
        w = filters.get("window") or ""
        since = None
        if w == "10m":
            since = now - timedelta(minutes=10)
        elif w == "today":
            k = now + timedelta(hours=9)
            since = k.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=9)
        elif w != "all":
            since = now - timedelta(hours=1)
        iso = since.replace(microsecond=0).isoformat().replace("+00:00", "Z") if since else None
        items = self.store.list_inbox(actor=filters.get("actor") or None, channel=filters.get("channel") or None, type=filters.get("type") or None,
                                      since=iso, after_id=after_id, limit=200)
        if filters.get("actor") and filters.get("channel") in (None, "", "email"):
            em = (self.store.get_receiver(self.cfg.target_base_url, filters["actor"]) or {}).get("email")
            if em:
                seen = {x["id"] for x in items}
                items += [x for x in self.store.list_inbox(channel="email", address=em, type=filters.get("type") or None, since=iso, after_id=after_id)
                          if x["id"] not in seen]
                items.sort(key=lambda x: -x["id"])
        runs = {}
        for x in items:
            if x.get("run_case_id"):
                if x["run_case_id"] not in runs:
                    rc = self.store._one("SELECT run_id FROM run_cases WHERE id=?", (x["run_case_id"],))
                    runs[x["run_case_id"]] = rc["run_id"] if rc else None
                x["run_id"] = runs[x["run_case_id"]]
        return items

    def receiver_on(self, actor: str, *, operator: str, session_hash=None, ip=None) -> dict:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        try:
            r = self.push.enable(actor, operator=operator)
        except PushError as ex:
            self.store.add_event(operator=operator, action="notify.receiver.on", target=actor, session_hash=session_hash, ip=ip, detail={"error": str(ex)[:300]})
            raise BadRequest(str(ex))
        self.store.add_event(operator=operator, action="notify.receiver.on", target=actor, session_hash=session_hash, ip=ip, detail={"base": self.cfg.target_base_url})
        return r

    def receiver_off(self, actor: str, *, operator: str, session_hash=None, ip=None) -> None:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        self.push.disable(actor, operator=operator)
        self.store.add_event(operator=operator, action="notify.receiver.off", target=actor, session_hash=session_hash, ip=ip, detail={"base": self.cfg.target_base_url})

    def inbox_refresh(self, *, operator: str, session_hash=None, ip=None) -> int:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        why = self.mail.unavailable()
        if why:
            raise BadRequest(why)
        n = self.mail.poll()
        self.store.add_event(operator=operator, action="notify.mail.refresh", target="inbox", session_hash=session_hash, ip=ip, detail={"added": n, "error": self.mail.error})
        if self.mail.error:
            raise BadRequest(f"메일함을 읽지 못했어요: {self.mail.error}")
        return n

    # ---- 스크립트 -----------------------------------------------------------------
    def reload_cases(self) -> tuple[int, list[str]]:
        """스크립트와 시나리오 파일을 다시 읽는다 (둘 다 레포 main 이 원본이고 같은 저장 흐름을 탄다)."""
        self.features, self.scenario_errors = scenariosmod.load_dir(self.scenarios_dir)
        self.cases, self.case_errors = load_dir(self.cases_dir)
        audit_cases(self.cases, self.catalog.get())
        if hasattr(self, "runner"):
            self.runner.cases = self.cases
        return len(self.cases), self.case_errors

    def current_catalog(self):
        """테스트 조건 목록을 돌려주고, 입력이 바뀌어 다시 계산됐으면 스크립트 정합성 검사도 다시 한다."""
        before = self.catalog.current
        cat = self.catalog.get()
        if cat is not None and (before is None or cat.key != before.key):
            audit_cases(self.cases, cat)
        return cat

    def coverage(self, cat) -> dict:
        """테스트 조건 id → 검증하는 스크립트 id 목록, 도메인×층 매트릭스. 분모는 전체 테스트 조건, 제외는 따로 센다 (§6.2)."""
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

    # ---- 시나리오 (docs/qa-platform-scenarios.md) ------------------------------------------
    def scenario_view(self) -> tuple[list[dict], dict]:
        """(기능별 트리, §6.1 검증 결과). 저장하지 않고 요청마다 계산한다 — 스크립트·테스트 조건 목록·PRD 가 바뀌면 바로 따라간다."""
        cat = self.current_catalog()
        ov = scenariosmod.overview(self.features, wiki=self.wiki, catalog=cat, cases=self.cases, last=self.store.last_verdicts(), ssot=self.ssot())
        chk = scenariosmod.check(self.features, wiki=self.wiki, catalog=cat, cases=self.cases)
        chk["errors"] = list(self.scenario_errors) + chk["errors"]
        return ov, chk

    def scenario_ctx(self, slug: str, sid: str) -> tuple[dict, dict]:
        """폼이 쓰는 (기능, 시나리오) 화면 데이터. PRD 2장에 없는 시나리오는 폼으로 만들지 않는다."""
        ov, _ = self.scenario_view()
        f = next((x for x in ov if x["slug"] == slug), None)
        s = next((x for x in (f or {}).get("scenarios", []) if x["id"] == sid), None)
        if not f or not s:
            raise BadRequest("그 기능·시나리오가 없다")
        if not s["in_prd"]:
            raise BadRequest(f"{sid} 가 PRD 2장에 없다 — 시나리오는 PRD 가 정한다")
        return f, s

    def tc_options(self) -> list[tuple[str, str]]:
        cat = self.current_catalog()
        return [(r["id"], r["title"]) for r in (cat.records.values() if cat else []) if not r.get("excluded")]

    def ssot(self) -> dict | None:
        """위키 규칙표 조립본. 파일이 바뀔 때만 다시 읽는다 (PRD·규칙표 변경 표시에 쓴다)."""
        if not self.wiki.available:
            return None
        try:
            mt = self.wiki.ssot_path.stat().st_mtime
            if getattr(self, "_ssot_cache", (None, None))[0] != mt:
                self._ssot_cache = (mt, self.wiki.read_ssot()[0])
            return self._ssot_cache[1]
        except Exception:
            return None

    def with_basis(self, op: dict, new_text: str) -> dict:
        """저장할 변경에 손댄 시나리오의 지문을 붙인다 (§10). 위키가 없으면 붙이지 않는다."""
        ssot = self.ssot()
        if ssot is None or not new_text:
            return op
        ft = scenariosmod.parse_feature(draftsmod.yaml.safe_load(new_text), f"{scenariosmod.doc_slug(op['feature'])}.yaml")
        sids = [str(x["id"]) for x in op.get("scenarios") or []] if op["action"] == "merge" else ([] if op["action"] == "scenario-delete" else [op["scenario"]])
        steps = {s["id"]: s["steps"] for s in self.wiki.prd_scenarios(ft.feature)}
        sidx = scenariosmod.ssot_index(ssot)
        basis = {sid: scenariosmod.basis_of(ft.scenario(sid), steps.get(sid) or [], sidx) for sid in sids if ft.scenario(sid)}
        return {**op, "basis": basis} if basis else op

    def run_groups(self, rcs: list[dict]) -> tuple:
        """실행 결과를 기능 · 시나리오 · 케이스로 묶는다 (§11). 시나리오 제목은 PRD 2장에서."""
        titles = {}
        if self.wiki.available:
            for slug in {str((draftsmod.yaml.safe_load(rc.get("case_yaml") or "") or {}).get("variant") or "").split("/")[0] for rc in rcs} - {""}:
                for s in self.wiki.prd_scenarios(slug.replace("-", " ")):
                    titles[(slug, s["id"])] = s["title"]
        return scenariosmod.group_run_cases(rcs, self.features, titles)

    def gate_names(self) -> dict:
        cat = self.catalog.current
        return {r["gate"]: r.get("gate_name") or "" for r in (cat.records.values() if cat else []) if r.get("gate")}

    def drift_of(self, case) -> list[dict]:
        return self.catalog.drift_for(case.covers, (case.reviewed or {}).get("at"))

    def op_of(self, method: str, path: str) -> str | None:
        """method + 경로(템플릿 `{{x}}` 든 채워진 값이든) → operationId. 러너가 단계 기록에, 조회가 옛 기록 폴백에 쓴다."""
        spec = self.spec.get()
        op = spec.op_for(method, path) if spec else None
        return op.id if op else None

    def scripts_by_op(self) -> dict[str, dict]:
        """operationId → {"calls": {case_id: [단계 이름]}, "declared": [case_id]} — 단계의 method/path 로 판별, `operations:` 선언은 따로."""
        out: dict[str, dict] = {}
        for c in self.cases.values():
            for st in c.own_steps:            # 전제 카드 단계는 이 스크립트가 확인하는 호출이 아니다
                req = st.get("request") or {}
                oid = self.op_of(req.get("method", ""), req.get("path", "")) if req.get("method") and req.get("path") else None
                if oid:
                    out.setdefault(oid, {"calls": {}, "declared": []})["calls"].setdefault(c.id, []).append(st.get("name") or "")
            for oid in c.operations:
                out.setdefault(oid, {"calls": {}, "declared": []})["declared"].append(c.id)
        return out

    def _resolve_unresolved_calls(self, limit: int = 300) -> dict[str, list[dict]]:
        """op_id 가 없는 옛 단계를 method/path 로 매칭해 op 별로 나눈다 (백필 없음, 조회 때만)."""
        out: dict[str, list[dict]] = {}
        for row in self.store.calls_unresolved(limit):
            oid = self.op_of(row.get("method") or "", row.get("path") or "")
            if oid:
                out.setdefault(oid, []).append(row)
        return out

    def api_overview(self) -> tuple[list[dict], object]:
        """API 목록 한 행씩 (docs/qa-platform-api.md §5.1). (rows, catalog). OpenAPI 가 없으면 ([], None)."""
        spec = self.spec.get()
        if not spec:
            return [], None
        cat = self.current_catalog()
        by_op = cat.by_operation() if cat else {}
        by_tc = self.coverage(cat)["by_tc"] if cat else {}
        scripts = self.scripts_by_op()
        last = self.store.last_call_by_op()
        old = self._resolve_unresolved_calls()
        recent = self.store.recent_op_results(20)
        rows = []
        for op in sorted(spec.ops.values(), key=lambda o: (o.path, o.method)):
            if not (op.path.startswith("/v1/") or op.path.startswith("/actuator")) or op.path.startswith("/v1/dev/"):
                continue
            ids = by_op.get(op.id, [])
            layers = {"contract": 0, "policy": 0, "manual": 0}
            covered = excluded = 0
            for i in ids:
                rec = cat.records.get(i) or {}
                layers[rec.get("layer", "manual")] = layers.get(rec.get("layer", "manual"), 0) + 1
                if rec.get("excluded"):
                    excluded += 1
                elif by_tc.get(i):
                    covered += 1
            sc = scripts.get(op.id) or {"calls": {}, "declared": []}
            lc = last.get(op.id)
            if lc is None and old.get(op.id):
                lc = old[op.id][0]
            rows.append({"id": op.id, "method": op.method, "path": op.path, "summary": op.summary, "domain": domain_of_path(op.path),
                         "tc": len(ids), "layers": layers, "covered": covered, "excluded": excluded, "uncovered": len(ids) - covered - excluded,
                         "scripts": len(sc["calls"]), "errors": len(op.errors), "last": lc,
                         "stats": ui.stats_of(recent.get(op.id) or [], same_hash=False)})
        return rows, cat

    def api_detail(self, op_id: str) -> dict | None:
        """API 하나의 모아 보기 (docs/qa-platform-api.md §5.2): 스펙 · 층별 테스트 조건 · 부르는 스크립트 · 최근 호출 20건. 화면·JSON·MCP 도구 공용."""
        spec = self.spec.get()
        op = spec.ops.get(op_id) if spec else None
        if not op:
            return None
        cat = self.current_catalog()
        qa = self.op_qa(op.id) or {"tc": 0, "covered": 0, "excluded": 0, "uncovered": 0, "ids": [], "scripts": [], "last": None}
        by_tc = self.coverage(cat)["by_tc"] if cat else {}
        last_v = self.store.last_verdicts()
        tcs: dict[str, list[dict]] = {"contract": [], "policy": [], "manual": []}
        for i in qa["ids"]:
            rec = cat.records.get(i) if cat else None
            if not rec:
                continue
            cov = by_tc.get(i, [])
            tcs.setdefault(rec["layer"], []).append({"id": i, "title": rec.get("title"), "kind": rec.get("kind"), "excluded": rec.get("excluded"),
                                                     "error_code": (rec.get("binding") or {}).get("error_code") or (rec.get("expect_hint") or {}).get("error_code"),
                                                     "scripts": cov, "last": {cid: last_v[cid] for cid in cov if cid in last_v}})
        sc = self.scripts_by_op().get(op.id) or {"calls": {}, "declared": []}
        scripts = []
        for cid, names in sc["calls"].items():
            c = self.cases.get(cid)
            scripts.append({"id": cid, "title": c.title if c else "", "suite": c.suite if c else "", "steps": names,
                            "declared": cid in sc["declared"], "last": last_v.get(cid)})
        for cid in sc["declared"]:
            if cid not in sc["calls"]:
                c = self.cases.get(cid)
                scripts.append({"id": cid, "title": c.title if c else "", "suite": c.suite if c else "", "steps": [], "declared": True, "last": last_v.get(cid)})
        recent = self.store.calls_for_op(op.id, 20)
        if len(recent) < 20:
            recent = (recent + self._resolve_unresolved_calls().get(op.id, []))[:20]
        return {"op": {"id": op.id, "method": op.method, "path": op.path, "summary": op.summary, "domain": domain_of_path(op.path), "params": op.params,
                       "request_example": op.request_example, "success": op.success,
                       "errors": {code: {"status": i.get("status"), "message": i.get("message")} for code, i in op.errors.items()}},
                "qa": qa, "tcs": tcs, "scripts": scripts, "recent_calls": recent,
                "stats": ui.stats_of(self.store.recent_op_results(20).get(op.id) or [], same_hash=False),
                "docs_url": (self.cfg.spec_docs_url + "#" + ui.restdocs_anchor(op.summary)) if (self.cfg.spec_docs_url and op.summary) else None,
                "spec_hash": spec.hash}

    def op_qa(self, op_id: str) -> dict | None:
        """API 하나의 검증 상태 요약 — 호출 카드의 QA 배지(docs/qa-platform-api.md §5.6). 테스트 조건 목록이 없으면 None.
        {tc, covered, excluded, uncovered, ids, scripts, last: {verdict, run_id, created_at, case_id}|None}"""
        cat = self.current_catalog()
        if cat is None:
            return None
        ids = cat.by_operation().get(op_id, [])
        by_tc = self.coverage(cat)["by_tc"]
        last_v = self.store.last_verdicts()
        covered = excluded = 0
        scripts: list[str] = []
        for i in ids:
            rec = cat.records.get(i) or {}
            if rec.get("excluded"):
                excluded += 1
            elif by_tc.get(i):
                covered += 1
            for cid in by_tc.get(i, []):
                if cid not in scripts:
                    scripts.append(cid)
        last = None
        for cid in scripts:
            lv = last_v.get(cid)
            if lv and (last is None or lv["created_at"] > last["created_at"]):
                last = dict(lv)
        return {"tc": len(ids), "covered": covered, "excluded": excluded, "uncovered": len(ids) - covered - excluded,
                "ids": ids, "scripts": scripts, "last": last}

    # ---- 트리거 준비: 사람에게 보여줄 제안 ------------------------------------------
    def suggest(self, trigger: str, sha: str | None, pr: int | None) -> tuple[list, str, dict]:
        """반환: (제안 스크립트, 근거 문장, 대상 정보)."""
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
                return select(self.cases, suite="sanity"), f"PR #{pr} 도메인 {', '.join(domains)} 에 맞는 스크립트가 없어 sanity 전체", info
            why = "PR 을 찾지 못함" if not pr else "변경 파일에서 도메인을 못 읽음"
            return select(self.cases, suite="sanity"), f"{why} → sanity 전체 (보수 폴백)", info
        if trigger in ("sprint-smoke", "release"):
            cs = select(self.cases, suite="smoke")
            return cs, f"smoke 스위트 전체 {len(cs)}개", info
        if trigger == "manual":
            return [], "직접 고른다", info
        raise BadRequest(f"모르는 실행 종류: {trigger}")

    # ---- 런 생성 (form / API 공용) --------------------------------------------------
    def create_run(self, *, trigger: str, operator: str, case_ids: list[str], sha: str | None, ref: str | None,
                   pr_number: int | None, deploy_run_id: str | None, reason: str, basis: str, extra: dict,
                   session_hash: str | None, ip: str | None, cases_override: list | None = None,
                   notify: bool = True, enqueue: bool = True) -> str:
        if trigger not in TRIGGERS:
            raise BadRequest(f"모르는 실행 종류: {trigger}")
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        chosen = list(cases_override) if cases_override else [self.cases[c] for c in case_ids if c in self.cases]
        if not chosen:
            raise BadRequest("스크립트를 하나 이상 골라야 한다")
        suite = chosen[0].suite if len({c.suite for c in chosen}) == 1 else None
        cat = self.catalog.current
        meta = {"basis": basis, "reason": reason, "deploy_run_id": deploy_run_id, "case_ids": [c.id for c in chosen], "target": self.target_for(operator)["name"],
                "catalog": (cat.versions if cat else None),   # 이 런의 TC 소스 버전 (§6.3). 과거 런은 다시 해석하지 않는다
                "covers": sorted({t for c in chosen for t in c.covers})}
        meta.update({k: v for k, v in extra.items() if v not in (None, "")})
        rid = self.store.create_run(trigger=trigger, operator=operator, suite=suite, env=self.cfg.target_env,
                                    base_url=self.target_for(operator)["base_url"], ref=ref or self.cfg.backend_branch, sha=sha,
                                    pr_number=pr_number, meta=meta, cases=chosen)
        self.store.add_event(operator=operator, action="run.create", target=rid, session_hash=session_hash, ip=ip,
                             detail={"trigger": trigger, "sha": sha, "pr": pr_number, "cases": len(chosen), "basis": basis, "reason": reason})
        if enqueue:
            self.runner.submit(rid)
        if notify:
            tgt = f"sha {sha[:8]}" + (f" PR #{pr_number}" if pr_number else "") if sha else self.cfg.target_env
            slack(self.cfg.slack_webhook_url, f"[QA] {operator} 가 {ui.TRIGGER_KO.get(trigger, trigger)} 실행 — {tgt}, {len(chosen)}건 · {self.cfg.public_url}/runs/{rid}")
        return rid

    # ---- Hermes 가 만들고 바로 저장 (docs/qa-platform-scenarios.md §9) --------------------------------
    def generate_cases(self, *, tc_ids: list[str], operator: str, session_hash: str | None, ip: str | None, ask=None, variant: str | None = None) -> dict:
        """고른 테스트 조건으로 Hermes 가 스크립트를 쓰고, 검증을 통과한 것은 바로 저장한다(Hermes 작성 표시).
        variant 가 있으면 케이스 화면의 [Hermes 로 스크립트 만들기] — 케이스의 제목·전제·기대 결과·분기·거절이 일어나는 단계와 테스트 데이터 만들기 카드를 근거에 더하고 variant: 를 박는다."""
        cat = self.current_catalog()
        if cat is None:
            raise BadRequest("테스트 조건 목록이 없어 스크립트를 만들 수 없다")
        tc_ids = [t for t in dict.fromkeys(tc_ids) if t in cat.records]
        if not tc_ids:
            raise BadRequest("테스트 조건 목록에 있는 테스트 조건을 하나 이상 골라야 한다")
        if variant:     # 변형의 checks 에 묶인 API 계약 TC 도 같이 요청한다 — 거절이면 그 코드, 성공이면 2xx (계약 대조가 결정론으로 확인한다)
            for t in list(tc_ids):
                b = cat.records[t].get("binding") or {}
                for o in b.get("operations") or []:
                    code = b.get("error_code")
                    tc_ids += [r["id"] for r in cat.records.values() if r["layer"] == "contract" and r.get("operation") == o and r["id"] not in tc_ids
                               and (r["id"].endswith(":" + code) if code else r["id"].rsplit(":", 1)[-1].startswith("2"))]
        if len(tc_ids) > 10:
            raise BadRequest("한 번에 10건까지")
        example = self.cases.get("room.create") or next(iter(self.cases.values()), None)
        try:
            res = draftsmod.generate(cfg=self.cfg, catalog=cat, spec=self.spec.get(), wiki=self.wiki, tc_ids=tc_ids,
                                     example=example, existing_ids=set(self.cases), ask=ask, library=self.cases,
                                     extra=self.variant_context(variant) if variant else None, variant=variant)
        except Exception as ex:
            self.store.add_event(operator=operator, action="hermes.generate", target=None, session_hash=session_hash, ip=ip,
                                 detail={"tc_ids": tc_ids, "error": str(ex)[:300]})
            raise BadRequest(f"스크립트 생성 실패: {ex}")
        saved, rejected = [], list(res["rejected"])
        for raw_id, errors in res["rejected"]:
            self.store.add_event(operator=operator, action="hermes.rejected_by_validation", target=None, session_hash=session_hash, ip=ip,
                                 detail={"case_id": raw_id, "errors": errors[:6], "prompt_hash": res["prompt_hash"]})
        for case, warnings in res["accepted"]:
            try:
                saved.append(self.save_change(kind="case", source="hermes", yaml_text=case.to_yaml(), operator=operator,
                                              domain=(case.domains[0] if case.domains else cat.records[tc_ids[0]]["domain"]), case_id=case.id, tc_ids=case.covers,
                                              validation={"status": case.audit["status"], "warnings": warnings}, prompt_hash=res["prompt_hash"],
                                              session_hash=session_hash, ip=ip))
            except BadRequest as ex:
                rejected.append((case.id, [str(ex)]))
        self.store.add_event(operator=operator, action="hermes.generate", target=",".join(s["id"] for s in saved) or None, session_hash=session_hash, ip=ip,
                             detail={"tc_ids": tc_ids, "model": res["model"], "prompt_hash": res["prompt_hash"], "prompt_chars": res["prompt_chars"],
                                     "saved": [s["case_id"] for s in saved], "rejected": len(rejected), "raw_chars": len(res["raw"])})
        return {"saved": saved, "rejected": rejected, "prompt_hash": res["prompt_hash"]}

    def variant_context(self, vid: str) -> str:
        """케이스에서 스크립트를 만들 때 근거에 더하는 절 (docs/qa-platform-scenarios.md §7)."""
        hit = scenariosmod.variant_index(self.features).get(vid)
        if not hit:
            raise BadRequest(f"케이스 {vid} 가 시나리오 파일에 없다")
        ft, sc, va = hit
        step = next((st for s in (self.wiki.prd_scenarios(ft.feature) if self.wiki.available else []) if s["id"] == sc.id
                     for st in s["steps"] if st.get("req") == va.at), None)
        cards = [{"id": c.id, "title": c.title, "description": c.description, "inputs": {k: v.get("default") for k, v in c.inputs.items()}, "outputs": c.outputs,
                  "steps": [s["name"] for s in c.steps]} for c in self.setup_cases()]
        lines = [f"# 이 스크립트가 구현할 케이스 {vid}", f"- 종류: {scenariosmod.KIND_KO.get(va.kind, va.kind)}", f"- 제목: {va.title}"]
        if va.at:
            lines.append(f"- 분기·거절이 일어나는 단계: {va.at} {(step or {}).get('text') or ''}".rstrip())
        if va.given:
            lines.append(f"- 전제: {va.given}")
        if va.then:
            lines.append(f"- 기대 결과: {va.then}")
        lines.append(f"- 기본 테스트 계정: {sc.actor or '(없음)'}")
        lines.append("- 스크립트 하나만 쓴다. `variant:` 는 플랫폼이 채운다.")
        return "\n".join(lines) + "\n\n# 테스트 데이터 만들기 카드 (uses 로 받을 수 있는 테스트 데이터 만들기 카드)\n```json\n" + json.dumps(cards, ensure_ascii=False, indent=1) + "\n```"

    def fill_scenarios(self, slug: str, *, operator: str, session_hash=None, ip=None, ask=None) -> dict:
        """[Hermes 로 케이스 채우기] (§7). 출력은 합친다 — 이미 있는 케이스와 적힌 gates 는 그대로, 새 케이스와 빈 단계의 gates 만 더한다.
        §6.1 검증에 막히면 오류를 붙여 한 번 더 묻고, 그래도 막히면 저장하지 않고 실패로 끝난다."""
        from qa import scenario_ai
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not self.wiki.available:
            raise BadRequest("위키 체크아웃이 없어 PRD 를 읽을 수 없다")
        ov, _ = self.scenario_view()
        f = next((x for x in ov if x["slug"] == slug), None)
        if not f:
            raise BadRequest("그 기능이 없다")
        ssot, _ = self.wiki.read_ssot()
        ft = self.features.get(slug)
        prompt, phash = scenario_ai.assemble_fill(doc=f["feature"], wiki=self.wiki, ssot=ssot, catalog=self.current_catalog(), spec=self.spec.get(),
                                                  feature=ft, ov_feature=f)
        asker = draftsmod._asker(self.cfg, ask)
        text, errors, op, new = asker(scenario_ai.FILL_SYSTEM, prompt, "qa-scenario"), [], None, None
        for attempt in (0, 1):
            try:
                op = scenario_ai.merge_op(f["feature"], scenario_ai.parse_fill(text), ft)
                if attempt == 1:       # 두 번째에도 목록에 없는 테스트 조건 id 가 남으면 플랫폼이 뺀다 (운영 기록: 케이스 채우기 실패의 대부분)
                    op = {**op, "scenarios": [self._drop_unknown_checks(s) for s in op["scenarios"]]}
                new, errors, _ = self.scenario_check(op)
            except scenariosmod.ScenarioError as ex:
                errors = [str(ex)]
            if not errors:
                break
            self.store.add_event(operator=operator, action="hermes.rejected_by_validation", target=slug, session_hash=session_hash, ip=ip,
                                 detail={"source": "hermes-scenario", "attempt": attempt + 1, "errors": errors[:6], "prompt_hash": phash})
            if attempt == 0:
                text = asker(scenario_ai.FILL_SYSTEM, prompt + "\n\n# 앞 출력이 검증에서 막혔다. 아래 오류를 고쳐 다시 낸다\n"
                             + "\n".join(f"- {x}" for x in errors[:12]) + "\n\n# 앞 출력\n" + text[:20000], "qa-scenario")
        if errors:
            raise BadRequest("Hermes 결과가 검증을 못 넘겼다 — 저장하지 않았다: " + "; ".join(errors[:3]))
        p = self.scenarios_dir / f"{slug}.yaml"
        added = sum(len(s["variants"]) for s in op["scenarios"])
        if new == (p.read_text(encoding="utf-8") if p.is_file() else None) or not new:
            self.store.add_event(operator=operator, action="hermes.generate", target=slug, session_hash=session_hash, ip=ip,
                                 detail={"source": "hermes-scenario", "prompt_hash": phash, "added": 0})
            return {"ok": True, "added": 0, "saved": None}
        out = self.save_scenario(op, operator=operator, source="hermes-scenario", prompt_hash=phash, session_hash=session_hash, ip=ip)
        self.store.add_event(operator=operator, action="hermes.generate", target=slug, session_hash=session_hash, ip=ip,
                             detail={"source": "hermes-scenario", "prompt_hash": phash, "prompt_chars": len(prompt), "added": added, "change": out.get("id")})
        return {**out, "added": added, "saved": out}

    def realign_scenario(self, slug: str, sid: str, *, operator: str, session_hash=None, ip=None, ask=None) -> dict:
        """[Hermes 로 다시 맞추기] (§10). 바뀐·없어진 문장에 걸린 케이스만 Hermes 판으로 바꾸고 지문을 새로 적는다."""
        from qa import scenario_ai
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        f, s = self.scenario_ctx(slug, sid)
        dr = s.get("drift")
        if not dr or not (dr["changed"] or dr["removed"] or dr["added"]):
            raise BadRequest("지난 저장 뒤 PRD·규칙표에서 바뀐 것이 없다")
        ft = self.features[slug]
        keys, reqs = scenario_ai.affected(ft.scenario(sid), dr)
        valid, stale = self._realign_checks(f["feature"], ft.scenario(sid))
        keys += [k for k in stale if k not in keys]          # 옛 id 를 가리키는 케이스도 고친다 (API 이름이 바뀌었을 때)
        if not keys and not reqs:
            raise BadRequest("바뀐 것에 걸린 케이스가 없다 — [변경 확인만 하기] 를 누르면 된다")
        prompt, phash = scenario_ai.assemble_realign(doc=f["feature"], wiki=self.wiki, ssot=self.ssot() or {}, feature=ft, sid=sid, drift=dr, keys=keys, reqs=reqs,
                                                     valid=valid, stale=stale)
        asker = draftsmod._asker(self.cfg, ask)
        text, errors, op = asker(scenario_ai.REALIGN_SYSTEM, prompt, "qa-realign"), [], None
        for attempt in (0, 1):
            try:
                op = scenario_ai.revise_op(f["feature"], sid, scenario_ai.parse_realign(text, sid), ft, keys, reqs)
                if attempt == 1:
                    op = self._drop_unknown_checks(op)      # 두 번째에도 옛 id 가 남으면 플랫폼이 뺀다
                _, errors, _ = self.scenario_check(op)
            except scenariosmod.ScenarioError as ex:
                errors = [str(ex)]
            if not errors:
                break
            self.store.add_event(operator=operator, action="hermes.rejected_by_validation", target=f"{slug}/{sid}", session_hash=session_hash, ip=ip,
                                 detail={"source": "hermes-realign", "attempt": attempt + 1, "errors": errors[:6], "prompt_hash": phash})
            if attempt == 0:
                text = asker(scenario_ai.REALIGN_SYSTEM, prompt + "\n\n# 앞 출력이 검증에서 막혔다. 아래 오류를 고쳐 다시 낸다\n"
                             + "\n".join(f"- {x}" for x in errors[:12]) + "\n\n# 앞 출력\n" + text[:20000], "qa-realign")
        if errors:
            raise BadRequest("Hermes 결과가 검증을 못 넘겼다 — 저장하지 않았다: " + "; ".join(errors[:3]))
        out = self.save_scenario(op, operator=operator, source="hermes-realign", prompt_hash=phash, session_hash=session_hash, ip=ip)
        self.store.add_event(operator=operator, action="hermes.generate", target=f"{slug}/{sid}", session_hash=session_hash, ip=ip,
                             detail={"source": "hermes-realign", "prompt_hash": phash, "keys": keys, "reqs": reqs, "change": out.get("id")})
        return {**out, "keys": keys}

    def _realign_checks(self, doc: str, scenario) -> tuple[list[str], dict]:
        """다시 맞추기에 쓸 수 있는 테스트 조건 id(이 기능의 명령·게이트 검사와 그 API 계약)와, 케이스가 가리키는 옛 id {key: [id]}."""
        from qa import scenario_ai
        cat = self.current_catalog()
        if cat is None:
            return [], {}
        gates, cmds = scenario_ai.feature_rules(self.ssot() or {}, doc, {g for gl in scenario.gates.values() for g in gl})
        ids = [c["id"] for c in cmds] + [f"{g['id']}#{k.get('key')}" for g in gates for k in g.get("checks") or []]
        ops = {o for i in ids for o in ((cat.records.get(i) or {}).get("binding") or {}).get("operations") or []}
        ids += sorted(r for r, rec in cat.records.items() if rec.get("layer") == "contract" and rec.get("operation") in ops)
        valid = [i for i in dict.fromkeys(ids) if i in cat.records]
        stale = {v.key: [c for c in v.checks if c not in cat.records] for v in scenario.variants}
        return valid, {k: v for k, v in stale.items() if v}

    def _drop_unknown_checks(self, op: dict) -> dict:
        """케이스 checks 에서 테스트 조건 목록에 없는 id 를 뺀다. 하나도 안 남으면 사람이 확인(manual)으로 둔다."""
        cat = self.current_catalog()
        if cat is None:
            return op
        vs = []
        for v in op.get("variants") or []:
            checks = [c for c in v.get("checks") or [] if c in cat.records]
            if len(checks) != len(v.get("checks") or []):
                v = {**v, "checks": checks}
                if not checks:
                    v["mode"] = "manual"
            vs.append(v)
        return {**op, "variants": vs}

    def job_realign(self, slug: str, sid: str, operator: str, session_hash=None, ip=None, sync=False):
        from qa.ui_scn import feature_url

        def fn(job):
            out = self.realign_scenario(slug, sid, operator=operator, session_hash=session_hash, ip=ip, ask=job.ask)
            return {"summary": f"바뀐 문장에 맞춰 케이스 {len(out['keys'])}개를 고쳐 저장했다 (Hermes 작성 표시)", "links": [self.change_link(out)]}
        return self.start_job("realign", operator=operator, label=f"{slug}/{sid}", fn=fn, back={"href": feature_url(slug) + f"#{sid}", "label": f"{slug} {sid}"},
                              session_hash=session_hash, ip=ip, sync=sync)

    def job_fill(self, slug: str, operator: str, session_hash=None, ip=None, sync=False):
        from qa.ui_scn import feature_url

        def fn(job):
            out = self.fill_scenarios(slug, operator=operator, session_hash=session_hash, ip=ip, ask=job.ask)
            if not out["saved"]:
                return {"summary": "새로 더할 케이스나 gates 가 없었다", "links": [{"href": feature_url(slug), "label": slug}]}
            return {"summary": f"케이스 {out['added']}개와 빈 단계의 gates 를 채워 저장했다 (Hermes 작성 표시)", "links": [self.change_link(out)]}
        return self.start_job("scenario", operator=operator, label=slug, fn=fn, back={"href": feature_url(slug), "label": slug},
                              session_hash=session_hash, ip=ip, sync=sync)

    def job_variant_script(self, vid: str, operator: str, session_hash=None, ip=None, sync=False):
        """[Hermes 로 스크립트 만들기] — 케이스의 checks 로 스크립트를 쓰게 한다. checks 가 없으면 근거가 없어 막는다."""
        from qa.ui_scn import variant_url
        hit = scenariosmod.variant_index(self.features).get(vid)
        if not hit:
            raise BadRequest(f"케이스 {vid} 가 시나리오 파일에 없다")
        if not hit[2].checks:
            raise BadRequest("확인할 테스트 조건(checks)이 없는 케이스다 — 폼으로 checks 를 먼저 적는다")

        def fn(job):
            res = self.generate_cases(tc_ids=list(hit[2].checks), operator=operator, session_hash=session_hash, ip=ip, ask=job.ask, variant=vid)
            links = [self.change_link(s) for s in res["saved"]]
            rej = "; ".join(f"{rid}: {', '.join(errs[:2])}" for rid, errs in res["rejected"][:3])
            return {"summary": f"스크립트 {len(res['saved'])}건 저장" + (f", {len(res['rejected'])}건은 검증에서 버림 — {rej}" if res["rejected"] else ""), "links": links}
        return self.start_job("draft", operator=operator, label=vid, fn=fn, back={"href": variant_url(vid), "label": vid},
                              session_hash=session_hash, ip=ip, sync=sync)

    def propose_tc(self, *, doc: str, section: str, domain: str | None, operator: str, session_hash: str | None, ip: str | None, ask=None) -> dict:
        """PRD 절 본문을 Hermes 에게 주어 수동 작성 테스트 조건을 받고 manual-tc.yaml 에 바로 저장한다. docs/qa-platform-hermes.md §3 트리 4 (P4d)."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not doc.strip() or not section.strip():
            raise BadRequest("PRD 문서 이름과 절 번호가 필요하다")
        cat = self.current_catalog()
        if cat is None:
            raise BadRequest("테스트 조건 목록이 없어 제안을 만들 수 없다")
        try:
            res = draftsmod.propose_manual_tc(cfg=self.cfg, catalog=cat, wiki=self.wiki, doc=doc.strip(), section=section.strip(), domain=(domain or "").strip() or None, ask=ask)
        except ValueError as ex:
            raise BadRequest(str(ex))
        except Exception as ex:
            self.store.add_event(operator=operator, action="hermes.generate", target=None, session_hash=session_hash, ip=ip, detail={"source": "hermes-propose", "doc": doc, "section": section, "error": str(ex)[:300]})
            raise BadRequest(f"제안 실패: {ex}")
        if not res["records"]:
            self.store.add_event(operator=operator, action="hermes.generate", target=None, session_hash=session_hash, ip=ip,
                                 detail={"source": "hermes-propose", "doc": doc, "section": section, "prompt_hash": res["prompt_hash"], "items": 0})
            raise BadRequest("Hermes 가 이 절에서 제안할 테스트 조건을 찾지 못했다 (이미 뽑힌 것과 겹치거나 본문에 확인 항목이 없다)")
        text = draftsmod.yaml.safe_dump({"cases": res["records"]}, allow_unicode=True, sort_keys=False)
        out = self.save_change(kind="tc", source="hermes-propose", yaml_text=text, operator=operator, domain=res["domain"],
                               note=f"PRD/{doc.strip()} §{section.strip().rstrip('.')} 에서 Hermes 가 뽑은 수동 작성 테스트 조건",
                               tc_ids=[r["id"] for r in res["records"]], validation={"status": "warn" if res["warnings"] else "ok", "warnings": res["warnings"]},
                               prompt_hash=res["prompt_hash"], session_hash=session_hash, ip=ip)
        self.store.add_event(operator=operator, action="hermes.generate", target=out["id"], session_hash=session_hash, ip=ip,
                             detail={"source": "hermes-propose", "kind": "tc", "doc": doc, "section": section, "tc_ids": out["tc_ids"],
                                     "model": res["model"], "prompt_hash": res["prompt_hash"], "raw_chars": len(res["raw"])})
        return out

    def revise_case(self, case_id: str, *, operator: str, session_hash: str | None, ip: str | None, ask=None) -> dict:
        """테스트 조건이 바뀐 스크립트를 Hermes 가 바뀐 만큼만 고쳐 바로 저장한다(같은 id). docs/qa-platform-hermes.md §3.3."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        c = self.cases.get(case_id)
        if not c:
            raise BadRequest("없는 스크립트")
        cat = self.current_catalog()
        if cat is None:
            raise BadRequest("테스트 조건 목록이 없어 다시 쓸 수 없다")
        drift = self.drift_of(c)
        if not drift:
            raise BadRequest("바뀐 테스트 조건이 없다 — 고칠 것이 없다")
        try:
            res = draftsmod.revise(cfg=self.cfg, catalog=cat, spec=self.spec.get(), wiki=self.wiki, case=c, drift=drift, changes=self.catalog.changes, existing_ids=set(self.cases), ask=ask, library=self.cases)
        except Exception as ex:
            self.store.add_event(operator=operator, action="hermes.generate", target=None, session_hash=session_hash, ip=ip, detail={"source": "hermes-revise", "case_id": case_id, "error": str(ex)[:300]})
            raise BadRequest(f"다시 쓰기 실패: {ex}")
        summary = ", ".join(f"{d['id']} {d['kind']}" for d in drift[:8])
        if not res["accepted"]:
            self.store.add_event(operator=operator, action="hermes.rejected_by_validation", target=None, session_hash=session_hash, ip=ip,
                                 detail={"source": "hermes-revise", "case_id": case_id, "errors": res["errors"][:6], "prompt_hash": res["prompt_hash"]})
            raise BadRequest("Hermes 가 고친 스크립트가 검증을 못 넘겼다: " + "; ".join(res["errors"][:3]))
        case, warnings = res["accepted"]
        out = self.save_change(kind="case", source="hermes-revise", yaml_text=case.to_yaml(), operator=operator, domain=(c.domains[0] if c.domains else None),
                               note=f"바뀐 테스트 조건에 맞게 다시 씀 — {summary}", case_id=c.id, tc_ids=case.covers,
                               validation={"status": case.audit["status"], "warnings": warnings}, prompt_hash=res["prompt_hash"], session_hash=session_hash, ip=ip)
        self.store.add_event(operator=operator, action="hermes.generate", target=out["id"], session_hash=session_hash, ip=ip,
                             detail={"source": "hermes-revise", "case_id": c.id, "drift": [d["id"] for d in drift], "allowed": res["allowed"], "model": res["model"],
                                     "prompt_hash": res["prompt_hash"], "raw_chars": len(res["raw"]), "warnings": len(warnings)})
        return out

    def change_link(self, out: dict) -> dict:
        """저장 결과로 갈 곳. main 에 들어갔으면 그 스크립트·테스트 조건, 아니면(토큰 없음) 파일 받기가 있는 변경 기록."""
        if out.get("commit"):
            if out.get("kind") in ("scenario", "scenario-delete"):
                from qa.ui_scn import feature_url
                parts = (out.get("case_id") or "").split("/")
                if len(parts) == 3 and out["kind"] == "scenario":
                    return {"href": feature_url(*parts), "label": out["case_id"]}
                return {"href": feature_url(parts[0]) + (f"#{parts[1]}" if len(parts) > 1 else ""), "label": parts[0]}
            if out.get("case_id") and not out.get("deleted"):
                return {"href": f"/cases/{out['case_id']}", "label": out["case_id"]}
            if out.get("tc_ids") and not out.get("deleted"):
                return {"href": "/catalog/tc?id=" + quote(out["tc_ids"][0], safe=""), "label": out["tc_ids"][0] + (f" 외 {len(out['tc_ids']) - 1}건" if len(out["tc_ids"]) > 1 else "")}
        return {"href": f"/drafts/{out['id']}", "label": f"변경 {out['id']}" + ("" if out.get("commit") else " (파일 받기)")}

    # ---- Hermes 작업 (docs/qa-platform-progress.md) ------------------------------------------
    def start_job(self, kind: str, *, operator: str, label: str, fn, back: dict | None = None, session_hash=None, ip=None, sync: bool = False):
        """사람이 버튼을 눌렀을 때만 부른다. 누른 것 자체를 감사 로그에 남기고, 결과 이벤트는 각 기능이 남긴다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not self.cfg.hermes_key:
            raise BadRequest("HERMES_API_KEY 가 없어 Hermes 를 부를 수 없다")
        job = self.jobs.submit(kind, operator, label, fn, back=back, sync=sync)
        self.store.add_event(operator=operator, action="hermes_job.start", target=job.id, session_hash=session_hash, ip=ip,
                             detail={"kind": kind, "label": label[:200]})
        return job

    def job_generate(self, tc_ids: list[str], operator: str, session_hash=None, ip=None, sync=False):
        def fn(job):
            res = self.generate_cases(tc_ids=tc_ids, operator=operator, session_hash=session_hash, ip=ip, ask=job.ask)
            links = [self.change_link(s) for s in res["saved"]]
            rej = "; ".join(f"{rid}: {', '.join(errs[:2])}" for rid, errs in res["rejected"][:3])
            return {"summary": f"스크립트 {len(res['saved'])}건 저장" + (f", {len(res['rejected'])}건은 검증에서 버림 — {rej}" if res["rejected"] else ""), "links": links}
        return self.start_job("draft", operator=operator, label="테스트 조건 " + ", ".join(tc_ids[:5]) + (" …" if len(tc_ids) > 5 else ""), fn=fn,
                              back={"href": "/catalog", "label": "테스트 조건 목록"}, session_hash=session_hash, ip=ip, sync=sync)

    def job_propose(self, doc: str, section: str, domain: str, operator: str, session_hash=None, ip=None, sync=False):
        def fn(job):
            out = self.propose_tc(doc=doc, section=section, domain=domain, operator=operator, session_hash=session_hash, ip=ip, ask=job.ask)
            return {"summary": f"수동 작성 테스트 조건 {len(out['tc_ids'])}건을 저장했다", "links": [self.change_link(out)]}
        return self.start_job("propose", operator=operator, label=f"PRD/{doc} §{section}", fn=fn, back={"href": "/catalog", "label": "테스트 조건 목록"},
                              session_hash=session_hash, ip=ip, sync=sync)

    def job_revise(self, case_id: str, operator: str, session_hash=None, ip=None, sync=False):
        def fn(job):
            out = self.revise_case(case_id, operator=operator, session_hash=session_hash, ip=ip, ask=job.ask)
            return {"summary": "바뀐 테스트 조건에 맞게 고쳐 저장했다", "links": [self.change_link(out)]}
        return self.start_job("revise", operator=operator, label=case_id, fn=fn, back={"href": f"/cases/{case_id}", "label": case_id},
                              session_hash=session_hash, ip=ip, sync=sync)

    def triage_rules(self, steps: list[dict]) -> str | None:
        """실패 분석에 줄 규칙표 설명 (2026-09-25: 멱등 생성이 기존 확정 룸을 돌려준 것을 Hermes 가 버그로 판정했다).
        처음 실패한 단계가 부른 API(op)에 묶인 명령의 이름·수행자·멱등 여부·메모와 그 게이트의 검사(메시지·코드)."""
        bad = next((s for s in steps if s["verdict"] not in ("pass",)), None)
        op = (bad or {}).get("op_id") or (self.op_of(bad["request"].get("method", ""), bad["request"].get("path", "")) if bad else None)
        ssot, cat = self.ssot(), self.catalog.current
        if not op or not ssot or cat is None:
            return None
        cids = [r["id"] for r in cat.records.values() if r["id"].startswith("C.") and op in ((r.get("binding") or {}).get("operations") or [])]
        cmds = {c["id"]: c for c in ssot.get("commands") or []}
        gates = {g["id"]: g for g in ssot.get("gates") or []}
        out = []
        for cid in cids:
            c = cmds.get(cid)
            if not c:
                continue
            out.append(f"- 명령 {cid} {c.get('name') or ''} · 수행자 {c.get('performer') or c.get('actor') or '-'}"
                       + (" · 멱등(같은 요청이면 새로 만들지 않는다)" if c.get("idempotent") else "") + (f"\n  메모: {' '.join(str(c['note']).split())[:600]}" if c.get("note") else ""))
            g = gates.get(c.get("gate") or "")
            if g:
                out += [f"  - 검사 {g['id']}#{k.get('key')}: {k.get('message') or k.get('ref') or ''}" + (f" ({k['error']})" if k.get("error") else "")
                        for k in g.get("checks") or []]
        return "\n".join(out)[:4000] or None

    def job_triage(self, run: dict, rc: dict, operator: str, session_hash=None, ip=None, sync=False):
        rid = run["id"]

        def fn(job):
            try:
                steps = self.store.list_steps(rc["id"])
                text = hermes_triage(self.cfg, run, rc, steps, ask=job.ask, rules=self.triage_rules(steps))
            except Exception as ex:
                self.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=session_hash, ip=ip,
                                     detail={"case": rc["case_id"], "error": str(ex)[:300], "job": job.id})
                raise
            self.store.update_run_case(rc["id"], triage=text, triaged_at=now_iso())
            self.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=session_hash, ip=ip,
                                 detail={"case": rc["case_id"], "chars": len(text), "job": job.id})
            return {"summary": f"실패 분석을 {rc['case_id']} 에 기록했다", "links": [{"href": f"/runs/{rid}", "label": f"실행 {rid}"}]}
        return self.start_job("triage", operator=operator, label=f"{rid} · {rc['case_id']}", fn=fn, back={"href": f"/runs/{rid}", "label": f"실행 {rid}"},
                              session_hash=session_hash, ip=ip, sync=sync)

    # ---- Sanity (docs/qa-platform-v2.md §4) -------------------------------------------------
    SANITY_MAX_SCRIPTS = 12          # 한 번에 Hermes 가 새로 쓰는 스크립트 수 상한 — 나머지는 다음 Sanity 나 케이스 화면에서

    def sanity_pr(self, number: int) -> dict:
        pr = self.github.pr(number)
        if not pr:
            raise BadRequest(f"PR #{number} 를 GitHub 에서 읽지 못했다" + (f" — {self.github.last_error}" if self.github.last_error else ""))
        return {**pr, **sanitymod.summarize(self.github.pr_file_details(number))}

    def sanity_start(self, number: int, *, operator: str, session_hash=None, ip=None, sync: bool = False) -> str:
        """[Sanity 시작] — 사람이 누른 이 한 번이 다섯 단계 전체의 시작이다 (§4.1). 머지로 저절로 시작하는 길은 없다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not self.cfg.hermes_key:
            raise BadRequest("HERMES_API_KEY 가 없어 Sanity 를 돌릴 수 없다")
        last = self.store.latest_sanity().get(number)
        if last and last["status"] in ("queued", "running"):
            raise BadRequest("이 PR 의 Sanity 가 이미 돌고 있다")
        pr = self.sanity_pr(number)
        sid = self.store.add_sanity(pr_number=number, pr_title=pr["title"], sha=pr.get("sha"), operator=operator)
        self.store.add_event(operator=operator, action="sanity.start", target=sid, session_hash=session_hash, ip=ip, detail={"pr": number, "sha": pr.get("sha")})
        self._sanity_job(sid, 1, operator=operator, session_hash=session_hash, ip=ip, sync=sync)
        return sid

    def _sanity_job(self, sid: str, from_step: int, *, operator: str, session_hash=None, ip=None, sync: bool = False):
        s = self.store.get_sanity(sid)
        self.store.update_sanity(sid, status="queued", error=None)
        job = self.start_job("sanity", operator=operator, label=f"PR #{s['pr_number']} · {from_step}단계부터",
                             fn=lambda job: self.sanity_run(sid, job, from_step, operator=operator, session_hash=session_hash, ip=ip),
                             back={"href": f"/sanity/{s['pr_number']}", "label": f"PR #{s['pr_number']}"}, session_hash=session_hash, ip=ip, sync=sync)
        self.store.update_sanity(sid, job_id=job.id)
        return job

    def sanity_run(self, sid: str, job, from_step: int, *, operator: str, session_hash=None, ip=None) -> dict:
        """다섯 단계를 차례로 (§4.2). 2단계에서 사람이 정할 것이 나오면 멈춘다. 단계마다 기록(log)과 감사 로그를 남긴다."""
        import time
        from qa import hermes as hermesmod
        s = self.store.get_sanity(sid)
        log = list(s["log"])

        def note(step: int, text: str, **kw):
            log.append({"at": now_iso(), "step": step, "text": text, **kw})
            self.store.update_sanity(sid, log=log, step=step)
            job.set_stage(f"{step}. {sanitymod.STEPS[step - 1]}", note=text)

        def ask(system: str, prompt: str, prefix: str) -> str:      # 호출마다 제한 시간을 새로 — 여러 번 부르는 긴 작업이라
            if job.cancel.is_set():
                raise hermesmod.Canceled("그만둠")
            return self.jobs.asker(self.cfg, system, prompt, session_prefix=prefix, on_event=job._on_event, cancel=job.cancel,
                                   deadline=time.monotonic() + self.cfg.job_timeout, stall=self.cfg.job_stall)
        self.store.update_sanity(sid, status="running")
        n = s["pr_number"]
        link = [{"href": f"/sanity/{n}", "label": f"PR #{n} Sanity"}]
        try:
            pr = self.github.pr(n) or {"number": n, "title": s["pr_title"], "sha": s["sha"], "body": "", "url": None}
            files = self.github.pr_file_details(n)
            scope, findings = s["scope"] or {}, list(s["findings"])
            if from_step <= 1:
                job.set_stage("1. 관련 스펙 찾기")
                scope = self._sanity_scope(pr, files, ask)
                self.store.update_sanity(sid, scope=scope)
                items = scope["items"]
                note(1, f"기능 {len({x['feature'] for x in items})}개 · 시나리오 {len(items)}개 · 요구 {sum(len(x['reqs']) for x in items)}개"
                     if items else "이 PR 이 닿는 사용자 기능이 없어요")
                if not items:
                    self.store.update_sanity(sid, status="empty", finished_at=now_iso())
                    return {"summary": "관련 스펙이 없어 확인할 것이 없어요", "links": link}
            if from_step <= 2:
                job.set_stage("2. 스펙 점검")
                findings = self._sanity_findings(pr, files, scope, ask)
                self.store.update_sanity(sid, findings=findings)
                blocking = [f for f in findings if f["kind"] in sanitymod.BLOCKING and not f.get("resolved_at")]
                note(2, f"확인 필요 {len(blocking)}건" if blocking else "사람이 정할 것이 없어요")
                if blocking:
                    self.store.update_sanity(sid, status="needs_spec")
                    slack(self.cfg.slack_webhook_url, f"[QA] PR #{n} Sanity — 스펙 확인이 {len(blocking)}건 필요해요 · {self.cfg.public_url}/sanity/{n}")
                    return {"summary": f"스펙 확인이 {len(blocking)}건 필요해요. 정한 뒤 이어서 할 수 있어요", "links": link}
            blocked = {r for f in findings if f["kind"] in sanitymod.BLOCKING and f.get("resolution") == "continued" for r in f.get("reqs") or []}
            if from_step <= 3:
                job.set_stage("3. 케이스 준비")
                note(3, self._sanity_prepare(scope, operator=operator, ask=ask, session_hash=session_hash, ip=ip))
            if from_step <= 4:
                job.set_stage("4. 스크립트 만들기")
                note(4, self._sanity_scripts(scope, blocked, operator=operator, ask=ask, session_hash=session_hash, ip=ip))
            job.set_stage("5. 실행·검사")
            rid, text = self._sanity_execute(s, pr, scope, findings, operator=operator, job=job, ask=ask, session_hash=session_hash, ip=ip)
            run = self.store.get_run(rid) if rid else None
            status = "empty" if not run else ("passed" if run.get("verdict") == "pass" else "failed")
            self.store.update_sanity(sid, run_id=rid, status=status, finished_at=now_iso())
            note(5, text, run_id=rid)
            self.store.add_event(operator=operator, action="sanity.finish", target=sid, session_hash=session_hash, ip=ip, detail={"pr": n, "status": status, "run": rid})
            return {"summary": text, "links": link + ([{"href": f"/runs/{rid}", "label": f"실행 {rid}"}] if rid else [])}
        except hermesmod.Canceled:
            self.store.update_sanity(sid, status="canceled", finished_at=now_iso())
            raise
        except Exception as ex:
            self.store.update_sanity(sid, status="error", error=str(ex)[:1000], finished_at=now_iso())
            raise

    def _scope_catalog(self) -> dict[str, dict[str, dict]]:
        """{기능: {Sn: {"title", "steps": [{req, text, branch}]}}} — 시나리오 파일이 있는 기능만(MVP 범위)."""
        out = {}
        for slug, ft in self.features.items():
            out[ft.feature] = {s["id"]: {"title": s["title"], "steps": [st for st in s["steps"] if st.get("req")]}
                               for s in (self.wiki.prd_scenarios(ft.feature) if self.wiki.available else [])}
        return out

    def _sanity_scope(self, pr: dict, files: list[dict], ask) -> dict:
        """1단계. 결정론 후보(바뀐 끝점 → API → 규칙표 명령의 출처 요구)를 만들고 Hermes 가 PR 을 읽어 고른다."""
        spec, cat, ssot = self.spec.get(), self.current_catalog(), self.ssot() or {}
        endpoints = sanitymod.endpoint_changes(files)
        for ep in endpoints:
            ep["op"] = sanitymod.path_to_op(spec, ep["method"], ep["path"])
        ops = {ep["op"] for ep in endpoints if ep["op"]}
        catalog = self._scope_catalog()
        req_at = {(f, st["req"]): sid for f, scs in catalog.items() for sid, sc in scs.items() for st in sc["steps"]}
        hints = []
        if cat is not None and ops:
            for c in ssot.get("commands") or []:
                b = (cat.records.get(c["id"]) or {}).get("binding") or {}
                if ops & set(b.get("operations") or []):
                    for src in c.get("source") or []:
                        m = re.match(r"^PRD/(.+?)\s+(R\d+)\s*$", str(src))
                        if m and (m.group(1), m.group(2)) in req_at:
                            hints.append((m.group(1), req_at[(m.group(1), m.group(2))], m.group(2), c["id"]))
        lines = [f"# PR #{pr['number']} {pr.get('title') or ''}", "## 본문", (pr.get("body") or "(없음)")[:3000],
                 "## 바뀐 파일", "\n".join(f"- {f['filename']} ({f.get('status')}, +{f.get('additions')} -{f.get('deletions')})" for f in files[:150]),
                 "## 컨트롤러에서 바뀐 끝점", "\n".join(f"- {ep['change']} {ep['method']} {ep['path']} ({ep['op'] or 'API 문서에 없음'}, {ep['file']})" for ep in endpoints) or "(없음)",
                 "## 플랫폼이 찾은 후보 (바뀐 API 에 묶인 규칙표 명령의 출처)", "\n".join(f"- {f} {s} {r} ← {c}" for f, s, r, c in hints) or "(없음)",
                 "## 고를 수 있는 기능 · 시나리오 · 요구 (PRD 2장)"]
        for f, scs in catalog.items():
            for sid, sc in scs.items():
                lines.append(f"### {f} {sid} {sc['title']}")
                lines += [f"- {st['req']}{' 분기' if st.get('branch') else ''}: {st['text']}" for st in sc["steps"]]
        lines.append("# 출력\n```json 블록 하나로 scope.")
        items = []
        try:
            items = sanitymod.parse_scope(ask(sanitymod.FIND_SYSTEM, "\n".join(lines), "qa-sanity-find"),
                                          {f: {sid: {st["req"] for st in sc["steps"]} for sid, sc in scs.items()} for f, scs in catalog.items()})
        except ValueError:
            items = []
        if not items and hints:          # Hermes 가 못 골랐으면 결정론 후보로
            merged: dict = {}
            for f, sid, r, c in hints:
                cell = merged.setdefault((f, sid), {"feature": f, "scenario": sid, "reqs": [], "why": f"바뀐 API 에 묶인 명령 {c}"})
                if r not in cell["reqs"]:
                    cell["reqs"].append(r)
            items = list(merged.values())
        for x in items:
            x["slug"] = scenariosmod.doc_slug(x["feature"])
            texts = {st["req"]: st["text"] for st in catalog[x["feature"]][x["scenario"]]["steps"]}
            x["title"] = catalog[x["feature"]][x["scenario"]]["title"]
            x["req_texts"] = {r: texts.get(r, "") for r in x["reqs"]}
        return {"items": items, "endpoints": endpoints, "hints": [list(h) for h in hints]}

    def _script_calls(self) -> dict[tuple, list[str]]:
        """(METHOD, 정규화 경로) → 그 요청을 보내는 스크립트 id."""
        out: dict[tuple, list[str]] = {}
        for c in self.cases.values():
            for st in c.steps:
                req = st.get("request") or {}
                path = re.sub(r"\{\{[^}]+\}\}", "{}", str(req.get("path") or "")).split("?")[0].rstrip("/")
                out.setdefault((str(req.get("method") or "").upper(), path), [])
                if c.id not in out[(str(req.get("method") or "").upper(), path)]:
                    out[(str(req.get("method") or "").upper(), path)].append(c.id)
        return out

    def _sanity_findings(self, pr: dict, files: list[dict], scope: dict, ask) -> list[dict]:
        """2단계. 플랫폼 결정론 점검 + Hermes 점검 (§4.2)."""
        from qa import scenario_ai
        spec = self.spec.get()
        norm = lambda p: re.sub(r"\{[^}]+\}", "{}", str(p).rstrip("/"))  # noqa: E731
        known = {(o.method, norm(o.path)) for o in (spec.ops.values() if spec else [])}
        scope_vids = {v for v in self._sanity_case_ids(scope)}
        scope_scripts = {c.id for c in self.cases.values() if c.variant in scope_vids}
        removed = {(ep["method"], norm(ep["path"])) for ep in scope.get("endpoints") or [] if ep["change"] == "removed"}
        found: list[dict] = []
        if spec is not None:
            for (m, pth), ids in sorted(self._script_calls().items()):
                if (m, pth) in known or not m or not pth:
                    continue
                if (m, pth) in removed or set(ids) & scope_scripts:
                    found.append({"kind": "missing_api", "title": f"{m} {pth} 가 dev API 문서에 없어요", "spec": "스크립트 " + ", ".join(ids) + " 가 이 API 를 불러요",
                                  "code": "이 PR 에서 지워진 끝점이에요" if (m, pth) in removed else "dev API 문서(openapi3.yaml)에 없어요",
                                  "question": "이 API 를 쓰는 케이스를 어떻게 할까요?", "suggestion": "스펙이 정해지면 Hermes 가 스크립트를 고치거나 시나리오에서 떼요. 실행에서는 실패로 나와요.",
                                  "scripts": ids, "source": "platform"})
            for ep in scope.get("endpoints") or []:
                if ep["change"] == "added" and not ep.get("op"):
                    found.append({"kind": "undocumented_api", "title": f"{ep['method']} {ep['path']} 가 코드에는 있지만 dev API 문서에 없어요",
                                  "spec": "dev API 문서(openapi3.yaml)", "code": f"{ep['file']} 에 새로 생긴 끝점",
                                  "question": "", "suggestion": "멈추지 않고 계속해요. 이 끝점은 문서가 생기면 다음 Sanity 에서 스크립트를 만들어요. 문서가 계속 없으면 백엔드에 REST Docs 를 요청해요.", "source": "platform"})
        ssot = self.ssot() or {}
        feats = sorted({x["feature"] for x in scope["items"]})
        rules = []
        for f in feats:
            gates, cmds = scenario_ai.feature_rules(ssot, f, set())
            if not cmds:
                found.append({"kind": "no_rules", "title": f"「{f}」에는 규칙표 명령이 없어요", "spec": f"「{f}」 PRD", "code": "규칙표(SSOT)",
                              "question": "", "suggestion": "케이스는 사람이 확인으로 둬요", "source": "platform"})
            rules += [f"- 명령 {c['id']} {c.get('name') or ''} (게이트 {c.get('gate') or '-'})" for c in cmds]
            rules += [f"- 게이트 {g['id']} {g.get('name') or ''}: " + "; ".join(f"{k.get('key')} {k.get('message') or k.get('ref') or ''}" for k in g.get("checks") or []) for g in gates]
        decisions = []
        for path in sanitymod.decision_files(files)[:3]:
            txt = self.github.file_text(path, pr.get("sha") or "")
            if txt:
                decisions.append(f"### {path}\n{txt[:6000]}")
        scen, catalog = [], self._scope_catalog()
        for x in scope["items"]:
            for sc in [catalog.get(x["feature"], {}).get(x["scenario"])]:
                if sc:
                    scen.append(f"### {x['feature']} {x['scenario']} {sc['title']} (이 PR 이 닿는 요구: {', '.join(x['reqs']) or '-'})")
                    scen += [f"- {st['req']}{' 분기' if st.get('branch') else ''}: {st['text']}" for st in sc["steps"]]
        prompt = "\n".join([f"# PR #{pr['number']} {pr.get('title') or ''}", (pr.get("body") or "")[:3000],
                            "# 백엔드 결정 기록", "\n\n".join(decisions) or "(없음)",
                            "# PRD 시나리오 (이 PR 이 닿는 것)", "\n".join(scen),
                            "# 규칙표 (이 기능들의 명령·게이트)", "\n".join(rules)[:12000] or "(없음)",
                            "# 플랫폼이 이미 찾은 것", "\n".join(f"- {f['title']}" for f in found) or "(없음)",
                            "# PR 변경 (diff 발췌)", sanitymod.diff_excerpt(files),
                            "# 출력\n```json 블록 하나로 findings. 항목마다 걸린 PRD 요구 id 가 있으면 \"reqs\": [\"R63\"] 도 적는다."])
        try:
            found += sanitymod.parse_findings(ask(sanitymod.CHECK_SYSTEM, prompt, "qa-sanity-check"))
        except ValueError as ex:
            found.append({"kind": "impact", "title": "Hermes 스펙 점검 결과를 읽지 못했어요", "spec": "", "code": str(ex), "question": "", "suggestion": "다시 점검하면 돼요", "source": "platform"})
        for i, f in enumerate(found, 1):
            f["id"] = f"f{i}"
        return found

    def _sanity_case_ids(self, scope: dict) -> list[str]:
        """이번 범위의 케이스: 관련 요구에 걸린 케이스 + 그 시나리오의 정상 흐름 (§4.2 3단계)."""
        out = []
        for x in scope.get("items") or []:
            ft = self.features.get(x["slug"])
            sc = ft.scenario(x["scenario"]) if ft else None
            for v in (sc.variants if sc else []):
                if v.kind == "happy" or (v.at and v.at in x["reqs"]):
                    out.append(f"{x['slug']}/{x['scenario']}/{v.key}")
        return out

    def _sanity_prepare(self, scope: dict, *, operator: str, ask, session_hash=None, ip=None) -> str:
        """3단계. 시나리오 파일·케이스가 비었으면 채우고, 지난 저장 뒤 PRD·규칙표가 바뀐 시나리오는 다시 맞춘다."""
        done = []
        for slug in dict.fromkeys(x["slug"] for x in scope["items"]):
            ft = self.features.get(slug)
            need_fill = ft is None or any(ft.scenario(x["scenario"]) is None or not ft.scenario(x["scenario"]).variants for x in scope["items"] if x["slug"] == slug)
            if need_fill:
                try:
                    out = self.fill_scenarios(slug, operator=operator, session_hash=session_hash, ip=ip, ask=ask)
                    done.append(f"{slug} 케이스 {out['added']}개 채움")
                except BadRequest as ex:
                    done.append(f"{slug} 채우기 실패: {ex}")
        ov, _ = self.scenario_view()
        for x in scope["items"]:
            f = next((y for y in ov if y["slug"] == x["slug"]), None)
            s = next((y for y in (f or {}).get("scenarios", []) if y["id"] == x["scenario"]), None)
            dr = (s or {}).get("drift") or {}
            if dr.get("changed") or dr.get("removed") or dr.get("added"):
                try:
                    out = self.realign_scenario(x["slug"], x["scenario"], operator=operator, session_hash=session_hash, ip=ip, ask=ask)
                    done.append(f"{x['slug']} {x['scenario']} 케이스 {len(out['keys'])}개 다시 맞춤")
                except BadRequest as ex:
                    if "걸린 케이스가 없다" in str(ex):
                        self.save_scenario({"feature": f["feature"], "scenario": x["scenario"], "action": "basis"}, operator=operator, source="sanity",
                                           session_hash=session_hash, ip=ip)
                        done.append(f"{x['slug']} {x['scenario']} 바뀐 문장 확인만")
                    else:
                        done.append(f"{x['slug']} {x['scenario']} 다시 맞추기 실패: {ex}")
        return " · ".join(done) or "케이스가 이미 준비돼 있어요"

    def _sanity_scripts(self, scope: dict, blocked: set, *, operator: str, ask, session_hash=None, ip=None) -> str:
        """4단계. 이번 범위에서 자동으로 확인할 수 있는데 스크립트가 없는 케이스마다 Hermes 가 쓴다. 검증을 통과하면 바로 저장."""
        idx = scenariosmod.variant_index(self.features)
        have = {c.variant for c in self.cases.values() if c.variant}
        todo, skipped = [], 0
        for vid in self._sanity_case_ids(scope):
            _, _, va = idx.get(vid) or (None, None, None)
            if va is None or vid in have or va.mode == "manual" or not va.checks:
                continue
            if va.at and va.at in blocked:
                skipped += 1
                continue
            todo.append((vid, va))
        made, failed = [], []
        for vid, va in todo[: self.SANITY_MAX_SCRIPTS]:
            try:
                res = self.generate_cases(tc_ids=list(va.checks), operator=operator, session_hash=session_hash, ip=ip, ask=ask, variant=vid)
                made += [s["case_id"] for s in res["saved"]]
                failed += [vid for _ in res["rejected"][:1]]
            except BadRequest as ex:
                failed.append(vid)
                self.store.add_event(operator=operator, action="hermes.generate", target=vid, session_hash=session_hash, ip=ip, detail={"source": "sanity", "error": str(ex)[:300]})
        rest = max(0, len(todo) - self.SANITY_MAX_SCRIPTS)
        parts = [f"스크립트 {len(made)}개 새로 저장"] + ([f"{len(failed)}개는 검증에서 버림"] if failed else []) \
            + ([f"{rest}개는 다음에"] if rest else []) + ([f"스펙 확인이 남은 요구의 케이스 {skipped}개는 건너뜀"] if skipped else [])
        return " · ".join(parts) if todo else "새로 만들 스크립트가 없어요"

    def _sanity_execute(self, s: dict, pr: dict, scope: dict, findings: list[dict], *, operator: str, job, ask, session_hash=None, ip=None) -> tuple[str | None, str]:
        """5단계. 범위의 케이스를 구현한 스크립트와 없어진 API 를 부르는 스크립트를 dev 에 실행하고, 실패는 Hermes 가 분석한다."""
        import time
        vids = set(self._sanity_case_ids(scope))
        ids = [c.id for c in self.cases.values() if c.variant in vids]
        ids += [x for f in findings if f["kind"] == "missing_api" for x in f.get("scripts") or [] if x in self.cases and self.cases[x].suite != "setup" and x not in ids]
        if not ids:
            return None, "돌릴 스크립트가 없어요. 케이스가 모두 사람이 확인이거나 아직 스크립트가 없어요"
        alive = self.runner._thread.is_alive()
        rid = self.create_run(trigger="deploy-sanity", operator=operator, case_ids=ids, sha=pr.get("sha"), ref=None, pr_number=pr["number"],
                              deploy_run_id=None, reason=f"Sanity {s['id']}", basis="Sanity — 이 PR 이 닿는 케이스",
                              extra={"pr_title": pr.get("title"), "pr_url": pr.get("url"), "sanity": s["id"]},
                              session_hash=session_hash, ip=ip, enqueue=alive, notify=True)
        if not alive:
            self.runner.execute_now(rid)
        while (self.store.get_run(rid) or {}).get("status") not in ("finished", None):
            if job.cancel.is_set():
                self.runner.cancel(rid)
            time.sleep(2)
        run = self.store.get_run(rid)
        bad = [rc for rc in self.store.list_run_cases(rid) if rc["verdict"] in ("fail", "error")]
        for rc in bad[:5]:
            try:
                steps = self.store.list_steps(rc["id"])
                self.store.update_run_case(rc["id"], triage=hermes_triage(self.cfg, run, rc, steps, ask=ask, rules=self.triage_rules(steps)), triaged_at=now_iso())
            except Exception as ex:          # 분석 실패는 결과를 바꾸지 않는다
                self.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=session_hash, ip=ip, detail={"case": rc["case_id"], "error": str(ex)[:300]})
        text = f"스크립트 {run['total']}개 중 {run['passed']}개 통과" + (f", 실패 {len(bad)}개 (Hermes 분석 {min(len(bad), 5)}개)" if bad else "")
        return rid, text

    def sanity_cases(self, scope: dict) -> list[dict]:
        """Sanity 화면의 '이번 범위의 케이스' 표."""
        from qa.ui_scn import state_badge, variant_url
        want = set(self._sanity_case_ids(scope))
        if not want:
            return []
        ov, _ = self.scenario_view()
        out = []
        for f in ov:
            for s in f["scenarios"]:
                for v in s["variants"]:
                    if v["id"] in want:
                        va = v["variant"]
                        out.append({"feature": f["feature"], "scenario": s["id"], "kind_ko": scenariosmod.KIND_KO.get(va.kind, va.kind), "title": va.title, "key": va.key,
                                    "href": variant_url(v["id"]), "state": v["state"], "mode": va.mode, "checks": va.checks, "state_html": state_badge(v["state"])})
        return out

    def sanity_resolve(self, sid: str, fid: str, *, choice: str, note: str, operator: str, session_hash=None, ip=None, sync: bool = False) -> dict:
        """스펙 확인 항목 하나를 사람이 정한다 — 추천대로 · 다르게(어떻게). 고칠 수 있는 종류면 Hermes 가 PRD·규칙표 수정안을 만든다(§14).
        위키는 사람이 [위키에 반영]을 누를 때만 바뀐다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        s = self.store.get_sanity(sid) or {}
        fs = list(s.get("findings") or [])
        f = next((x for x in fs if x.get("id") == fid), None)
        if not f:
            raise BadRequest("그 항목이 없다")
        if choice not in ("recommended", "other"):
            raise BadRequest("추천대로 · 다르게 중 하나")
        if choice == "other" and not note.strip():
            raise BadRequest("다르게 정할 때는 어떻게 정했는지 적어야 한다")
        f = self._update_finding(sid, fid, resolution=choice, resolved_by=operator, resolved_at=now_iso(), note=note.strip()[:500] or None)
        self.store.add_event(operator=operator, action="sanity.finding.resolve", target=sid, session_hash=session_hash, ip=ip,
                             detail={"finding": fid, "title": f["title"][:200], "choice": choice, "note": note.strip()[:300]})
        if f["kind"] in specfixmod.FIXABLE and self.cfg.hermes_key and self.wiki.available:
            self.sanity_propose(sid, fid, operator=operator, session_hash=session_hash, ip=ip, sync=sync)
        return next(x for x in self.store.get_sanity(sid)["findings"] if x["id"] == fid)

    # ---- 스펙 수정안 (docs/qa-platform-v2.md §14) ----------------------------------------------
    def _update_finding(self, sid: str, fid: str, **fields) -> dict:
        with self._finding_lock:
            s = self.store.get_sanity(sid) or {}
            fs = list(s.get("findings") or [])
            f = next((x for x in fs if x.get("id") == fid), None)
            if not f:
                raise BadRequest("그 항목이 없다")
            f.update(fields)
            self.store.update_sanity(sid, findings=fs)
            return f

    def sanity_propose(self, sid: str, fid: str, *, operator: str, session_hash=None, ip=None, sync: bool = False, remade: str | None = None):
        """[수정안 만들기] — 정한 결정대로 Hermes 가 PRD·규칙표를 찾아 바꾸기로 고친 안을 낸다. 위키에는 아직 쓰지 않는다.
        remade 는 반영하다 같은 줄 충돌이 나서 플랫폼이 다시 만들게 한 이유다. 화면에 '다시 만들었어요, 확인 후 반영' 으로 보인다."""
        s = self.store.get_sanity(sid) or {}
        f = next((x for x in s.get("findings") or [] if x.get("id") == fid), None)
        if not f:
            raise BadRequest("그 항목이 없다")
        if f["kind"] not in specfixmod.FIXABLE or f.get("resolution") not in ("recommended", "other"):
            raise BadRequest("추천대로나 다르게로 정한, 스펙과 코드가 다르거나 모호한 항목만 수정안을 만들 수 있다")
        if not self.wiki.available:
            raise BadRequest("위키 체크아웃이 없어 PRD 를 읽을 수 없다")
        feats = sorted({x["feature"] for x in (s.get("scope") or {}).get("items") or []})
        pr = {"number": s["pr_number"], "title": s.get("pr_title")}

        def fn(job):
            self._update_finding(sid, fid, proposal={"status": "making", "job_id": job.id, "made_by": operator})
            try:
                out = specfixmod.propose(finding=f, pr=pr, root=self.wiki.root, scope_features=feats, ask=job.ask, blobs=self.blobs)
            except Exception as ex:
                self._update_finding(sid, fid, proposal={"status": "failed", "error": str(ex)[:600], "made_by": operator, "made_at": now_iso()})
                self.store.add_event(operator=operator, action="sanity.spec.propose", target=sid, session_hash=session_hash, ip=ip,
                                     detail={"finding": fid, "error": str(ex)[:300]})
                raise
            self._update_finding(sid, fid, proposal={"status": "ready" if out["files"] else "empty", **out, "made_by": operator, "made_at": now_iso(),
                                                     **({"remade": remade} if remade else {})})
            self.store.add_event(operator=operator, action="sanity.spec.propose", target=sid, session_hash=session_hash, ip=ip,
                                 detail={"finding": fid, "summary": out["summary"][:200], "files": [x["path"] for x in out["files"]],
                                         **({"remade": remade[:300]} if remade else {})})
            return {"summary": out["summary"] or "수정안을 만들었어요", "links": [{"href": f"/sanity/{s['pr_number']}", "label": f"PR #{s['pr_number']} Sanity"}]}
        self._update_finding(sid, fid, proposal={"status": "making", "made_by": operator, **({"remade": remade} if remade else {})})   # 그사이 옛 수정안을 반영하지 않게
        return self.start_job("specfix", operator=operator, label=f"PR #{s['pr_number']} · {f['title'][:60]}", fn=fn,
                              back={"href": f"/sanity/{s['pr_number']}", "label": f"PR #{s['pr_number']}"}, session_hash=session_hash, ip=ip, sync=sync)

    def sanity_discard(self, sid: str, fid: str, *, operator: str, session_hash=None, ip=None) -> None:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        self._update_finding(sid, fid, proposal={"status": "discarded", "discarded_by": operator, "discarded_at": now_iso()})
        self.store.add_event(operator=operator, action="sanity.spec.discard", target=sid, session_hash=session_hash, ip=ip, detail={"finding": fid})

    def sanity_apply(self, sid: str, fids: list[str], *, operator: str, session_hash=None, ip=None, sync: bool = False) -> dict:
        """[위키에 반영] — 고른 수정안을 지금 위키 파일에 줄 단위 3-way merge 로 얹어 검증하고 커밋한다(§14.5).
        같은 줄 충돌이 난 수정안은 빼고 나머지만 반영한 뒤, 충돌한 것은 Hermes 가 지금 위키 기준으로 다시 만든다.
        반영 뒤 이 Sanity 의 다른 대기 수정안은 바뀐 줄 비교를 지금 파일 기준으로 다시 계산한다(같은 줄이면 다시 만들기).
        커밋 순서: 규칙표 조각 → PRD(wiki_apply archive) → index.yaml 기준 날짜 → wiki_content_commit. 다시 점검은 사람이 따로 누른다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not (self.cfg.wiki_mcp_url and self.cfg.wiki_mcp_token):
            raise BadRequest("LLM_WIKI_MCP_* 가 없어 위키에 쓸 수 없다")
        s = self.store.get_sanity(sid) or {}
        pick = [f for f in s.get("findings") or [] if f.get("id") in fids and (f.get("proposal") or {}).get("status") == "ready"]
        if not pick:
            raise BadRequest("반영할 수정안이 없다")
        try:
            before, after, conflicts = specfixmod.combine(self.wiki.root, [f["proposal"] for f in pick], self.blobs)
        except specfixmod.SpecFixError as ex:
            raise BadRequest(f"합친 결과가 검증을 넘지 못했어요. 수정안을 하나씩 반영하거나 [다시 만들기]를 눌러 주세요 ({ex})")
        ok = [f for i, f in enumerate(pick) if i not in conflicts]
        clash = [(f, conflicts[i]) for i, f in enumerate(pick) if i in conflicts]
        changed = [p for p in after if after[p] != before[p]]
        msg = None
        if ok and changed:
            first = ok[0]["proposal"].get("summary") or ok[0]["title"]
            msg = f"spec: {first}{f' 외 {len(ok) - 1}건' if len(ok) > 1 else ''} — PR #{s['pr_number']} Sanity (qa-platform, {operator})"
            commits = self._spec_write(changed, after, msg)
            if "error" in commits:
                self.store.add_event(operator=operator, action="sanity.spec.apply", target=sid, session_hash=session_hash, ip=ip,
                                     detail={"findings": [f["id"] for f in ok], "files": changed, "error": commits["error"][:300]})
                raise BadRequest(f"위키에 쓰지 못했어요: {commits['error']}")
            at = now_iso()
            for f in ok:
                self._update_finding(sid, f["id"], proposal={**f["proposal"], "status": "applied", "applied_by": operator, "applied_at": at, "commit_message": msg})
            self.store.add_event(operator=operator, action="sanity.spec.apply", target=sid, session_hash=session_hash, ip=ip,
                                 detail={"findings": [f["id"] for f in ok], "files": changed, "message": msg, "commits": commits,
                                         "conflicts": [f["id"] for f, _ in clash]})
        elif ok:
            for f in ok:                                                                   # 이미 같은 내용이 위키에 있다
                self._update_finding(sid, f["id"], proposal={**f["proposal"], "status": "empty", "summary": "이미 위키에 같은 내용이 있어요"})
            ok = []
        cur = lambda p: after[p] if p in after else (self.wiki.root / p).read_text(encoding="utf-8")  # noqa: E731
        remake = list(clash)
        if msg:
            done = {f["id"] for f in pick}
            for f in (self.store.get_sanity(sid) or {}).get("findings") or []:
                pr = f.get("proposal") or {}
                if f["id"] in done or pr.get("status") != "ready":
                    continue
                try:
                    new = specfixmod.rebase(pr, {p: cur(p) for p in specfixmod._paths(pr)}, self.blobs)
                except specfixmod.SpecFixError as ex:
                    remake.append((f, str(ex)))
                    continue
                self._update_finding(sid, f["id"], proposal={**new, "status": "ready" if new["files"] else "empty", "rebased_at": now_iso(),
                                                             **({} if new["files"] else {"summary": "이미 위키에 같은 내용이 있어요"})})
        for f, why in remake:
            self.store.add_event(operator=operator, action="sanity.spec.conflict", target=sid, session_hash=session_hash, ip=ip,
                                 detail={"finding": f["id"], "reason": why[:300]})
            self.sanity_propose(sid, f["id"], operator=operator, session_hash=session_hash, ip=ip, sync=sync, remade=why)
        return {"files": changed if msg else [], "message": msg, "count": len(ok), "remade": len(remake)}

    def _spec_write(self, changed: list[str], after: dict[str, str], msg: str) -> dict:
        """조각 → PRD → index.yaml 순서로 쓰고 커밋. 렌더러는 조각(_src) 해시가 바뀔 때 PRD 를 읽어 렌더하니,
        기준 날짜는 PRD 가 바뀐 뒤에 써야 렌더가 새 PRD 문장을 기준으로 잡는다."""
        client = McpClient(self.cfg.wiki_mcp_url, self.cfg.wiki_mcp_token, timeout=60)
        commits = {}
        yml = [p for p in changed if p.endswith(".yaml")]
        try:
            for p in yml:
                if p != specfixmod.INDEX:
                    client.call_tool("wiki_content_write", {"uri": specfixmod.uri_of(p), "content": after[p]})
            md = [p for p in changed if p.endswith(".md")]
            if md:
                res = client.call_tool("wiki_apply", {"mode": "archive", "changes": [{"path": p, "content": after[p]} for p in md], "message": msg})
                commits["prd"] = McpClient.tool_text(res)[:300]
            if specfixmod.INDEX in yml:
                client.call_tool("wiki_content_write", {"uri": specfixmod.uri_of(specfixmod.INDEX), "content": after[specfixmod.INDEX]})
            if yml:
                try:
                    res = client.call_tool("wiki_content_commit", {"message": msg, "slugs": ",".join(specfixmod.uri_of(p) for p in yml)})
                except McpError:
                    res = client.call_tool("wiki_content_commit", {"message": msg})
                commits["ssot"] = McpClient.tool_text(res)[:300]
        except McpError as ex:
            commits["error"] = str(ex)
        return commits

    def sanity_continue(self, sid: str, *, reason: str, operator: str, session_hash=None, ip=None, sync: bool = False):
        """[이대로 계속] — 남은 확인 항목은 '정하지 않고 계속' 으로 적고 3단계부터. 그 요구의 케이스는 스크립트를 만들지 않는다."""
        s = self.store.get_sanity(sid)
        if not s or s["status"] not in ("needs_spec", "error", "interrupted", "canceled", "failed"):
            raise BadRequest("멈춘 Sanity 만 이어서 할 수 있다")
        left = [f for f in s["findings"] if f["kind"] in sanitymod.BLOCKING and not f.get("resolved_at")]
        if left and not reason.strip():
            raise BadRequest("정하지 않은 항목이 있으면 사유를 적어야 한다")
        for f in left:
            self._update_finding(sid, f["id"], resolution="continued", resolved_by=operator, resolved_at=now_iso(), note=reason.strip()[:500])
        self.store.add_event(operator=operator, action="sanity.continue", target=sid, session_hash=session_hash, ip=ip, detail={"left": len(left), "reason": reason.strip()[:300]})
        start = 3 if s["step"] >= 2 else 1
        return self._sanity_job(sid, start, operator=operator, session_hash=session_hash, ip=ip, sync=sync)

    def sanity_recheck(self, sid: str, *, operator: str, session_hash=None, ip=None, sync: bool = False):
        """[위키 고친 뒤 다시 점검] — 2단계부터. 스펙을 다시 읽는다."""
        s = self.store.get_sanity(sid)
        if not s or s["status"] in ("queued", "running"):
            raise BadRequest("돌고 있는 Sanity 는 다시 점검할 수 없다")
        self.store.add_event(operator=operator, action="sanity.recheck", target=sid, session_hash=session_hash, ip=ip, detail={"pr": s["pr_number"]})
        return self._sanity_job(sid, 2 if s["scope"] else 1, operator=operator, session_hash=session_hash, ip=ip, sync=sync)

    def sanity_slack(self, sid: str, *, operator: str, session_hash=None, ip=None) -> int:
        """[Slack 으로 묻기] — 남은 질문을 WIKI_SLACK_WEBHOOK_URL 로. 사람이 누를 때만."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        s = self.store.get_sanity(sid) or {}
        left = [f for f in s.get("findings") or [] if f["kind"] in sanitymod.BLOCKING and not f.get("resolved_at")]
        if not left:
            raise BadRequest("물을 것이 없다")
        slack(self.cfg.slack_webhook_url, f"[QA] PR #{s['pr_number']} {s.get('pr_title') or ''} — 스펙 확인 {len(left)}건 ({operator})\n"
              + "\n".join(f"• {f['title']}\n  질문: {f.get('question') or '-'}\n  추천: {f.get('suggestion') or '-'}" for f in left)
              + f"\n{self.cfg.public_url}/sanity/{s['pr_number']}")
        self.store.add_event(operator=operator, action="sanity.slack", target=sid, session_hash=session_hash, ip=ip, detail={"count": len(left)})
        return len(left)

    # ---- 폼으로 스크립트·수동 TC 편집 (docs/qa-platform-editor.md) -----------------------------
    def resync_repo(self) -> str | None:
        """[스크립트 다시 읽기] — 쓰기 토큰이 있으면 main 을 다시 받는다. 실패 사유를 돌려준다."""
        if not self.repo.enabled:
            return None
        ok = self.repo.sync()
        if self.repo.synced:
            self.cases_dir = self.repo.local / "cases"
            self.scenarios_dir = self.repo.local / "scenarios"
            self.catalog.catalog_dir = self.repo.local / "catalog"
            self.catalog.get(force=True)
        return None if ok else (self.repo.state.get("error") or "main 을 받지 못했다")

    def editor_context(self) -> dict:
        """폼이 자동완성에 쓰는 것 — API 목록, 테스트 조건 id, 테스트 계정, 픽스처 키."""
        spec = self.spec.get()
        cat = self.current_catalog()
        ops = [{"id": o.id, "method": o.method, "path": o.path, "summary": o.summary} for o in sorted((spec.ops.values() if spec else []), key=lambda o: (o.path, o.method))]
        tcs = [{"id": r["id"], "title": r["title"], "layer": r["layer"]} for r in (cat.records.values() if cat else []) if not r.get("excluded")]
        setups = [{"id": c.id, "title": c.title, "outputs": c.outputs, "steps": len(c.steps), "uses": (c.uses or {}).get("setup"),
                   "inputs": [{"name": k, **v} for k, v in c.inputs.items()]} for c in self.setup_cases()]
        variants = [{"id": vid, "title": va.title, "checks": va.checks} for vid, (_, _, va) in sorted(scenariosmod.variant_index(self.features).items())]
        return {"ops": ops, "tcs": tcs, "actors": sorted(self.all_actors()), "fixtures": sorted(self.cfg.fixtures),
                "suites": ["smoke", "sanity", "manual", "setup"], "setups": setups, "variants": variants}

    def editor_op(self, op_id: str) -> dict | None:
        spec = self.spec.get()
        o = spec.ops.get(op_id) if spec else None
        if not o:
            return None
        statuses = sorted({str(s) for s in o.success} | {str(i.get("status")) for i in o.errors.values() if i.get("status")})
        return {"id": o.id, "method": o.method, "path": o.path, "summary": o.summary, "params": o.params, "body_fields": o.body_fields,
                "example": o.request_example, "statuses": statuses,
                "errors": [{"code": c, "status": i.get("status"), "message": i.get("message")} for c, i in sorted(o.errors.items())],
                "domain": domain_of_path(o.path)}

    def _form_raw(self, state: dict, *, mode: str, original_id: str | None, draft: dict | None) -> tuple:
        """폼 상태 → (raw, case, errors, warnings, text). 저장·미리보기·저장 전 실행이 같은 검사를 쓴다."""
        try:
            raw = editormod.from_state(state, op_of=self.op_of)
        except editormod.FormError as ex:
            return None, None, [str(ex)], [], ""
        if mode == "edit" and raw.get("id") != original_id:
            return raw, None, [f"id 는 바꿀 수 없다 ({original_id}) — 새 id 가 필요하면 새 스크립트로 만들고 이것은 지운다"], [], ""
        existing = set(self.cases) - ({original_id} if mode == "edit" else set()) - ({draft.get("case_id")} if draft and draft.get("case_id") else set())
        case, errors, warnings = editormod.validate_case(raw, catalog=self.current_catalog(), cfg=self.cfg, actors=self.all_actors(), existing_ids=existing,
                                                         library=self.cases)
        warnings = warnings + editormod.body_warnings(raw, self.spec.get())
        return raw, case, errors, warnings, draftsmod.yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)

    def form_case(self, state: dict, *, mode: str, original_id: str | None, draft_id: str | None, operator: str,
                  session_hash=None, ip=None, dry: bool = False) -> dict:
        """폼 저장. mode new | edit(기존 스크립트) | draft(API 호출 화면에서 담은 것·예전 초안). 검증을 통과하면 바로 main 에 저장한다.
        반환 {ok, errors, warnings, yaml, id, case_id, commit}. 오류가 있으면 저장하지 않는다(폼에 그대로 남는다). dry=True 는 YAML 미리보기."""
        if not dry and (not operator or operator not in self.cfg.operators):
            raise BadRequest("담당자를 목록에서 골라야 한다")
        d = self.store.get_draft(draft_id) if draft_id else None
        if d and d["status"] in ("approved", "rejected"):
            raise BadRequest("이미 저장했거나 버린 것이다 — 스크립트 화면에서 폼으로 고친다")
        raw, case, errors, warnings, text = self._form_raw(state, mode=mode, original_id=original_id, draft=d)
        if dry or errors:
            return {"ok": not errors, "errors": errors, "warnings": warnings, "yaml": text}
        out = self.save_change(kind="case", source="form-edit" if mode == "edit" else "form", yaml_text=text, operator=operator,
                               domain=(case.domains[0] if case.domains else None), case_id=case.id, tc_ids=case.covers,
                               validation={"status": "warn" if warnings else "ok", "errors": [], "warnings": warnings}, draft=d, session_hash=session_hash, ip=ip)
        return {"ok": True, "errors": [], "warnings": warnings, "yaml": text, **out}

    def try_case(self, state: dict, *, mode: str, original_id: str | None, draft_id: str | None, operator: str, session_hash=None, ip=None) -> str:
        """[저장 전에 한 번 실행해 보기] — 폼 내용을 저장하지 않고 dev 에 한 번 돌린다. 실행 기록은 남는다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        d = self.store.get_draft(draft_id) if draft_id else None
        _, case, errors, _, _ = self._form_raw(state, mode=mode, original_id=original_id, draft=d)
        if errors:
            raise BadRequest("검사를 통과하지 못해 실행하지 않는다: " + "; ".join(errors[:3]))
        rid = self.create_run(trigger="draft-check", operator=operator, case_ids=[], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                              reason=f"{case.id} 저장 전 실행", basis="저장 전 실행 1건", extra={"try": {"case_id": case.id, "mode": mode}},
                              session_hash=session_hash, ip=ip, cases_override=[case], notify=False)
        self.store.add_event(operator=operator, action="case.try", target=rid, session_hash=session_hash, ip=ip, detail={"case_id": case.id, "mode": mode})
        return rid

    def manual_item(self, tc_id: str) -> dict | None:
        """manual-tc.yaml 의 원본 항목 (카탈로그 레코드는 모양이 바뀌어 있다 — doc·section 은 prd, given·when·then 은 expect_hint)."""
        p = self.catalog.catalog_dir / "manual-tc.yaml"
        try:
            doc = draftsmod.yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, draftsmod.yaml.YAMLError):
            return None
        return next((dict(it) for it in (doc.get("cases") or []) if isinstance(it, dict) and str(it.get("id")) == tc_id), None)

    def form_tc(self, f: dict, *, tc_id: str | None, operator: str, session_hash=None, ip=None) -> dict:
        """수동 작성 테스트 조건 폼 저장 — 바로 manual-tc.yaml 에. tc_id 가 있으면 고치기, 없으면 새로(번호 자동)."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        cat = self.current_catalog()
        if cat is None:
            raise BadRequest("테스트 조건 목록이 없다")
        if tc_id:
            r = cat.records.get(tc_id)
            if not r or r["layer"] != "manual":
                raise BadRequest("수동 작성 테스트 조건만 폼으로 고친다 — 비즈니스 규칙·API 계약 테스트 조건은 원본(SSOT·OpenAPI)을 고친다")
            orig = self.manual_item(tc_id) or {}
            keep = {k: orig.get(k) for k in ("doc", "section", "domain", "source") if orig.get(k)}
            rec = editormod.manual_record({**keep, **{k: v for k, v in f.items() if str(v or "").strip()}, "doc": keep.get("doc"), "section": keep.get("section")}, tc_id=tc_id)
        else:
            kind = str(f.get("tc_kind") or "prd")
            if kind == "ops":
                stem = str(f.get("ops_id") or "").strip().rstrip("#")
                if not re.match(r"^OPS\.[A-Za-z0-9가-힣\-]+\.[A-Za-z0-9가-힣\-]+$", stem):
                    raise BadRequest("운영 기준 테스트 조건은 OPS.영역.이름 꼴 (예: OPS.platform.health)")
                prefix = stem + "#"
            else:
                if not str(f.get("doc") or "").strip() or not str(f.get("section") or "").strip():
                    raise BadRequest("PRD 문서와 절 번호가 필요하다")
                from qa.wiki import doc_slug
                prefix = f"PRD.{doc_slug(str(f['doc']).strip())}.{str(f['section']).strip().rstrip('.')}#"
            tid = editormod.next_manual_id(prefix, list(cat.records))
            rec = editormod.manual_record(f, tc_id=tid)
        text = draftsmod.yaml.safe_dump({"cases": [rec]}, allow_unicode=True, sort_keys=False)
        _, errors = draftsmod.validate_manual_tc(text)
        if errors:
            raise BadRequest("; ".join(errors[:4]))
        return self.save_change(kind="tc", source="form-edit" if tc_id else "form", yaml_text=text, operator=operator, domain=rec.get("domain"),
                                tc_ids=[rec["id"]], validation={"status": "ok", "warnings": []}, session_hash=session_hash, ip=ip)

    def delete_item(self, *, what: str, target: str, reason: str = "", operator: str, session_hash=None, ip=None) -> dict:
        """지우기도 바로 저장한다. what case | tc. 사유는 있으면 커밋 메시지에 남긴다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if what == "case":
            c = self.cases.get(target)
            if not c:
                raise BadRequest("없는 스크립트")
            others = {t for x in self.cases.values() if x.id != c.id for t in x.covers}
            orphan = [t for t in c.covers if t not in others]
            out = self.save_change(kind="case-delete", source="form-delete", yaml_text=c.to_yaml(), operator=operator, domain=(c.domains[0] if c.domains else None),
                                   note=reason.strip() or None, case_id=c.id, tc_ids=c.covers,
                                   validation={"status": "warn" if orphan else "ok", "warnings": [f"지워서 미자동화가 된 테스트 조건: {', '.join(orphan)}"] if orphan else []},
                                   session_hash=session_hash, ip=ip)
        else:
            cat = self.current_catalog()
            r = cat.records.get(target) if cat else None
            if not r or r["layer"] != "manual":
                raise BadRequest("수동 작성 테스트 조건만 지울 수 있다")
            users = self.coverage(cat)["by_tc"].get(target) or []
            if users:
                raise BadRequest(f"이 테스트 조건을 검증하는 스크립트가 있다: {', '.join(users)} — 먼저 그 스크립트의 covers 에서 뺀다")
            rec = self.manual_item(target) or {"id": target, "title": r["title"]}
            out = self.save_change(kind="tc-delete", source="form-delete", yaml_text=draftsmod.yaml.safe_dump({"cases": [rec]}, allow_unicode=True, sort_keys=False),
                                   operator=operator, domain=r.get("domain"), note=reason.strip() or None, tc_ids=[target],
                                   validation={"status": "ok", "warnings": []}, session_hash=session_hash, ip=ip)
        return {**out, "deleted": True}

    def _plan(self, d: dict, operator: str):
        kind = d.get("kind") or "case"
        if kind in ("scenario", "scenario-delete"):
            op = draftsmod.yaml.safe_load(d["yaml"])

            def change(text):
                try:
                    return scenariosmod.apply_op(text, op)
                except scenariosmod.ScenarioError as ex:
                    raise RepoError(str(ex))
            return f"scenarios/{scenariosmod.doc_slug(op['feature'])}.yaml", change, scenariosmod.op_summary(op), [scenariosmod.op_target(op)]
        if kind in ("tc", "tc-delete"):
            cat = self.current_catalog()
            return editormod.plan_tc(d, covered_by=self.coverage(cat)["by_tc"] if cat else {})
        return editormod.plan_case(d, cases=self.cases, operator=operator)

    SAVE_ACTIONS = {"case": "case.save", "case-delete": "case.delete", "case-unlink": "case.save", "tc": "manual_tc.save", "tc-delete": "manual_tc.delete",
                    "scenario": "scenario.save", "scenario-delete": "scenario.delete"}

    # ---- 시나리오 폼 (docs/qa-platform-scenarios.md §9, §14 5단계) ----------------------------------
    def scenario_check(self, op: dict) -> tuple[str | None, list[str], list[str]]:
        """변경을 지금 파일에 적용해 본다 → (새 파일 텍스트|None, 오류, 경고). §6.1 오류는 저장을 막는다.
        지우는 변경은 그 케이스를 가리키던 스크립트를 "시나리오에 연결되지 않은 스크립트"로 돌리므로 그 스크립트 오류는 세지 않는다."""
        slug = scenariosmod.doc_slug(op["feature"])
        p = self.scenarios_dir / f"{slug}.yaml"
        text = p.read_text(encoding="utf-8") if p.is_file() else None
        try:
            new = scenariosmod.apply_op(text, op)
            ft = scenariosmod.parse_feature(draftsmod.yaml.safe_load(new), f"{slug}.yaml")
        except scenariosmod.ScenarioError as ex:
            return None, [str(ex).replace(f"{slug}.yaml: ", "")], []
        feats = dict(self.features)
        feats[slug] = ft
        unlinked = set(self.scenario_unlinks(op))
        cases = {k: c for k, c in self.cases.items() if k not in unlinked}
        chk = scenariosmod.check(feats, wiki=self.wiki, catalog=self.current_catalog(), cases=cases)
        fc = chk["by_feature"].get(slug) or {"errors": [], "warnings": []}
        return new, fc["errors"], fc["warnings"]

    def scenario_unlinks(self, op: dict) -> list[str]:
        """지우는 변경이면 그 케이스(들)를 구현하던 스크립트 id."""
        slug = scenariosmod.doc_slug(op["feature"])
        if op["action"] == "variant-delete":
            gone = {f"{slug}/{op['scenario']}/{op['key']}"}
        elif op["action"] == "scenario-delete":
            gone = {vid for vid in scenariosmod.variant_index(self.features) if vid.startswith(f"{slug}/{op['scenario']}/")}
        else:
            return []
        return sorted(c.id for c in self.cases.values() if c.variant in gone)

    def save_scenario(self, op: dict, *, operator: str, source: str = "form", note: str | None = None, prompt_hash: str | None = None,
                      session_hash=None, ip=None) -> dict:
        """시나리오 변경 하나를 검증하고 바로 저장한다. 오류가 있으면 저장하지 않고 {ok: False, errors}.
        케이스·시나리오를 지우면 그것을 구현하던 스크립트의 variant: 를 떼어 "시나리오에 연결되지 않은 스크립트"로 남긴다(스크립트는 지우지 않는다)."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if source == "form" and op["action"] == "variant":        # 사람이 폼으로 저장하면 Hermes 작성 표시가 떨어진다 (§7)
            op = {**op, "variant": {k: x for k, x in op["variant"].items() if k != "written_by"}}
        new, errors, warnings = self.scenario_check(op)
        if errors:
            return {"ok": False, "errors": errors, "warnings": warnings}
        unlinks = self.scenario_unlinks(op)
        op = self.with_basis(op, new)
        p = self.scenarios_dir / f"{scenariosmod.doc_slug(op['feature'])}.yaml"
        cur = p.read_text(encoding="utf-8") if p.is_file() else None
        if cur is not None and scenariosmod.apply_op(cur, op) == cur:
            return {"ok": False, "errors": ["바뀐 내용이 없다"], "warnings": warnings}
        delete = op["action"].endswith("-delete")
        v = scenariosmod.variant_raw(op["variant"]) if op["action"] == "variant" else {}
        out = self.save_change(kind="scenario-delete" if delete else "scenario", source=source,
                               yaml_text=draftsmod.yaml.safe_dump(op, allow_unicode=True, sort_keys=False), operator=operator,
                               note=(note or "").strip() or None, case_id=scenariosmod.op_target(op), prompt_hash=prompt_hash,
                               tc_ids=v.get("checks") or [t for s in op.get("scenarios") or [] for x in s.get("variants") or [] for t in x.get("checks") or []],
                               validation={"status": "warn" if warnings else "ok", "errors": [], "warnings": warnings + ([f"시나리오에 연결되지 않은 스크립트로 돌린 스크립트: {', '.join(unlinks)}"] if unlinks else [])},
                               session_hash=session_hash, ip=ip)
        for cid in unlinks:
            c = self.cases.get(cid)
            if c and c.variant:
                self.save_change(kind="case-unlink", source="scenario-delete", yaml_text=c.to_yaml(), operator=operator, case_id=cid,
                                 domain=(c.domains[0] if c.domains else None), tc_ids=c.covers, note=f"{scenariosmod.op_target(op)} 를 지워 variant: 를 뗐다",
                                 validation={"status": "ok", "warnings": []}, session_hash=session_hash, ip=ip)
        return {"ok": True, "errors": [], "warnings": warnings, "unlinked": unlinks, **out}

    def save_change(self, *, kind: str, source: str, yaml_text: str, operator: str, domain: str | None = None, note: str | None = None,
                    case_id: str | None = None, tc_ids: list | None = None, validation: dict | None = None, prompt_hash: str | None = None,
                    draft: dict | None = None, session_hash=None, ip=None) -> dict:
        """검증을 마친 변경 하나를 바로 저장한다 (docs/qa-platform-scenarios.md §9). 변경 기록(drafts 테이블) 한 줄을 남기고,
        쓰기 토큰이 있으면 main 에 커밋해 플랫폼에 바로 반영한다. 토큰이 없으면 기록만 남고 [반영된 파일 받기] 로 끝난다."""
        if draft:
            did = draft["id"]
            self.store.update_draft(did, yaml=yaml_text, validation=validation or {}, case_id=case_id, tc_ids=tc_ids or [], domain=domain, source=source, kind=kind)
        else:
            did = self.store.add_draft(operator=operator, source=source, domain=domain, yaml_text=yaml_text, note=note, case_id=case_id,
                                       tc_ids=tc_ids or [], validation=validation or {}, prompt_hash=prompt_hash, kind=kind)
        return self._apply(self.store.get_draft(did), operator=operator, action=self.SAVE_ACTIONS.get(kind, "case.save"), session_hash=session_hash, ip=ip)

    def _apply(self, d: dict, *, operator: str, action: str, note: str | None = None, session_hash=None, ip=None) -> dict:
        """변경 기록 하나를 main 에 커밋하고 플랫폼에 반영한다. 커밋이 실패하면 기록은 '저장 실패' 로 남고 BadRequest."""
        kind = d.get("kind") or "case"
        commit, rel, ids = None, None, None
        if self.repo.enabled:
            try:
                rel, change, summary, ids = self._plan(d, operator)
                why = note or (d.get("note") if kind.endswith("-delete") or str(d.get("source") or "").startswith("hermes") else None)
                msg = (f"qa({rel.split('/')[0]}): {summary} — {operator} [skip ci]\n\nQA 플랫폼 변경 {d['id']} ({d.get('source')})."
                       + (f"\n메모: {why}" if why else "") + f"\n\nQA-Operator: {operator}")
                commit = self.repo.commit(rel, change, msg)
            except RepoError as ex:
                self.store.update_draft(d["id"], status="failed", note=f"저장 실패: {ex}"[:500])
                self.store.add_event(operator=operator, action=action, target=d["id"], session_hash=session_hash, ip=ip, detail={"kind": kind, "error": str(ex)[:300]})
                raise BadRequest(f"main 에 저장하지 못했다 — {ex}")
            if self.cases_dir != self.repo.local / "cases":      # 시작 때 main 받기에 실패해 이미지 파일을 읽고 있었다 — 지금 받는다
                self.resync_repo()
            elif kind in ("tc", "tc-delete"):
                self.catalog.get(force=True)
            self.reload_cases()
        fields = {"status": "approved", "decided_by": operator, "decided_at": now_iso(), "note": (note or "").strip() or d.get("note")}
        tc_ids = d["tc_ids"]
        if commit:
            fields.update(commit_sha=commit["sha"], commit_url=commit["url"], file=rel)
            if kind == "tc" and ids:
                fields["tc_ids"] = tc_ids = ids
        self.store.update_draft(d["id"], **fields)
        self.store.add_event(operator=operator, action=action, target=d.get("case_id") or ",".join(tc_ids[:3]) or d["id"], session_hash=session_hash, ip=ip,
                             detail={"change": d["id"], "kind": kind, "source": d.get("source"), "case_id": d.get("case_id"), "tc_ids": tc_ids,
                                     "commit": (commit or {}).get("sha")})
        return {"id": d["id"], "commit": commit, "case_id": d.get("case_id"), "tc_ids": tc_ids, "file": rel, "kind": kind}

    def approve_draft(self, d: dict, *, operator: str, note: str | None, session_hash=None, ip=None) -> dict:
        """예전 방식으로 남은 초안(저장 안 된 것) 하나를 저장한다. 검증을 다시 돌린다."""
        if d["status"] in ("approved", "rejected"):
            raise BadRequest("이미 저장했거나 버린 것이다")
        kind = d.get("kind") or "case"
        if kind == "tc":
            _, errors = draftsmod.validate_manual_tc(d["yaml"])
            if errors:
                raise BadRequest("형식 오류가 있어 저장하지 않는다: " + "; ".join(errors[:3]))
        elif kind == "case":
            case, errors, _ = self.revalidate_draft(d, d["yaml"])
            if not case:
                raise BadRequest("검증 오류가 있어 저장하지 않는다: " + "; ".join(errors[:3]))
        return self._apply(d, operator=operator, action="draft.approve", note=note, session_hash=session_hash, ip=ip)

    def draft_file(self, d: dict, operator: str) -> tuple[str, str]:
        """쓰기 토큰이 없을 때: 이 변경을 반영한 파일 전체(플랫폼이 지금 읽는 판 기준). (레포 안 경로, 텍스트)."""
        rel, change, _, _ = self._plan(d, operator)
        sub, name = rel.split("/", 1)
        base = {"cases": self.cases_dir, "scenarios": self.scenarios_dir}.get(sub, self.catalog.catalog_dir) / name
        text = base.read_text(encoding="utf-8") if base.is_file() else None
        try:
            return rel, change(text)
        except RepoError as ex:
            raise BadRequest(str(ex))

    # ---- 탐색기 (docs/qa-platform-tc.md §8) ----------------------------------------
    def explorer_send(self, *, op_id: str, path_params: dict, query: dict, body_text: str, actor: str | None, operator: str,
                      session_hash: str | None, ip: str | None) -> str:
        """op 하나를 지금 보낸다. 전송 = 실행 기록(trigger explorer, 단계 1개, expect 없음). 응답은 실행 상세와 같은 기록."""
        spec = self.spec.get()
        op = spec.ops.get(op_id) if spec else None
        if not op:
            raise BadRequest("OpenAPI 에 없는 operationId")
        if actor and actor not in self.all_actors():
            raise BadRequest("없는 테스트 계정")
        path = op.path
        for prm in op.params:
            if prm["in"] == "path":
                v = str(path_params.get(prm["name"], "")).strip()
                if not v:
                    raise BadRequest(f"path 파라미터 {prm['name']} 이 비었다")
                path = path.replace("{" + prm["name"] + "}", v)
        req: dict = {"method": op.method, "path": path}
        q = {k: v for k, v in query.items() if str(v).strip() != ""}
        if q:
            req["query"] = q
        if body_text.strip():
            try:
                req["body"] = json.loads(body_text)
            except ValueError as ex:
                raise BadRequest(f"본문이 JSON 이 아니다: {ex}")
        cid = "explorer." + re.sub(r"[^a-z0-9.\-]", "", re.sub(r"(?<!^)(?=[A-Z])", "-", op_id).lower())
        raw = {"id": cid, "title": f"API 호출 · {op.summary or op_id}", "suite": "manual", "domains": [], "operations": [op_id],
               "steps": [{"name": f"{op.method} {path}", "request": req}]}
        if actor:
            raw["actor"] = actor
        from qa.cases import _validate
        case = _validate(raw, "<explorer>")
        rid = self.create_run(trigger="explorer", operator=operator, case_ids=[], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                              reason="", basis="API 호출", extra={"explorer": {"op": op_id, "actor": actor}}, session_hash=session_hash, ip=ip,
                              cases_override=[case], notify=False, enqueue=False)
        self.store.add_event(operator=operator, action="explorer.send", target=rid, session_hash=session_hash, ip=ip,
                             detail={"op": op_id, "method": op.method, "path": path, "actor": actor})
        self.runner.execute_now(rid)
        return rid

    # ---- 준비 작업 (docs/qa-platform-api.md §5.4) ------------------------------------
    def setup_cases(self) -> list:
        return sorted((c for c in self.cases.values() if c.suite == "setup"), key=lambda c: (len(c.steps), c.id))   # 단순한 것부터

    def setup_run(self, case_id: str, values: dict, *, operator: str, session_hash: str | None, ip: str | None) -> str:
        """버튼 하나로 테스트 데이터 만들기. 입력을 스크립트에 박아(스냅샷에 값이 남는다) 바로 실행한다 — 실행 기록·감사 로그는 남고 Slack 은 안 보낸다."""
        c = self.cases.get(case_id)
        if not c or c.suite != "setup":
            raise BadRequest("준비 작업 스크립트가 아니다")
        try:
            baked = bake_inputs(c, values)
        except CaseError as e:
            raise BadRequest(str(e))
        rid = self.create_run(trigger="setup", operator=operator, case_ids=[], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                              reason="", basis="준비 작업", extra={"setup": {"case": c.id, "inputs": baked.raw.get("input_values") or {}}},
                              session_hash=session_hash, ip=ip, cases_override=[baked], notify=False, enqueue=False)
        self.store.add_event(operator=operator, action="setup.run", target=rid, session_hash=session_hash, ip=ip,
                             detail={"case": c.id, "inputs": baked.raw.get("input_values") or {}})
        self.runner.execute_now(rid)
        return rid

    def refresh_spec(self, *, operator: str, session_hash: str | None, ip: str | None) -> dict:
        """[API 문서 다시 읽기] — 캐시를 무시하고 OpenAPI 를 다시 받아 테스트 조건 목록을 다시 계산한다. 새 API 가 배포된 직후 1시간(캐시)을 기다리지 않으려고.
        읽기라 자동 실행 원칙 밖이지만 사람이 누른 것이라 감사 로그에 남긴다. 반환: {ok, before, after, added, removed, tc_added, tc_removed, error}."""
        before = self.spec.get()
        before_ops = set(before.ops) if before else set()
        before_hash = before.hash if before else None
        cat_before = self.catalog.current
        tc_before = set(cat_before.records) if cat_before else set()
        spec = self.spec.get(force=True)
        cat = self.catalog.get(force=True) if spec else self.catalog.current
        if cat is not None:
            audit_cases(self.cases, cat)
        after_ops = set(spec.ops) if spec else set()
        tc_after = set(cat.records) if cat else set()
        out = {"ok": bool(spec), "error": (None if spec else (self.spec.last_error or "OpenAPI 를 읽지 못했다")),
               "before": before_hash, "after": (spec.hash if spec else None), "changed": bool(spec) and spec.hash != before_hash,
               "added": sorted(after_ops - before_ops), "removed": sorted(before_ops - after_ops),
               "tc_added": len(tc_after - tc_before), "tc_removed": len(tc_before - tc_after), "ops": len(after_ops)}
        self.store.add_event(operator=operator, action="spec.refresh", target=out["after"], session_hash=session_hash, ip=ip,
                             detail={k: v for k, v in out.items() if k != "ok"})
        return out

    def all_actors(self) -> dict:
        """테스트 계정 이름 → 회원 UUID. SSM 고정 계정(qa-host·qa-guest) + 플랫폼이 만든 QA 회원(label)."""
        return self.runner.actors.mapping()

    def create_qa_member(self, label: str, *, operator: str, session_hash: str | None, ip: str | None) -> dict:
        """QA 테스트 회원 만들기 카드. label 이 테스트 계정 이름이 된다 (스크립트 actor:, API 호출 화면 드롭다운)."""
        label = label.strip()
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}$", label):
            raise BadRequest("이름은 소문자·숫자·하이픈 (예: qa-3)")
        if label in self.all_actors():
            raise BadRequest(f"이미 있는 테스트 계정 이름: {label}")
        base = self.target_for(operator)["base_url"]
        ok, data, status = self.qadata.create_member(base=base)
        token = None
        if ok:
            data = dict(data)
            token = data.pop("accessToken", None)      # 화면에 보여 주기만 — DB·감사 로그에는 안 남긴다
            self.store.add_qa_member(member_id=data["memberId"], label=label, nickname=data.get("nickname"), email=data.get("email"), operator=operator)
            if token:
                self.runner.actors.remember(data["memberId"], base, token)
        self.store.add_event(operator=operator, action="qa_data.create_member", target=label, session_hash=session_hash, ip=ip,
                             detail={"ok": ok, "status": status, "error": (None if ok else data.get("code"))})
        return {"ok": ok, "member": data if ok else None, "token": token, "error": (None if ok else data)}

    def qa_member_token(self, member_id: str, *, operator: str, session_hash: str | None, ip: str | None) -> dict:
        """QA 회원의 액세스 토큰 — 화면에서 복사해 앱·Postman 에서 그 회원으로 로그인할 때. 담당자가 고른 대상 서버의 dev-sessions 로 받는다.
        토큰 값은 저장하지 않고, 본 사실만 감사 로그 `qa_data.view_token` 에 남긴다."""
        base = self.target_for(operator)["base_url"]
        try:
            token, err = self.runner.actors.token_for_member(member_id, base), None
        except Exception as ex:  # noqa: BLE001
            token, err = None, str(ex)
        self.store.add_event(operator=operator, action="qa_data.view_token", target=member_id, session_hash=session_hash, ip=ip,
                             detail={"ok": bool(token), "error": err})
        return {"ok": bool(token), "token": token, "error": err}

    def qa_data_action(self, action: str, target: str, *, operator: str, session_hash: str | None, ip: str | None) -> dict:
        """정리 화면의 버튼 — delete_room(룸 id) · delete_all(호스트 테스트 계정 이름 또는 빈 값) · reset(테스트 계정 이름) · delete_member(회원 id).
        결과 {ok, deleted(dict)|error(dict)}. 감사 로그 events `qa_data.<action>`."""
        base = self.target_for(operator)["base_url"]
        if action == "delete_room":
            ok, data, status = self.qadata.delete_room(target, base=base)
        elif action == "delete_all":
            host = self.runner.actors.member_id(target, base) if target else None
            if target and not host:
                raise BadRequest("없는 테스트 계정")
            ok, data, status = self.qadata.delete_all(host, base=base)
        elif action == "reset":
            mid = self.runner.actors.member_id(target, base)
            if not mid:
                raise BadRequest("없는 테스트 계정")
            ok, data, status = self.qadata.reset_member(mid, base=base)
        elif action == "delete_member":
            ok, data, status = self.qadata.delete_member(target, base=base)
            if ok:
                self.store.delete_qa_member(target)      # 플랫폼이 만든 회원이면 테스트 계정 목록에서도 뺀다
        else:
            raise BadRequest("모르는 정리 동작")
        deleted = (data.get("deleted") or {}) if ok else {}
        self.store.add_event(operator=operator, action=f"qa_data.{action}", target=target or None, session_hash=session_hash, ip=ip,
                             detail={"ok": ok, "status": status, "total": deleted.get("total"), "rooms": deleted.get("rooms"),
                                     "error": (None if ok else data.get("code"))})
        return {"ok": ok, "deleted": deleted, "error": (None if ok else data)}

    def setup_outputs(self, run: dict) -> dict:
        """준비 작업이 돌려줄 값 — 스냅샷의 save 경로를 단계 응답에서 다시 읽는다 (러너의 변수 상태는 저장하지 않으므로)."""
        from qa.cases import parse_one
        from qa.templating import get_path
        rcs = self.store.list_run_cases(run["id"])
        if not rcs:
            return {}
        try:
            case = parse_one(rcs[0]["case_yaml"], "run")
        except Exception:
            return {}
        steps = self.store.list_steps(rcs[0]["id"])
        out: dict = {}
        for i, st in enumerate(case.steps):
            resp = (steps[i].get("response") or {}) if i < len(steps) else {}
            for var, path in (st.get("save") or {}).items():
                if var in case.outputs:
                    out[var] = get_path(resp.get("json"), path) if resp.get("json") is not None else None
        for var in case.outputs:
            out.setdefault(var, None)
        return out

    def explorer_to_draft(self, rid: str, operator: str, session_hash: str | None, ip: str | None) -> str:
        """API 호출 기록 하나를 스크립트 폼에 담는다(단계 1개, 관측한 status·error_code 를 기대로). 저장 안 된 변경 기록으로 두고 폼을 연다. covers 는 사람이 채운다."""
        run = self.store.get_run(rid)
        if not run or run["trigger"] != "explorer":
            raise BadRequest("API 호출 기록이 아니다")
        rcs = self.store.list_run_cases(rid)
        steps = self.store.list_steps(rcs[0]["id"]) if rcs else []
        if not steps:
            raise BadRequest("기록된 단계가 없다")
        st = steps[0]
        req = st["request"]
        resp = st.get("response") or {}
        expect: dict = {}
        if resp.get("status"):
            expect["status"] = resp["status"]
        js = resp.get("json") if isinstance(resp.get("json"), dict) else None
        if js and js.get("result"):
            expect["result"] = js["result"]
        if js and isinstance(js.get("error"), dict) and js["error"].get("code"):
            expect["error_code"] = js["error"]["code"]
        op_id = (run["meta"].get("explorer") or {}).get("op") or "op"
        request = {"method": req["method"], "path": req["path"]}
        if req.get("query"):
            request["query"] = req["query"]
        if req.get("body") is not None:
            request["body"] = req["body"]
        raw = {"id": rcs[0]["case_id"].replace("explorer.", "draft.", 1), "title": f"TODO: {rcs[0]['case_title']}", "suite": "manual",
               "domains": [], "operations": [op_id], "covers": [], "steps": [{"name": st["name"], "covers": [], "request": request, "expect": expect}]}
        if req.get("actor"):
            raw["actor"] = req["actor"]
        text = draftsmod.yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        did = self.store.add_draft(operator=operator, source="explorer", domain=None, yaml_text=text, note=f"API 호출 기록 {rid}", case_id=raw["id"], tc_ids=[],
                                   validation={"status": "warn", "warnings": ["covers 와 suite 를 채워야 한다 (지금은 manual)"]}, prompt_hash=None)
        self.store.add_event(operator=operator, action="explorer.to_form", target=did, session_hash=session_hash, ip=ip, detail={"source": "explorer", "run_id": rid})
        return did

    # ---- 위키 보고서 발행 (docs/qa-platform-tc.md §9) ------------------------------
    def publish_run(self, run: dict, *, operator: str, dry_run: bool, session_hash: str | None, ip: str | None) -> dict:
        if not (self.cfg.wiki_mcp_url and self.cfg.wiki_mcp_token):
            raise BadRequest("LLM_WIKI_MCP_URL / LLM_WIKI_MCP_BEARER_TOKEN 이 없어 게시할 수 없다")
        if run["trigger"] not in ("sprint-smoke", "release", "deploy-sanity"):
            raise BadRequest("스프린트·릴리스·배포 검증 실행만 게시한다")
        if run["status"] != "finished":
            raise BadRequest("실행이 끝난 뒤에 게시한다")
        rcs = self.store.list_run_cases(run["id"])
        cat = self.current_catalog()
        sprint = self.cfg.current_sprint(datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))) if run["trigger"] == "sprint-smoke" else None
        slug = reportmod.slug_for(run)
        content = reportmod.render(run, rcs, coverage=self.coverage(cat) if cat else None, catalog=cat, public_url=self.cfg.public_url, sprint=sprint,
                                   groups=self.run_groups(rcs))
        client = McpClient(self.cfg.wiki_mcp_url, self.cfg.wiki_mcp_token, timeout=60)
        try:
            res = wiki_apply(client, path=slug, content=content, message=f"qa: {run['trigger']} 보고서 {run['id']} ({operator})", dry_run=dry_run)
        except McpError as ex:
            self.store.add_event(operator=operator, action="run.publish", target=run["id"], session_hash=session_hash, ip=ip,
                                 detail={"slug": slug, "dry_run": dry_run, "error": str(ex)[:300]})
            raise BadRequest(str(ex))
        rec = {"slug": slug, "at": now_iso(), "by": operator, "dry_run": dry_run, "result": (res if isinstance(res, dict) else {"text": str(res)}),
               "url": f"{self.cfg.wiki_public_url}/{slug}/"}
        if not dry_run:
            self.store.merge_run_meta(run["id"], {"published": rec})
        self.store.add_event(operator=operator, action="run.publish", target=run["id"], session_hash=session_hash, ip=ip,
                             detail={"slug": slug, "dry_run": dry_run, "chars": len(content)})
        return rec

    # ---- Hermes 대화 (docs/qa-platform-hermes.md §3.2) ----------------------------------
    def chat_create(self, *, operator: str, context: dict, session_hash: str | None, ip: str | None) -> str:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not self.cfg.hermes_key:
            raise BadRequest("HERMES_API_KEY 가 없어 Hermes 와 이야기할 수 없다")
        _, title = chatmod.context_block(self, context)
        cid = self.store.add_chat(operator=operator, title=title, context={k: v for k, v in context.items() if v})
        self.store.add_event(operator=operator, action="chat.create", target=cid, session_hash=session_hash, ip=ip, detail={"context": context})
        return cid

    def chat_check(self, chat: dict, text: str, *, operator: str) -> None:
        """보내기 전 검사 — 스트림을 열기 전에 400 으로 돌려줄 수 있게 따로 둔다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        if not text.strip():
            raise BadRequest("메시지가 비었다")
        if len(text) > 8000:
            raise BadRequest("메시지는 8000자까지")
        if chat["status"] != "open":
            raise BadRequest("닫힌 대화다 — 새 대화를 연다")
        if chat["turns"] >= self.cfg.chat_max_turns:
            raise BadRequest(f"대화당 {self.cfg.chat_max_turns}턴까지 — 새 대화를 연다")
        if self.chat_stale(chat):
            raise BadRequest(f"{self.cfg.chat_stale_days}일 넘게 조용했던 대화다 — 새 대화를 연다")

    def chat_send(self, chat: dict, text: str, *, operator: str, session_hash: str | None, ip: str | None, emit=None) -> dict:
        self.chat_check(chat, text, operator=operator)
        return chatmod.send(self, chat, text, operator=operator, session_hash=session_hash, ip=ip, emit=emit)

    def chat_stale(self, chat: dict) -> bool:
        try:
            last = datetime.fromisoformat(chat["updated_at"].replace("Z", "+00:00"))
        except ValueError:
            return False
        return (datetime.now(last.tzinfo) - last).days >= self.cfg.chat_stale_days

    def revalidate_draft(self, d: dict, yaml_text: str) -> tuple:
        """편집된 YAML 을 다시 검증한다. (Case|None, errors, warnings)."""
        cat = self.current_catalog()
        try:
            raw = draftsmod.yaml.safe_load(yaml_text)
        except Exception as ex:
            return None, [f"YAML 파싱 실패: {ex}"], []
        if not isinstance(raw, dict):
            return None, ["스크립트는 맵이어야 한다"], []
        return draftsmod.validate(raw, actors=self.all_actors(), requested=list(raw.get("covers") or []) + [t for s in (raw.get("steps") or []) if isinstance(s, dict) for t in (s.get("covers") or [])],
                                  catalog=cat, cfg=self.cfg, existing_ids=set(self.cases) - {d.get("case_id")}, library=self.cases)

    def _on_finish(self, run: dict):
        if run["trigger"] in HIDDEN_TRIGGERS:
            return
        rcs = self.store.list_run_cases(run["id"])
        bad = [f"{rc['case_id']}" for rc in rcs if rc["verdict"] in ("fail", "error")]
        icon = {"pass": "✅", "fail": "❌", "error": "⚠️", "skipped": "⏭", "canceled": "⏹"}.get(run["verdict"], "")
        msg = (f"[QA] {icon} {ui.TRIGGER_KO.get(run['trigger'], run['trigger'])} {run['verdict']} — 통과 {run['passed']} 실패 {run['failed']} 오류 {run['errored']} skip {run['skipped']}"
               + (f"\n실패: {', '.join(bad[:8])}" if bad else "") + f"\n{self.cfg.public_url}/runs/{run['id']}")
        slack(self.cfg.slack_webhook_url, msg)

    # ---- 홈 · 왼쪽 메뉴 (docs/qa-platform-v2.md §7) --------------------------------------
    def smoke_scripts(self) -> list:
        """스모크에서 돌 수 있는 스크립트 — 테스트 데이터 만들기 카드와 API 호출 전용(manual)은 뺀다."""
        return [c for c in self.cases.values() if c.suite not in ("setup", "manual")]

    SMOKE_DOMAIN_GROUP = {"auth": "기본 (로그인 · 상태)", "member": "기본 (로그인 · 상태)", "platform": "기본 (로그인 · 상태)", "catalog": "카탈로그 (약관 · 직무 · 지역)"}

    def smoke_groups(self) -> list[dict]:
        """스모크 범위 표 (docs/qa-platform-v2.md §6): 스크립트를 기능별로 묶는다. 시나리오에 연결된 것은 그 기능, 아니면 도메인으로."""
        names = {slug: f.feature for slug, f in self.features.items()}
        last = self.store.last_verdicts()
        groups: dict[str, list] = {}
        for c in self.smoke_scripts():
            if c.variant:
                g = names.get(c.variant.split("/", 1)[0], c.variant.split("/", 1)[0])
            else:
                d = c.id.split(".", 1)[0] if c.id.split(".", 1)[0] in self.SMOKE_DOMAIN_GROUP else (c.domains or ["기타"])[0]
                g = self.SMOKE_DOMAIN_GROUP.get(d) or (("룸 탐색" if "explore" in c.id else "룸 생성") if d == "room" else d)
            groups.setdefault(g, []).append({"id": c.id, "title": c.title, "steps": len(c.steps), "suite": c.suite, "last": last.get(c.id)})
        return sorted(({"name": k, "scripts": v} for k, v in groups.items()), key=lambda x: (-len(x["scripts"]), x["name"]))

    def nav_counts(self) -> dict:
        return {"sanity": self._sanity_todo, "smoke": len(self.smoke_scripts())}

    def sanity_prs(self, limit: int = 12) -> list[dict]:
        """dev 로 머지된 PR 과 그 PR 의 마지막 Sanity (§4.4). API 가 바뀐 PR 이 앞, 나머지는 뒤."""
        last = self.store.latest_sanity()
        out = []
        for pr in self.github.merged_prs(limit):
            s = sanitymod.summarize(self.github.pr_file_details(pr["number"]))
            out.append({**pr, **s, "sanity": last.get(pr["number"])})
        self._sanity_todo = sum(1 for p in out if p["api"] and (not p["sanity"] or p["sanity"]["status"] in ("needs_spec", "failed", "error", "interrupted")))
        return out

    def qa_snapshot(self, operator: str, fresh: bool = False) -> dict | None:
        """담당자가 고른 대상에 남은 QA 데이터. fresh 면 대상에 묻고, 아니면 마지막으로 물은 값(10분 안)만 — 홈이 대상 서버를 기다리지 않게."""
        import time
        base = self.target_for(operator)["base_url"]
        if fresh:
            self._qa_snap[base] = (time.monotonic(), self.qadata.snapshot(base))
        hit = self._qa_snap.get(base)
        if hit and time.monotonic() - hit[0] < 600:
            return hit[1]
        return None

    # ---- 대상 서버 (docs/qa-platform-v2.md §13, 사용자 결정 2026-09-27) ----------------------
    def dev_target(self) -> dict:
        return {"id": targetsmod.DEV_ID, "name": "dev", "base_url": self.cfg.target_base_url, "actors": {}, "default": True}

    def targets(self) -> list[dict]:
        return [self.dev_target()] + self.store.list_targets()

    def target_for(self, operator: str | None) -> dict:
        """담당자가 고른 대상. 고른 적 없거나 지워졌으면 dev."""
        tid = self.store.get_setting(f"target:{operator}") if operator else None
        if tid and tid != targetsmod.DEV_ID:
            t = self.store.get_target(tid)
            if t:
                return t
        return self.dev_target()

    def target_actors(self, base_url: str) -> dict:
        """러너가 부른다 — 그 주소로 등록한 대상에 따로 적은 테스트 계정."""
        if base_url == self.cfg.target_base_url:
            return {}
        t = next((x for x in self.store.list_targets() if x["base_url"] == base_url), None)
        return {k: v for k, v in (t or {}).get("actors", {}).items() if v}

    def select_target(self, tid: str, *, operator: str, session_hash=None, ip=None) -> dict:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        t = self.dev_target() if tid == targetsmod.DEV_ID else self.store.get_target(tid)
        if not t:
            raise BadRequest("없는 대상")
        self.store.set_setting(f"target:{operator}", t["id"])
        self.store.add_event(operator=operator, action="target.select", target=t["id"], session_hash=session_hash, ip=ip, detail={"name": t["name"], "url": t["base_url"]})
        return t

    def add_target(self, *, name: str, base_url: str, actors: dict, operator: str, session_hash=None, ip=None) -> dict:
        """[+ 대상 추가] — 주소를 검사하고 한 번 불러 본 뒤 저장한다. 불러 보기 결과는 보여 주기만 한다."""
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        name = name.strip()
        if not name or len(name) > 40:
            raise BadRequest("이름을 40자 안으로 적어 주세요")
        try:
            url = targetsmod.check(base_url, allow_local=self.cfg.allow_local_targets)
        except targetsmod.TargetError as ex:
            raise BadRequest(str(ex))
        if any(x["base_url"] == url or x["name"] == name for x in self.targets()):
            raise BadRequest("같은 이름이나 주소의 대상이 이미 있어요")
        actors = {k: v.strip() for k, v in actors.items() if v and v.strip()}
        bad = [k for k, v in actors.items() if not re.match(r"^[0-9a-fA-F-]{8,64}$", v)]
        if bad:
            raise BadRequest(f"회원 id 형식이 아니에요: {', '.join(bad)}")
        pr = targetsmod.probe(url)
        tid = self.store.add_target(name=name, base_url=url, actors=actors, operator=operator, probe=pr)
        self.store.add_event(operator=operator, action="target.add", target=tid, session_hash=session_hash, ip=ip,
                             detail={"name": name, "url": url, "actors": sorted(actors), "probe": {k: v["status"] for k, v in pr.items()}})
        return self.store.get_target(tid)

    def remove_target(self, tid: str, *, operator: str, session_hash=None, ip=None) -> None:
        if not operator or operator not in self.cfg.operators:
            raise BadRequest("담당자를 목록에서 골라야 한다")
        t = self.store.get_target(tid)
        if not t:
            raise BadRequest("없는 대상 (dev 는 지울 수 없어요)")
        self.store.delete_target(tid)
        self.store.add_event(operator=operator, action="target.delete", target=tid, session_hash=session_hash, ip=ip, detail={"name": t["name"], "url": t["base_url"]})

    def home_todo(self, prs: list[dict], operator: str = "") -> list[dict]:
        """지금 할 일 (§7.2). 한 줄에 버튼 하나. tone: warn · info · plain · bad"""
        todo = []
        for p in prs:
            s = p["sanity"]
            if not p["api"]:
                continue
            if s and s["status"] == "needs_spec":
                n = sum(1 for f in s["findings"] if f.get("kind") in sanitymod.BLOCKING and not f.get("resolved_at"))
                todo.append({"tone": "warn", "icon": "!", "title": f"PR #{p['number']} 스펙 확인이 {n}건 필요해요", "desc": p["title"],
                             "href": f"/sanity/{p['number']}", "button": "질문 보기"})
            elif s and s["status"] in ("failed", "error", "interrupted"):
                todo.append({"tone": "bad", "icon": "✕", "title": f"PR #{p['number']} Sanity 가 {sanitymod.STATUS_KO[s['status']]}했어요".replace("멈춤했어요", "멈췄어요"),
                             "desc": p["title"], "href": f"/sanity/{p['number']}", "button": "결과 보기"})
            elif not s:
                todo.append({"tone": "info", "icon": "#", "title": f"PR #{p['number']} · 아직 검증하지 않았어요", "desc": p["title"],
                             "href": f"/sanity/{p['number']}", "button": "Sanity 시작"})
        sprint = self.cfg.current_sprint()
        if not self.store.runs_since(sprint["starts_at"].isoformat().replace("+00:00", "Z"), "sprint-smoke"):
            end = sprint["ends_at"].astimezone(ui.KST)
            todo.append({"tone": "plain", "icon": "▶", "title": f"이번 스프린트(Cycle {sprint['number']}) 스모크를 아직 안 했어요",
                         "desc": f"스크립트 {len(self.smoke_scripts())}개 · {end.month}월 {end.day}일 전까지", "href": "/smoke", "button": "스모크 실행"})
        snap = self.qa_snapshot(operator)
        if snap and (snap.get("rooms") or snap.get("members")):
            nr, nm = len(snap.get("rooms") or []), len(snap.get("members") or [])
            todo.append({"tone": "plain", "icon": "▦", "title": f"dev 에 QA 데이터가 남아 있어요 (룸 {nr} · 회원 {nm})",
                         "desc": "실패한 실행이 만든 룸일 수 있어요", "href": "/data", "button": "정리하기"})
        return todo


# ---- HTTP -------------------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "qa-platform/0.1"

    def log_message(self, fmt, *args):  # 조용히: 요청 로그에 쿼리(담당자 등)가 섞이지 않게 경로만
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
        op = c["qa_operator"].value if "qa_operator" in c else ""
        return op if op in self.app.cfg.operators else ""     # 목록에서 빠진 이름은 없는 것으로 — 다시 고르게 한다

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

    def _page(self, title, body, active="", flash=None, status=200, context=None, autostart=None, inline_chat=None):
        op = self._operator()
        if flash is None:           # 다른 화면에서 돌아온 알림 (?done= · ?err=) — 대상 바꾸기처럼 원래 화면으로 돌려보내는 동작
            q = parse_qs(urlsplit(self.path).query)
            flash = ("ok", q["done"][0]) if q.get("done") else (("err", q["err"][0]) if q.get("err") else None)
        self._send(status, ui.page(title, body, active=active, operator=op, flash=flash, context=context, hermes=bool(self.app.cfg.hermes_key),
                                   operators=self.app.cfg.operators, autostart=autostart, inline_chat=inline_chat, counts=self.app.nav_counts(),
                                   target=self.app.target_for(op), targets=self.app.targets()))

    # -- SSE (Hermes 위젯) --
    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse(self, event: str, data) -> bool:
        try:
            if event == "keepalive":
                self.wfile.write(b": keepalive\n\n")
            else:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _job_events(self, jid: str):
        """Hermes 작업 진행 SSE. 연결하자마자 전체 상태(글 포함)를 snapshot 으로, 이후 state·text(덧붙일 글)를, 끝나면 end 를 보내고 닫는다."""
        from qa.jobs import TERMINAL
        app = self.app
        snap = app.jobs.snapshot(jid, with_text=True)
        if not snap:
            return self._json(404, {"error": "그 Hermes 작업이 없다"})
        self._sse_start()
        if not self._sse("snapshot", snap):
            return
        job = app.jobs.get(jid)
        if job is None or snap["status"] in TERMINAL:
            self._sse("end", snap)
            return
        ver, sent = snap["version"], snap["text_len"]
        while True:
            if not app.jobs.wait(job, ver, 15):
                if not self._sse("keepalive", None):
                    return
                continue
            st = job.snapshot()
            ver = st["version"]
            if len(job.text) > sent:
                if not self._sse("text", {"append": job.text[sent:]}):
                    return
                sent = len(job.text)
            if st["status"] in TERMINAL:
                self._sse("end", st)
                return
            if not self._sse("state", st):
                return

    def _wants_json(self) -> bool:
        return self.path.startswith("/api/") or "application/json" in self.headers.get("Accept", "")

    # -- 라우팅 --
    def do_GET(self):
        try:
            self._route("GET")
        except BadRequest as e:
            self._error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self._error(500, _crash_summary(e))

    def do_POST(self):
        try:
            self._route("POST")
        except BadRequest as e:
            self._error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self._error(500, _crash_summary(e))

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
                                    "wiki": {"available": app.wiki.available, "head": app.wiki.head()},
                                    "mcp": {"enabled": app.mcp.enabled, "tools": len(app.mcp._impl)}, "config": app.cfg.summary()})

        # ---------- QA MCP (내부 전용 — Hermes 만 부른다. Caddy @qa 는 이 경로를 403 으로 막는다) ----------
        if path == "/mcp":
            if method != "POST":
                return self._send(HTTPStatus.METHOD_NOT_ALLOWED, "", headers={"Allow": "POST"})
            if not app.mcp.enabled:
                return self._json(503, {"error": "QA_MCP_TOKEN 이 없어 QA MCP 가 꺼져 있다"})
            if not app.mcp.authorized(self.headers.get("Authorization")):
                app.store.add_event(operator="(미인증)", action="mcp.denied", target=None, ip=self._ip(), detail={"has_header": bool(self.headers.get("Authorization"))})
                return self._send(HTTPStatus.UNAUTHORIZED, json.dumps({"error": "bearer 토큰이 틀리다"}), "application/json; charset=utf-8",
                                  headers={"WWW-Authenticate": "Bearer"})
            status, resp = app.mcp.handle(self._body(), ip=self._ip())
            if resp is None:
                return self._send(HTTPStatus.ACCEPTED, "")
            return self._json(status, resp)

        # ---------- 담당자 고르기 (처음 들어올 때, 사용자 요청 2026-09-22) ----------
        if path == "/static/tour.js" and method == "GET":
            from qa import tour
            return self._send(200, tour.JS, "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/static/help.js" and method == "GET":
            return self._send(200, helpmod.js(), "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/whoami":
            if method == "POST":
                f = self._form()
                op = str((f.get("operator") or [""])[0]).strip()
                nxt = str((f.get("next") or ["/"])[0]) or "/"
                if op not in app.cfg.operators:
                    raise BadRequest("담당자를 목록에서 골라야 한다")
                if not nxt.startswith("/") or nxt.startswith("//"):
                    nxt = "/"
                app.store.add_event(operator=op, action="operator.pick", target=None, session_hash=self._session_hash(), ip=self._ip(), detail={})
                return self._redirect(nxt, set_operator=op)
            return self._page("누구세요?", ui.whoami_page(app.cfg.operators, current=self._operator(), next_url=g("next") or "/"), "")
        # HTML 화면인데 담당자 쿠키가 없으면 먼저 고르게 한다 (API·정적 파일·MCP 는 제외)
        if method == "GET" and not self._operator() and not path.startswith(("/api/", "/static/")) and "application/json" not in self.headers.get("Accept", ""):
            from urllib.parse import quote
            return self._redirect(f"/whoami?next={quote(self.path, safe='')}")

        # ---------- 대시보드 ----------
        if path == "/" and method == "GET":
            prs = app.sanity_prs()
            ov, _ = app.scenario_view()
            body = ui.home(operator=self._operator(), todo=app.home_todo(prs, self._operator()), ov=ov, counts=app.nav_counts(),
                           recent=app.store.list_runs(5, exclude=HIDDEN_TRIGGERS), target=app.target_for(self._operator())["base_url"], gh_error=app.github.last_error)
            return self._page("홈", body, "home")

        # ---------- 시나리오 (docs/qa-platform-scenarios.md §12) ----------
        if path == "/features" and method == "GET":
            ov, chk = app.scenario_view()
            return self._page("시나리오", ui.scenario_tree(ov, errors=chk["errors"], title="시나리오"), "features")
        # Hermes (§7): 변형 채우기 · 변형에서 스크립트 만들기 — 사람이 누른 것만 작업이 된다
        if path in ("/features/fill", "/features/script", "/features/realign") and method == "POST":
            f = self._form()
            fv = lambda k, d="": str((f.get(k) or [d])[0])  # noqa: E731
            operator = fv("operator").strip() or self._operator()
            if path == "/features/fill":
                job = app.job_fill(fv("slug"), operator, self._session_hash(), self._ip())
            elif path == "/features/realign":
                job = app.job_realign(fv("slug"), fv("scenario"), operator, self._session_hash(), self._ip())
            else:
                job = app.job_variant_script(fv("variant"), operator, self._session_hash(), self._ip())
            return self._json(200, {"job": job.id, "url": f"/jobs/{job.id}"}) if self._wants_json() else self._redirect(f"/jobs/{job.id}", set_operator=operator)
        # 시나리오 폼 (§14 5단계): 저장·지우기는 §6.1 검사를 거쳐 main 에 바로 커밋한다
        if path in ("/features/save", "/features/delete") and method == "POST":
            f = self._form()
            fv = lambda k, d="": str((f.get(k) or [d])[0])  # noqa: E731
            operator = fv("operator").strip() or self._operator()
            feature, sid, action = fv("feature").strip(), fv("scenario").strip(), fv("action")
            op: dict = {"feature": feature, "scenario": sid, "action": action}
            if path == "/features/delete":
                if action == "variant-delete":
                    op["key"] = fv("key")
                elif action != "scenario-delete":
                    raise BadRequest("모르는 지우기")
            elif action == "variant":
                op["original_key"] = fv("original_key").strip() or None
                op["variant"] = {k: fv(k) for k in ("key", "kind", "at", "title", "given", "then", "checks", "mode", "manual_reason")}
                if op["variant"].get("mode") != "manual":
                    op["variant"]["manual_reason"] = ""
            elif action == "basis":
                pass                                             # PRD·규칙표 변경을 확인만 했다 — 저장이 지문을 새로 적는다
            elif action == "scenario":
                op["actor"] = fv("actor").strip() or None
                op["gates"] = {k[5:]: [x.strip() for x in str(v[0]).split(",") if x.strip()] for k, v in f.items() if k.startswith("gate.")}
            else:
                raise BadRequest("모르는 저장")
            out = app.save_scenario(op, operator=operator, note=fv("reason") or None, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200 if out["ok"] else 400, out)
            if not out["ok"]:
                if path == "/features/delete" or action == "basis":
                    raise BadRequest("지우지 못했다: " + "; ".join(out["errors"][:3]))
                fx, sx = app.scenario_ctx(scenariosmod.doc_slug(feature), sid)
                if action == "variant":
                    raw = scenariosmod.variant_raw(op["variant"])
                    body = ui.variant_form(fx, sx, raw, mode="edit" if op["original_key"] else "new", operator=operator, tc_options=app.tc_options(),
                                           errors=out["errors"], warnings=out["warnings"])
                else:
                    body = ui.scenario_form(fx, sx, operator=operator, actors=sorted(app.all_actors()), gate_options=sorted(app.gate_names().items()),
                                            errors=out["errors"], warnings=out["warnings"], values={"actor": op["actor"], "gates": op["gates"]})
                return self._page("시나리오 폼", body, "features")
            link = app.change_link(out)
            return self._redirect(link["href"], set_operator=operator)
        m = re.match(r"^/features/([^/]+)/(S\d+)/(new|edit)$", path) or re.match(r"^/features/([^/]+)/(S\d+)/([^/]+)/(edit)$", path)
        if m and method == "GET":
            from urllib.parse import unquote
            import unicodedata
            fx, sx = app.scenario_ctx(unicodedata.normalize("NFC", unquote(m.group(1))), m.group(2))
            if m.lastindex == 4:
                key = unquote(m.group(3))
                v = next((x for x in sx["variants"] if x["variant"].key == key), None)
                if not v:
                    return self._error(404, "그 케이스가 없다")
                body = ui.variant_form(fx, sx, dict(v["variant"].raw), mode="edit", operator=self._operator(), tc_options=app.tc_options())
            elif m.group(3) == "new":
                raw = {k: g(k) for k in ("key", "kind", "at", "title", "given", "then", "mode", "manual_reason") if g(k)}
                raw["checks"] = [x.strip() for x in g("checks").split(",") if x.strip()]
                body = ui.variant_form(fx, sx, raw, mode="new", operator=self._operator(), tc_options=app.tc_options())
            else:
                body = ui.scenario_form(fx, sx, operator=self._operator(), actors=sorted(app.all_actors()), gate_options=sorted(app.gate_names().items()))
            return self._page("시나리오 폼", body, "features")
        m = re.match(r"^/features/([^/]+)(?:/(S\d+)/([^/]+))?$", path)
        if m and method == "GET":
            from urllib.parse import unquote
            import unicodedata
            slug = unicodedata.normalize("NFC", unquote(m.group(1)))
            ov, chk = app.scenario_view()
            f = next((x for x in ov if x["slug"] == slug), None)
            if not f:
                return self._error(404, "그 기능이 없다")
            if not m.group(2):
                return self._page(f["feature"], ui.feature_page(f, check=chk, gate_names=app.gate_names(), operator=self._operator(), hermes=bool(app.cfg.hermes_key),
                                                               prd_url=app.wiki.prd_url(f["feature"]) if app.wiki.available else None), "features")
            s = next((x for x in f["scenarios"] if x["id"] == m.group(2)), None)
            key = unquote(m.group(3))
            v = next((x for x in (s or {}).get("variants", []) if x["variant"].key == key), None)
            if not v:
                return self._error(404, "그 케이스가 없다")
            cat = app.current_catalog()
            hist = sorted((dict(r, case_id=c.id) for c in v["scripts"] for r in app.store.case_history(c.id, 10)), key=lambda r: r["created_at"], reverse=True)[:15]
            step = next((st for st in s["steps"] if st.get("req") == v["variant"].at), None)
            return self._page(v["variant"].title, ui.variant_page(f, s, v, check=chk, tc_records=(cat.records if cat else {}), history=hist, step=step, operator=self._operator(),
                                                                   hermes=bool(app.cfg.hermes_key)), "features")

        # ---------- 런 ----------
        if path == "/runs" and method == "GET":
            show_all = g("all") == "1"
            return self._page("테스트 실행", ui.runs_list(app.store.list_runs(100, exclude=() if show_all else HIDDEN_TRIGGERS), show_all), "runs")

        if path == "/runs/new" and method == "GET":
            trigger = g("trigger", "manual")
            if trigger not in TRIGGERS:
                raise BadRequest(f"모르는 실행 종류: {trigger}")
            sha, pr = g("sha") or None, (int(g("pr")) if g("pr").isdigit() else None)
            suggested, basis, info = app.suggest(trigger, sha, pr)
            picked = [x.strip() for v in q.get("case_ids", []) for x in v.split(",") if x.strip()]
            if trigger == "manual" and picked:        # 시나리오 트리에서 고른 케이스 → 그 케이스를 구현한 스크립트 (§11)
                suggested = [app.cases[i] for i in dict.fromkeys(picked) if i in app.cases]
                basis = f"시나리오 화면에서 고른 케이스의 스크립트 {len(suggested)}개"
            pr = info.get("pr_number", pr)
            target = {"환경": f'<span class="mono">{ui.e(app.target_for(self._operator())["base_url"])}</span>'}
            if sha:
                target["SHA"] = f'<span class="mono">{ui.e(sha)}</span>'
            if pr:
                target["PR"] = f'<a href="{ui.e(info.get("pr_url"))}">#{pr}</a> {ui.e(info.get("pr_title") or "")}'
            if info.get("domains") is not None:
                target["변경 도메인"] = ui.e(", ".join(info["domains"]) or "–")
            warnings = []
            if any(c.needs_actor() for c in suggested) and not app.cfg.actors:
                warnings.append("테스트 계정(QA_ACTORS)이 설정되지 않았다 — 테스트 계정이 필요한 스크립트는 skipped 로 기록된다.")
            if app.github.last_error and trigger == "deploy-sanity":
                warnings.append(app.github.last_error)
            app.current_catalog()
            drifted = [c.id for c in suggested if app.drift_of(c)]
            if drifted:
                warnings.append("검증하는 테스트 조건이 바뀐 스크립트가 있다 (스크립트 화면에서 확인): " + ", ".join(drifted[:6]) + (" …" if len(drifted) > 6 else ""))
            blocked = [c.id for c in app.cases.values() if c.blocked]
            if blocked:
                warnings.append("테스트 조건 정합성 불일치로 스위트에서 빠진 스크립트: " + ", ".join(blocked[:6]))
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
                return self._error(404, "실행 기록이 없다")
            rcs = app.store.list_run_cases(rid)
            steps = {rc["id"]: app.store.list_steps(rc["id"]) for rc in rcs}
            if m.group(1):
                return self._json(200, {"run": run, "cases": [dict(rc, steps=steps[rc["id"]]) for rc in rcs]})
            checklist = app.github.release_checklist() if run["trigger"] == "release" else []
            # 도메인별 진행 막대(docs/qa-platform-api.md §5.7)는 스냅샷의 domains 로 — 지금 파일이 아니라 그때 돌린 스크립트 기준
            # 검증(parse_one)이 아니라 YAML 만 읽는다 — covers 가 필수이기 전의 옛 스냅샷도 도메인은 있다
            domains_by_rc = {}
            for rc in rcs:
                try:
                    d = yaml.safe_load(rc["case_yaml"]) or {}
                    domains_by_rc[rc["id"]] = [str(x) for x in (d.get("domains") or [])]
                except Exception:
                    domains_by_rc[rc["id"]] = []
            flash = None
            if run["meta"].get("_flash"):
                flash = tuple(run["meta"]["_flash"])
                m2 = dict(run["meta"]); m2.pop("_flash", None)
                app.store.update_run(rid, meta=m2)
                run["meta"] = m2
            return self._page(f"실행 {rid}", ui.run_detail(run, rcs, steps, operators=app.cfg.operators, operator=self._operator(),
                                                        checklist=checklist, public_url=app.cfg.public_url,
                                                        can_publish=bool(app.cfg.wiki_mcp_url and app.cfg.wiki_mcp_token), domains_by_rc=domains_by_rc, f_verdict=g("verdict"),
                                                        groups=app.run_groups(rcs)),
                              "runs", flash=flash, context={"run": rid})

        m = re.match(r"^/(api/)?runs/(r-[0-9a-f\-]+)/(cancel|triage|decide|publish)$", path)
        if m and method == "POST":
            rid, action = m.group(2), m.group(3)
            run = app.store.get_run(rid)
            if not run:
                return self._error(404, "실행 기록이 없다")
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
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
                    raise BadRequest("run_case_id 가 이 실행의 것이 아니다")
                if not m.group(1):        # 화면: Hermes 작업으로 돌리고 진행을 SSE 로 (docs/qa-platform-progress.md)
                    job = app.job_triage(run, rc, operator, sh, ip)
                    if self.headers.get("X-QA-Job"):
                        return self._json(200, {"job": job.id})
                    return self._redirect(f"/jobs/{job.id}", set_operator=operator)
                try:
                    steps = app.store.list_steps(rc["id"])
                    text = hermes_triage(app.cfg, run, rc, steps, rules=app.triage_rules(steps))
                    app.store.update_run_case(rc["id"], triage=text, triaged_at=now_iso())
                    app.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=sh, ip=ip,
                                        detail={"case": rc["case_id"], "chars": len(text)})
                    flash = ("ok", f"Hermes 실패 분석을 {rc['case_id']} 에 기록했다")
                except Exception as ex:
                    app.store.add_event(operator=operator, action="run.triage", target=rid, session_hash=sh, ip=ip,
                                        detail={"case": rc["case_id"], "error": str(ex)[:300]})
                    flash = ("err", f"Hermes 실패 분석 실패: {ex}")
                if m.group(1):
                    return self._json(200 if flash[0] == "ok" else 502, {"ok": flash[0] == "ok", "message": flash[1]})
                self._send(HTTPStatus.SEE_OTHER, "", headers={"Location": f"/runs/{rid}", "Set-Cookie": f"qa_operator={operator}; Path=/; Max-Age=31536000; SameSite=Lax"})
                return
            if action == "publish":
                dry = str(fv("dry")) == "1"
                try:
                    rec = app.publish_run(run, operator=operator, dry_run=dry, session_hash=sh, ip=ip)
                    flash = ("ok", ("dry-run 통과: " if dry else "게시됨: ") + rec["slug"] + (" — " + json.dumps(rec["result"], ensure_ascii=False)[:300] if dry else ""))
                except BadRequest as ex:
                    flash = ("err", f"게시 실패: {ex}")
                if m.group(1):
                    return self._json(200 if flash[0] == "ok" else 502, {"ok": flash[0] == "ok", "message": flash[1]})
                app.store.merge_run_meta(rid, {"_flash": list(flash)})   # 다음 GET 에서 한 번 보여 주고 지운다
                return self._redirect(f"/runs/{rid}", operator)
            if action == "decide":
                if run["trigger"] != "release":
                    raise BadRequest("릴리스 QA 실행에만 판단을 기록한다")
                if run["status"] != "finished":
                    raise BadRequest("실행이 끝난 뒤에 판단한다")
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
                return self._page("테스트 조건", f'<h1>테스트 조건</h1><div class="flash err">테스트 조건 목록을 만들지 못했다: {ui.e(app.catalog.last_error or "원인 미상")}</div>', "catalog")
            cov = app.coverage(cat)
            domain = g("domain") or (cat.domains()[0] if cat.domains() else "")
            body = ui.catalog_list(cat, cov, app.store.last_verdicts(), domain=domain, layer=g("layer"), only=g("only"),
                                   changes=app.catalog.changes, wiki_available=app.wiki.available,
                                   operators=app.cfg.operators, operator=self._operator(), hermes=bool(app.cfg.hermes_key),
                                   op=g("op"), op_ids=cat.by_operation().get(g("op")) if g("op") else None)
            body = body.replace("</h1>", "</h1>" + ui.coverage_card(cat, cov, app.catalog.last_error), 1)    # 옛 대시보드의 커버리지 표 (v2 §7.2)
            return self._page("테스트 조건", body, "catalog", flash=("ok", g("msg")) if g("msg") else None)
        if path == "/catalog/tc" and method == "GET":
            cat = app.current_catalog()
            rec = cat.records.get(g("id")) if cat else None
            if not rec:
                return self._error(404, "그 테스트 조건이 테스트 조건 목록에 없다")
            cov = app.coverage(cat)
            covering = [app.cases[i] for i in cov["by_tc"].get(rec["id"], []) if i in app.cases]
            excerpts, seen_sec = [], set()
            for ref in rec.get("prd") or []:
                if not ref.get("section") or (ref["doc"], ref["section"]) in seen_sec:
                    continue          # 같은 절의 요구 여러 개를 인용해도 절 본문은 한 번
                seen_sec.add((ref["doc"], ref["section"]))
                text = app.wiki.prd_section(ref["doc"], ref["section"], max_lines=40) if app.wiki.available else None
                excerpts.append((ref, text))
            src_link = None
            if rec["layer"] == "contract" and app.cfg.spec_docs_url:
                spec = app.spec.get()
                oid = ((rec.get("binding") or {}).get("operations") or [rec.get("operation")])[0] if (rec.get("binding") or rec.get("operation")) else None
                o = spec.ops.get(oid) if (spec and oid) else None
                src_link = app.cfg.spec_docs_url + (("#" + ui.restdocs_anchor(o.summary)) if o and o.summary else "")
            elif rec["layer"] == "policy":
                src_link = next((p["url"] for p in rec.get("prd") or [] if p.get("url")), None)
            ov, _ = app.scenario_view()
            return self._page(rec["id"], ui.catalog_detail(rec, covering, app.store.last_verdicts(), excerpts, app.catalog.changes.get(rec["id"]), source_link=src_link)
                              + ui.tc_variants_card(ui.variants_of_tc(ov, rec["id"])),
                              "catalog", context={"tc": rec["id"]})
        if path == "/catalog/propose-tc" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if self._wants_json():
                return self._json(200, app.propose_tc(doc=str(fv("doc")), section=str(fv("section")), domain=str(fv("domain")), operator=operator, session_hash=self._session_hash(), ip=self._ip()))
            if not str(fv("doc")).strip() or not str(fv("section")).strip():
                raise BadRequest("PRD 문서 이름과 절 번호가 필요하다")
            job = app.job_propose(str(fv("doc")).strip(), str(fv("section")).strip(), str(fv("domain")).strip(), operator, self._session_hash(), self._ip())
            return self._redirect(f"/jobs/{job.id}", set_operator=operator)
        if path == "/api/catalog" and method == "GET":
            cat = app.current_catalog()
            return self._json(200, cat.to_json() if cat else {"error": app.catalog.last_error})

        # ---------- API 문서 다시 읽기 (사람이 누를 때만 — 캐시 무시) ----------
        if path == "/spec/refresh" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip() or self._operator()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            res = app.refresh_spec(operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200 if res["ok"] else 502, res)
            from urllib.parse import quote
            nxt = str(fv("next") or "/apis")
            if not nxt.startswith("/") or nxt.startswith("//"):
                nxt = "/apis"
            if not res["ok"]:
                msg = f"API 문서를 다시 읽지 못했다 — {res['error']}. 이전 문서 그대로 쓴다"
            elif not res["changed"]:
                msg = f"API 문서가 그대로다 ({res['after']}, API {res['ops']}개). 백엔드 dev 배포와 문서 게시가 끝났는지 확인"
            else:
                parts = [f"API 문서를 다시 읽었다 {res['before'] or '–'} → {res['after']}"]
                if res["added"]:
                    parts.append(f"새 API {len(res['added'])}개: {', '.join(res['added'][:6])}{' …' if len(res['added']) > 6 else ''}")
                if res["removed"]:
                    parts.append(f"사라진 API {len(res['removed'])}개: {', '.join(res['removed'][:6])}")
                parts.append(f"테스트 조건 +{res['tc_added']} / -{res['tc_removed']}")
                msg = " · ".join(parts)
            sep = "&" if "?" in nxt else "?"
            return self._redirect(f"{nxt}{sep}msg={quote(msg)}", set_operator=operator)

        # ---------- API 별로 모아 보기 (docs/qa-platform-api.md §5.1·§5.2) ----------
        if path == "/apis" and method == "GET":
            rows, cat = app.api_overview()
            if cat is None and not rows:
                return self._page("API", f'<h1>API</h1><div class="flash err">OpenAPI 를 읽지 못했다: {ui.e(app.spec.last_error or "")}</div>', "apis")
            spec = app.spec.get()
            known = cat.domains() if cat else []
            domains = [d for d in known if any(r["domain"] == d for r in rows)] + sorted({r["domain"] for r in rows} - set(known))
            return self._page("API", ui.apis_list(rows, domains=domains, domain=g("domain") or (domains[0] if domains else ""), only=g("only"), q=g("q"),
                                                 spec_hash=spec.hash if spec else None, spec_source=spec.source if spec else None, docs_url=app.cfg.spec_docs_url,
                                                 operator=self._operator(), fetched_ago=app.spec.age_seconds()), "apis", flash=("ok", g("msg")) if g("msg") else None)
        m = re.match(r"^/(api/)?apis/([A-Za-z0-9_.\-]+)$", path)
        if m and method == "GET":
            d = app.api_detail(m.group(2))
            if not d:
                return self._json(404, {"error": "OpenAPI 에 없는 operationId"}) if m.group(1) else self._error(404, "OpenAPI 에 없는 operationId")
            if m.group(1):
                return self._json(200, d)
            return self._page(f"{d['op']['method']} {d['op']['path']}", ui.api_detail(d, operators=app.cfg.operators, operator=self._operator(), hermes=bool(app.cfg.hermes_key)),
                              "apis", context={"op": d["op"]["id"]})

        # ---------- 준비 작업 (docs/qa-platform-api.md §5.4) ----------
        # ---------- Sanity (docs/qa-platform-v2.md §4) ----------
        m = re.match(r"^/sanity(?:/(\d+))?$", path)
        if m and method == "GET":
            prs = app.sanity_prs(20)
            num = int(m.group(1)) if m.group(1) else next((p["number"] for p in prs if p["api"]), None)
            sel = next((p for p in prs if p["number"] == num), None)
            if num and sel is None:
                try:
                    sel = {**app.sanity_pr(num), "sanity": app.store.latest_sanity().get(num)}
                except BadRequest as ex:
                    return self._page("Sanity 테스트", f'<h1>Sanity 테스트</h1><div class="flash err">{ui.e(str(ex))}</div>', "sanity")
            history = app.store.list_sanity(num) if num else []
            s = history[0] if history else None
            run = app.store.get_run(s["run_id"]) if s and s.get("run_id") else None
            body = ui_sanity.sanity_page(prs, sel, s, operator=self._operator(), target=app.target_for(self._operator())["base_url"], hermes=bool(app.cfg.hermes_key),
                                         cases=app.sanity_cases(s["scope"]) if s and s.get("scope") else [], run=run, history=history,
                                         gh_error=app.github.last_error, flt=g("f") or "all")
            notice = ("ok", g("done")) if g("done") else (("err", g("err")) if g("err") else None)
            return self._page("Sanity 테스트", body, "sanity", flash=notice, context={"run": run["id"]} if run else None)
        if path == "/sanity/start" and method == "POST":
            f = self._form()
            operator = str((f.get("operator") or [""])[0]).strip()
            num = int(str((f.get("pr") or ["0"])[0]) or 0)
            try:
                app.sanity_start(num, operator=operator, session_hash=self._session_hash(), ip=self._ip())
            except BadRequest as ex:
                return self._redirect(f"/sanity/{num}?err={_urlq(str(ex))}", set_operator=operator)
            return self._redirect(f"/sanity/{num}", set_operator=operator)
        m = re.match(r"^/sanity/(s-[0-9a-f]+)/(continue|recheck|resolve|slack|cancel|propose|apply|discard)$", path)
        if m and method == "POST":
            sid, act = m.group(1), m.group(2)
            s = app.store.get_sanity(sid)
            if not s:
                return self._error(404, "그 Sanity 기록이 없다")
            f = self._form()
            fv = lambda k, d="": str((f.get(k) or [d])[0])  # noqa: E731
            operator = fv("operator").strip()
            kw = {"operator": operator, "session_hash": self._session_hash(), "ip": self._ip()}
            msg = None
            try:
                if not operator or operator not in app.cfg.operators:
                    raise BadRequest("담당자를 목록에서 골라야 한다")
                if act == "continue":
                    app.sanity_continue(sid, reason=fv("reason"), **kw)
                elif act == "recheck":
                    app.sanity_recheck(sid, **kw)
                elif act == "resolve":
                    app.sanity_resolve(sid, fv("fid"), choice=fv("choice"), note=fv("note"), **kw)
                elif act == "propose":
                    app.sanity_propose(sid, fv("fid"), **kw)
                    msg = "Hermes 가 수정안을 만들고 있어요. 다 되면 이 화면에 바뀐 줄이 보여요"
                elif act == "discard":
                    app.sanity_discard(sid, fv("fid"), **kw)
                elif act == "apply":
                    res = app.sanity_apply(sid, [str(x) for x in f.get("fid") or []], **kw)
                    parts = []
                    if res["count"]:
                        parts.append(f"수정안 {res['count']}개를 위키에 반영했어요 ({', '.join(res['files'])})")
                    if res["remade"]:
                        parts.append(f"{res['remade']}개는 같은 줄을 고쳐서 Hermes 가 지금 위키 기준으로 다시 만들고 있어요. 다 되면 확인하고 반영해 주세요")
                    msg = ". ".join(parts) or "반영할 내용이 없었어요"
                    if res["count"]:
                        msg += ". 고칠 것을 다 반영했으면 [위키 고친 뒤 다시 점검]을 눌러 주세요"
                elif act == "slack":
                    msg = f"질문 {app.sanity_slack(sid, **kw)}건을 Slack 으로 보냈어요"
                elif act == "cancel":
                    if s.get("job_id") and app.jobs.cancel(s["job_id"]):
                        app.store.add_event(action="sanity.cancel", target=sid, detail={"pr": s["pr_number"]}, **kw)
                        msg = "그만두라고 했어요. 지금 하던 호출이 끝나면 멈춰요"
            except BadRequest as ex:
                return self._redirect(f"/sanity/{s['pr_number']}?err={_urlq(str(ex))}", set_operator=operator)
            return self._redirect(f"/sanity/{s['pr_number']}" + (f"?done={_urlq(msg)}" if msg else ""), set_operator=operator)
        # ---------- 알림함 (docs/qa-platform-v2.md §15.5) ----------
        if path in ("/inbox", "/inbox/items") and method == "GET":
            filters = {k: g(k) for k in ("actor", "channel", "type", "window") if g(k)}
            if path == "/inbox/items":
                try:
                    after = int(g("after") or 0)
                except ValueError:
                    after = 0
                return self._send(200, ui_inbox.cards(app.inbox_items(filters, after), new=True))
            actors = app.notify_actors()
            receivers = {r["actor"]: r for r in app.store.list_receivers(app.cfg.target_base_url)}
            for a in actors:
                if a not in receivers or not receivers[a].get("email"):
                    app._actor_email(a)
            receivers = {r["actor"]: r for r in app.store.list_receivers(app.cfg.target_base_url)}
            items = app.inbox_items(filters)
            counts = {"all": len(app.store.list_inbox(limit=10000))}
            body = ui_inbox.inbox_page(items=items, actors=actors, receivers=receivers, filters=filters, operator=self._operator(),
                                       push_why=app.push.unavailable(), mail_why=app.mail.unavailable(),
                                       mail_state={"error": app.mail.error, "last_ok": app.mail.last_ok, "user": app.cfg.mail_user},
                                       mail_mine=app.mail.mine, counts=counts, target=app.target_for(self._operator()),
                                       settings={a: app.push.setting(a) for a in actors})
            return self._page("알림함", body, "inbox")
        m = re.match(r"^/inbox/(receivers/on|receivers/off|refresh)$", path)
        if m and method == "POST":
            f = self._form()
            fv = lambda k, d="": str((f.get(k) or [d])[0])  # noqa: E731
            operator = fv("operator").strip() or self._operator()
            kw = {"operator": operator, "session_hash": self._session_hash(), "ip": self._ip()}
            actor = fv("actor").strip()
            try:
                if m.group(1) == "receivers/on":
                    app.receiver_on(actor, **kw)
                    msg = f"{actor} 의 웹 푸시를 받기 시작했어요. 이제 이 계정에 온 웹 푸시가 여기에 보여요"
                elif m.group(1) == "receivers/off":
                    app.receiver_off(actor, **kw)
                    msg = f"{actor} 의 웹 푸시 받기를 껐어요. 백엔드의 기기 등록도 지웠어요"
                else:
                    n = app.inbox_refresh(**kw)
                    msg = f"메일함을 읽었어요. 새 알림 메일 {n}건"
            except BadRequest as ex:
                return self._redirect(f"/inbox?err={_urlq(str(ex))}", set_operator=operator)
            back = f"/inbox?actor={_urlq(actor)}&" if actor else "/inbox?"
            return self._redirect(f"{back}done={_urlq(msg)}", set_operator=operator)
        # ---------- 대상 서버 (docs/qa-platform-v2.md §13) ----------
        if path == "/targets" and method == "GET":
            notice = ("ok", g("done")) if g("done") else (("err", g("err")) if g("err") else None)
            return self._page("대상 서버", ui.targets_page(app.targets(), current=app.target_for(self._operator()), operator=self._operator(),
                                                         allow_local=app.cfg.allow_local_targets, actor_names=sorted(app.cfg.actors) or ["qa-host", "qa-guest"]),
                              "targets", flash=notice)
        m = re.match(r"^/targets/(select|add|delete)$", path)
        if m and method == "POST":
            f = self._form()
            fv = lambda k, d="": str((f.get(k) or [d])[0])  # noqa: E731
            operator = fv("operator").strip() or self._operator()
            kw = {"operator": operator, "session_hash": self._session_hash(), "ip": self._ip()}
            back = fv("next") if fv("next").startswith("/") else "/targets"
            try:
                if m.group(1) == "select":
                    t = app.select_target(fv("id"), **kw)
                    msg = f"대상을 {t['name']} 로 바꿨어요. 실행·API 호출·QA 데이터가 모두 {t['base_url']} 로 가요"
                elif m.group(1) == "add":
                    t = app.add_target(name=fv("name"), base_url=fv("url"), actors={k[6:]: str(v[0]) for k, v in f.items() if k.startswith("actor.")}, **kw)
                    pr = t["probe"]
                    msg = (f"{t['name']} 를 등록했어요. 헬스 {pr['health']['status'] or '응답 없음'} · dev-sessions {pr['dev_sessions']['status'] or '응답 없음'}"
                           + ("" if pr["health"]["ok"] and pr["dev_sessions"]["ok"] else " — 서버가 떠 있는지, dev 프로파일인지 확인해 주세요"))
                else:
                    app.remove_target(fv("id"), **kw)
                    msg = "대상을 지웠어요"
            except BadRequest as ex:
                return self._redirect(f"/targets?err={_urlq(str(ex))}", set_operator=operator)
            sep = "&" if "?" in back else "?"
            return self._redirect(f"{back}{sep}done={_urlq(msg)}", set_operator=operator)
        if path == "/smoke" and method == "GET":         # docs/qa-platform-v2.md §6
            sprint = app.cfg.current_sprint()
            last_smoke = app.store.list_runs(1, trigger="sprint-smoke")
            return self._page("스모크 테스트", ui.smoke_page(app.smoke_groups(), operator=self._operator(), sprint=sprint,
                                                         last_smoke=last_smoke[0] if last_smoke else None, target=app.target_for(self._operator())["base_url"],
                                                         mode=g("mode") or "all"), "smoke")
        if path == "/setup" and method == "GET":        # 옛 주소 — QA 데이터 화면으로 (docs/qa-platform-v2.md §5)
            qs = urlsplit(self.path).query
            return self._redirect("/data" + (("?" + qs) if qs else ""))
        if path == "/data" and method == "GET":
            run = app.store.get_run(g("run")) if g("run") else None
            result = None
            if run and run["trigger"] == "setup":
                rcs = app.store.list_run_cases(run["id"])
                result = {"run": run, "case": rcs[0] if rcs else None, "steps": app.store.list_steps(rcs[0]["id"]) if rcs else [],
                          "outputs": app.setup_outputs(run)}
            notice = ("ok", g("done")) if g("done") else (("err", g("err")) if g("err") else None)
            qa_members = app.store.list_qa_members()
            created = None
            if g("member") and self._operator():          # 방금 만든 QA 회원 — 정보와 토큰을 패널로
                m = next((x for x in qa_members if x["member_id"] == g("member")), None)
                if m:
                    created = dict(m, **app.qa_member_token(m["member_id"], operator=self._operator(), session_hash=self._session_hash(), ip=self._ip()))
            return self._page("QA 데이터", ui.data_page(app.setup_cases(), actors=sorted(app.all_actors()), operators=app.cfg.operators, created=created,
                                                       qa_members=qa_members, operator=self._operator(), result=result,
                                                       errors=[x for x in app.case_errors if "setup" in x], cleanup=app.qa_snapshot(self._operator(), fresh=True)),
                              "data", flash=notice, context={"run": run["id"]} if run else None)
        if path == "/setup/member" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            res = app.create_qa_member(str(fv("label")), operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200 if res["ok"] else 409, res)
            from urllib.parse import quote
            if res["ok"]:
                m = res["member"]      # 토큰은 주소에 싣지 않는다 — /data 가 member 로 패널을 열고 캐시에서 꺼내 보여 준다
                return self._redirect(f"/data?member={quote(str(m.get('memberId') or ''))}&done={quote(f'QA 회원을 만들었어요. 테스트 계정 이름 {fv('label').strip()} (닉네임 {m.get('nickname')}). 스크립트 actor: 와 API 호출 화면에서 고를 수 있어요')}", set_operator=operator)
            e = res["error"] or {}
            return self._redirect(f"/data?err={quote(f'{e.get('code')}: {e.get('message')}')}", set_operator=operator)
        if path == "/setup/member-token" and method == "POST":     # 정리 표의 [토큰 보기] — 값은 응답 본문으로만 (주소·기록에 안 남긴다)
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            res = app.qa_member_token(str(fv("member")).strip(), operator=operator, session_hash=self._session_hash(), ip=self._ip())
            return self._json(200 if res["ok"] else 409, res)
        if path == "/setup/cleanup" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            res = app.qa_data_action(str(fv("action")), str(fv("target")).strip(), operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200 if res["ok"] else 409, res)
            from urllib.parse import quote
            if res["ok"]:
                d = res["deleted"]
                msg = f"지웠어요. 룸 {d.get('rooms', 0)} · 신청 {d.get('applications', 0)} · 참여 {d.get('participants', 0)} · 회원 {d.get('members', 0)} (모두 {d.get('total', 0)}행)"
                return self._redirect(f"/data?done={quote(msg)}", set_operator=operator)
            e = res["error"] or {}
            return self._redirect(f"/data?err={quote(f'{e.get('code')}: {e.get('message')}')}", set_operator=operator)
        if path == "/setup/run" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            values = {k[6:]: str(v[0]) for k, v in f.items() if k.startswith("input.")}
            rid = app.setup_run(str(fv("case_id")), values, operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200, {"run": app.store.get_run(rid), "outputs": app.setup_outputs(app.store.get_run(rid))})
            return self._redirect(f"/data?run={rid}", set_operator=operator)

        # ---------- 탐색기 (docs/qa-platform-tc.md §8) ----------
        if path == "/explorer" and method == "GET":
            spec = app.spec.get()
            if not spec:
                return self._page("API 호출", f'<h1>API 호출</h1><div class="flash err">OpenAPI 를 읽지 못했다: {ui.e(app.spec.last_error or "")}</div>', "explorer")
            op = spec.ops.get(g("op")) if g("op") else None
            run = app.store.get_run(g("run")) if g("run") else None
            steps = []
            if run:
                rcs = app.store.list_run_cases(run["id"])
                steps = app.store.list_steps(rcs[0]["id"]) if rcs else []
            # 프리필 (docs/qa-platform-api.md §5.3): p.<path 파라미터> · q.<query> · actor · body · view — 채우기만 하고 보내지 않는다
            prefill = {"p": {k[2:]: v[0] for k, v in q.items() if k.startswith("p.")}, "q": {k[2:]: v[0] for k, v in q.items() if k.startswith("q.")},
                       "actor": g("actor"), "body": g("body"), "view": g("view")}
            return self._page("API 호출", ui.explorer(spec, op, run, steps, actors=sorted(app.all_actors()), operators=app.cfg.operators,
                                                 operator=self._operator(), q=g("q"), domain_of=domain_of_path,
                                                 qa=app.op_qa(op.id) if op else None, prefill=prefill, spec_hash=spec.hash, fetched_ago=app.spec.age_seconds()), "explorer",
                              flash=("ok", g("msg")) if g("msg") else None)
        if path == "/explorer/send" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            op_id = str(fv("op"))
            path_params = {k[2:]: str(v[0]) for k, v in f.items() if k.startswith("p_")}
            query = {k[2:]: str(v[0]) for k, v in f.items() if k.startswith("q_")}
            rid = app.explorer_send(op_id=op_id, path_params=path_params, query=query, body_text=str(fv("body")), actor=str(fv("actor")) or None,
                                    operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                run = app.store.get_run(rid)
                rcs = app.store.list_run_cases(rid)
                return self._json(200, {"run": run, "steps": app.store.list_steps(rcs[0]["id"]) if rcs else []})
            return self._redirect(f"/explorer?op={op_id}&run={rid}", set_operator=operator)
        if path == "/explorer/draft" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            did = app.explorer_to_draft(str(fv("run")), operator, self._session_hash(), self._ip())
            return self._json(200, {"id": did}) if self._wants_json() else self._redirect(f"/drafts/{did}/edit", set_operator=operator)

        # ---------- 변경 기록 (예전 스크립트 초안. 저장은 바로 한다 — docs/qa-platform-scenarios.md §9) ----------
        if path == "/drafts" and method == "GET":
            st = g("status")
            return self._page("변경 기록", ui.drafts_list(app.store.list_drafts(st or None), app.store.draft_counts(), st, active_jobs=app.jobs.active()), "drafts")
        if path == "/drafts/generate" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            tc_ids = [str(x) for x in f.get("tc_ids") or []]
            if self._wants_json():
                return self._json(200, app.generate_cases(tc_ids=tc_ids, operator=operator, session_hash=self._session_hash(), ip=self._ip()))
            if not tc_ids:
                raise BadRequest("테스트 조건을 하나 이상 골라야 한다")
            job = app.job_generate(tc_ids, operator, self._session_hash(), self._ip())
            return self._redirect(f"/jobs/{job.id}", set_operator=operator)
        m = re.match(r"^/drafts/(d-[0-9a-f]+)$", path)
        if m and method == "GET":
            d = app.store.get_draft(m.group(1))
            if not d:
                return self._error(404, "그 변경 기록이 없다")
            cat = app.current_catalog()
            recs = {t: (cat.records.get(t) if cat else None) for t in d["tc_ids"]}
            run = app.store.get_run(d["run_id"]) if d.get("run_id") else None
            orig = (app.cases.get(d["case_id"]) if d["status"] not in ("approved", "rejected") and d.get("source") in ("hermes-revise", "form-edit")
                    and d.get("case_id") and (d.get("kind") or "case") == "case" else None)
            return self._page(f"변경 {d['id']}", ui.draft_detail(d, recs, run, operators=app.cfg.operators, operator=self._operator(),
                                                                     original_yaml=(orig.to_yaml() if orig else None), repo_write=app.repo.enabled), "drafts")
        m = re.match(r"^/drafts/(d-[0-9a-f]+)/(save|check|approve|reject)$", path)
        if m and method == "POST":      # 예전 방식으로 남은 초안(저장 안 됨)만 — 고치고, 한 번 돌려 보고, 저장하거나 버린다
            did, action = m.group(1), m.group(2)
            d = app.store.get_draft(did)
            if not d:
                return self._error(404, "그 변경 기록이 없다")
            f = self._form()
            fv = lambda k, d_="": (f.get(k) or [d_])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            sh, ip = self._session_hash(), self._ip()
            if d["status"] in ("approved", "rejected"):
                raise BadRequest("이미 저장했거나 버린 것이다 — 고치려면 스크립트 화면에서 폼으로 연다")
            is_tc = (d.get("kind") or "case") == "tc"
            is_delete = (d.get("kind") or "").endswith("-delete")
            if is_delete and action in ("save", "check"):
                raise BadRequest("삭제는 고치거나 실행하지 않는다 — 저장하거나 버린다")
            if action == "approve":
                out = app.approve_draft(d, operator=operator, note=str(fv("note")).strip() or None, session_hash=sh, ip=ip)
                return self._json(200, out) if self._wants_json() else self._redirect(app.change_link(out)["href"], operator)
            if action == "save":
                text = str(fv("yaml"))
                if is_tc:
                    items, errors = draftsmod.validate_manual_tc(text)
                    validation = {"status": "error" if errors else "ok", "errors": errors, "warnings": []}
                    app.store.update_draft(did, yaml=text, validation=validation, tc_ids=[str(i.get("id")) for i in items], status="draft")
                else:
                    case, errors, warnings = app.revalidate_draft(d, text)
                    validation = {"status": ("error" if errors else (case.audit["status"] if case else "error")), "errors": errors, "warnings": warnings}
                    app.store.update_draft(did, yaml=text, validation=validation, case_id=(case.id if case else d.get("case_id")),
                                           tc_ids=(case.covers if case else d["tc_ids"]), status="draft", run_id=None)
                app.store.add_event(operator=operator, action="draft.save", target=did, session_hash=sh, ip=ip, detail={"errors": len(validation["errors"])})
            elif action == "check":
                if is_tc:
                    raise BadRequest("수동 작성 테스트 조건은 실행할 것이 없다")
                case, errors, _ = app.revalidate_draft(d, d["yaml"])
                if not case:
                    raise BadRequest("검증 오류가 있어 실행하지 않는다: " + "; ".join(errors[:3]))
                rid = app.create_run(trigger="draft-check", operator=operator, case_ids=[], sha=None, ref=None, pr_number=None,
                                     deploy_run_id=None, reason=f"변경 {did} 저장 전 실행", basis="저장 전 실행 1건", extra={"draft_id": did},
                                     session_hash=sh, ip=ip, cases_override=[case])
                app.store.update_draft(did, status="checked", run_id=rid)
                app.store.add_event(operator=operator, action="draft.check", target=did, session_hash=sh, ip=ip, detail={"run_id": rid})
            elif action == "reject":
                app.store.update_draft(did, status="rejected", decided_by=operator, decided_at=now_iso(), note=str(fv("note")).strip() or d.get("note"))
                app.store.add_event(operator=operator, action="draft.reject", target=did, session_hash=sh, ip=ip, detail={"note": str(fv("note")).strip()[:200]})
            return self._json(200, {"ok": True}) if self._wants_json() else self._redirect(f"/drafts/{did}", operator)

        # ---------- Hermes 작업 (docs/qa-platform-progress.md) ----------
        if path == "/static/jobs.js" and method == "GET":
            return self._send(200, ui.JOBS_JS, "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/jobs" and method == "GET":
            return self._page("Hermes 작업", ui.jobs_list(app.store.list_jobs(100)), "drafts")
        m = re.match(r"^/(api/)?jobs/(j-[0-9a-f]+)$", path)
        if m and method == "GET":
            snap = app.jobs.snapshot(m.group(2), with_text=True)
            if not snap:
                return self._error(404, "그 Hermes 작업이 없다")
            if m.group(1):
                return self._json(200, snap)
            return self._page(f"Hermes 작업 {snap['id']}", ui.job_detail(snap, operator=self._operator()), "drafts")
        m = re.match(r"^/api/jobs/(j-[0-9a-f]+)/events$", path)
        if m and method == "GET":
            return self._job_events(m.group(1))
        m = re.match(r"^/jobs/(j-[0-9a-f]+)/cancel$", path)
        if m and method == "POST":
            f = self._form()
            operator = str((f.get("operator") or [""])[0]).strip() or self._operator()
            if operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            ok = app.jobs.cancel(m.group(1))
            app.store.add_event(operator=operator, action="hermes_job.cancel", target=m.group(1), session_hash=self._session_hash(), ip=self._ip(), detail={"ok": ok})
            return self._json(200, {"ok": ok}) if self._wants_json() else self._redirect(f"/jobs/{m.group(1)}", operator)

        # ---------- 폼으로 스크립트·수동 TC 편집 (docs/qa-platform-editor.md) ----------
        if path == "/static/editor.js" and method == "GET":
            return self._send(200, ui.EDITOR_JS, "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/api/editor/context" and method == "GET":
            return self._json(200, app.editor_context())
        m = re.match(r"^/api/editor/op/([A-Za-z0-9_.\-:{}/]+)$", path)
        if m and method == "GET":
            o = app.editor_op(m.group(1))
            return self._json(200, o) if o else self._json(404, {"error": "그 API 가 OpenAPI 에 없다"})
        if path == "/api/editor/preview" and method == "POST":
            f = self._form()
            st = (f.get("state") or [{}])[0]
            res = app.form_case(st if isinstance(st, dict) else json.loads(st or "{}"), mode=str((f.get("mode") or ["new"])[0]),
                                original_id=(f.get("original_id") or [None])[0], draft_id=(f.get("draft_id") or [None])[0], operator=self._operator(), dry=True)
            return self._json(200, res)
        new_case = path == "/cases/new" and method == "GET"
        m_edit = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)/edit$", path)
        m_dedit = re.match(r"^/drafts/(d-[0-9a-f]+)/edit$", path)
        if method == "GET" and (new_case or m_edit or m_dedit):
            mode, original_id, draft_id, errors = "new", None, None, []
            if new_case:
                tcs = [t for t in q.get("tc", []) + q.get("tc_ids", []) if t]
                vinfo = scenariosmod.variant_index(app.features).get(g("variant")) if g("variant") else None     # 변형 화면의 [스크립트 만들기 (폼)]
                st = editormod.to_state({"suite": g("suite") or "sanity", "covers": tcs,
                                          "steps": [{"name": "", "request": {"method": "GET", "path": ""}}]})
                cat = app.current_catalog()
                if cat and tcs:
                    recs = [cat.records[t] for t in tcs if t in cat.records]
                    st["domains"] = sorted({r["domain"] for r in recs})
                    st["source"] = sorted({f"PRD/{p['doc']} §{p['section']}" for r in recs for p in (r.get("prd") or [])})
                if vinfo:
                    ft, sc, va = vinfo
                    st.update({"variant": g("variant"), "title": va.title, "actor": sc.actor or "",
                               "source": ([f"PRD/{ft.feature} {va.at}"] if va.at else []) + [x for x in st.get("source") or [] if x != f"PRD/{ft.feature} {va.at}"]})
            else:
                if m_edit:
                    c = app.cases.get(m_edit.group(1))
                    if not c:
                        return self._error(404, "스크립트가 없다")
                    raw, mode, original_id = c.raw, "edit", c.id
                else:
                    d = app.store.get_draft(m_dedit.group(1))
                    if not d or (d.get("kind") or "case") != "case":
                        return self._error(404, "폼으로 열 스크립트 변경이 없다")
                    if d["status"] in ("approved", "rejected"):
                        raise BadRequest("이미 저장했거나 버린 것이다 — 스크립트 화면에서 폼으로 연다")
                    try:
                        raw = yaml.safe_load(d["yaml"])
                    except yaml.YAMLError as ex:
                        raise BadRequest(f"초안 YAML 을 읽지 못했다 — YAML 칸에서 고친다: {ex}")
                    if not isinstance(raw, dict):
                        raise BadRequest("초안 YAML 이 스크립트 맵이 아니다 — YAML 칸에서 고친다")
                    mode, draft_id = "draft", d["id"]
                bad = editormod.unsupported(raw)
                if bad:
                    raise BadRequest("폼으로 표현할 수 없는 키가 있다 — YAML 로 고친다: " + ", ".join(bad[:5]))
                st = editormod.to_state(raw)
            return self._page("스크립트 폼", ui.editor_page(st, mode=mode, original_id=original_id, draft_id=draft_id, errors=errors,
                                                        operator=self._operator(), operators=app.cfg.operators), "cases")
        if path == "/editor/save" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip() or self._operator()
            st = fv("state", "{}")
            try:
                st = st if isinstance(st, dict) else json.loads(st or "{}")
            except ValueError:
                raise BadRequest("폼 상태를 읽지 못했다")
            mode = str(fv("mode", "new"))
            res = app.form_case(st, mode=mode, original_id=fv("original_id") or None, draft_id=fv("draft_id") or None, operator=operator,
                                session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200 if res["ok"] else 400, res)
            if not res["ok"]:
                return self._page("스크립트 폼", ui.editor_page(st, mode=mode, original_id=fv("original_id") or None, draft_id=fv("draft_id") or None,
                                                            errors=res["errors"], warnings=res["warnings"], operator=operator, operators=app.cfg.operators), "cases", status=400)
            return self._redirect(app.change_link(res)["href"], set_operator=operator)
        if path == "/editor/try" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            st = fv("state", "{}")
            try:
                st = st if isinstance(st, dict) else json.loads(st or "{}")
            except ValueError:
                raise BadRequest("폼 상태를 읽지 못했다")
            rid = app.try_case(st, mode=str(fv("mode", "new")), original_id=fv("original_id") or None, draft_id=fv("draft_id") or None,
                               operator=str(fv("operator")).strip() or self._operator(), session_hash=self._session_hash(), ip=self._ip())
            return self._json(200, {"run_id": rid, "url": f"/runs/{rid}"}) if self._wants_json() else self._redirect(f"/runs/{rid}")
        m = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)/delete(?:-request)?$", path)
        if m and method == "POST":
            f = self._form()
            operator = str((f.get("operator") or [""])[0]).strip() or self._operator()
            out = app.delete_item(what="case", target=m.group(1), reason=str((f.get("reason") or [""])[0]), operator=operator,
                                  session_hash=self._session_hash(), ip=self._ip())
            return self._json(200, out) if self._wants_json() else self._redirect("/cases" if out["commit"] else f"/drafts/{out['id']}", set_operator=operator)
        if path in ("/catalog/manual/new", "/catalog/tc/edit") and method == "GET":
            cat = app.current_catalog()
            rec = None
            if path == "/catalog/tc/edit":
                rec = cat.records.get(g("id")) if cat else None
                rec = app.manual_item(rec["id"]) if rec and rec["layer"] == "manual" else None
                if not rec:
                    raise BadRequest("수동 작성 테스트 조건만 폼으로 고친다 — 비즈니스 규칙·API 계약 테스트 조건은 원본(SSOT·OpenAPI)을 고친다")
            docs = sorted({r["doc"] for r in (cat.records.values() if cat else []) if r.get("doc")} | {p["doc"] for r in (cat.records.values() if cat else []) for p in (r.get("prd") or [])})
            return self._page("수동 작성 테스트 조건 폼", ui.manual_tc_form(rec, docs=docs, domains=(cat.domains() if cat else []), ops=app.editor_context()["ops"],
                                                             prefill={k: g(k) for k in ("doc", "section", "domain")}, operator=self._operator()), "catalog")
        if path == "/catalog/manual/save" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip() or self._operator()
            form = {k: fv(k) for k in ("tc_kind", "ops_id", "doc", "section", "domain", "title", "given", "when", "then", "operations", "source")}
            out = app.form_tc(form, tc_id=fv("id") or None, operator=operator, session_hash=self._session_hash(), ip=self._ip())
            return self._json(200, out) if self._wants_json() else self._redirect(app.change_link(out)["href"], set_operator=operator)
        if path in ("/catalog/tc/delete", "/catalog/tc/delete-request") and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip() or self._operator()
            out = app.delete_item(what="tc", target=str(fv("id")), reason=str(fv("reason")), operator=operator, session_hash=self._session_hash(), ip=self._ip())
            return self._json(200, out) if self._wants_json() else self._redirect("/catalog" if out["commit"] else f"/drafts/{out['id']}", set_operator=operator)
        m = re.match(r"^/drafts/(d-[0-9a-f]+)/file$", path)
        if m and method == "GET":
            d = app.store.get_draft(m.group(1))
            if not d:
                return self._error(404, "그 변경 기록이 없다")
            rel, text = app.draft_file(d, self._operator() or d["operator"])
            return self._send(200, text, "application/x-yaml; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{rel.rsplit("/", 1)[-1]}"'})

        # ---------- 스크립트 ----------
        if path == "/cases" and method == "GET":
            app.current_catalog()
            cs = sorted(app.cases.values(), key=lambda c: c.id)
            drift = {c.id: app.drift_of(c) for c in cs}
            recent = app.store.recent_case_results(20)
            stats = {cid: ui.stats_of(rows) for cid, rows in recent.items()}
            chk = scenariosmod.check(app.features, wiki=None, catalog=None, cases=app.cases)      # 없는 변형을 가리키는 스크립트만 본다
            vtitles = {vid: va.title for vid, (_, _, va) in scenariosmod.variant_index(app.features).items()}
            return self._page("스크립트", ui.cases_list(cs, app.store.last_verdicts(), app.case_errors, drift=drift, stats=stats,
                                                     variants=vtitles, variant_errors=chk["scripts"]), "cases")
        if path == "/cases/reload" and method == "POST":
            sync_err = app.resync_repo()
            n, errs = app.reload_cases()
            if sync_err:
                errs = errs + [f"main 받기 실패: {sync_err}"]
            app.store.add_event(operator=self._operator() or "(미선택)", action="cases.reload", target=None, detail={"cases": n, "errors": len(errs)})
            return self._redirect("/cases")
        m = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)$", path)
        if m and method == "GET":
            c = app.cases.get(m.group(1))
            if not c:
                return self._error(404, "스크립트가 없다")
            cat = app.current_catalog()
            recs = {t: (cat.records.get(t) if cat else None) for t in c.covers}
            return self._page(c.id, ui.case_detail(c, app.store.case_history(c.id), tc_records=recs, drift=app.drift_of(c),
                                                 revise={"operator": self._operator(), "operators": app.cfg.operators, "hermes": bool(app.cfg.hermes_key)},
                                                 stats=ui.stats_of(app.store.recent_case_results(20).get(c.id) or []),
                                                 changes=app.store.list_changes(case_id=c.id)), "cases", context={"case": c.id})
        m = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)/revise$", path)
        if m and method == "POST":
            f = self._form()
            operator = str((f.get("operator") or [""])[0]).strip()
            if self._wants_json():
                return self._json(200, app.revise_case(m.group(1), operator=operator, session_hash=self._session_hash(), ip=self._ip()))
            c = app.cases.get(m.group(1))
            if not c:
                raise BadRequest("없는 스크립트")
            if not app.drift_of(c):
                raise BadRequest("바뀐 테스트 조건이 없다 — 고칠 것이 없다")
            job = app.job_revise(m.group(1), operator, self._session_hash(), self._ip())
            return self._redirect(f"/jobs/{job.id}", set_operator=operator)

        # ---------- Hermes 대화 (docs/qa-platform-hermes.md §3.2) — 위젯 스크립트 + JSON/SSE API + 기록 화면 ----------
        if path == "/static/hermes.js" and method == "GET":
            return self._send(200, ui.HERMES_JS, "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/chat" and method == "GET":
            chats = app.store.list_chats(100)
            return self._page("Hermes", ui.chats_list(chats, stale={c["id"]: app.chat_stale(c) for c in chats}, hermes=bool(app.cfg.hermes_key),
                                                     operator=self._operator(), operators=app.cfg.operators), "chat")
        if path == "/chat/new" and method == "GET":
            # 상세 화면의 [Hermes 와 이야기] — 위젯을 그 객체를 첨부한 새 대화로 연다
            ctx = {k: g(k) for k in ("run", "case", "tc", "op") if g(k)}
            chats = app.store.list_chats(100)
            return self._page("Hermes", ui.chats_list(chats, stale={c["id"]: app.chat_stale(c) for c in chats}, hermes=bool(app.cfg.hermes_key),
                                                     operator=self._operator(), operators=app.cfg.operators), "chat", autostart=ctx or {"new": True})
        m = re.match(r"^/chat/(c-[0-9a-f]+)$", path)
        if m and method == "GET":
            chat = app.store.get_chat(m.group(1))
            if not chat:
                return self._error(404, "대화가 없다")
            head = (f'<h1>{ui.e(chat.get("title") or "대화")} <span class="small mut mono">{ui.e(chat["id"])}</span> <a class="btn" href="/chat">목록</a></h1>'
                    f'<p class="small mut">담당자 {ui.e(chat["operator"])} · {ui.kst(chat["created_at"])} · 저장 {chat["drafts"]}건(<a href="/drafts">변경 기록</a>)</p>')
            return self._page(f"대화 {chat['id']}", head, "chat", inline_chat=chat["id"])
        if path == "/api/chats" and method == "GET":
            chats = app.store.list_chats(50)
            return self._json(200, {"chats": [dict(c, stale=app.chat_stale(c)) for c in chats]})
        if path == "/api/chats" and method == "POST":
            f = self._form()
            ctx = {k: str((f.get(k) or [""])[0]) for k in ("run", "case", "tc") if (f.get(k) or [""])[0]}
            cid = app.chat_create(operator=self._operator(), context=ctx, session_hash=self._session_hash(), ip=self._ip())
            return self._json(200, {"id": cid, "chat": app.store.get_chat(cid)})
        m = re.match(r"^/api/chats/(c-[0-9a-f]+)(?:/(send|close))?$", path)
        if m:
            chat = app.store.get_chat(m.group(1))
            if not chat:
                return self._json(404, {"error": "대화가 없다"})
            action = m.group(2)
            if not action and method == "GET":
                msgs = app.store.list_chat_messages(chat["id"])
                drafts = {}
                for mm in msgs:
                    for d in mm["draft_ids"]:
                        dd = app.store.get_draft(d)
                        drafts[d] = ui.DRAFT_KO.get(dd["status"], dd["status"]) if dd else None
                return self._json(200, {"chat": chat, "messages": msgs, "drafts": drafts, "stale": app.chat_stale(chat), "max_turns": app.cfg.chat_max_turns})
            operator = self._operator()
            sh, ip = self._session_hash(), self._ip()
            if action == "close" and method == "POST":
                if not operator or operator not in app.cfg.operators:
                    raise BadRequest("담당자를 목록에서 골라야 한다")
                app.store.update_chat(chat["id"], status="closed")
                app.store.add_event(operator=operator, action="chat.close", target=chat["id"], session_hash=sh, ip=ip, detail={"turns": chat["turns"]})
                return self._json(200, {"ok": True})
            if action == "send" and method == "POST":
                f = self._form()
                text = str((f.get("text") or [""])[0])
                app.chat_check(chat, text, operator=operator)          # 한도·담당자 검사는 스트림을 열기 전에 (400 으로)
                if "text/event-stream" not in self.headers.get("Accept", ""):
                    return self._json(200, app.chat_send(chat, text, operator=operator, session_hash=sh, ip=ip))
                self._sse_start()
                alive = {"ok": True}
                def emit(kind, data):
                    if alive["ok"] and not self._sse(kind, data):
                        alive["ok"] = False        # 브라우저가 떠나도 Hermes 스트림은 끝까지 읽어 기록한다
                app.chat_send(chat, text, operator=operator, session_hash=sh, ip=ip, emit=emit)
                return

        # ---------- 가이드 ----------
        if path == "/guide" and method == "GET":
            return self._page("가이드", ui.guide(public_url=app.cfg.public_url, target=app.cfg.target_base_url,
                                                wiki_url=app.cfg.wiki_public_url, sprint_days=app.cfg.sprint_days), "guide")

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
