"""[API 문서 다시 읽기] — 캐시를 무시하고 다시 읽어 테스트 조건 목록을 다시 계산하고, 새/사라진 API 를 요약하며, 감사 로그에 남긴다."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import ui  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


class SpecRefreshTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sp = Path(self.tmp.name, "spec.yaml"); self.sp.write_text(SPEC_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        env = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(self.sp), "QA_PUBLIC_URL": "https://qa.test", "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_SPEC_TTL": "5"}
        self.app = App(Config(env))
        self.app.current_catalog()

    def tearDown(self):
        self.tmp.cleanup()

    def test_refresh_picks_up_new_api_and_logs(self):
        self.assertEqual(self.app.cfg.spec_ttl, 5)
        d = yaml.safe_load(self.sp.read_text(encoding="utf-8"))
        ok_example = {"ok": {"value": {"result": "SUCCESS", "data": {}}}}
        d["paths"]["/v1/foo"] = {"get": {"operationId": "listFoo", "summary": "foo",
                                         "responses": {"200": {"description": "ok", "content": {"application/json": {"examples": ok_example}}}}}}
        self.sp.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
        self.assertNotIn("listFoo", self.app.spec.get().ops)                       # 파일 모드는 force 없이는 다시 안 읽는다 (캐시와 같은 상황)
        res = self.app.refresh_spec(operator="bebe", session_hash=None, ip=None)
        self.assertTrue(res["ok"] and res["changed"])
        self.assertEqual(res["added"], ["listFoo"]); self.assertEqual(res["removed"], [])
        self.assertGreaterEqual(res["tc_added"], 1)
        self.assertIn("op.listFoo:200", self.app.current_catalog().records)         # TC 목록도 다시 계산됐다
        ev = self.app.store.list_events(3)[0]
        self.assertEqual((ev["action"], ev["detail"]["added"]), ("spec.refresh", ["listFoo"]))
        res2 = self.app.refresh_spec(operator="bebe", session_hash=None, ip=None)
        self.assertFalse(res2["changed"])                                            # 그대로면 changed=False

    def test_refresh_form_renders_on_screens(self):
        h = ui.refresh_form(operator="bebe", next_url="/apis", spec_hash="abc", fetched_ago=125)
        self.assertIn('action="/spec/refresh"', h); self.assertIn("2분 전 읽음", h); self.assertIn('value="/apis"', h)
        self.assertIn("disabled", ui.refresh_form(operator="", next_url="/apis", spec_hash=None, fetched_ago=None))
        rows, cat = self.app.api_overview()
        page = ui.apis_list(rows, domains=cat.domains(), domain="room", only="", q="", spec_hash="abc", spec_source="file", docs_url="", operator="bebe", fetched_ago=3)
        self.assertIn("API 문서 다시 읽기", page)
        self.assertIsNotNone(self.app.spec.age_seconds())


if __name__ == "__main__":
    unittest.main()
