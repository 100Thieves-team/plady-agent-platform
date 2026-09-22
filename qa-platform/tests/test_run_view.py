"""실행 결과 요약 P5d (docs/qa-platform-api.md §5.7) — 요약 카드·도넛·도메인별 막대·판정 필터 렌더."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import ui  # noqa: E402

RUN = {"id": "r-1", "status": "finished", "verdict": "fail", "trigger": "sprint-smoke", "operator": "bebe", "base_url": "https://dev", "created_at": "2026-09-22T00:00:00Z",
       "passed": 3, "failed": 1, "errored": 0, "skipped": 1, "total": 5, "meta": {}}
CASES = [{"id": i, "run_id": "r-1", "case_id": f"c{i}", "case_title": f"t{i}", "case_suite": "smoke", "case_hash": "h", "verdict": v, "duration_ms": 1, "error": None}
         for i, v in enumerate(["pass", "pass", "pass", "fail", "skipped"], 1)]
DOMS = {1: ["room"], 2: ["room", "application"], 3: ["member"], 4: ["room"], 5: []}


class RunViewTest(unittest.TestCase):
    def test_summary(self):
        h = ui.run_summary(RUN, CASES, DOMS)
        self.assertIn("<b>5</b>", h)                                  # 전체
        self.assertIn("60% 통과율", h)                                 # 3/5
        self.assertIn('aria-label="통과율 60%"', h)                    # 도넛 SVG
        self.assertIn("room <span class=\"mut small\">3</span>", h)    # 도메인별 (여러 도메인은 각각 센다)
        self.assertIn("2/3 통과", h)
        self.assertIn("(도메인 없음)", h)
        self.assertIn('href="/runs/r-1?verdict=fail"', h)
        self.assertIn("실패 · 오류 1", h)

    def test_filter_in_detail(self):
        h = ui.run_detail(RUN, CASES, {}, operators=["bebe"], operator="bebe", checklist=[], public_url="", domains_by_rc=DOMS, f_verdict="fail")
        self.assertIn("c4", h)
        self.assertNotIn('class="mono">c1</a>', h)
        h2 = ui.run_detail(RUN, CASES, {}, operators=["bebe"], operator="bebe", checklist=[], public_url="", domains_by_rc=DOMS, f_verdict="error")
        self.assertIn("해당 판정의 스크립트가 없다", h2)
        h3 = ui.run_detail(RUN, CASES, {}, operators=["bebe"], operator="bebe", checklist=[], public_url="")   # 인자 없이도 (기존 호출 호환)
        self.assertIn("(도메인 없음)", h3)


if __name__ == "__main__":
    unittest.main()
