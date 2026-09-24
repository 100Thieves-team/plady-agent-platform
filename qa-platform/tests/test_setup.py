"""준비 작업 P5c (docs/qa-platform-api.md §5.4) — suite setup · inputs · outputs 로더 검증, 입력 박기, 버튼 실행과 결과값, 화면."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import httpx, ui  # noqa: E402
from qa.cases import CaseError, bake_inputs, load_dir, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"

SETUP = """
id: setup.demo
title: 데모 룸 만들기
suite: setup
actor: qa-host
inputs:
  title: { label: 룸 제목, default: "[QA] 데모", required: true }
  size: { label: 정원, default: 4 }
  open: true
outputs: [roomId]
steps:
  - name: 생성
    request: { method: POST, path: /v1/rooms, body: { title: "{{input.title}} {{rand}}", maxParticipants: "{{input.size}}", public: "{{input.open}}", note: "정원 {{input.size}}명" } }
    expect: { status: 200 }
    save: { roomId: data.roomId }
"""


class LoaderTest(unittest.TestCase):
    def test_inputs_only_in_setup(self):
        with self.assertRaises(CaseError) as cm:
            parse_one(SETUP.replace("suite: setup", "suite: manual"))
        self.assertIn("setup 에서만", str(cm.exception))

    def test_outputs_must_be_saved_and_inputs_declared(self):
        with self.assertRaises(CaseError) as cm:
            parse_one(SETUP.replace("outputs: [roomId]", "outputs: [nope]"))
        self.assertIn("outputs", str(cm.exception))
        with self.assertRaises(CaseError) as cm:
            parse_one(SETUP.replace("  size: { label: 정원, default: 4 }\n", ""))
        self.assertIn("input.*", str(cm.exception))

    def test_bake_keeps_types_and_requires(self):
        c = parse_one(SETUP)
        self.assertEqual(c.inputs["open"], {"label": "open", "default": True, "required": False, "hint": ""})   # 스칼라 축약
        b = bake_inputs(c, {"title": "[QA] 내 룸", "size": "6", "open": "false"})
        body = b.steps[0]["request"]["body"]
        self.assertEqual((body["maxParticipants"], body["public"], body["note"]), (6, False, "정원 6명"))   # 전체 일치는 타입 유지, 일부는 문자열
        self.assertEqual(body["title"], "[QA] 내 룸 {{rand}}")                                             # 다른 치환은 그대로
        self.assertEqual(b.raw["input_values"], {"title": "[QA] 내 룸", "size": 6, "open": False})
        self.assertNotIn("inputs", b.raw)
        b2 = bake_inputs(c, {})                                                                            # 비우면 기본값
        self.assertEqual(b2.steps[0]["request"]["body"]["maxParticipants"], 4)
        with self.assertRaises(CaseError):
            bake_inputs(parse_one(SETUP.replace('default: "[QA] 데모", ', "")), {})                     # 필수인데 기본값도 없음
        with self.assertRaises(CaseError):
            bake_inputs(parse_one(SETUP.replace("suite: setup", "suite: manual").replace("inputs:", "x:").replace("{{input.title}}", "t").replace("{{input.size}}", "1").replace("{{input.open}}", "1")), {})

    def test_seed_file_loads(self):
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        setups = [c for c in cases.values() if c.suite == "setup"]
        self.assertEqual({c.id for c in setups}, {"setup.room-open", "setup.room-with-application", "setup.room-confirmed", "setup.room-reschedule", "setup.room-ready-to-start", "setup.resume-list", "setup.resume-summary"})
        for c in setups:
            self.assertTrue(c.inputs and c.outputs and c.description)
            self.assertEqual(c.covers, [])


class FakeHttp:
    def __init__(self):
        self.sent = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.sent.append((method, url, body))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok"}}), 3)
        if method == "POST" and url.endswith("/v1/rooms"):
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"roomId": "room-9", "status": "RECRUITING"}}), 10)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


class SetupRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "cases").mkdir()
        import yaml
        Path(self.tmp.name, "cases", "s.yaml").write_text(yaml.safe_dump({"cases": [yaml.safe_load(SETUP)]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        env = {"QA_DATA_DIR": self.tmp.name, "QA_CASES_DIR": str(Path(self.tmp.name, "cases")), "QA_SPEC_FILE": str(SPEC_FIXTURE),
               "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_PUBLIC_URL": "https://qa.test"}
        self.app = App(Config(env))
        self.http = FakeHttp()
        self._orig = httpx.request
        httpx.request = self.http

    def tearDown(self):
        httpx.request = self._orig
        self.tmp.cleanup()

    def test_run_bakes_inputs_records_and_returns_outputs(self):
        self.assertEqual(self.app.case_errors, [])
        rid = self.app.setup_run("setup.demo", {"title": "[QA] 버튼", "size": "3"}, operator="bebe", session_hash=None, ip="127.0.0.1")
        run = self.app.store.get_run(rid)
        self.assertEqual((run["trigger"], run["status"], run["verdict"]), ("setup", "finished", "pass"))
        self.assertEqual(run["meta"]["setup"], {"case": "setup.demo", "inputs": {"title": "[QA] 버튼", "size": 3, "open": True}})
        sent_body = [b for m, u, b in self.http.sent if u.endswith("/v1/rooms")][0]
        self.assertEqual(sent_body["maxParticipants"], 3)
        self.assertTrue(sent_body["title"].startswith("[QA] 버튼 "))
        self.assertEqual(self.app.setup_outputs(run), {"roomId": "room-9"})
        rcs = self.app.store.list_run_cases(rid)
        self.assertIn("input_values", rcs[0]["case_yaml"])                                            # 스냅샷에 입력값이 남는다
        acts = [ev["action"] for ev in self.app.store.list_events(10)]
        self.assertIn("setup.run", acts)
        with self.assertRaises(BadRequest):
            self.app.setup_run("nope", {}, operator="bebe", session_hash=None, ip=None)

    def test_page_and_run_new_hide_setup(self):
        h = ui.setup_page(self.app.setup_cases(), actors=["qa-host"], operators=["bebe"], operator="bebe", result=None, errors=[])
        for frag in ('name="input.title"', 'value="4"', "Normal", "Swagger", "/v1/rooms", "roomId", "실행 — dev 에 실제로 만든다"):
            self.assertIn(frag, h)
        h2 = ui.run_new(trigger="manual", target={}, suggested=[], all_cases=list(self.app.cases.values()), basis="", operators=["bebe"], operator="bebe", hidden={}, warnings=[])
        self.assertNotIn("setup.demo", h2)                                                               # 수동 실행 범위에 준비 작업은 안 뜬다
        rid = self.app.setup_run("setup.demo", {}, operator="bebe", session_hash=None, ip=None)
        run = self.app.store.get_run(rid)
        rcs = self.app.store.list_run_cases(rid)
        h3 = ui.setup_page(self.app.setup_cases(), actors=["qa-host"], operators=["bebe"], operator="bebe",
                           result={"run": run, "case": rcs[0], "steps": self.app.store.list_steps(rcs[0]["id"]), "outputs": self.app.setup_outputs(run)}, errors=[])
        self.assertIn("room-9", h3)
        self.assertIn('window.SETUP_OUT={"roomId": "room-9"}', h3)


class SeedUsesTest(unittest.TestCase):
    """시드 카드끼리의 중복과 room.apply-and-withdraw 의 준비 단계를 uses 로 줄였다 (docs/qa-platform-scenarios.md §13)."""

    def test_seed_cards_and_scripts_use_uses(self):
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        for cid, card in (("setup.room-with-application", "setup.room-open"), ("setup.room-confirmed", "setup.room-with-application"),
                          ("setup.room-ready-to-start", "setup.room-confirmed"), ("room.apply-and-withdraw", "setup.room-open")):
            self.assertEqual((cases[cid].uses or {}).get("setup"), card, cid)
        ready = cases["setup.room-ready-to-start"]
        self.assertEqual([s["name"] for s in ready.steps][:4], ["룸 생성", "참가자가 신청", "방장이 수락", "방장이 진행 확정"])
        aw = cases["room.apply-and-withdraw"]
        self.assertNotIn("op.createRoom:200", aw.covers)
        self.assertEqual((aw.steps[0]["given"], aw.steps[0]["request"]["path"]), ("setup.room-open", "/v1/rooms"))
        self.assertTrue(aw.steps[0]["request"]["body"]["title"].startswith("[QA] 참가 신청 sanity"))


if __name__ == "__main__":
    unittest.main()
