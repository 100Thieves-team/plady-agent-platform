"""통계 배지 P5e (docs/qa-platform-api.md §5.5) — 최근 N회 통과율·평균 소요·불안정(flaky) 계산과 조회."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import ui  # noqa: E402
from qa.store import Store  # noqa: E402


def rows(seq, hashes=None, ms=100):
    return [{"verdict": v, "duration_ms": ms, "case_hash": (hashes[i] if hashes else "h1")} for i, v in enumerate(seq)]


class StatsTest(unittest.TestCase):
    def test_rate_avg_and_skip_excluded(self):
        st = ui.stats_of(rows(["pass", "fail", "skipped", "pass", "pass"]))
        self.assertEqual((st["n"], st["passed"], st["failed"], st["skipped"], st["pass_rate"], st["avg_ms"]), (5, 3, 1, 1, 75, 100))
        self.assertIsNone(ui.stats_of([]))
        self.assertIsNone(ui.stats_of(rows(["skipped"]))["pass_rate"])

    def test_flaky_needs_flips_within_same_hash(self):
        self.assertTrue(ui.stats_of(rows(["pass", "fail", "pass", "pass"]))["flaky"])            # 2번 뒤집힘
        self.assertFalse(ui.stats_of(rows(["fail", "pass", "pass", "pass"]))["flaky"])           # 1번 (고쳐서 나아진 것)
        self.assertFalse(ui.stats_of(rows(["pass", "fail", "pass"], hashes=["h2", "h1", "h1"]))["flaky"])   # 최신 해시만 보면 pass 하나
        self.assertTrue(ui.stats_of(rows(["pass", "fail", "pass"], hashes=["h2", "h1", "h1"]), same_hash=False)["flaky"])
        old = ["pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass"] + ["fail", "pass", "fail"]
        self.assertFalse(ui.stats_of(rows(old))["flaky"])                                       # 창(10회) 밖의 뒤집힘은 안 센다

    def test_badge_text(self):
        h = ui.stats_badge(ui.stats_of(rows(["pass", "fail", "pass"])))
        self.assertIn("최근 3회 통과율 67%", h)
        self.assertIn("평균 100 ms", h)
        self.assertIn("불안정 (flaky)", h)
        self.assertIn("기록 없음", ui.stats_badge(None))

    def test_store_recent_queries(self):
        with tempfile.TemporaryDirectory() as d:
            st = Store(Path(d) / "t.sqlite")
            class C:  # 최소한의 Case 흉내
                def __init__(self, i): self.id, self.title, self.suite, self.hash = i, i, "smoke", "h"
                def run_yaml(self): return "id: x\n"
            for k in range(3):
                rid = st.create_run(trigger="manual", operator="bebe", suite="smoke", env="dev", base_url="u", ref="dev", sha=None, pr_number=None, meta={}, cases=[C("a"), C("b")])
                for rc in st.list_run_cases(rid):
                    st.update_run_case(rc["id"], verdict="pass" if (k + (rc["case_id"] == "b")) % 2 else "fail", duration_ms=50)
                    st.add_step(rc["id"], 0, "s", {"method": "GET", "path": "/v1/terms"}, {"status": 200}, [], "pass", 40, None, op_id="termsList")
            rc = st.recent_case_results(2)
            self.assertEqual(len(rc["a"]), 2)                                     # limit
            self.assertEqual([r["verdict"] for r in st.recent_case_results(20)["a"]], ["fail", "pass", "fail"])   # 최신순
            op = st.recent_op_results(20)["termsList"]
            self.assertEqual(len(op), 6)
            self.assertEqual(ui.stats_of(op, same_hash=False)["avg_ms"], 40)


if __name__ == "__main__":
    unittest.main()
