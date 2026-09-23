"""이력서 카드 — 목록 보기(입력으로 테스트 계정을 고른다)와 AI 요약 강제 완료(dev 전용 API). 초안 검증이 만든 QA 회원 이름도 아는지."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import httpx  # noqa: E402
from qa.cases import bake_inputs, load_dir  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


class FakeDev:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.calls.append((method, url, body, (headers or {}).get("Authorization")))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok-" + (body or {}).get("memberId", "")}}), 3)
        if url.endswith("/v1/members/me/resumes"):
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"maxCount": 10, "resumes": [{"resumeId": "res-1", "name": "[QA] r.pdf", "aiSummary": {"status": "FAILED", "text": None}}]}}), 5)
        if "/summary" in url:
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"resumeId": "res-1", "memberId": "m2", "status": "DONE", "summary": (body or {}).get("summary"), "isDefault": True}}), 5)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


class ResumeCardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.http = FakeDev(); self._orig = httpx.request; httpx.request = self.http
        env = {"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_PUBLIC_URL": "https://qa.test",
               "QA_ACTORS": json.dumps({"qa-host": "m1", "qa-guest": "m2"})}
        self.app = App(Config(env))

    def tearDown(self):
        httpx.request = self._orig; self.tmp.cleanup()

    def test_list_card_uses_input_actor(self):
        c = self.app.cases["setup.resume-list"]
        b = bake_inputs(c, {"actor": "qa-guest"})
        self.assertEqual(b.steps[0]["actor"], "qa-guest")                         # 입력이 단계의 테스트 계정이 된다
        rid = self.app.setup_run("setup.resume-list", {"actor": "qa-guest"}, operator="bebe", session_hash=None, ip=None)
        run = self.app.store.get_run(rid)
        self.assertEqual(run["verdict"], "pass")
        self.assertEqual([c[3] for c in self.http.calls if c[1].endswith("/resumes")], ["Bearer tok-m2"])   # qa-guest 토큰
        self.assertEqual(self.app.setup_outputs(run), {"resumeCount": 10, "firstResumeId": "res-1", "firstResumeName": "[QA] r.pdf", "firstSummaryStatus": "FAILED"})

    def test_summary_card_calls_dev_api_and_returns_status(self):
        rid = self.app.setup_run("setup.resume-summary", {"resumeId": "res-1", "summary": "[QA] 요약"}, operator="bebe", session_hash=None, ip=None)
        run = self.app.store.get_run(rid)
        self.assertEqual(run["verdict"], "pass")
        call = [c for c in self.http.calls if "/summary" in c[1]][0]
        self.assertTrue(call[1].endswith("/v1/dev/resumes/res-1/summary")); self.assertEqual(call[2], {"summary": "[QA] 요약"})
        self.assertEqual(self.app.setup_outputs(run), {"resumeId": "res-1", "summaryStatus": "DONE", "isDefault": True})

    def test_seed_cards_present(self):
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        self.assertEqual(cases["setup.resume-summary"].operations, ["completeQaResumeSummary"])
        self.assertTrue(cases["setup.resume-list"].outputs)

    def test_draft_validation_knows_platform_made_members(self):
        from qa import drafts as draftsmod
        self.app.store.add_qa_member(member_id="m-9", label="qa-3", nickname="n", email="e", operator="bebe")
        raw = {"id": "x.qa3", "title": "t", "suite": "manual", "actor": "qa-3", "covers": ["op.termsList:200"],
               "steps": [{"name": "s", "request": {"method": "GET", "path": "/v1/terms"}, "expect": {"status": 200}, "covers": ["op.termsList:200"]}]}
        cat = self.app.current_catalog()
        _, errors, _ = draftsmod.validate(raw, requested=["op.termsList:200"], catalog=cat, cfg=self.app.cfg, existing_ids=set(), actors=self.app.all_actors())
        self.assertFalse(any("없는 테스트 계정" in e for e in errors), errors)
        _, errors, _ = draftsmod.validate(raw, requested=["op.termsList:200"], catalog=cat, cfg=self.app.cfg, existing_ids=set())
        self.assertTrue(any("없는 테스트 계정 qa-3" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
