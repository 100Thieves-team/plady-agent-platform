#!/usr/bin/env python3
"""qa-platform HTTP 서버. 설계: docs/qa-platform.md.

inbound 은 브라우저(팀 세션 뒤)뿐이다. 외부에서 실행을 시작시키는 경로는 없다.
모든 변경 행위는 담당자 필드가 필수이고 감사 로그(events)에 남는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import traceback
from datetime import datetime
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
from qa import chat as chatmod  # noqa: E402
from qa import drafts as draftsmod  # noqa: E402
from qa.github import GitHub, domains_from_files  # noqa: E402
from qa.hermes import triage as hermes_triage  # noqa: E402
from qa.mcp import McpClient, McpError, wiki_apply  # noqa: E402
from qa.mcp_server import McpServer  # noqa: E402
from qa import report as reportmod  # noqa: E402
from qa.notify import slack  # noqa: E402
from qa.reminder import Reminder  # noqa: E402
from qa.runner import Runner  # noqa: E402
from qa.spec import Spec  # noqa: E402
from qa.store import Store, now_iso  # noqa: E402
from qa.wiki import Wiki  # noqa: E402

TRIGGERS = ("deploy-sanity", "sprint-smoke", "release", "manual", "draft-check", "explorer")
HIDDEN_TRIGGERS = ("explorer",)          # 테스트 실행 목록 기본 숨김 (API 직접 호출은 건수가 많다)


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
        self.reminder = Reminder(cfg, self.store, lambda text: slack(cfg.slack_webhook_url, text))
        # QA MCP 서버 (docs/qa-platform-hermes.md §3.1): Hermes 가 부르는 읽기·제안 도구. 실행 도구는 없다
        self.mcp = McpServer(self, hidden_triggers=HIDDEN_TRIGGERS)

    def start(self):
        self.runner.start()
        self.reminder.start()      # 알림만. 실행은 여전히 사람 버튼

    # ---- 케이스 -----------------------------------------------------------------
    def reload_cases(self) -> tuple[int, list[str]]:
        self.cases, self.case_errors = load_dir(self.cfg.cases_dir)
        audit_cases(self.cases, self.catalog.get())
        if hasattr(self, "runner"):
            self.runner.cases = self.cases
        return len(self.cases), self.case_errors

    def current_catalog(self):
        """TC 목록을 돌려주고, 입력이 바뀌어 다시 계산됐으면 스크립트 정합성 검사도 다시 한다."""
        before = self.catalog.current
        cat = self.catalog.get()
        if cat is not None and (before is None or cat.key != before.key):
            audit_cases(self.cases, cat)
        return cat

    def coverage(self, cat) -> dict:
        """TC id → 검증하는 스크립트 id 목록, 도메인×층 매트릭스. 분모는 전체 TC, 제외는 따로 센다 (§6.2)."""
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
        meta = {"basis": basis, "reason": reason, "deploy_run_id": deploy_run_id, "case_ids": [c.id for c in chosen],
                "catalog": (cat.versions if cat else None),   # 이 런의 TC 소스 버전 (§6.3). 과거 런은 다시 해석하지 않는다
                "covers": sorted({t for c in chosen for t in c.covers})}
        meta.update({k: v for k, v in extra.items() if v not in (None, "")})
        rid = self.store.create_run(trigger=trigger, operator=operator, suite=suite, env=self.cfg.target_env,
                                    base_url=self.cfg.target_base_url, ref=ref or self.cfg.backend_branch, sha=sha,
                                    pr_number=pr_number, meta=meta, cases=chosen)
        self.store.add_event(operator=operator, action="run.create", target=rid, session_hash=session_hash, ip=ip,
                             detail={"trigger": trigger, "sha": sha, "pr": pr_number, "cases": len(chosen), "basis": basis, "reason": reason})
        if enqueue:
            self.runner.submit(rid)
        if notify:
            tgt = f"sha {sha[:8]}" + (f" PR #{pr_number}" if pr_number else "") if sha else self.cfg.target_env
            slack(self.cfg.slack_webhook_url, f"[QA] {operator} 가 {ui.TRIGGER_KO.get(trigger, trigger)} 실행 — {tgt}, {len(chosen)}건 · {self.cfg.public_url}/runs/{rid}")
        return rid

    # ---- 초안 (Hermes) ------------------------------------------------------------
    def generate_drafts(self, *, tc_ids: list[str], operator: str, session_hash: str | None, ip: str | None) -> dict:
        cat = self.current_catalog()
        if cat is None:
            raise BadRequest("TC 목록이 없어 초안을 만들 수 없다")
        tc_ids = [t for t in dict.fromkeys(tc_ids) if t in cat.records]
        if not tc_ids:
            raise BadRequest("TC 목록에 있는 TC 를 하나 이상 골라야 한다")
        if len(tc_ids) > 10:
            raise BadRequest("한 번에 10건까지")
        example = self.cases.get("room.create-and-cancel") or next(iter(self.cases.values()), None)
        try:
            res = draftsmod.generate(cfg=self.cfg, catalog=cat, spec=self.spec.get(), wiki=self.wiki, tc_ids=tc_ids,
                                     example=example, existing_ids=set(self.cases))
        except Exception as ex:
            self.store.add_event(operator=operator, action="draft.generate", target=None, session_hash=session_hash, ip=ip,
                                 detail={"tc_ids": tc_ids, "error": str(ex)[:300]})
            raise BadRequest(f"초안 생성 실패: {ex}")
        ids = []
        for case, warnings in res["accepted"]:
            did = self.store.add_draft(operator=operator, source="hermes", domain=(case.domains[0] if case.domains else cat.records[tc_ids[0]]["domain"]),
                                       yaml_text=case.to_yaml(), note=None, case_id=case.id, tc_ids=case.covers,
                                       validation={"status": case.audit["status"], "warnings": warnings}, prompt_hash=res["prompt_hash"])
            ids.append(did)
        for raw_id, errors in res["rejected"]:
            self.store.add_event(operator=operator, action="draft.rejected_by_validation", target=None, session_hash=session_hash, ip=ip,
                                 detail={"case_id": raw_id, "errors": errors[:6], "prompt_hash": res["prompt_hash"]})
        self.store.add_event(operator=operator, action="draft.generate", target=",".join(ids) or None, session_hash=session_hash, ip=ip,
                             detail={"tc_ids": tc_ids, "model": res["model"], "prompt_hash": res["prompt_hash"], "prompt_chars": res["prompt_chars"],
                                     "accepted": len(ids), "rejected": len(res["rejected"]), "raw_chars": len(res["raw"])})
        return {"ids": ids, "rejected": res["rejected"], "prompt_hash": res["prompt_hash"]}

    # ---- 탐색기 (docs/qa-platform-tc.md §8) ----------------------------------------
    def explorer_send(self, *, op_id: str, path_params: dict, query: dict, body_text: str, actor: str | None, operator: str,
                      session_hash: str | None, ip: str | None) -> str:
        """op 하나를 지금 보낸다. 전송 = 실행 기록(trigger explorer, 단계 1개, expect 없음). 응답은 실행 상세와 같은 기록."""
        spec = self.spec.get()
        op = spec.ops.get(op_id) if spec else None
        if not op:
            raise BadRequest("OpenAPI 에 없는 operationId")
        if actor and actor not in self.cfg.actors:
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

    def explorer_to_draft(self, rid: str, operator: str, session_hash: str | None, ip: str | None) -> str:
        """API 호출 기록 하나를 초안(단계 1개, 관측한 status·error_code 를 기대로)으로 담는다. covers 는 사람이 채운다."""
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
        self.store.add_event(operator=operator, action="draft.generate", target=did, session_hash=session_hash, ip=ip, detail={"source": "explorer", "run_id": rid})
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
        content = reportmod.render(run, rcs, coverage=self.coverage(cat) if cat else None, catalog=cat, public_url=self.cfg.public_url, sprint=sprint)
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
        return draftsmod.validate(raw, requested=list(raw.get("covers") or []) + [t for s in (raw.get("steps") or []) if isinstance(s, dict) for t in (s.get("covers") or [])],
                                  catalog=cat, cfg=self.cfg, existing_ids=set(self.cases) - {d.get("case_id")})

    def _on_finish(self, run: dict):
        if run["trigger"] in HIDDEN_TRIGGERS:
            return
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

    def _page(self, title, body, active="", flash=None, status=200, context=None, autostart=None, inline_chat=None):
        self._send(status, ui.page(title, body, active=active, operator=self._operator(), flash=flash, context=context, hermes=bool(self.app.cfg.hermes_key),
                                   operators=self.app.cfg.operators, autostart=autostart, inline_chat=inline_chat))

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
            show_all = g("all") == "1"
            return self._page("테스트 실행", ui.runs_list(app.store.list_runs(100, exclude=() if show_all else HIDDEN_TRIGGERS), show_all), "runs")

        if path == "/runs/new" and method == "GET":
            trigger = g("trigger", "manual")
            if trigger not in TRIGGERS:
                raise BadRequest(f"모르는 실행 종류: {trigger}")
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
                warnings.append("테스트 계정(QA_ACTORS)이 설정되지 않았다 — 테스트 계정이 필요한 스크립트는 skipped 로 기록된다.")
            if app.github.last_error and trigger == "deploy-sanity":
                warnings.append(app.github.last_error)
            app.current_catalog()
            drifted = [c.id for c in suggested if app.drift_of(c)]
            if drifted:
                warnings.append("검증하는 TC 가 바뀐 스크립트가 있다 (스크립트 화면에서 확인): " + ", ".join(drifted[:6]) + (" …" if len(drifted) > 6 else ""))
            blocked = [c.id for c in app.cases.values() if c.blocked]
            if blocked:
                warnings.append("TC 정합성 불일치로 스위트에서 빠진 스크립트: " + ", ".join(blocked[:6]))
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
            flash = None
            if run["meta"].get("_flash"):
                flash = tuple(run["meta"]["_flash"])
                m2 = dict(run["meta"]); m2.pop("_flash", None)
                app.store.update_run(rid, meta=m2)
                run["meta"] = m2
            return self._page(f"실행 {rid}", ui.run_detail(run, rcs, steps, operators=app.cfg.operators, operator=self._operator(),
                                                        checklist=checklist, public_url=app.cfg.public_url,
                                                        can_publish=bool(app.cfg.wiki_mcp_url and app.cfg.wiki_mcp_token)), "runs", flash=flash, context={"run": rid})

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
                try:
                    text = hermes_triage(app.cfg, run, rc, app.store.list_steps(rc["id"]))
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
                return self._page("테스트 케이스", f'<h1>테스트 케이스</h1><div class="flash err">TC 목록을 만들지 못했다: {ui.e(app.catalog.last_error or "원인 미상")}</div>', "catalog")
            cov = app.coverage(cat)
            domain = g("domain") or (cat.domains()[0] if cat.domains() else "")
            body = ui.catalog_list(cat, cov, app.store.last_verdicts(), domain=domain, layer=g("layer"), only=g("only"),
                                   changes=app.catalog.changes, wiki_available=app.wiki.available,
                                   operators=app.cfg.operators, operator=self._operator(), hermes=bool(app.cfg.hermes_key))
            return self._page("테스트 케이스", body, "catalog")
        if path == "/catalog/tc" and method == "GET":
            cat = app.current_catalog()
            rec = cat.records.get(g("id")) if cat else None
            if not rec:
                return self._error(404, "그 TC 가 TC 목록에 없다")
            cov = app.coverage(cat)
            covering = [app.cases[i] for i in cov["by_tc"].get(rec["id"], []) if i in app.cases]
            excerpts = []
            for ref in rec.get("prd") or []:
                text = app.wiki.prd_section(ref["doc"], ref["section"], max_lines=40) if app.wiki.available else None
                excerpts.append((ref, text))
            return self._page(rec["id"], ui.catalog_detail(rec, covering, app.store.last_verdicts(), excerpts, app.catalog.changes.get(rec["id"])), "catalog", context={"tc": rec["id"]})
        if path == "/api/catalog" and method == "GET":
            cat = app.current_catalog()
            return self._json(200, cat.to_json() if cat else {"error": app.catalog.last_error})

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
            return self._page("API 호출", ui.explorer(spec, op, run, steps, actors=sorted(app.cfg.actors), operators=app.cfg.operators,
                                                 operator=self._operator(), q=g("q")), "explorer")
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
            return self._json(200, {"id": did}) if self._wants_json() else self._redirect(f"/drafts/{did}", set_operator=operator)

        # ---------- 케이스 초안 (docs/qa-platform-tc.md §7.3) ----------
        if path == "/drafts" and method == "GET":
            st = g("status")
            return self._page("스크립트 초안", ui.drafts_list(app.store.list_drafts(st or None), app.store.draft_counts(), st), "drafts")
        if path == "/drafts/generate" and method == "POST":
            f = self._form()
            fv = lambda k, d="": (f.get(k) or [d])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            res = app.generate_drafts(tc_ids=[str(x) for x in f.get("tc_ids") or []], operator=operator, session_hash=self._session_hash(), ip=self._ip())
            if self._wants_json():
                return self._json(200, res)
            return self._redirect(f"/drafts/{res['ids'][0]}" if res["ids"] else "/drafts?status=draft", set_operator=operator)
        m = re.match(r"^/drafts/(d-[0-9a-f]+)$", path)
        if m and method == "GET":
            d = app.store.get_draft(m.group(1))
            if not d:
                return self._error(404, "초안이 없다")
            cat = app.current_catalog()
            recs = {t: (cat.records.get(t) if cat else None) for t in d["tc_ids"]}
            run = app.store.get_run(d["run_id"]) if d.get("run_id") else None
            return self._page(f"스크립트 초안 {d['id']}", ui.draft_detail(d, recs, run, operators=app.cfg.operators, operator=self._operator()), "drafts")
        m = re.match(r"^/drafts/(d-[0-9a-f]+)/(save|check|approve|reject)$", path)
        if m and method == "POST":
            did, action = m.group(1), m.group(2)
            d = app.store.get_draft(did)
            if not d:
                return self._error(404, "초안이 없다")
            f = self._form()
            fv = lambda k, d_="": (f.get(k) or [d_])[0]  # noqa: E731
            operator = str(fv("operator")).strip()
            if not operator or operator not in app.cfg.operators:
                raise BadRequest("담당자를 목록에서 골라야 한다")
            sh, ip = self._session_hash(), self._ip()
            if d["status"] in ("approved", "rejected") and action in ("save", "check"):
                raise BadRequest("결정된 초안은 고치거나 실행하지 않는다")
            is_tc = (d.get("kind") or "case") == "tc"     # 수동 TC 제안: 실행할 수 없고, 승인은 manual-tc.yaml 로 옮기라는 뜻
            if action == "save":
                text = str(fv("yaml"))
                if is_tc:
                    items, errors = draftsmod.validate_manual_tc(text)
                    validation = {"status": "error" if errors else "ok", "errors": errors, "warnings": []}
                    app.store.update_draft(did, yaml=text, validation=validation, tc_ids=[str(i.get("id")) for i in items], status="draft")
                    app.store.add_event(operator=operator, action="draft.save", target=did, session_hash=sh, ip=ip, detail={"kind": "tc", "errors": len(errors)})
                    return self._json(200, {"ok": True}) if self._wants_json() else self._redirect(f"/drafts/{did}", operator)
                case, errors, warnings = app.revalidate_draft(d, text)
                validation = {"status": ("error" if errors else (case.audit["status"] if case else "error")), "errors": errors, "warnings": warnings}
                app.store.update_draft(did, yaml=text, validation=validation, case_id=(case.id if case else d.get("case_id")),
                                       tc_ids=(case.covers if case else d["tc_ids"]), status="draft", run_id=None)
                app.store.add_event(operator=operator, action="draft.save", target=did, session_hash=sh, ip=ip, detail={"errors": len(errors), "warnings": len(warnings)})
            elif action == "check":
                if is_tc:
                    raise BadRequest("수동 TC 제안은 실행할 것이 없다 — 승인 뒤 manual-tc.yaml 에 붙여 PR 로 낸다")
                case, errors, _ = app.revalidate_draft(d, d["yaml"])
                if not case:
                    raise BadRequest("검증 오류가 있는 초안은 실행하지 않는다: " + "; ".join(errors[:3]))
                rid = app.create_run(trigger="draft-check", operator=operator, case_ids=[], sha=None, ref=None, pr_number=None,
                                     deploy_run_id=None, reason=f"스크립트 초안 {did} 확인 실행", basis="스크립트 초안 1건", extra={"draft_id": did},
                                     session_hash=sh, ip=ip, cases_override=[case])
                app.store.update_draft(did, status="checked", run_id=rid)
                app.store.add_event(operator=operator, action="draft.check", target=did, session_hash=sh, ip=ip, detail={"run_id": rid})
            elif action == "approve":
                if is_tc:
                    _, errors = draftsmod.validate_manual_tc(d["yaml"])
                    if errors:
                        raise BadRequest("형식 오류가 있는 제안은 승인하지 않는다: " + "; ".join(errors[:3]))
                    app.store.update_draft(did, status="approved", decided_by=operator, decided_at=now_iso(), note=str(fv("note")).strip() or d.get("note"))
                    app.store.add_event(operator=operator, action="draft.approve", target=did, session_hash=sh, ip=ip, detail={"kind": "tc", "tc_ids": d["tc_ids"]})
                    return self._json(200, {"ok": True}) if self._wants_json() else self._redirect(f"/drafts/{did}", operator)
                case, errors, _ = app.revalidate_draft(d, d["yaml"])
                if not case:
                    raise BadRequest("검증 오류가 있는 초안은 승인하지 않는다: " + "; ".join(errors[:3]))
                app.store.update_draft(did, status="approved", decided_by=operator, decided_at=now_iso(), note=str(fv("note")).strip() or d.get("note"))
                app.store.add_event(operator=operator, action="draft.approve", target=did, session_hash=sh, ip=ip, detail={"case_id": d.get("case_id"), "tc_ids": d["tc_ids"]})
            elif action == "reject":
                app.store.update_draft(did, status="rejected", decided_by=operator, decided_at=now_iso(), note=str(fv("note")).strip() or d.get("note"))
                app.store.add_event(operator=operator, action="draft.reject", target=did, session_hash=sh, ip=ip, detail={"note": str(fv("note")).strip()[:200]})
            return self._json(200, {"ok": True}) if self._wants_json() else self._redirect(f"/drafts/{did}", operator)

        # ---------- 케이스 ----------
        if path == "/cases" and method == "GET":
            app.current_catalog()
            cs = sorted(app.cases.values(), key=lambda c: c.id)
            drift = {c.id: app.drift_of(c) for c in cs}
            return self._page("스크립트", ui.cases_list(cs, app.store.last_verdicts(), app.case_errors, drift=drift), "cases")
        if path == "/cases/reload" and method == "POST":
            n, errs = app.reload_cases()
            app.store.add_event(operator=self._operator() or "(미선택)", action="cases.reload", target=None, detail={"cases": n, "errors": len(errs)})
            return self._redirect("/cases")
        m = re.match(r"^/cases/([a-z0-9][a-z0-9.\-]*)$", path)
        if m and method == "GET":
            c = app.cases.get(m.group(1))
            if not c:
                return self._error(404, "스크립트가 없다")
            cat = app.current_catalog()
            recs = {t: (cat.records.get(t) if cat else None) for t in c.covers}
            return self._page(c.id, ui.case_detail(c, app.store.case_history(c.id), tc_records=recs, drift=app.drift_of(c)), "cases", context={"case": c.id})

        # ---------- Hermes 대화 (docs/qa-platform-hermes.md §3.2) — 위젯 스크립트 + JSON/SSE API + 기록 화면 ----------
        if path == "/static/hermes.js" and method == "GET":
            return self._send(200, ui.HERMES_JS, "application/javascript; charset=utf-8", headers={"Cache-Control": "public, max-age=300"})
        if path == "/chat" and method == "GET":
            chats = app.store.list_chats(100)
            return self._page("Hermes", ui.chats_list(chats, stale={c["id"]: app.chat_stale(c) for c in chats}, hermes=bool(app.cfg.hermes_key),
                                                     operator=self._operator(), operators=app.cfg.operators), "chat")
        if path == "/chat/new" and method == "GET":
            # 상세 화면의 [Hermes 와 이야기] — 위젯을 그 객체를 첨부한 새 대화로 연다
            ctx = {k: g(k) for k in ("run", "case", "tc") if g(k)}
            chats = app.store.list_chats(100)
            return self._page("Hermes", ui.chats_list(chats, stale={c["id"]: app.chat_stale(c) for c in chats}, hermes=bool(app.cfg.hermes_key),
                                                     operator=self._operator(), operators=app.cfg.operators), "chat", autostart=ctx or {"new": True})
        m = re.match(r"^/chat/(c-[0-9a-f]+)$", path)
        if m and method == "GET":
            chat = app.store.get_chat(m.group(1))
            if not chat:
                return self._error(404, "대화가 없다")
            head = (f'<h1>{ui.e(chat.get("title") or "대화")} <span class="small mut mono">{ui.e(chat["id"])}</span> <a class="btn" href="/chat">목록</a></h1>'
                    f'<p class="small mut">담당자 {ui.e(chat["operator"])} · {ui.kst(chat["created_at"])} · 초안 {chat["drafts"]}건(승인은 <a href="/drafts">스크립트 초안</a> 화면에서)</p>')
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
