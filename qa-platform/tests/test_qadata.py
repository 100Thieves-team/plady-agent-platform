"""QA 데이터 정리 (백엔드 PR #135 dev 전용 API) — 목록·삭제·초기화 호출, 감사 로그, TC 목록·API 화면에서 /v1/dev 제외, 화면."""
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

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
LIVE_SPEC = Path("/private/tmp/claude-501/-Users-luna-Desktop-nonsync-teams-100-thieves-100Thieves-wiki-mcp/73a608b6-af64-4a3a-a3d5-80a9e019abda/scratchpad/openapi3.yaml")

DEV_PATHS = {
    "/v1/dev/qa-data": {"get": {"operationId": "listQaData", "summary": "[dev] QA 데이터 목록", "responses": {"200": {"description": "ok"}}},
                        "delete": {"operationId": "deleteQaData", "summary": "[dev] QA 데이터 일괄 삭제", "responses": {"200": {"description": "ok"}}}},
    "/v1/dev/rooms/{roomId}": {"delete": {"operationId": "deleteQaRoom", "summary": "[dev] QA 룸 삭제", "parameters": [{"name": "roomId", "in": "path", "required": True}], "responses": {"200": {"description": "ok"}}}},
    "/v1/dev/members/{memberId}/reset": {"post": {"operationId": "resetQaMember", "summary": "[dev] 테스트 계정 초기화", "parameters": [{"name": "memberId", "in": "path", "required": True}], "responses": {"200": {"description": "ok"}}}},
}
DELETED = {"rooms": 1, "applications": 2, "participants": 1, "members": 0, "total": 9}


class FakeDev:
    def __init__(self):
        self.calls = []
        self.fail_next = None

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.calls.append((method, url, (headers or {}).get("Authorization")))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok"}}), 3)
        if self.fail_next:
            code, st = self.fail_next; self.fail_next = None
            return httpx.HttpResult(st, {}, json.dumps({"result": "ERROR", "error": {"code": code, "message": "거절"}}), 3)
        if "/v1/dev/qa-data" in url and method == "GET":
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {
                "rooms": [{"roomId": "r-1", "title": "[QA] 룸", "status": "RECRUITING", "hostMemberId": "m1", "createdAt": "2026-09-22T10:00:00", "counts": {"applications": 2, "participants": 1}},
                          {"roomId": "r-2", "title": "[QA] 남의 룸", "status": "CANCELED", "hostMemberId": "zzz-other", "createdAt": "2026-09-21T09:00:00", "counts": {"applications": 0, "participants": 0}}],
                "members": [{"memberId": "m-9", "nickname": "테스트", "email": "qa-x@qa.moimyeon.test"}]}}), 5)
        if "/v1/dev/" in url:
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"deleted": DELETED}}), 5)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


class QaDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        spec = yaml.safe_load(SPEC_FIXTURE.read_text(encoding="utf-8"))
        spec["paths"].update(DEV_PATHS)
        self.spec_path = Path(self.tmp.name, "spec.yaml"); self.spec_path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
        self.http = FakeDev(); self._orig = httpx.request; httpx.request = self.http

    def tearDown(self):
        httpx.request = self._orig; self.tmp.cleanup()

    def app(self, actors=None):
        env = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(self.spec_path), "QA_PUBLIC_URL": "https://qa.test",
               "QA_ACTORS": json.dumps(actors if actors is not None else {"qa-host": "m1", "qa-guest": "m2"})}
        return App(Config(env))

    def test_dev_api_excluded_from_tc_and_api_views_but_kept_for_explorer(self):
        a = self.app()
        cat = a.current_catalog()
        self.assertFalse(any(i.startswith("op.listQaData") or i.startswith("op.deleteQaRoom") for i in cat.records))
        rows, _ = a.api_overview()
        self.assertFalse(any(r["id"] == "listQaData" for r in rows))
        from qa.catalog import domain_of_path
        self.assertEqual(domain_of_path("/v1/dev/qa-data"), "qa-dev")
        h = ui.explorer(a.spec.get(), None, None, [], actors=[], operators=["bebe"], operator="bebe", q="", domain_of=domain_of_path)
        self.assertIn("qa-dev", h)                                              # API 호출 화면에는 남는다

    def test_snapshot_and_actions_with_audit(self):
        a = self.app()
        snap = a.qadata.snapshot()
        self.assertTrue(snap["available"])
        self.assertEqual([r["host_label"] for r in snap["rooms"]], ["qa-host", "zzz-othe…"])   # UUID → 테스트 계정 이름, 남은 건 앞 8자리
        self.assertEqual(self.http.calls[0][1].endswith("/v1/auth/dev-sessions"), True)      # qa-host 토큰
        self.assertEqual(self.http.calls[1][2], "Bearer tok")
        res = a.qa_data_action("delete_room", "r-1", operator="bebe", session_hash=None, ip=None)
        self.assertTrue(res["ok"]); self.assertEqual(res["deleted"]["total"], 9)
        self.assertTrue(self.http.calls[-1][1].endswith("/v1/dev/rooms/r-1") and self.http.calls[-1][0] == "DELETE")
        res = a.qa_data_action("reset", "qa-guest", operator="bebe", session_hash=None, ip=None)
        self.assertTrue(self.http.calls[-1][1].endswith("/v1/dev/members/m2/reset"))
        res = a.qa_data_action("delete_all", "qa-host", operator="bebe", session_hash=None, ip=None)
        self.assertIn("hostMemberId=m1", self.http.calls[-1][1])
        self.http.fail_next = ("E2201", 409)
        res = a.qa_data_action("delete_room", "r-x", operator="bebe", session_hash=None, ip=None)
        self.assertFalse(res["ok"]); self.assertEqual(res["error"]["code"], "E2201")
        acts = [(ev["action"], ev["detail"].get("ok")) for ev in a.store.list_events(10)]
        self.assertIn(("qa_data.delete_room", True), acts); self.assertIn(("qa_data.reset", True), acts); self.assertIn(("qa_data.delete_room", False), acts)
        with self.assertRaises(BadRequest):
            a.qa_data_action("reset", "nobody", operator="bebe", session_hash=None, ip=None)

    def test_unavailable_without_actors_or_api(self):
        a = self.app(actors={})
        snap = a.qadata.snapshot()
        self.assertFalse(snap["available"]); self.assertIn("QA_ACTORS", snap["why"])
        env = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_PUBLIC_URL": "https://qa.test", "QA_ACTORS": json.dumps({"qa-host": "m1"})}
        b = App(Config(env))
        self.assertIn("listQaData", b.qadata.why_unavailable())

    def test_cleanup_section_renders(self):
        a = self.app()
        h = ui.setup_page(a.setup_cases(), actors=["qa-host", "qa-guest"], operators=["bebe"], operator="bebe", result=None, errors=[], cleanup=a.qadata.snapshot())
        for frag in ("QA 데이터 정리", "[QA] 룸 2개", 'value="delete_room"', 'value="r-1"', "[QA] 룸 전부 삭제", "qa-host 초기화", "qa-guest 초기화", "QA 테스트 회원 1명", 'value="delete_member"'):
            self.assertIn(frag, h)
        h2 = ui.setup_page(a.setup_cases(), actors=[], operators=["bebe"], operator="bebe", result=None, errors=[], cleanup={"available": False, "why": "없음", "rooms": [], "members": [], "actors": []})
        self.assertIn("지금은 쓸 수 없다", h2)

    @unittest.skipUnless(LIVE_SPEC.is_file(), "실제 스펙 사본 없음")
    def test_live_spec_has_the_ops_we_call(self):
        d = yaml.safe_load(LIVE_SPEC.read_text(encoding="utf-8"))
        ops = {op.get("operationId") for item in d["paths"].values() for m, op in item.items() if m in ("get", "post", "delete")}
        for need in ("listQaData", "deleteQaRoom", "deleteQaData", "resetQaMember", "deleteQaMember"):
            self.assertIn(need, ops)


if __name__ == "__main__":
    unittest.main()
