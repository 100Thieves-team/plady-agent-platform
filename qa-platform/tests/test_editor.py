"""폼으로 스크립트·수동 테스트 조건 만들기·고치기·지우기 (docs/qa-platform-editor.md, 사용자 요청 2026-09-23).

폼 상태 ⇄ YAML 왕복, 파일에서 항목 하나만 바꾸기, 사람 검증, 승인 → main 커밋(가짜 GitHub Contents API) → 플랫폼 즉시 반영,
삭제 요청, 수동 테스트 조건 번호 매기기, 본문 스키마 경고, 화면 라우트.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as appmod  # noqa: E402
from app import App, BadRequest  # noqa: E402
from qa import editor, httpx, ui  # noqa: E402
from qa.cases import _validate  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.repo import RepoError, append_item, ids_in, item_spans, replace_item  # noqa: E402
from qa.spec import SpecData, parse  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
HAS_WIKI = (WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file()

SAMPLE = """# 머리 주석
cases:
  - id: a.one
    title: 하나
    suite: smoke
    steps: [{request: {method: GET, path: /x}}]

  # 둘째 항목 설명 주석
  - id: a.two
    title: 둘
    suite: smoke
    steps: [{request: {method: GET, path: /y}}]
"""


class SpliceTest(unittest.TestCase):
    def test_spans_and_ids(self):
        self.assertEqual(ids_in(SAMPLE), ["a.one", "a.two"])
        (s1, e1, _), (s2, _, _) = item_spans(SAMPLE)
        self.assertLess(e1, s2)

    def test_replace_keeps_other_items_and_comments(self):
        out = replace_item(SAMPLE, "a.one", {"id": "a.one", "title": "하나(고침)", "suite": "smoke", "steps": [{"request": {"method": "GET", "path": "/x"}}]})
        self.assertIn("# 머리 주석", out)
        self.assertIn("# 둘째 항목 설명 주석", out)
        self.assertIn("하나(고침)", out)
        self.assertEqual(out.split("# 둘째")[1], SAMPLE.split("# 둘째")[1])
        self.assertEqual([c["title"] for c in yaml.safe_load(out)["cases"]], ["하나(고침)", "둘"])

    def test_delete_and_delete_last(self):
        out = replace_item(SAMPLE, "a.two", None)
        self.assertEqual(ids_in(out), ["a.one"])
        self.assertNotIn("둘", yaml.safe_dump(yaml.safe_load(out), allow_unicode=True))
        out = replace_item(out, "a.one", None)
        self.assertEqual(yaml.safe_load(out)["cases"], [])

    def test_append_and_missing(self):
        out = append_item(SAMPLE, {"id": "a.three", "title": "셋", "suite": "smoke", "steps": [{"request": {"method": "GET", "path": "/z"}}]})
        self.assertEqual(ids_in(out), ["a.one", "a.two", "a.three"])
        self.assertTrue(out.startswith(SAMPLE))
        self.assertEqual(ids_in(append_item(None, {"id": "b", "title": "t"})), ["b"])
        self.assertEqual(ids_in(append_item("cases: []\n", {"id": "b", "title": "t"})), ["b"])
        with self.assertRaises(RepoError):
            replace_item(SAMPLE, "nope", None)

    def test_manual_tc_ids_with_hash(self):
        text = (ROOT / "catalog" / "manual-tc.yaml").read_text(encoding="utf-8")
        ids = ids_in(text)
        self.assertIn("PRD.룸-탐색.4.1#1", ids)
        self.assertEqual(ids, [c["id"] for c in yaml.safe_load(text)["cases"]])

    def test_real_case_files_roundtrip_every_item(self):
        for f in sorted((ROOT / "cases").glob("*.yaml")):
            text = f.read_text(encoding="utf-8")
            raw = yaml.safe_load(text)["cases"]
            self.assertEqual(ids_in(text), [c["id"] for c in raw], f.name)
            for c in raw:        # 같은 값으로 바꿔 끼워도 파일 전체 의미가 같다
                again = yaml.safe_load(replace_item(text, c["id"], c))["cases"]
                self.assertEqual(again, raw, f"{f.name}:{c['id']}")


class StateTest(unittest.TestCase):
    def test_cells(self):
        for v in ("RECRUITING", 200, True, None, "200", "{{roomId}}", 1.5, "", "a b"):
            self.assertEqual(editor.cell_to_value(editor.value_to_cell(v)), v, repr(v))

    def test_roundtrip_all_repo_cases(self):
        from qa.cases import load_dir
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        for c in cases.values():
            raw = yaml.safe_load(c.to_yaml())
            self.assertEqual(editor.unsupported(raw), [], c.id)
            back = editor.from_state(json.loads(json.dumps(editor.to_state(raw))))
            back["operations"] = raw.get("operations") or []
            a, b = _validate(back, "x"), _validate(yaml.safe_load(c.to_yaml()), "y")
            self.assertEqual(a.steps, b.steps, c.id)
            self.assertEqual(sorted(a.covers), sorted(b.covers), c.id)
            self.assertEqual((a.inputs, a.outputs, a.actor, a.suite, a.title), (b.inputs, b.outputs, b.actor, b.suite, b.title), c.id)

    def test_form_errors(self):
        st = editor.to_state({"id": "x.y", "title": "t", "suite": "smoke", "steps": [{"request": {"method": "POST", "path": "/v1/x"}}]})
        st["steps"][0]["body"] = "{not json"
        with self.assertRaises(editor.FormError):
            editor.from_state(st)
        st["steps"][0]["body"] = ""
        st["steps"][0]["expect"]["status"] = "abc"
        with self.assertRaises(editor.FormError):
            editor.from_state(st)

    def test_unsupported_keys(self):
        self.assertTrue(editor.unsupported({"id": "a", "weird": 1, "steps": [{"request": {"method": "GET", "path": "/", "headers": {}}}]}))


MINI_SPEC = {
    "paths": {"/v1/rooms": {"post": {"operationId": "createRoom", "summary": "룸 생성", "requestBody": {"content": {"application/json": {
        "schema": {"$ref": "#/components/schemas/Create"},
        "examples": {"ok": {"value": json.dumps({"postingId": 1, "method": "OFFLINE", "sigunguId": 1, "title": "t"})}}}}},
        "responses": {"200": {"description": "ok"}}}}},
    "components": {"schemas": {"Create": {"type": "object", "required": ["postingId", "method", "title"], "properties": {
        "title": {"type": "string", "description": "룸 제목"},
        "sigunguId": {"type": "number", "description": "지역 시군구 id (OFFLINE 일 때, /v1/regions)", "nullable": True},
        "method": {"type": "string", "description": "진행 방식 (ONLINE | OFFLINE)"},
        "postingId": {"type": "number", "description": "공고 id"},
        "schedule": {"type": "object", "properties": {"date": {"type": "string"}}}}}}},
}


class BodySchemaTest(unittest.TestCase):
    def setUp(self):
        self.spec = SpecData(hash="h", ops=parse(MINI_SPEC), fetched_at=0, source="file")

    def test_fields(self):
        fs = self.spec.ops["createRoom"].body_fields
        self.assertEqual([f["name"] for f in fs][:4], ["postingId", "method", "sigunguId", "title"])     # 예시 키 순서
        by = {f["name"]: f for f in fs}
        self.assertEqual(by["method"]["enum"], ["ONLINE", "OFFLINE"])
        self.assertTrue(by["postingId"]["required"])
        self.assertFalse(by["sigunguId"]["required"])
        self.assertEqual([x["name"] for x in by["schedule"]["fields"]], ["date"])

    def test_conditional_field_warning(self):
        """2026-09-23 r-20260923-090724-c90e: ONLINE 룸 본문에 sigunguId → E400. 폼이 저장 전에 경고한다."""
        raw = {"steps": [{"request": {"method": "POST", "path": "/v1/rooms", "body": {"postingId": 1, "method": "ONLINE", "sigunguId": 1, "title": "t"}}}]}
        w = editor.body_warnings(raw, self.spec)
        self.assertEqual(len(w), 1)
        self.assertIn("sigunguId", w[0])
        self.assertIn("OFFLINE", w[0])
        raw["steps"][0]["request"]["body"]["method"] = "OFFLINE"
        self.assertEqual(editor.body_warnings(raw, self.spec), [])
        raw["steps"][0]["request"]["body"] = {"method": "OFFLINE", "extra": 1}
        w = editor.body_warnings(raw, self.spec)
        self.assertTrue(any("postingId" in x for x in w) and any("extra" in x for x in w))


class FakeGitHub:
    """GitHub Contents API 흉내 — qa-platform/cases/*.yaml · catalog/*.yaml 을 메모리에 둔다."""

    def __init__(self):
        self.files = {f"qa-platform/{d}/{p.name}": p.read_text(encoding="utf-8") for d in ("cases", "catalog") for p in (ROOT / d).glob("*.yaml")}
        self.puts: list[dict] = []
        self.sha = 0

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        if not url.startswith("https://api.github.com/"):
            return httpx.HttpResult(0, {}, "", 1, error="offline")
        assert url.isascii(), f"URL 에 인코딩 안 된 글자가 있다: {url}"      # 실제 urllib 은 여기서 UnicodeEncodeError (2026-09-24 룸-방명록.yaml)
        from urllib.parse import unquote
        path = unquote(url.split("/contents/", 1)[1].split("?")[0])
        if method == "GET":
            if path in self.files:
                return httpx.HttpResult(200, {}, json.dumps({"content": base64.b64encode(self.files[path].encode()).decode(), "sha": f"blob-{path}"}), 1)
            kids = [{"name": k.rsplit("/", 1)[1], "type": "file"} for k in self.files if k.rsplit("/", 1)[0] == path]
            return httpx.HttpResult(200, {}, json.dumps(kids), 1) if kids else httpx.HttpResult(404, {}, '{"message":"Not Found"}', 1)
        if method == "PUT":
            self.sha += 1
            self.files[path] = base64.b64decode(body["content"]).decode()
            self.puts.append({"path": path, **body})
            return httpx.HttpResult(200, {}, json.dumps({"commit": {"sha": f"c{self.sha:040d}", "html_url": f"https://github.com/x/commit/{self.sha}"}}), 1)
        return httpx.HttpResult(405, {}, "", 1)


def make_app(tmp, *, token=True):
    env = {"QA_DATA_DIR": tmp, "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_WIKI_DIR": str(WIKI_DIR), "HERMES_API_KEY": "k",
           "QA_ACTORS": json.dumps({"qa-host": "m1", "qa-guest": "m2"}), "QA_FIXTURES": json.dumps({"postingId": 1, "jobRoleId": 1, "qa-host.resumeId": "r1", "qa-guest.resumeId": "r2"})}
    if token:
        env["QA_REPO_TOKEN"] = "t"
    return App(Config(env))


SMOKE_STATE = {"id": "room.form-options-again", "title": "폼 선택지를 한 번 더 본다", "suite": "smoke", "description": "", "domains": ["room"], "source": [],
               "actor": "", "covers": ["op.roomFormOptions:200"], "inputs": [], "outputs": [],
               "steps": [{"name": "폼 선택지", "actor": "", "covers": [], "method": "GET", "path": "/v1/rooms/form-options", "query": [], "body": "",
                          "expect": {"status": "200", "result": "SUCCESS", "error_code": "", "json": [], "exists": []}, "save": []}]}


@unittest.skipUnless(HAS_WIKI, "wiki-workspace 체크아웃 없음")
class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        httpx.request = self.gh
        self.app = make_app(self.tmp.name)

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_synced_from_main(self):
        self.assertTrue(self.app.repo.synced)
        self.assertEqual(self.app.cases_dir, self.app.repo.local / "cases")
        self.assertIn("room.explore", self.app.cases)

    def test_new_script_saves_commits_and_applies(self):
        """초안·승인 없이 저장이 곧 main 커밋 (docs/qa-platform-scenarios.md §9)."""
        res = self.app.form_case(json.loads(json.dumps(SMOKE_STATE)), mode="new", original_id=None, draft_id=None, operator="dbwp031")
        self.assertTrue(res["ok"], res)
        self.assertTrue(res["commit"]["sha"].startswith("c"))
        d = self.app.store.get_draft(res["id"])
        self.assertEqual((d["source"], d["case_id"], d["kind"], d["status"]), ("form", "room.form-options-again", "case", "approved"))
        put = self.gh.puts[-1]
        self.assertEqual(put["path"], "qa-platform/cases/room.yaml")
        self.assertEqual(put["branch"], "main")
        self.assertIn("[skip ci]", put["message"])
        self.assertIn("room.form-options-again 추가", put["message"])
        self.assertIn("QA-Operator: dbwp031", put["message"])
        new = self.gh.files["qa-platform/cases/room.yaml"]
        self.assertTrue(new.startswith((ROOT / "cases" / "room.yaml").read_text(encoding="utf-8").rstrip("\n")))
        self.assertIn("room.form-options-again", self.app.cases)                       # 플랫폼에 바로
        self.assertEqual(self.app.cases["room.form-options-again"].reviewed["by"], "dbwp031")
        self.assertNotIn("written_by", self.app.cases["room.form-options-again"].raw)
        self.assertEqual(d["file"], "cases/room.yaml")
        self.assertEqual(self.app.change_link(res)["href"], "/cases/room.form-options-again")
        acts = [e["action"] for e in self.app.store.list_events(10)]
        self.assertIn("case.save", acts)

    def test_new_script_validation_blocks_save(self):
        st = json.loads(json.dumps(SMOKE_STATE))
        st["covers"] = []
        res = self.app.form_case(st, mode="new", original_id=None, draft_id=None, operator="bebe")
        self.assertFalse(res["ok"])
        self.assertTrue(any("covers" in x for x in res["errors"]))
        st = json.loads(json.dumps(SMOKE_STATE))
        st["id"] = "room.explore"
        self.assertTrue(any("이미 있는" in x for x in self.app.form_case(st, mode="new", original_id=None, draft_id=None, operator="bebe")["errors"]))
        st = json.loads(json.dumps(SMOKE_STATE))
        st["actor"] = "nobody"
        self.assertTrue(any("nobody" in x for x in self.app.form_case(st, mode="new", original_id=None, draft_id=None, operator="bebe")["errors"]))
        self.assertEqual(self.app.store.list_drafts(), [])
        self.assertEqual(self.gh.puts, [])
        with self.assertRaises(BadRequest):
            self.app.form_case(json.loads(json.dumps(SMOKE_STATE)), mode="new", original_id=None, draft_id=None, operator="누구")

    def test_edit_replaces_only_that_item(self):
        before = self.gh.files["qa-platform/cases/room.yaml"]
        st = editor.to_state(yaml.safe_load(self.app.cases["room.explore"].to_yaml()))
        st["title"] = "비로그인으로 모집 중인 룸을 탐색한다 (폼으로 고침)"
        bad = dict(st, id="room.explore2")
        self.assertIn("바꿀 수 없다", self.app.form_case(bad, mode="edit", original_id="room.explore", draft_id=None, operator="bebe")["errors"][0])
        res = self.app.form_case(st, mode="edit", original_id="room.explore", draft_id=None, operator="bebe")
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.app.store.get_draft(res["id"])["source"], "form-edit")
        after = self.gh.files["qa-platform/cases/room.yaml"]
        self.assertIn("(폼으로 고침)", after)
        self.assertEqual(after.split("  - id: room.create\n")[1], before.split("  - id: room.create\n")[1])
        self.assertTrue(after.startswith(before.split("  - id: room.explore")[0]))
        self.assertIn("room.explore 수정", self.gh.puts[-1]["message"])
        self.assertEqual(self.app.cases["room.explore"].title, st["title"])
        self.assertEqual([c["id"] for c in self.app.store.list_changes(case_id="room.explore")], [res["id"]])

    def test_hermes_mark_is_removed_by_form_save(self):
        """Hermes 가 저장한 것은 written_by: hermes. 사람이 폼으로 한 번 저장하면 뗀다."""
        raw = dict(editor.from_state(SMOKE_STATE))
        out = self.app.save_change(kind="case", source="hermes", yaml_text=yaml.safe_dump(raw, allow_unicode=True), operator="bebe",
                                   case_id=raw["id"], tc_ids=["op.roomFormOptions:200"])
        self.assertTrue(out["commit"])
        self.assertEqual(self.app.cases["room.form-options-again"].raw.get("written_by"), "hermes")
        self.assertIn("Hermes 작성", ui.hermes_badge(self.app.cases["room.form-options-again"].raw))
        st = editor.to_state(self.app.cases["room.form-options-again"].raw)
        st["title"] = "사람이 본 제목"
        res = self.app.form_case(st, mode="edit", original_id="room.form-options-again", draft_id=None, operator="bebe")
        self.assertTrue(res["ok"], res)
        self.assertNotIn("written_by", self.app.cases["room.form-options-again"].raw)
        self.assertNotIn("written_by", self.gh.files["qa-platform/cases/room.yaml"])

    def test_form_saves_unsaved_draft(self):
        """API 호출 화면에서 담은 것(저장 안 된 변경 기록)을 폼으로 열어 저장하면 그 기록이 저장됨이 된다."""
        did = self.app.store.add_draft(operator="bebe", source="explorer", domain="room", yaml_text=yaml.safe_dump(dict(editor.from_state(SMOKE_STATE))), note=None,
                                       case_id="room.form-options-again", tc_ids=["op.roomFormOptions:200"])
        st = json.loads(json.dumps(SMOKE_STATE))
        st["title"] = "사람이 고친 제목"
        res = self.app.form_case(st, mode="draft", original_id=None, draft_id=did, operator="bebe")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["id"], did)
        d = self.app.store.get_draft(did)
        self.assertEqual((d["status"], d["source"]), ("approved", "form"))
        self.assertIn("사람이 고친 제목", d["yaml"])
        self.assertEqual(self.app.cases["room.form-options-again"].title, "사람이 고친 제목")
        with self.assertRaises(BadRequest):          # 저장한 것은 다시 안 연다
            self.app.form_case(st, mode="draft", original_id=None, draft_id=did, operator="bebe")

    def test_delete_is_immediate(self):
        out = self.app.delete_item(what="case", target="room.explore", reason="중복", operator="dbwp031")
        d = self.app.store.get_draft(out["id"])
        self.assertEqual((d["kind"], d["note"], d["status"]), ("case-delete", "중복", "approved"))
        self.assertNotIn("room.explore", self.app.cases)
        self.assertNotIn("id: room.explore\n", self.gh.files["qa-platform/cases/room.yaml"])
        self.assertIn("room.explore 삭제", self.gh.puts[-1]["message"])
        self.assertIn("메모: 중복", self.gh.puts[-1]["message"])
        self.app.delete_item(what="case", target="room.creation-limit", operator="bebe")          # 사유는 선택
        self.assertNotIn("room.creation-limit", self.app.cases)
        with self.assertRaises(BadRequest):
            self.app.delete_item(what="case", target="room.nope", operator="bebe")

    def test_manual_tc_add_edit_delete(self):
        with self.assertRaises(BadRequest):      # 검증하는 스크립트가 있으면 막는다
            self.app.delete_item(what="tc", target="PRD.룸-탐색.4.1#1", reason="x", operator="bebe")
        with self.assertRaises(BadRequest):      # 규칙·계약 TC 는 폼으로 안 고친다
            self.app.form_tc({"title": "x", "when": "w", "then": "t"}, tc_id="op.roomFormOptions:200", operator="bebe")
        out = self.app.form_tc({"tc_kind": "prd", "doc": "룸 탐색", "section": "4.1", "domain": "room", "title": "필터 없이 조회한다",
                                "when": "GET /v1/rooms", "then": "200", "operations": "rooms"}, tc_id=None, operator="bebe")
        self.assertEqual(out["kind"], "tc")
        new_id = out["tc_ids"][0]
        self.assertTrue(new_id.startswith("PRD.룸-탐색.4.1#"))
        self.assertNotEqual(new_id, "PRD.룸-탐색.4.1#1")
        self.assertIn(new_id, ids_in(self.gh.files["qa-platform/catalog/manual-tc.yaml"]))
        self.assertIn(new_id, self.app.current_catalog().records)
        self.assertEqual(self.app.change_link(out)["href"], "/catalog/tc?id=" + quote(new_id, safe=""))
        # 예전 방식으로 남은 초안(같은 번호)은 저장 때 다음 번호로
        dup = self.app.store.add_draft(operator="bebe", source="hermes-propose", domain="room", note=None, case_id=None, tc_ids=[new_id], kind="tc",
                                       yaml_text=yaml.safe_dump({"cases": [{"id": new_id, "doc": "룸 탐색", "section": "4.1", "domain": "room", "title": "또", "when": "w", "then": "t"}]}, allow_unicode=True))
        self.app.approve_draft(self.app.store.get_draft(dup), operator="bebe", note=None)
        n = int(new_id.rsplit("#", 1)[1])
        self.assertEqual(self.app.store.get_draft(dup)["tc_ids"], [f"PRD.룸-탐색.4.1#{n + 1}"])
        self.assertIn("written_by: hermes", self.gh.files["qa-platform/catalog/manual-tc.yaml"])
        # 고치기 → 지우기
        self.app.form_tc({"domain": "room", "title": "필터 없이 조회한다 (고침)", "when": "GET /v1/rooms", "then": "200"}, tc_id=new_id, operator="bebe")
        self.assertEqual(self.app.current_catalog().records[new_id]["title"], "필터 없이 조회한다 (고침)")
        self.app.delete_item(what="tc", target=new_id, operator="bebe")
        self.assertNotIn(new_id, self.app.current_catalog().records)

    def test_conflict_is_reported(self):
        orig = self.gh.__call__

        def conflict(method, url, **kw):
            if method == "PUT":
                return httpx.HttpResult(409, {}, '{"message":"sha mismatch"}', 1)
            return orig(method, url, **kw)
        httpx.request = conflict
        with self.assertRaises(BadRequest) as cm:
            self.app.form_case(json.loads(json.dumps(SMOKE_STATE)), mode="new", original_id=None, draft_id=None, operator="bebe")
        self.assertIn("그사이 바뀌었다", str(cm.exception))
        d = self.app.store.list_drafts()[0]
        self.assertEqual(d["status"], "failed")
        self.assertNotIn("room.form-options-again", self.app.cases)
        httpx.request = self.gh                                   # 다시 저장하면 된다
        self.assertTrue(self.app.approve_draft(self.app.store.get_draft(d["id"]), operator="bebe", note=None)["commit"])
        self.assertIn("room.form-options-again", self.app.cases)


@unittest.skipUnless(HAS_WIKI, "wiki-workspace 체크아웃 없음")
class NoTokenTest(unittest.TestCase):
    def test_save_without_token_offers_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = make_app(tmp, token=False)
            self.assertFalse(app.repo.enabled)
            res = app.form_case(json.loads(json.dumps(SMOKE_STATE)), mode="new", original_id=None, draft_id=None, operator="bebe")
            self.assertIsNone(res["commit"])
            d = app.store.get_draft(res["id"])
            self.assertEqual(d["status"], "approved")
            self.assertIsNone(d["commit_sha"])
            self.assertEqual(app.change_link(res)["href"], f"/drafts/{d['id']}")
            rel, text = app.draft_file(d, "bebe")
            self.assertEqual(rel, "cases/room.yaml")
            self.assertIn("room.form-options-again", ids_in(text))


@unittest.skipUnless(HAS_WIKI, "wiki-workspace 체크아웃 없음")
class RouteTest(unittest.TestCase):
    """실제 HTTP 서버로 화면·API 를 부른다."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.orig = httpx.request
        cls.gh = FakeGitHub()
        httpx.request = cls.gh
        cls.app = make_app(cls.tmp.name)
        appmod.Handler.app = cls.app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        httpx.request = cls.orig
        cls.tmp.cleanup()

    def get(self, path, accept="text/html"):
        req = urllib.request.Request(self.base + path, headers={"Cookie": "qa_operator=bebe", "Accept": accept})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()

    def post(self, path, data: dict, *, json_body=False):
        body = json.dumps(data).encode() if json_body else "&".join(f"{k}={quote(str(v))}" for k, v in data.items()).encode()
        req = urllib.request.Request(self.base + path, data=body, method="POST",
                                     headers={"Cookie": "qa_operator=bebe", "Content-Type": "application/json" if json_body else "application/x-www-form-urlencoded",
                                              "Accept": "application/json" if json_body else "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read().decode()

    def test_pages(self):
        for path in ("/cases/new", "/cases/new?tc=op.roomFormOptions:200", "/cases/room.explore/edit", "/catalog/manual/new",
                     "/catalog/tc/edit?id=" + quote("PRD.룸-탐색.4.1#1"), "/cases", "/cases/room.explore", "/catalog/tc?id=op.roomFormOptions:200", "/drafts", "/jobs"):
            st, body = self.get(path)
            self.assertEqual(st, 200, path)
            self.assertNotIn("내부 오류", body, path)
        st, body = self.get("/cases/new?tc=op.roomFormOptions:200")
        self.assertIn('id="ed-state"', body)
        self.assertIn("op.roomFormOptions:200", body)
        st, body = self.get("/catalog/tc?id=op.roomFormOptions:200")
        self.assertIn("플랫폼에서 고치거나 지우지 않는다", body)
        st, body = self.get("/catalog/tc?id=" + quote("PRD.룸-탐색.4.1#1"))
        self.assertIn("/catalog/tc/edit?id=", body)

    def test_static_and_context(self):
        for p in ("/static/editor.js", "/static/jobs.js"):
            self.assertEqual(self.get(p, "*/*")[0], 200)
        st, body = self.get("/api/editor/context", "application/json")
        ctx = json.loads(body)
        self.assertIn("createRoom", [o["id"] for o in ctx["ops"]])
        self.assertIn("qa-host", ctx["actors"])
        st, body = self.get("/api/editor/op/createRoom", "application/json")
        self.assertIn("E1402", [x["code"] for x in json.loads(body)["errors"]])

    def test_preview_and_save_via_http(self):
        st, body = self.post("/api/editor/preview", {"state": SMOKE_STATE, "mode": "new"}, json_body=True)
        j = json.loads(body)
        self.assertTrue(j["ok"], j)
        self.assertIn("room.form-options-again", j["yaml"])
        self.assertEqual(self.app.store.list_drafts(), [])       # 미리보기는 저장하지 않는다
        bad = dict(SMOKE_STATE, covers=[])
        st, body = self.post("/editor/save", {"state": json.dumps(bad), "mode": "new", "operator": "bebe"})
        self.assertEqual(st, 400)
        self.assertIn("저장하지 않았다", body)
        st, body = self.post("/editor/save", {"state": json.dumps(dict(SMOKE_STATE, id="room.via-http")), "mode": "new", "operator": "bebe"})
        self.assertEqual(st, 200)       # 303 → 저장된 스크립트 화면을 따라간다
        self.assertIn("room.via-http", body)
        self.assertIn("최근 변경", body)
        self.assertIn("room.via-http", self.app.cases)
        did = next(d["id"] for d in self.app.store.list_drafts() if d["case_id"] == "room.via-http")
        st, body = self.get(f"/drafts/{did}")
        self.assertEqual(st, 200)
        self.assertIn("저장됨", body)
        st, body = self.post("/editor/try", {"state": dict(SMOKE_STATE, id="room.try-only"), "mode": "new", "operator": "bebe"}, json_body=True)
        self.assertEqual(st, 200, body)
        self.assertTrue(json.loads(body)["run_id"].startswith("r-"))
        self.assertNotIn("room.try-only", self.app.cases)                      # 실행해 봐도 저장하지 않는다


if __name__ == "__main__":
    unittest.main()
