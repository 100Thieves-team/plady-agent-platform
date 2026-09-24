"""표준 unittest. `python3 -m unittest discover -s qa-platform/tests` 또는 `python3 qa-platform/tests/test_core.py`."""
from __future__ import annotations

import json
import os
import sys
import tempfile

import yaml
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import httpx  # noqa: E402
from qa.cases import CaseError, audit, load_dir, parse_one, select  # noqa: E402
from qa.catalog import CatalogService, build, diff, domain_of_path, load_inputs  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.github import domains_from_files  # noqa: E402
from qa.runner import Runner, evaluate  # noqa: E402
from qa.spec import Spec, match_path  # noqa: E402
from qa.store import Store  # noqa: E402
from qa.templating import Context, TemplateError, get_path  # noqa: E402
from qa.wiki import Wiki  # noqa: E402

# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")          # 레포 안의 team-wiki-v2 체크아웃 — 카탈로그 파생 회귀 테스트에 쓴다
SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


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
        self.assertTrue(cases["room.create"].needs_actor())
        self.assertEqual(len(cases["platform.health"].hash), 16)

    def test_validation_errors(self):
        with self.assertRaises(CaseError):
            parse_one("id: Bad_ID\ntitle: x\nsuite: smoke\nsteps: [{request: {method: GET, path: /}}]")
        with self.assertRaises(CaseError):
            parse_one("id: a\ntitle: x\nsuite: nope\nsteps: [{request: {method: GET, path: /}}]")
        with self.assertRaises(CaseError):
            parse_one("id: a\ntitle: x\nsuite: smoke\nsteps: [{request: {method: GET, path: /}, expect: {bogus: 1}}]")
        c = parse_one("id: a\ntitle: x\nsuite: manual\nsteps: [{request: {method: get, path: /}}]")
        self.assertEqual(c.steps[0]["request"]["method"], "GET")
        self.assertEqual(c.steps[0]["name"], "step 1")

    def test_covers_required_and_union(self):
        with self.assertRaises(CaseError):   # smoke 는 covers 필수
            parse_one("id: a\ntitle: x\nsuite: smoke\nsteps: [{request: {method: GET, path: /}}]")
        with self.assertRaises(CaseError):   # 형식
            parse_one("id: a\ntitle: x\nsuite: smoke\ncovers: [room-create]\nsteps: [{request: {method: GET, path: /}}]")
        c = parse_one("id: a\ntitle: x\nsuite: sanity\ncovers: [C.room.create]\nsteps:\n"
                      "  - {covers: ['op.createRoom:200', C.room.create], request: {method: POST, path: /v1/rooms}}\n"
                      "  - {covers: ['G.participation.cancel#participation-joined'], request: {method: POST, path: '/v1/rooms/{{roomId}}/cancellation'}}\n")
        self.assertEqual(c.covers, ["C.room.create", "op.createRoom:200", "G.participation.cancel#participation-joined"])
        m = parse_one("id: a\ntitle: x\nsuite: manual\nsteps: [{request: {method: GET, path: /}}]")
        self.assertEqual(m.covers, [])

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
            "a.pass": self._case("id: a.pass\ntitle: t\nsuite: smoke\ncovers: ['op.memberMe:200']\nactor: qa-host\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/members/me}\n"
                                 "    expect: {status: 200, json: {'data.memberId': '{{actor.qa-host.memberId}}'}}\n"),
            "b.save": self._case("id: b.save\ntitle: t\nsuite: sanity\ncovers: ['op.createRoom:200']\nactor: qa-host\nsteps:\n"
                                 "  - request: {method: POST, path: /v1/rooms, body: {postingId: '{{fixture.postingId}}'}}\n"
                                 "    expect: {status: 200}\n    save: {roomId: data.roomId}\n"
                                 "  - request: {method: GET, path: '/v1/rooms/{{roomId}}'}\n"
                                 "    expect: {status: 200, json: {'data.hostMemberId': '{{actor.qa-host.memberId}}'}}\n"),
            "c.fail": self._case("id: c.fail\ntitle: t\nsuite: smoke\ncovers: ['op.termsList:200']\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/terms}\n    expect: {status: 200, result: SUCCESS}\n"),
            "d.skip": self._case("id: d.skip\ntitle: t\nsuite: smoke\ncovers: ['op.memberMe:200']\nactor: qa-guest\nsteps:\n"
                                 "  - request: {method: GET, path: /v1/members/me}\n    expect: {status: 200}\n"),
            "e.skipfx": self._case("id: e.skipfx\ntitle: t\nsuite: smoke\ncovers: ['OPS.x.y#1']\nsteps:\n"
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
        self.assertIn("테스트 계정 미설정", rcs["d.skip"]["error"])
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
        c = self._case("id: t\ntitle: t\nsuite: smoke\ncovers: ['op.termsList:200']\nsteps:\n  - request: {method: GET, path: /v1/terms}\n    expect: {status: 200}\n")
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


class SpecTest(unittest.TestCase):
    def test_parse_fixture(self):
        sp = Spec("http://unused", Path(tempfile.mkdtemp()), file=str(SPEC_FIXTURE)).get()
        self.assertIsNotNone(sp)
        self.assertEqual(sp.ops["createRoom"].method, "POST")
        self.assertIn("E1402", sp.ops["createRoom"].errors)
        self.assertIn("E1102", sp.ops["memberMe"].errors)          # application/json;charset=UTF-8 도 읽는다
        self.assertEqual(list(sp.ops["submitRoomApplication"].success), ["201"])
        self.assertEqual(sp.op_for("GET", "/v1/rooms/creation-limit").id, "roomCreationLimit")   # 고정 세그먼트 우선
        self.assertEqual(sp.op_for("GET", "/v1/rooms/{{roomId}}").id, "roomDetail")

    def test_match_path(self):
        self.assertTrue(match_path("/v1/rooms/{roomId}/cancellation", "/v1/rooms/{{roomId}}/cancellation"))
        self.assertTrue(match_path("/v1/rooms/{roomId}", "/v1/rooms/abc?x=1"))
        self.assertFalse(match_path("/v1/rooms/{roomId}", "/v1/rooms"))
        self.assertFalse(match_path("/v1/rooms/creation-limit", "/v1/rooms/{{roomId}}"))


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class CatalogTest(unittest.TestCase):
    """실제 team-wiki-v2 체크아웃으로 파생이 되는지 — render_tests.cases() 시그니처가 바뀌면 여기서 먼저 잡힌다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wiki = Wiki(WIKI_DIR)
        self.spec = Spec("http://unused", Path(self.tmp.name) / "catalog", file=str(SPEC_FIXTURE))
        self.svc = CatalogService(wiki=self.wiki, spec=self.spec, catalog_dir=ROOT / "catalog", data_dir=Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_build_and_seed_cases_audit_clean(self):
        cat = self.svc.get(force=True)
        self.assertIsNone(self.svc.last_error)
        c = cat.counts()
        self.assertGreaterEqual(c["by_layer"]["policy"], 200)
        self.assertGreaterEqual(c["by_layer"]["contract"], 20)
        self.assertGreaterEqual(c["by_layer"]["manual"], 1)
        self.assertEqual(len(cat.versions["ssot"]), 12)
        rec = cat.records["G.room.create#duplicate-slot-left"]
        self.assertEqual(rec["domain"], "room")
        # 코드는 SSOT error 가 채워지면 그것이, 비었으면 bindings.checks 가 정본이다 (위키 판에 따라 둘 다 있다)
        self.assertEqual({k: rec["binding"][k] for k in ("operations", "error_code")}, {"operations": ["createRoom"], "error_code": "E1427"})
        self.assertIn(rec["binding"]["error_source"], ("ssot", "bindings"))
        self.assertEqual(rec["prd"][0]["doc"], "룸 생성")
        self.assertTrue(cat.records["C.room.autocancel_not_started"]["excluded"])   # actor: system 제외
        self.assertEqual(cat.records["op.createRoom:E1402"]["expect_hint"]["status"], 400)
        # 시드 케이스 13건은 카탈로그와 어긋나지 않는다
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        audit(cases, cat)
        # 오류(스위트에서 빠짐)는 없어야 한다. 경고는 위키 판에 따라 생길 수 있다
        bad = {cid: c.audit["errors"] for cid, c in cases.items() if c.audit["errors"]}
        self.assertEqual(bad, {})
        self.assertTrue(all(c.covers for c in cases.values() if c.suite != "setup"))   # 준비 작업(setup)은 covers 가 없다
        # 캐시가 남고 같은 입력이면 재계산하지 않는다
        self.assertTrue((Path(self.tmp.name) / "catalog" / "latest.json").is_file())
        self.assertIs(self.svc.get(force=False), cat)

    def test_audit_catches_false_claims(self):
        cat = self.svc.get(force=True)
        cases = {
            "x.ghost": parse_one("id: x.ghost\ntitle: t\nsuite: smoke\ncovers: [G.room.cancel]\nsteps: [{request: {method: GET, path: /v1/terms}}]"),
            "x.wrongcode": parse_one("id: x.wrongcode\ntitle: t\nsuite: smoke\nsteps:\n"
                                     "  - {covers: ['op.cancelRoom:E1410'], request: {method: POST, path: '/v1/rooms/{{r}}/cancellation'}, expect: {status: 409, error_code: E1420}}\n"),
            "x.wrongop": parse_one("id: x.wrongop\ntitle: t\nsuite: smoke\ncovers: ['op.createRoom:200']\nsteps: [{request: {method: GET, path: /v1/terms}, expect: {status: 200}}]"),
            "x.policywarn": parse_one("id: x.policywarn\ntitle: t\nsuite: sanity\ncovers: ['G.room.create#duplicate-slot-left']\nsteps: [{request: {method: POST, path: /v1/rooms}, expect: {status: 409, error_code: E1425}}]"),
            "x.ok": parse_one("id: x.ok\ntitle: t\nsuite: smoke\ncovers: ['op.termsList:200']\nsteps: [{request: {method: GET, path: /v1/terms}, expect: {status: 200}}]"),
        }
        audit(cases, cat)
        self.assertEqual(cases["x.ghost"].audit["status"], "error")
        self.assertIn("카탈로그에 없는 TC G.room.cancel", cases["x.ghost"].audit["errors"][0])
        self.assertEqual(cases["x.wrongcode"].audit["status"], "error")
        self.assertEqual(cases["x.wrongop"].audit["status"], "error")
        self.assertEqual(cases["x.policywarn"].audit["status"], "warn")
        self.assertEqual(cases["x.ok"].audit["status"], "ok")
        self.assertTrue(cases["x.ghost"].blocked)
        self.assertEqual([c.id for c in select(cases, suite="smoke")], ["x.ok"])          # 오류 케이스는 스위트에서 빠진다
        self.assertEqual(len(select(cases, ids=["x.ghost"])), 1)                          # 직접 고르면 들어간다

    def test_key_ids_resolve_on_numeric_catalog(self):
        """위키가 아직 게이트 검사 key 가 없는 판(G.x#5)이어도, key 로 옮긴 스크립트 covers 가 tc-aliases.yaml 로 풀려
        스위트에서 빠지지 않는다. 반대로 key 판 카탈로그에서는 옛 번호 covers 가 별칭으로 풀리고 경고가 붙는다 (docs/policy-ssot-split.md §4.5)."""
        import copy
        wiki = Wiki(WIKI_DIR)
        ssot, h = wiki.read_ssot()
        rt = wiki.render_tests()
        old = copy.deepcopy(ssot)
        for g in old["gates"]:
            for c in g.get("checks") or []:
                if isinstance(c, dict):
                    c.pop("key", None)
        inputs = load_inputs(ROOT / "catalog")
        spec = Spec("", Path(tempfile.mkdtemp()), file=str(SPEC_FIXTURE)).get()
        cat_old = build(ssot=old, ssot_hash="old", rt_mod=rt, spec=spec, inputs=inputs, wiki=wiki)
        self.assertIn("G.room.create#8", cat_old.records)
        self.assertEqual(cat_old.canonical("G.room.create#duplicate-slot-left"), "G.room.create#8")
        cases, _ = load_dir(ROOT / "cases")
        audit(cases, cat_old)
        self.assertEqual({cid: c.audit["errors"] for cid, c in cases.items() if c.audit["errors"]}, {})
        # 바인딩(key 로 옮김)도 번호 카탈로그에서 찾는다
        self.assertEqual(cat_old.records["G.room.create#8"]["binding"]["error_code"], "E1427")
        # key 판 카탈로그 + 옛 번호 covers → 풀리고 경고
        cat_new = build(ssot=ssot, ssot_hash=h, rt_mod=rt, spec=spec, inputs=inputs, wiki=wiki)
        c = parse_one(yaml.safe_dump({"id": "room.legacy", "title": "t", "suite": "sanity", "covers": ["G.room.create#8"],
                                      "steps": [{"request": {"method": "POST", "path": "/v1/rooms"}, "expect": {"status": 409, "error_code": "E1427"}}]}))
        audit({c.id: c}, cat_new)
        self.assertEqual(c.covers, ["G.room.create#duplicate-slot-left"])
        self.assertTrue(any("옛 TC id" in w for w in c.audit["warnings"]))
        # 이름만 바뀐 TC 는 diff 에서 삭제+추가가 아니다
        d = diff(cat_old, cat_new)
        self.assertNotIn("G.room.create#duplicate-slot-left", d["added"])
        self.assertNotIn("G.room.create#8", d["removed"])

    def test_diff_and_drift(self):
        cat = self.svc.get(force=True)
        import copy
        nxt = copy.deepcopy(cat)
        nxt.records["G.room.create#duplicate-slot-left"]["hash"] = "changed"
        del nxt.records["op.termsList:200"]
        nxt.records["op.new:200"] = dict(nxt.records["op.regions:200"], id="op.new:200")
        d = diff(cat, nxt)
        self.assertEqual(d, {"changed": ["G.room.create#duplicate-slot-left"], "added": ["op.new:200"], "removed": ["op.termsList:200"]})
        self.svc.changes = {"G.room.create#duplicate-slot-left": {"at": "2026-09-22T00:00:00Z", "kind": "changed"}}
        self.assertEqual(len(self.svc.drift_for(["G.room.create#duplicate-slot-left", "op.regions:200"], None)), 1)
        self.assertEqual(self.svc.drift_for(["G.room.create#duplicate-slot-left"], "2026-09-23"), [])      # 검토 이후 변경 없음
        self.assertEqual(len(self.svc.drift_for(["G.room.create#duplicate-slot-left"], "2026-09-21")), 1)

    def test_ssot_error_precedes_bindings(self):
        from qa.catalog import build, load_inputs
        ssot, h = self.wiki.read_ssot()
        import copy
        ssot2 = copy.deepcopy(ssot)
        for g in ssot2["gates"]:
            if g["id"] == "G.room.create":
                g["checks"][7]["error"] = "E9999"          # #8 에 SSOT 가 코드를 채운 상황 (bindings 는 E1427)
        cat = build(ssot=ssot2, ssot_hash=h, rt_mod=self.wiki.render_tests(), spec=self.spec.get(), inputs=load_inputs(ROOT / "catalog"), wiki=self.wiki)
        b = cat.records["G.room.create#duplicate-slot-left"]["binding"]
        self.assertEqual((b["error_code"], b["error_source"]), ("E9999", "ssot"))
        self.assertTrue(any("SSOT error E9999" in w for w in cat.warnings))

    def test_wiki_helpers(self):
        self.assertEqual(Wiki.parse_source("PRD/룸 생성 §4.7"), ("룸 생성", "4.7"))
        self.assertIsNone(Wiki.parse_source("DEC-003"))
        sec = self.wiki.prd_section("룸 생성", "4.7")
        self.assertTrue(sec.startswith("### 4.7"))
        self.assertIn("3개", sec)
        self.assertIsNone(self.wiki.prd_section("룸 생성", "99.9"))
        self.assertEqual(domain_of_path("/v1/rooms/{roomId}/applications/me"), "application")
        self.assertEqual(domain_of_path("/v1/members/me/resumes/{id}"), "resume")


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class DraftsTest(unittest.TestCase):
    """Hermes 초안 — 근거 조립·출력 파싱·결정론 검증 (docs/qa-platform-tc.md §7)."""

    GOOD = """```yaml
cases:
  - id: room.create-limit-reject
    title: 활성 룸이 3개면 네 번째 생성은 E1427 로 거절된다
    suite: sanity
    domains: [room]
    actor: qa-host
    covers: ["G.room.create#duplicate-slot-left"]
    steps:
      - name: 4번째 생성
        covers: ["G.room.create#duplicate-slot-left"]
        request: { method: POST, path: /v1/rooms, body: { postingId: "{{fixture.postingId}}", title: "[QA] x" } }
        expect: { status: 409, error_code: E1427 }
```"""

    def setUp(self):
        from qa import drafts
        self.drafts = drafts
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config({"QA_DATA_DIR": self.tmp.name, "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_FIXTURES": json.dumps({"postingId": 1}),
                           "HERMES_API_KEY": "k", "HERMES_API_URL": "http://hermes:8642"})
        self.wiki = Wiki(WIKI_DIR)
        self.spec = Spec("http://unused", Path(self.tmp.name) / "catalog", file=str(SPEC_FIXTURE))
        self.svc = CatalogService(wiki=self.wiki, spec=self.spec, catalog_dir=ROOT / "catalog", data_dir=Path(self.tmp.name))
        self.cat = self.svc.get(force=True)
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_assemble_contains_evidence_only(self):
        text, h = self.drafts.assemble(cfg=self.cfg, catalog=self.cat, spec=self.spec.get(), wiki=self.wiki, tc_ids=["G.room.create#duplicate-slot-left", "op.createRoom:E1402"], example=None)
        self.assertEqual(len(h), 12)
        self.assertIn("G.room.create#duplicate-slot-left", text)
        self.assertIn("must_pass_first", text)
        self.assertIn('"operationId": "createRoom"', text)
        self.assertIn("### 4.7", text)                       # PRD 절 본문이 들어간다
        self.assertIn("qa-host", text)
        self.assertNotIn("m1", text)                          # 회원 UUID 는 넣지 않는다
        text2, h2 = self.drafts.assemble(cfg=self.cfg, catalog=self.cat, spec=self.spec.get(), wiki=self.wiki, tc_ids=["G.room.create#duplicate-slot-left", "op.createRoom:E1402"], example=None)
        self.assertEqual(h, h2)                               # 같은 근거 → 같은 해시

    def test_parse_and_validate(self):
        items = self.drafts.parse_output(self.GOOD)
        self.assertEqual(len(items), 1)
        case, errors, warnings = self.drafts.validate(items[0], requested=["G.room.create#duplicate-slot-left"], catalog=self.cat, cfg=self.cfg, existing_ids=set())
        self.assertIsNotNone(case)
        self.assertEqual(errors, [])
        self.assertTrue(any("정리" in w for w in warnings))    # 쓰기인데 정리 단계 없음 → 경고
        # covers 가 요청 밖이면 버린다
        bad = dict(items[0], covers=["G.room.create#participation-slot-left"])
        bad["steps"] = [dict(bad["steps"][0], covers=["G.room.create#participation-slot-left"])]
        case, errors, _ = self.drafts.validate(bad, requested=["G.room.create#duplicate-slot-left"], catalog=self.cat, cfg=self.cfg, existing_ids=set())
        self.assertIsNone(case)
        self.assertIn("요청하지 않은", errors[0])
        # 없는 테스트 계정 → 버린다
        bad = dict(items[0], actor="qa-nobody")
        case, errors, _ = self.drafts.validate(bad, requested=["G.room.create#duplicate-slot-left"], catalog=self.cat, cfg=self.cfg, existing_ids=set())
        self.assertIsNone(case)
        self.assertTrue(any("테스트 계정" in x for x in errors))
        # 계약 TC 를 덮는다면서 코드가 다르면 버린다
        bad = dict(items[0], covers=["op.createRoom:E1402"])
        bad["steps"] = [dict(bad["steps"][0], covers=["op.createRoom:E1402"])]
        case, errors, _ = self.drafts.validate(bad, requested=["op.createRoom:E1402"], catalog=self.cat, cfg=self.cfg, existing_ids=set())
        self.assertIsNone(case)
        # 기존 id 와 겹치면 -2 접미
        case, errors, warnings = self.drafts.validate(items[0], requested=["G.room.create#duplicate-slot-left"], catalog=self.cat, cfg=self.cfg, existing_ids={"room.create-limit-reject"})
        self.assertEqual(case.id, "room.create-limit-reject-2")

    def test_generate_flow_with_fake_hermes(self):
        seen = {}

        def fake(method, url, headers=None, body=None, timeout=30):
            seen.update(url=url, body=body, timeout=timeout)
            content = self.GOOD + "\n```yaml\ncases:\n  - id: junk\n    title: t\n    suite: smoke\n    covers: [C.room.create]\n    steps: [{request: {method: GET, path: /nope}}]\n```"
            return httpx.HttpResult(200, {}, json.dumps({"choices": [{"message": {"content": content}}]}), 1)

        httpx.request = fake
        res = self.drafts.generate(cfg=self.cfg, catalog=self.cat, spec=self.spec.get(), wiki=self.wiki, tc_ids=["G.room.create#duplicate-slot-left"], example=None, existing_ids=set())
        self.assertEqual(seen["url"], "http://hermes:8642/v1/chat/completions")
        self.assertEqual(seen["body"]["messages"][0]["content"][:20], self.drafts.DRAFT_SYSTEM[:20])
        self.assertGreaterEqual(seen["timeout"], 180)
        self.assertEqual([c.id for c, _ in res["accepted"]], ["room.create-limit-reject"])
        self.assertEqual([r for r, _ in res["rejected"]], ["junk"])           # 요청 밖 TC → 버림
        # 케이스 초안에 넣고 다시 읽는다 (열 추가 마이그레이션 포함)
        st = Store(Path(self.tmp.name) / "qa.sqlite")
        c, w = res["accepted"][0]
        did = st.add_draft(operator="bebe", source="hermes", domain="room", yaml_text=c.to_yaml(), note=None, case_id=c.id, tc_ids=c.covers,
                           validation={"status": "warn", "warnings": w}, prompt_hash=res["prompt_hash"])
        d = st.get_draft(did)
        self.assertEqual(d["tc_ids"], ["G.room.create#duplicate-slot-left"])
        self.assertEqual(d["validation"]["status"], "warn")
        st.update_draft(did, status="approved", decided_by="bebe")
        self.assertEqual(st.draft_counts(), {"approved": 1})


class ReminderTest(unittest.TestCase):
    def test_due_and_once_per_sprint(self):
        from qa.reminder import Reminder, due
        tmp = tempfile.TemporaryDirectory()
        cfg = Config({"QA_DATA_DIR": tmp.name, "WIKI_SLACK_WEBHOOK_URL": "http://hook"})
        store = Store(cfg.db_path)
        sent = []
        r = Reminder(cfg, store, sent.append)
        sprint = cfg.current_sprint(datetime(2026, 9, 25, tzinfo=timezone.utc))      # Cycle 10: 9/20 15:00Z ~ 9/27 15:00Z
        self.assertFalse(due(datetime(2026, 9, 25, tzinfo=timezone.utc), sprint, 0, False, 1))   # 마감 이틀 전 → 아직
        self.assertTrue(due(datetime(2026, 9, 26, 16, tzinfo=timezone.utc), sprint, 0, False, 1))
        self.assertFalse(due(datetime(2026, 9, 26, 16, tzinfo=timezone.utc), sprint, 1, False, 1))   # smoke 있으면 조용
        self.assertFalse(r.tick(datetime(2026, 9, 25, tzinfo=timezone.utc)))
        self.assertTrue(r.tick(datetime(2026, 9, 26, 16, tzinfo=timezone.utc)))
        self.assertFalse(r.tick(datetime(2026, 9, 27, 1, tzinfo=timezone.utc)))                    # 스프린트당 한 번
        self.assertEqual(len(sent), 1)
        self.assertIn("Cycle 10", sent[0])
        self.assertEqual(store.list_events(action="sprint.remind")[0]["operator"], "system")
        off = Reminder(Config({"QA_DATA_DIR": tmp.name, "QA_SPRINT_REMINDER": "0"}), store, sent.append)
        off.start()
        self.assertFalse(off._thread.is_alive())
        tmp.cleanup()


class McpAndReportTest(unittest.TestCase):
    def test_mcp_client_sse_and_session(self):
        from qa.mcp import McpClient, McpError, wiki_apply
        orig = httpx.request
        calls = []

        def fake(method, url, headers=None, body=None, timeout=30):
            calls.append((headers, body))
            if body.get("method") == "initialize":
                return httpx.HttpResult(200, {"Content-Type": "text/event-stream", "Mcp-Session-Id": "s-1"},
                                        'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"llm-wiki"}}}\n\n', 1)
            if body.get("method") == "notifications/initialized":
                return httpx.HttpResult(202, {}, "", 1)
            self.assertEqual(headers["Mcp-Session-Id"], "s-1")          # 세션이 이어진다
            self.assertEqual(headers["Authorization"], "Bearer tok")
            args = body["params"]["arguments"]
            self.assertEqual(args["mode"], "generated")
            self.assertEqual(args["changes"][0]["path"], "qa/2026-W39-sprint-smoke")
            return httpx.HttpResult(200, {"Content-Type": "application/json"},
                                    json.dumps({"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "{\"head\":\"abc\",\"written\":1}"}]}}), 1)

        httpx.request = fake
        try:
            c = McpClient("http://mcp-proxy:18765/mcp", "tok")
            res = wiki_apply(c, path="qa/2026-W39-sprint-smoke", content="---\nmanaged_by: harness\n---\n# x", message="m")
            self.assertEqual(res, {"head": "abc", "written": 1})
            self.assertEqual([b.get("method") for _, b in calls], ["initialize", "notifications/initialized", "tools/call"])
            # 도구 오류는 예외로
            httpx.request = lambda *a, **k: httpx.HttpResult(200, {"Content-Type": "application/json"},
                                                             json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [{"type": "text", "text": "mode `generated` is for harness output"}]}}), 1)
            with self.assertRaises(McpError):
                c.call_tool("wiki_apply", {})
        finally:
            httpx.request = orig

    def test_report_masks_ids_and_has_frontmatter(self):
        from qa import report
        run = {"id": "r-20260921-100000-ab12", "created_at": "2026-09-21T01:00:00Z", "trigger": "sprint-smoke", "operator": "bebe",
               "base_url": "https://api.test", "sha": None, "pr_number": None, "status": "finished", "verdict": "fail",
               "passed": 9, "failed": 1, "errored": 0, "skipped": 0, "total": 10,
               "meta": {"catalog": {"ssot": "4bc51d05edce", "openapi": "e07e0cdb698b"}}}
        rcs = [{"case_id": "member.me", "case_title": "t", "case_suite": "smoke", "verdict": "fail",
                "error": "json(data.memberId) 기대 '88dd1cac-1234-5678-9abc-def012345678' 실제 None", "triage": "분류: 환경"}]
        md = report.render(run, rcs, coverage=None, catalog=None, public_url="https://qa.agent.plady.io", sprint={"number": 10})
        self.assertTrue(md.startswith("---\n"))
        self.assertIn("managed_by: harness", md)
        self.assertNotIn("88dd1cac-1234-5678-9abc-def012345678", md)
        self.assertIn("88dd1cac-…", md)
        self.assertIn("Cycle 10", md)
        self.assertIn("분류: 환경", md)
        self.assertEqual(report.slug_for(run), "qa/2026-W39-sprint-smoke")


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
