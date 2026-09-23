"""QA 테스트 회원 만들기 + 시작 시각 변경 카드 — 회원 생성이 테스트 계정 이름이 되고, 러너가 그 이름으로 토큰을 받고, 응답의 토큰은 기록에 안 남는다."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import httpx, ui  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.runner import _mask_secrets  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
DEV_PATHS = {
    "/v1/dev/qa-data": {"get": {"operationId": "listQaData", "responses": {"200": {"description": "ok"}}}},
    "/v1/dev/members": {"post": {"operationId": "createQaMember", "responses": {"200": {"description": "ok"}}}},
    "/v1/dev/members/{memberId}": {"delete": {"operationId": "deleteQaMember", "parameters": [{"name": "memberId", "in": "path", "required": True}], "responses": {"200": {"description": "ok"}}}},
    "/v1/dev/rooms/{roomId}/schedule": {"post": {"operationId": "rescheduleQaRoom", "parameters": [{"name": "roomId", "in": "path", "required": True}], "responses": {"200": {"description": "ok"}}}},
}


class FakeDev:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.calls.append((method, url, body))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok-" + (body or {}).get("memberId", "")}}), 3)
        if url.endswith("/v1/dev/members") and method == "POST":
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"memberId": "m-new", "nickname": "새닉", "email": "qa-1@qa.moimyeon.test", "accessToken": "secret"}}), 5)
        if "/v1/dev/qa-data" in url:
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"rooms": [], "members": [{"memberId": "m-new", "nickname": "새닉", "email": "qa-1@qa.moimyeon.test"}]}}), 5)
        if "/schedule" in url:
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"roomId": "r-1", "status": "CONFIRMED", "startAt": (body or {}).get("startAt")}}), 5)
        if "/v1/dev/members/" in url and method == "DELETE":
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"deleted": {"members": 1, "total": 3}}}), 5)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"ok": True}}), 5)


class QaMembersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        spec = yaml.safe_load(SPEC_FIXTURE.read_text(encoding="utf-8")); spec["paths"].update(DEV_PATHS)
        sp = Path(self.tmp.name, "spec.yaml"); sp.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
        self.http = FakeDev(); self._orig = httpx.request; httpx.request = self.http
        env = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(sp), "QA_PUBLIC_URL": "https://qa.test", "QA_ACTORS": json.dumps({"qa-host": "m1"})}
        self.app = App(Config(env))

    def tearDown(self):
        httpx.request = self._orig; self.tmp.cleanup()

    def test_create_member_becomes_actor_and_token_flows(self):
        res = self.app.create_qa_member("qa-3", operator="bebe", session_hash=None, ip=None)
        self.assertTrue(res["ok"]); self.assertNotIn("accessToken", res["member"])                  # 토큰은 버린다
        self.assertEqual(self.app.all_actors(), {"qa-host": "m1", "qa-3": "m-new"})
        self.assertEqual(self.app.runner.actors.token("qa-3", "https://dev"), "tok-m-new")          # 이름으로 dev-sessions 토큰
        self.assertIn(("qa_data.create_member", "qa-3"), [(ev["action"], ev["target"]) for ev in self.app.store.list_events(5)])
        with self.assertRaises(BadRequest):
            self.app.create_qa_member("qa-3", operator="bebe", session_hash=None, ip=None)         # 중복 이름
        with self.assertRaises(BadRequest):
            self.app.create_qa_member("Bad Name", operator="bebe", session_hash=None, ip=None)
        snap = self.app.qadata.snapshot()
        self.assertEqual(snap["members"][0]["label"], "qa-3")                                       # 정리 표에 이름이 붙는다
        self.app.qa_data_action("delete_member", "m-new", operator="bebe", session_hash=None, ip=None)
        self.assertNotIn("qa-3", self.app.all_actors())                                             # 지우면 목록에서도 빠진다

    def test_mask_secrets_in_recorded_response(self):
        self.assertEqual(_mask_secrets({"data": {"memberId": "m", "accessToken": "s", "nested": [{"refreshToken": "r"}]}}),
                         {"data": {"memberId": "m", "accessToken": "***", "nested": [{"refreshToken": "***"}]}})

    def test_reschedule_cards_load_and_run(self):
        from qa.cases import load_dir
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        self.assertEqual(cases["setup.room-reschedule"].operations, ["rescheduleQaRoom"])
        self.assertIn("rescheduleQaRoom", cases["setup.room-ready-to-start"].operations)
        # 카드 실행: 입력값이 박히고 dev 전용 API 를 qa-host 토큰으로 부른다
        self.app.cases.update({k: v for k, v in cases.items() if k == "setup.room-reschedule"})
        rid = self.app.setup_run("setup.room-reschedule", {"roomId": "r-1", "daysFromNow": "-2", "time": "08:30:00"}, operator="bebe", session_hash=None, ip=None)
        run = self.app.store.get_run(rid)
        self.assertEqual(run["verdict"], "pass")
        call = [c for c in self.http.calls if "/schedule" in c[1]][0]
        self.assertTrue(call[1].endswith("/v1/dev/rooms/r-1/schedule"))
        self.assertTrue(call[2]["startAt"].endswith("T08:30:00"))
        self.assertEqual(self.app.setup_outputs(run)["roomStatus"], "CONFIRMED")

    def test_setup_page_shows_member_card(self):
        self.app.create_qa_member("qa-3", operator="bebe", session_hash=None, ip=None)
        h = ui.setup_page(self.app.setup_cases(), actors=sorted(self.app.all_actors()), operators=["bebe"], operator="bebe", result=None, errors=[],
                          cleanup=self.app.qadata.snapshot(), qa_members=self.app.store.list_qa_members())
        for frag in ("QA 테스트 회원 만들기", 'name="label"', "회원 만들기", "qa-3", "새닉", "qa-3, qa-host"):
            self.assertIn(frag, h)


if __name__ == "__main__":
    unittest.main()
