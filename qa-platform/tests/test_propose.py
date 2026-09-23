"""P4d — PRD 절에서 수동 작성 TC 제안: 공용 조립(번호·도메인·경고), Hermes 제안 파싱, 버튼 경로 초안(kind tc), 도구 경로와 동일 결과."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import drafts, httpx  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")


def _chat_reply(text: str):
    def fake(method, url, headers=None, body=None, timeout=30):
        fake.bodies.append(body)
        return httpx.HttpResult(200, {}, json.dumps({"choices": [{"message": {"content": text}}]}), 1)
    fake.bodies = []
    return fake


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class ProposeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE), "HERMES_API_KEY": "k", "HERMES_API_URL": "http://hermes:8642"}))
        self.cat = self.app.current_catalog()
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_build_manual_tc(self):
        recs, warns, dom = drafts.build_manual_tc(catalog=self.cat, doc="룸 탐색", section="4.1", items=[{"title": "t", "when": "w", "then": "x"}, {"title": "t2", "given": "g", "when": "w", "then": "x", "operations": ["rooms"]}], domain=None, wiki=self.app.wiki)
        self.assertEqual([r["id"] for r in recs], ["PRD.룸-탐색.4.1#2", "PRD.룸-탐색.4.1#3"])    # 기존 #1 다음부터
        self.assertEqual(dom, "room")                                                        # 같은 문서의 기존 수동 TC 에서
        self.assertEqual(recs[1]["operations"], ["rooms"])
        self.assertEqual(warns, [])
        _, warns, dom = drafts.build_manual_tc(catalog=self.cat, doc="없는 문서", section="1", items=[{"title": "t", "when": "w", "then": "x"}], domain=None, wiki=self.app.wiki)
        self.assertEqual(dom, "other")
        self.assertTrue(warns and "찾지 못했다" in warns[0])
        with self.assertRaises(ValueError):
            drafts.build_manual_tc(catalog=self.cat, doc="룸 탐색", section="4.1", items=[{"title": "", "when": "w", "then": "x"}], domain=None, wiki=None)

    def test_propose_button_path(self):
        httpx.request = _chat_reply("```yaml\nitems:\n  - title: 마감 지난 룸은 목록에 안 나온다\n    given: 마감일이 지난 룸\n    when: GET /v1/rooms\n    then: 그 룸이 없다\n    operations: [rooms]\n  - title: 잘못된 항목\n    when: w\n    then: t\n```")
        did = self.app.propose_tc(doc="룸 탐색", section="4.1", domain="", operator="bebe", session_hash=None, ip=None)
        d = self.app.store.get_draft(did)
        self.assertEqual((d["kind"], d["source"], d["domain"], d["operator"]), ("tc", "hermes-propose", "room", "bebe"))
        self.assertEqual(d["tc_ids"], ["PRD.룸-탐색.4.1#2", "PRD.룸-탐색.4.1#3"])
        self.assertIn("cases:", d["yaml"])
        self.assertTrue(d["prompt_hash"])
        sent = httpx.request.bodies[-1]
        self.assertIn("PRD/룸 탐색 §4.1 본문", sent["messages"][1]["content"])
        self.assertIn("기존 TC", sent["messages"][1]["content"])          # 이미 뽑힌 #1 을 알려 준다
        # 저장·승인 경로는 tc 형식 검증
        items, errors = drafts.validate_manual_tc(d["yaml"])
        self.assertEqual((len(items), errors), (2, []))

    def test_propose_guards(self):
        with self.assertRaises(BadRequest):
            self.app.propose_tc(doc="", section="1", domain="", operator="bebe", session_hash=None, ip=None)
        with self.assertRaises(BadRequest):
            self.app.propose_tc(doc="없는 문서", section="1", domain="", operator="bebe", session_hash=None, ip=None)
        with self.assertRaises(BadRequest):
            self.app.propose_tc(doc="룸 탐색", section="99.9", domain="", operator="bebe", session_hash=None, ip=None)
        httpx.request = _chat_reply("```yaml\nitems: []\n```")
        with self.assertRaises(BadRequest) as cm:
            self.app.propose_tc(doc="룸 탐색", section="4.1", domain="", operator="bebe", session_hash=None, ip=None)
        self.assertIn("찾지 못했다", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
