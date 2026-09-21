"""표준 unittest. `python3 -m unittest discover -s qa-platform/tests` 또는 `python3 qa-platform/tests/test_core.py`."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import httpx  # noqa: E402
from qa.cases import CaseError, load_dir, parse_one, select  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.github import domains_from_files  # noqa: E402
from qa.runner import Runner, evaluate  # noqa: E402
from qa.store import Store  # noqa: E402
from qa.templating import Context, TemplateError, get_path  # noqa: E402


class TemplatingTest(unittest.TestCase):
    def test_full_match_keeps_type(self):
        ctx = Context(fixtures={"postingId": 42}, variables={"roomId": "abc"})
        self.assertEqual(ctx.render("{{fixture.postingId}}"), 42)
        self.assertEqual(ctx.render("/v1/rooms/{{roomId}}/x"), "/v1/rooms/abc/x")
        self.assertEqual(ctx.render({"a": ["{{roomId}}", 1]}), {"a": ["abc", 1]})

    def test_actor_and_dotted_fixture(self):
        ctx = Context(actors={"qa-host": "u-1"}, fixtures={"qa-host.resumeId": "r-1", "nested": {"k": "v"}})
        self.assertEqual(ctx.render("{{actor.qa-host.memberId}}"), "u-1")
        self.assertEqual(ctx.render("{{fixture.qa-host.resumeId}}"), "r-1")
        self.assertEqual(ctx.render("{{fixture.nested.k}}"), "v")
        with self.assertRaises(TemplateError) as cm:
            ctx.render("{{actor.nobody.memberId}}")
        self.assertEqual(cm.exception.kind, "actor")
        with self.assertRaises(TemplateError) as cm:
            ctx.render("{{fixture.missing}}")
        self.assertEqual(cm.exception.kind, "fixture")
        with self.assertRaises(TemplateError) as cm:
            ctx.render("{{unknownVar}}")
        self.assertEqual(cm.exception.kind, "var")

    def test_date_uuid_rand(self):
        ctx = Context(today=datetime(2026, 9, 20, tzinfo=timezone.utc))
        self.assertEqual(ctx.render("{{date:+7}}"), "2026-09-27")
        self.assertEqual(ctx.render("{{date:-1}}"), "2026-09-19")
        self.assertEqual(len(ctx.render("{{uuid}}")), 36)
        self.assertEqual(len(ctx.render("{{rand}}")), 6)

    def test_get_path(self):
        d = {"data": {"rooms": [{"roomId": "r1"}], "n": 0}}
        self.assertEqual(get_path(d, "data.rooms[0].roomId"), "r1")
        self.assertEqual(get_path(d, "data.n"), 0)
        self.assertIsNone(get_path(d, "data.rooms[3].roomId"))
        self.assertIsNone(get_path(d, "nope"))


class EvaluateTest(unittest.TestCase):
    def test_checks(self):
        body = {"result": "ERROR", "data": None, "error": {"code": "E1102"}}
        cs = evaluate({"status": 401, "result": "ERROR", "error_code": "E1102", "exists": ["error.code"]}, 401, body)
        self.assertTrue(all(c["ok"] for c in cs))
        cs = evaluate({"status": 200, "json": {"data.status": "ACTIVE"}}, 401, body)
        self.assertEqual([c["ok"] for c in cs], [False, False])

    def test_json_numeric_string_tolerance(self):
        cs = evaluate({"json": {"data.n": "3"}}, 200, {"data": {"n": 3}})
        self.assertTrue(cs[0]["ok"])


class CasesTest(unittest.TestCase):
    def test_seed_cases_load(self):
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        self.assertGreaterEqual(len(cases), 9)
        self.assertEqual(cases["auth.me-without-token"].suite, "smoke")
        self.assertTrue(cases["room.create-and-cancel"].needs_actor())
        self.assertEqual(len(cases["platform.health"].hash), 16)

    def test_validation_errors(self):
        with self.assertRaises(CaseError):
            parse_one("id: Bad_ID\ntitle: x\nsuite: smoke\nsteps: [{request: {method: GET, path: /}}]")
        with self.assertRaises(CaseError):
            parse_one("id: a\ntitle: x\nsuite: nope\nsteps: [{request: {method: GET, path: /}}]")
        with self.assertRaises(CaseError):
            parse_one("id: a\ntitle: x\nsuite: smoke\nsteps: [{request: {method: GET, path: /}, expect: {bogus: 1}}]")
        c = parse_one("id: a\ntitle: x\nsuite: smoke\nsteps: [{request: {method: get, path: /}}]")
        self.assertEqual(c.steps[0]["request"]["method"], "GET")
        self.assertEqual(c.steps[0]["name"], "step 1")

    def test_select(self):
        cases, _ = load_dir(ROOT / "cases")
        self.assertTrue(all(c.suite == "smoke" for c in select(cases, suite="smoke")))
        ids = {c.id for c in select(cases, suite="sanity", domains=["application"])}
        self.assertEqual(ids, {"room.apply-and-withdraw"})
        self.assertEqual(select(cases, suite="sanity", domains=["nothing"]), [])
        ids = {c.id for c in select(cases, operations=["memberMe"])}
        self.assertEqual(ids, {"auth.me-without-token", "member.me"})


class GithubMappingTest(unittest.TestCase):
    def test_domains(self):
        files = [
            "core/core-api/src/main/kotlin/io/plady/moimyeon/core/domain/room/RoomService.kt",
            "core/core-api/src/main/kotlin/io/plady/moimyeon/core/api/controller/v1/DevAuthController.kt",
            "core/core-api/src/main/kotlin/io/plady/moimyeon/core/domain/roomapplication/X.kt",
            "storage/db-core/src/main/resources/db/migration/V27__x.sql",
            "docs/conventions/git.md",
        ]
        self.assertEqual(domains_from_files(files), {"room", "auth", "application", "schema"})
        self.assertEqual(domains_from_files(["README.md"]), set())


class SprintTest(unittest.TestCase):
    def test_cycle_number(self):
        cfg = Config()
        s = cfg.current_sprint(datetime(2026, 9, 20, 12, tzinfo=timezone.utc))
        self.assertEqual(s["number"], 9)
        s = cfg.current_sprint(datetime(2026, 9, 21, 0, tzinfo=timezone.utc))   # 9/20 15:00Z 이후 → 10
        self.assertEqual(s["number"], 10)


class FakeHttp:
    """qa.httpx.request 대역. (method, path) → (status, json)."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        path = url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        self.calls.append((method, "/" + path, headers or {}, body))
        status, js = self.table.get((method, "/" + path), (404, {"result": "ERROR", "error": {"code": "E404"}}))
        if callable(js):
            js = js(body)
        return httpx.HttpResult(status, {}, json.dumps(js), 1)


class RunnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["QA_DATA_DIR"] = self.tmp.name
        os.environ["QA_ACTORS"] = json.dumps({"qa-host": "member-1"})
        os.environ["QA_FIXTURES"] = json.dumps({"postingId": 7})
        self.cfg = Config()
        self.store = Store(self.cfg.db_path)
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        for k in ("QA_DATA_DIR", "QA_ACTORS", "QA_FIXTURES"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def _case(self, text):
        return parse_one(text)

    def test_pass_fail_skip_flow(self):
        fake = FakeHttp({
            ("POST", "/v1/auth/dev-sessions"): (200, {"result": "SUCCESS", "data": {"accessToken": "tok-1"}}),
            ("GET", "/v1/members/me"): (200, {"result": "SUCCESS", "data": {"memberId": "member-1", "status": "ACTIVE"}}),
            ("POST", "/v1/rooms"): (200, {"result": "SUCCESS", "data": {"roomId": "room-9", "status": "RECRUITING"}}),
            ("GET", "/v1/rooms/room-9"): (200, {"result": "SUCCESS", "data": {"status": "RECRUITING", "hostMemberId": "member-1"}}),
            ("GET", "/v1/terms"): (500, {"result": "ERROR", "error": {"code": "E500"}}),
        })
        httpx.request = fake
        cases = {
            "a.pass": self._case("id: a.pass\ntitle: t\nsuite: smoke\nactor: qa-host\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/members/me}\n"
                                 "    expect: {status: 200, json: {'data.memberId': '{{actor.qa-host.memberId}}'}}\n"),
            "b.save": self._case("id: b.save\ntitle: t\nsuite: sanity\nactor: qa-host\nsteps:\n"
                                 "  - request: {method: POST, path: /v1/rooms, body: {postingId: '{{fixture.postingId}}'}}\n"
                                 "    expect: {status: 200}\n    save: {roomId: data.roomId}\n"
                                 "  - request: {method: GET, path: '/v1/rooms/{{roomId}}'}\n"
                                 "    expect: {status: 200, json: {'data.hostMemberId': '{{actor.qa-host.memberId}}'}}\n"),
            "c.fail": self._case("id: c.fail\ntitle: t\nsuite: smoke\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/terms}\n    expect: {status: 200, result: SUCCESS}\n"),
            "d.skip": self._case("id: d.skip\ntitle: t\nsuite: smoke\nactor: qa-guest\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/members/me}\n    expect: {status: 200}\n"),
            "e.skipfx": self._case("id: e.skipfx\ntitle: t\nsuite: smoke\nsteps:\n"
                                   "  - request: {method: GET, path: '/x/{{fixture.nope}}'}\n    expect: {status: 200}\n"),
        }
        runner = Runner(self.cfg, self.store, cases)
        rid = self.store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=list(cases.values()))
        runner.execute(rid)
        run = self.store.get_run(rid)
        self.assertEqual(run["status"], "finished")
        self.assertEqual(run["verdict"], "fail")
        self.assertEqual((run["passed"], run["failed"], run["errored"], run["skipped"]), (2, 1, 0, 2))
        rcs = {rc["case_id"]: rc for rc in self.store.list_run_cases(rid)}
        self.assertEqual(rcs["a.pass"]["verdict"], "pass")
        self.assertEqual(rcs["b.save"]["verdict"], "pass")
        self.assertEqual(rcs["c.fail"]["verdict"], "fail")
        self.assertIn("기대 200 실제 500", rcs["c.fail"]["error"])
        self.assertEqual(rcs["d.skip"]["verdict"], "skipped")
        self.assertIn("배우 미설정", rcs["d.skip"]["error"])
        self.assertEqual(rcs["e.skipfx"]["verdict"], "skipped")
        # 토큰은 한 번만 발급, Authorization 은 기록에서 마스킹, 스텝 기록에 save 된 변수가 반영됨
        self.assertEqual(sum(1 for c in fake.calls if c[1] == "/v1/auth/dev-sessions"), 1)
        steps = self.store.list_steps(rcs["b.save"]["id"])
        self.assertEqual(steps[1]["request"]["url"], "https://api.test/v1/rooms/room-9")
        self.assertEqual(steps[1]["request"]["headers"]["Authorization"], "Bearer ***")
        self.assertEqual(steps[0]["request"]["body"], {"postingId": 7})
        # 스냅샷 불변: 케이스 본문이 런에 박혀 있다
        self.assertIn("id: b.save", rcs["b.save"]["case_yaml"])

    def test_cancel_and_events(self):
        httpx.request = FakeHttp({("GET", "/v1/terms"): (200, {"result": "SUCCESS", "data": []})})
        c = self._case("id: t\ntitle: t\nsuite: smoke\nsteps:\n  - request: {method: GET, path: /v1/terms}\n    expect: {status: 200}\n")
        runner = Runner(self.cfg, self.store, {"t": c})
        rid = self.store.create_run(trigger="manual", operator="bebe", suite="smoke", env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=[c, c])
        runner.cancel(rid)
        runner.execute(rid)
        self.assertEqual(self.store.get_run(rid)["verdict"], "canceled")
        self.store.add_event(operator="bebe", action="run.cancel", target=rid, detail={"x": 1}, session_hash="abc", ip="1.2.3.4")
        evs = self.store.list_events(operator="bebe")
        self.assertEqual(evs[0]["action"], "run.cancel")
        self.assertEqual(evs[0]["detail"], {"x": 1})
        self.assertEqual(self.store.list_events(action="nope"), [])


class HermesTest(unittest.TestCase):
    def test_triage_parses_choice(self):
        from qa import hermes
        orig = httpx.request
        seen = {}

        def fake(method, url, headers=None, body=None, timeout=30):
            seen.update(url=url, headers=headers, body=body)
            return httpx.HttpResult(200, {}, json.dumps({"choices": [{"message": {"content": "분류: 케이스 노후\n근거: …"}}]}), 1)

        httpx.request = fake
        try:
            cfg = Config({"HERMES_API_KEY": "k", "HERMES_API_URL": "http://hermes:8642", "QA_DATA_DIR": "/tmp"})
            run = {"trigger": "manual", "base_url": "https://api.test", "sha": None, "pr_number": None}
            rc = {"case_id": "c", "case_title": "t", "verdict": "fail", "error": "e", "case_yaml": "id: c"}
            steps = [{"ord": 0, "name": "s", "verdict": "fail", "request": {"method": "GET", "path": "/x", "headers": {"Authorization": "Bearer ***"}},
                      "response": {"status": 500, "json": {"result": "ERROR"}}, "checks": [], "error": "e"}]
            out = hermes.triage(cfg, run, rc, steps)
            self.assertTrue(out.startswith("분류: 케이스 노후"))
            self.assertEqual(seen["url"], "http://hermes:8642/v1/chat/completions")
            self.assertEqual(seen["headers"]["Authorization"], "Bearer k")
            self.assertEqual(seen["body"]["model"], "gpt-5.5")
            self.assertNotIn("Bearer ***", seen["body"]["messages"][1]["content"].split("요청:")[1].split("\n")[0])
        finally:
            httpx.request = orig

    def test_triage_without_key(self):
        from qa import hermes
        cfg = Config({"QA_DATA_DIR": "/tmp"})
        with self.assertRaises(RuntimeError):
            hermes.triage(cfg, {"trigger": "manual", "base_url": "x"}, {"case_id": "c", "case_title": "t", "verdict": "fail", "case_yaml": ""}, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
