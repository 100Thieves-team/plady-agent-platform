"""[스크립트 한꺼번에 만들기] — 스크립트 없는 케이스를 차례로 만든다."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import BadRequest  # noqa: E402
from qa import httpx  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        httpx.request = self.gh
        self.app = make_app(self.tmp.name)
        self.app.cfg.operators = ["bebe"]
        self.app.cfg.hermes_key = "test"

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_batch(self):
        vids = self.app.untested_variants()
        self.assertGreaterEqual(len(vids), 4)
        seen = []

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None):
            seen.append(variant)
            n = len(seen)
            if n == 2:
                return {"saved": [], "rejected": [("x", ["covers 가 틀렸다"])]}
            if n == 3:
                raise RuntimeError("Hermes 응답 없음")
            return {"saved": [{"id": f"d-{n}"}], "rejected": []}
        self.app.generate_cases = fake
        with self.assertRaises(BadRequest):
            self.app.job_batch_scripts("bebe", slug="없는-기능")
        job = self.app.job_batch_scripts("bebe", sync=True)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(seen, vids)                                  # 한 건씩 차례로, 실패해도 다음 건으로
        b = job.info["batch"]
        self.assertEqual((b["total"], b["saved"], b["rejected"], b["failed"]), (len(vids), len(vids) - 2, 1, 1))
        self.assertIn(f"스크립트 저장 {len(vids) - 2}개", job.result["summary"])
        self.assertIn(f"===== 1/{len(vids)} {vids[0]} =====", job.text)
        self.assertIn("hermes.batch_draft", [x["action"] for x in self.app.store.list_events(20)])

    def test_cancel_keeps_saved(self):
        vids = self.app.untested_variants()
        holder = {}

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None):
            if variant == vids[1]:
                holder["job"].cancel.set()                            # 두 번째 건을 쓰는 중에 사람이 그만둔다
            return {"saved": [{"id": "d-1"}], "rejected": []}
        self.app.generate_cases = fake
        orig_submit = self.app.jobs.submit

        def submit(kind, operator, label, fn, **kw):
            def wrapped(job):
                holder["job"] = job
                return fn(job)
            return orig_submit(kind, operator, label, wrapped, **kw)
        self.app.jobs.submit = submit
        job = self.app.job_batch_scripts("bebe", sync=True)
        self.assertEqual(job.status, "canceled")
        self.assertIn("그때까지 저장한 것은 남는다", job.error)
        self.assertEqual(job.info["batch"]["saved"], 2)


if __name__ == "__main__":
    unittest.main()
