"""P4c — 바뀐 TC 에 맞게 스크립트 다시 쓰기 (docs/qa-platform-hermes.md §3.3): 변경 이력 스냅샷·대체 후보·조립·검증·초안·diff 화면."""
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
from qa import drafts, httpx, ui  # noqa: E402
from qa.catalog import snapshot  # noqa: E402
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
class ReviseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE), "HERMES_API_KEY": "k",
                               "HERMES_API_URL": "http://hermes:8642", "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_FIXTURES": json.dumps({"postingId": 1, "jobRoleId": 1, "qa-host.resumeId": "r1"})}))
        self.cat = self.app.current_catalog()
        self.case = self.app.cases["room.create-and-cancel"]
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def _drift(self, changed="G.room.create#duplicate-slot-left", removed=None):
        """변경 이력을 흉내 낸다: changed 는 hash 가 바뀐 것, removed 는 사라진 것 + 같은 배치에 추가된 대체 후보."""
        at = "2026-09-22T00:00:00Z"
        ch = {changed: {"at": at, "kind": "changed", "before": dict(snapshot(self.cat.records[changed]), title="(옛 제목)")}}
        if removed:
            ch[removed] = {"at": at, "kind": "removed", "before": snapshot(self.cat.records.get(removed) or {"title": "옛것"})}
        self.app.catalog.changes = ch
        return ch

    def test_snapshot_slim(self):
        s = snapshot(self.cat.records["op.createRoom:E1402"])
        self.assertIn("title", s)
        self.assertNotIn("example", s.get("expect_hint") or {})
        self.assertIsNone(snapshot(None))

    def test_candidates(self):
        changes = {"G.room.create#duplicate-slot-left": {"at": "t1", "kind": "removed"}, "G.room.create#login-required": {"at": "t1", "kind": "added"}, "G.room.create#account-active": {"at": "t0", "kind": "added"}}
        # 같은 배치(t1)에 추가된 같은 앞부분 → #1 만 (#2 는 다른 배치)
        self.assertEqual(drafts._candidates("G.room.create#duplicate-slot-left", self.cat, changes), ["G.room.create#login-required"])
        # 배치에 없으면 TC 목록에서 앞부분 같은 것
        c = drafts._candidates("op.createRoom:E9999", self.cat, {})
        self.assertTrue(all(x.startswith("op.createRoom:") for x in c) and c)

    def test_assemble_revision(self):
        ch = self._drift(changed="C.room.create", removed="op.cancelRoom:E1410")
        drift = self.app.drift_of(self.case)
        self.assertEqual({d["id"] for d in drift}, {"C.room.create", "op.cancelRoom:E1410"})
        text, h, allowed = drafts.assemble_revision(cfg=self.app.cfg, catalog=self.cat, spec=self.app.spec.get(), wiki=self.app.wiki, case=self.case, drift=drift, changes=ch)
        self.assertEqual(len(h), 12)
        self.assertIn("# 현재 스크립트", text)
        self.assertIn("(옛 제목)", text)                       # 변경 전 스냅샷
        self.assertIn("사라진 TC op.cancelRoom:E1410", text)
        self.assertNotIn("op.cancelRoom:E1410", allowed)       # 사라진 것은 허용 목록에서 빠진다
        self.assertIn("C.room.create", allowed)
        self.assertIn("# 허용되는 covers", text)

    def test_revise_saves_with_same_id(self):
        self._drift(changed="C.room.create")
        new_yaml = self.case.to_yaml().replace("title: ", "title: 고침 — ", 1)
        httpx.request = _chat_reply("# 변경: 제목만\n```yaml\n" + new_yaml + "```")
        out = self.app.revise_case(self.case.id, operator="bebe", session_hash=None, ip=None)
        d = self.app.store.get_draft(out["id"])
        self.assertEqual((d["source"], d["case_id"], d["status"]), ("hermes-revise", self.case.id, "approved"))     # 초안 없이 바로 저장
        self.assertTrue(d["note"].startswith("바뀐 TC 에 맞게 다시 씀"))
        self.assertTrue(d["prompt_hash"])
        self.assertIn("고침 — ", d["yaml"])
        sent = httpx.request.bodies[-1]
        self.assertIn("바뀐 만큼만 고친다", sent["messages"][0]["content"])
        html = ui.draft_detail(d, {}, None, operators=["bebe"], operator="bebe", original_yaml=self.case.to_yaml())
        self.assertIn("원본 스크립트와의 차이", html)
        self.assertIn("+title: 고침", html)
        ev = [x for x in self.app.store.list_events(10) if x["action"] == "hermes.generate"][0]
        self.assertEqual(ev["detail"]["source"], "hermes-revise")

    def test_revise_keeps_id_even_if_hermes_changes_it(self):
        self._drift(changed="C.room.create")
        httpx.request = _chat_reply("```yaml\n" + self.case.to_yaml().replace("id: room.create-and-cancel", "id: room.other") + "```")
        out = self.app.revise_case(self.case.id, operator="bebe", session_hash=None, ip=None)
        self.assertEqual(self.app.store.get_draft(out["id"])["case_id"], self.case.id)

    def test_revise_rejects_extra_covers_and_guards(self):
        with self.assertRaises(BadRequest):                    # 바뀐 TC 없음
            self.app.revise_case(self.case.id, operator="bebe", session_hash=None, ip=None)
        self._drift(changed="C.room.create")
        import yaml as _y
        raw = _y.safe_load(self.case.to_yaml()); raw["steps"][0]["covers"].append("G.room.create#99")     # 허용 목록 밖 TC
        httpx.request = _chat_reply("```yaml\n" + _y.safe_dump(raw, allow_unicode=True, sort_keys=False) + "```")
        with self.assertRaises(BadRequest) as cm:
            self.app.revise_case(self.case.id, operator="bebe", session_hash=None, ip=None)
        self.assertIn("검증을 못 넘겼다", str(cm.exception))
        self.assertTrue(any(x["action"] == "hermes.rejected_by_validation" for x in self.app.store.list_events(10)))
        with self.assertRaises(BadRequest):
            self.app.revise_case("room.nope", operator="bebe", session_hash=None, ip=None)

    def test_case_detail_button_only_with_drift(self):
        html = ui.case_detail(self.case, [], tc_records={}, drift=[], revise={"operator": "bebe", "operators": ["bebe"], "hermes": True})
        self.assertNotIn("/revise", html)
        html = ui.case_detail(self.case, [], tc_records={}, drift=[{"id": "C.room.create", "kind": "changed", "at": "t"}], revise={"operator": "bebe", "operators": ["bebe"], "hermes": True})
        self.assertIn(f"/cases/{self.case.id}/revise", html)


if __name__ == "__main__":
    unittest.main()
