"""Sanity 테스트 (docs/qa-platform-v2.md §4) — PR 하나: 관련 스펙 찾기 → 스펙 점검(멈춤) → 정하기 → 이어서 → 실행·분석."""
from __future__ import annotations

import base64
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as appmod  # noqa: E402
from app import BadRequest  # noqa: E402
from qa import httpx, sanity as S, ui  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402

REPO = "https://api.github.com/repos/100Thieves-team/moimyeon-backend"
PATCH = ('@@ -51,18 +51,6 @@ class RoomController(\n-    @PostMapping("/v1/rooms/{roomId}/cancellation")\n-    fun cancel(\n'
         '     @PostMapping("/v1/rooms/{roomId}/confirmation")\n')
FILES = [
    {"filename": "core/core-api/src/main/kotlin/io/plady/moimyeon/core/api/controller/v1/RoomController.kt", "status": "modified", "additions": 0, "deletions": 12, "patch": PATCH},
    {"filename": "core/core-api/src/main/kotlin/io/plady/moimyeon/core/domain/room/RoomManager.kt", "status": "modified", "additions": 20, "deletions": 23, "patch": "@@ x\n+ fun leave()"},
    {"filename": ".worklog/MOI-541-room-lifecycle/decisions.md", "status": "added", "additions": 5, "deletions": 0, "patch": "+# 결정"},
    {"filename": "core/core-api/src/test/kotlin/io/plady/moimyeon/core/api/controller/v1/RoomControllerTest.kt", "status": "modified", "additions": 1, "deletions": 50, "patch": "-test"},
]
PR = {"number": 138, "title": "feat(room): MVP 상태 흐름과 완료 출석 분리 (MOI-541)", "html_url": "https://github.com/x/pull/138", "user": {"login": "dbwp031"},
      "merged_at": "2026-09-25T09:29:58Z", "merge_commit_sha": "7b7104c6aaaa", "body": "방장 이탈이 취소와 위임을 결정한다"}
INFRA = {"number": 136, "title": "fix(infra): 로그 옵션", "html_url": "u", "user": {"login": "bebeis"}, "merged_at": "2026-09-23T07:04:33Z", "merge_commit_sha": "c1", "body": ""}
DECISIONS = "## DR-002 방장 이탈이 취소와 위임을 결정한다\n- 명시적 룸 취소 HTTP API는 제거한다.\n"
FIND = '```json\n{"scope": [{"feature": "룸 생성", "scenario": "S2", "reqs": ["R147", "R999"], "why": "취소 API 가 없어졌다"}, {"feature": "없는 기능", "scenario": "S1", "reqs": ["R1"]}]}\n```'
CHECK = ('```json\n{"findings": [{"kind": "mismatch", "title": "룸 취소 API 가 없어졌어요", "spec": "「룸 생성」 S2 R147", "code": "DR-002",'
         ' "question": "R147 을 바꿀까요?", "suggestion": "바꾼다", "reqs": ["R147"]}, {"kind": "nope", "title": "버려질 것"}]}\n```')


class Backend:
    """GitHub(백엔드 PR · 이 레포 파일)과 dev 서버, Hermes 흉내."""

    def __init__(self, gh: FakeGitHub):
        self.gh, self.dev = gh, []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        if url.startswith(REPO):
            rest = url[len(REPO):]
            if rest.startswith("/pulls/138/files"):
                return httpx.HttpResult(200, {}, json.dumps(FILES), 1)
            if rest.startswith("/pulls/136/files"):
                return httpx.HttpResult(200, {}, json.dumps([{"filename": "infra/x.tf", "status": "modified", "additions": 1, "deletions": 1}]), 1)
            if rest.startswith("/pulls/138"):
                return httpx.HttpResult(200, {}, json.dumps(PR), 1)
            if rest.startswith("/pulls/136"):
                return httpx.HttpResult(200, {}, json.dumps(INFRA), 1)
            if rest.startswith("/pulls?"):
                return httpx.HttpResult(200, {}, json.dumps([PR, INFRA]), 1)
            if rest.startswith("/contents/.worklog/"):
                return httpx.HttpResult(200, {}, json.dumps({"encoding": "base64", "content": base64.b64encode(DECISIONS.encode()).decode()}), 1)
            return httpx.HttpResult(404, {}, "{}", 1)
        if url.startswith("https://api.github.com/"):
            if "/contents/" not in url:
                return httpx.HttpResult(0, {}, "", 1, error="offline")
            return self.gh(method, url, headers=headers, body=body, timeout=timeout)
        if url.startswith("https://api.dev.moimyeon.plady.io"):
            self.dev.append((method, url))
            if url.endswith("/v1/auth/dev-sessions"):
                return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "t"}}), 1)
            if url.endswith("/cancellation"):
                return httpx.HttpResult(404, {}, json.dumps({"error": "Not Found"}), 1)
            if method == "POST" and url.endswith("/v1/rooms"):
                return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"roomId": "r-1", "status": "RECRUITING"}}), 1)
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 1)
        return httpx.HttpResult(0, {}, "", 1, error="offline")


def hermes(replies: dict, seen: list):
    """jobs.asker 흉내 — 시스템 프롬프트로 어떤 일인지 가려 준비한 답을 준다."""
    def ask(cfg, system, prompt, *, session_prefix, on_event=None, cancel=None, deadline=None, stall=None):
        seen.append((session_prefix, prompt))
        if system == S.FIND_SYSTEM:
            return replies.get("find", "")
        if system == S.CHECK_SYSTEM:
            return replies.get("check", "")
        if "실패" in system or "분류" in system:
            return "분류: 스크립트 낡음 — PR #138 이 API 를 지웠다"
        return ""
    return ask


class UnitTest(unittest.TestCase):
    def test_summarize_and_endpoints(self):
        s = S.summarize(FILES)
        self.assertEqual((s["changed_files"], s["additions"], s["deletions"], s["api"]), (4, 26, 85, True))
        self.assertIn("room", s["domains"])
        self.assertEqual(s["scope"], "api")
        self.assertFalse(S.summarize([{"filename": "infra/a.tf"}])["api"])
        base = "core/core-api/src/main/kotlin/io/plady/moimyeon/core/"
        pr153 = [{"filename": ".worklog/MOI-571/plan.md"}, {"filename": base + "api/controller/v1/response/RoomParticipantsResponse.kt"},
                 {"filename": base + "domain/participation/RoomParticipantReader.kt"},
                 {"filename": "core/core-api/src/test/kotlin/io/plady/moimyeon/core/api/controller/v1/RoomParticipantControllerTest.kt"}]
        s = S.summarize(pr153)                                                              # PR #153: 응답 DTO 에 필드를 더했다 — 컨트롤러는 그대로
        self.assertEqual((s["scope"], s["api"], s["contract"]), ("api", True, ["RoomParticipantsResponse.kt"]))
        s = S.summarize([pr153[0], pr153[2], pr153[3]])                                      # API 모양은 그대로, 동작 코드만
        self.assertEqual((s["scope"], s["api"]), ("code", True))
        s = S.summarize([pr153[0], pr153[3], {"filename": "infra/terraform/a.tf"}])         # 시험·작업 기록·인프라만
        self.assertEqual((s["scope"], s["api"]), ("none", False))
        self.assertEqual(S.endpoint_changes(FILES), [{"change": "removed", "method": "POST", "path": "/v1/rooms/{roomId}/cancellation", "file": "RoomController.kt"}])
        self.assertEqual(S.decision_files(FILES), [".worklog/MOI-541-room-lifecycle/decisions.md"])
        ex = S.diff_excerpt(FILES)
        self.assertLess(ex.index("RoomController.kt"), ex.index("RoomManager.kt"))       # 컨트롤러가 먼저
        self.assertNotIn("RoomControllerTest", ex)                                        # 시험 코드는 뺀다

    def test_parse(self):
        cat = {"룸 생성": {"S2": {"R147", "R148"}}}
        self.assertEqual(S.parse_scope(FIND, cat), [{"feature": "룸 생성", "scenario": "S2", "reqs": ["R147"], "why": "취소 API 가 없어졌다"}])
        fs = S.parse_findings(CHECK)
        self.assertEqual([(f["kind"], f["reqs"], f["source"]) for f in fs], [("mismatch", ["R147"], "hermes")])
        with self.assertRaises(ValueError):
            S.parse_findings("모르겠다")


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        self.backend = Backend(self.gh)
        httpx.request = self.backend
        self.app = make_app(self.tmp.name)
        self.seen: list = []
        self.app.jobs.asker = hermes({"find": FIND, "check": CHECK}, self.seen)
        self.cancel_op = self.app.spec.get().ops.pop("cancelRoom")        # dev API 문서에서 없어진 것처럼 (백엔드 #138)

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def events(self):
        return [x["action"] for x in self.app.store.list_events(50)]

    def test_stops_for_spec_then_continues_and_runs(self):
        with self.assertRaises(BadRequest):
            self.app.sanity_start(138, operator="nobody")
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        s = self.app.store.get_sanity(sid)
        self.assertEqual((s["status"], s["step"]), ("needs_spec", 2))
        self.assertEqual([(x["feature"], x["scenario"], x["reqs"]) for x in s["scope"]["items"]], [("룸 생성", "S2", ["R147"])])
        self.assertEqual(s["scope"]["endpoints"][0]["change"], "removed")
        kinds = [f["kind"] for f in s["findings"]]
        self.assertIn("mismatch", kinds)
        missing = next(f for f in s["findings"] if f["kind"] == "missing_api")          # 없어진 API 를 부르는 스크립트를 플랫폼이 찾는다
        self.assertIn("/v1/rooms/{}/cancellation", missing["title"])
        self.assertTrue({"room.cancel", "room.cancel-not-recruiting"} <= set(missing["scripts"]))
        check_prompt = next(p for pre, p in self.seen if pre == "qa-sanity-check")
        self.assertIn("명시적 룸 취소 HTTP API는 제거한다", check_prompt)                 # 결정 기록을 근거로 준다
        self.assertIn("RoomController.kt", check_prompt)
        self.assertNotIn("RoomControllerTest", check_prompt)
        # 하나는 추천대로, 나머지는 사유를 적고 계속
        mm = next(f for f in s["findings"] if f["kind"] == "mismatch")
        with self.assertRaises(BadRequest):
            self.app.sanity_resolve(sid, mm["id"], choice="other", note="", operator="bebe")
        self.app.sanity_resolve(sid, mm["id"], choice="recommended", note="", operator="bebe")
        with self.assertRaises(BadRequest):
            self.app.sanity_continue(sid, reason="", operator="bebe", sync=True)
        self.app.sanity_continue(sid, reason="기획 확인 중", operator="bebe", sync=True)
        s = self.app.store.get_sanity(sid)
        self.assertEqual(s["status"], "failed")
        self.assertEqual(missing["id"], next(f["id"] for f in s["findings"] if f.get("resolution") == "continued"))
        run = self.app.store.get_run(s["run_id"])
        self.assertEqual((run["trigger"], run["pr_number"]), ("deploy-sanity", 138))
        rcs = {rc["case_id"]: rc for rc in self.app.store.list_run_cases(run["id"])}
        self.assertEqual(rcs["room.cancel"]["verdict"], "fail")
        self.assertIn("스크립트 낡음", rcs["room.cancel"]["triage"])                    # 실패는 Hermes 가 분석
        self.assertTrue(any(u.endswith("/v1/dev/rooms/r-1") for m, u in self.backend.dev))   # 실패 뒤에도 정리
        self.assertEqual([x["step"] for x in s["log"]], [1, 2, 3, 4, 5])
        for a in ("sanity.start", "sanity.finding.resolve", "sanity.continue", "sanity.finish", "hermes_job.start"):
            self.assertIn(a, self.events())
        # 화면
        prs = self.app.sanity_prs()
        self.assertEqual([(p["number"], p["api"]) for p in prs], [(138, True), (136, False)])
        page = ui.page("x", ui_sanity_page(self.app, prs, 138), active="sanity", operator="bebe")
        for frag in ("룸 취소 API 가 없어졌어요", "정하지 않고 계속했어요", "추천대로 정했어요", "이번 범위의 케이스", "API·코드 변경이 없는 PR", "실패"):
            self.assertIn(frag, page)
        todo = self.app.home_todo(prs)
        self.assertEqual(todo[0]["href"], "/sanity/138")
        self.assertIn("실패", todo[0]["title"])

    def test_infra_pr_has_nothing_to_check(self):
        self.app.jobs.asker = hermes({"find": '```json\n{"scope": []}\n```'}, self.seen)
        sid = self.app.sanity_start(136, operator="bebe", sync=True)
        s = self.app.store.get_sanity(sid)
        self.assertEqual((s["status"], s["run_id"]), ("empty", None))
        self.assertIn("이 PR 이 닿는 사용자 기능이 없어요", s["log"][-1]["text"])

    def test_recheck_after_wiki_fix(self):
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        self.app.jobs.asker = hermes({"find": FIND, "check": '```json\n{"findings": []}\n```'}, self.seen)
        self.app.spec.get().ops["cancelRoom"] = self.cancel_op          # 위키·문서를 고친 뒤처럼
        self.app.sanity_recheck(sid, operator="bebe", sync=True)
        s = self.app.store.get_sanity(sid)
        self.assertEqual(s["status"], "passed" if s["run_id"] and self.app.store.get_run(s["run_id"])["verdict"] == "pass" else "failed")
        self.assertIn("sanity.recheck", self.events())
        self.assertNotIn("mismatch", [f["kind"] for f in s["findings"]])


def ui_sanity_page(app, prs, num):
    from qa import ui_sanity
    hist = app.store.list_sanity(num)
    s = hist[0]
    run = app.store.get_run(s["run_id"]) if s.get("run_id") else None
    return ui_sanity.sanity_page(prs, next(p for p in prs if p["number"] == num), s, operator="bebe", target="https://api.dev", hermes=True,
                                 cases=app.sanity_cases(s["scope"]), run=run, history=hist)


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.orig = httpx.request
        gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        httpx.request = Backend(gh)
        cls.app = make_app(cls.tmp.name)
        cls.app.jobs.asker = hermes({"find": FIND, "check": CHECK}, [])
        appmod.Handler.app = cls.app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        httpx.request = cls.orig
        cls.tmp.cleanup()

    def req(self, path, data=None):
        from urllib.parse import urlencode

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        r = urllib.request.Request(self.base + path, data=urlencode(data).encode() if data else None, headers={"Cookie": "qa_operator=bebe", "Accept": "text/html"})
        try:
            with urllib.request.build_opener(NoRedirect).open(r, timeout=20) as resp:
                return resp.status, resp.read().decode(), resp.headers.get("Location")
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read().decode(), ex.headers.get("Location")

    def test_pages_and_start(self):
        for path in ("/", "/sanity", "/sanity/138", "/sanity/136", "/sanity?f=todo", "/smoke", "/smoke?mode=failed", "/data"):
            st, body, _ = self.req(path)
            self.assertEqual(st, 200, path)
            self.assertNotIn("내부 오류", body, path)
        st, body, _ = self.req("/sanity/138")
        self.assertIn("Sanity 시작", body)
        self.assertIn('action="/sanity/start"', body)
        for path, marks in (("/", ("todo", "features")), ("/sanity/138", ("prs", "tabs", "start")), ("/smoke", ("scope", "mode", "run")),
                            ("/data", ("make", "left")), ("/catalog", ("filters", "write"))):
            st, body, _ = self.req(path)
            self.assertIn("window.QA_TOUR=", body, path)                                      # 처음 쓰는 사람을 위한 둘러보기
            self.assertIn("data-tour-start", body, path)
            for m in marks:
                self.assertIn(f'data-tour="{m}"', body, (path, m))
        st, js, _ = self.req("/static/tour.js")
        self.assertEqual(st, 200)
        self.assertIn("window.qaTour", js)
        st, _, loc = self.req("/setup")
        self.assertEqual((st, loc), (303, "/data"))
        st, _, loc = self.req("/sanity/start", {"pr": "138", "operator": "bebe"})
        self.assertEqual((st, loc), (303, "/sanity/138"))
        st, _, loc = self.req("/sanity/start", {"pr": "138", "operator": ""})
        self.assertIn("err=", loc)


if __name__ == "__main__":
    unittest.main()
