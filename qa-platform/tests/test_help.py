"""도움말 '?' 와 담당자 고르기 (사용자 요청 2026-09-22) — 화면이 쓰는 도움말 키가 전부 있고, JS 가 만들어지고, 누구세요 화면이 그려진다."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import help as helpmod, ui  # noqa: E402


class HelpTest(unittest.TestCase):
    def test_every_help_button_has_content(self):
        src = (ROOT / "qa" / "ui.py").read_text(encoding="utf-8")
        used = set(re.findall(r'h\("([a-z.]+)"\)', src))
        self.assertGreaterEqual(len(used), 55)
        missing = sorted(used - set(helpmod.HELP))
        self.assertEqual(missing, [])
        for k, (t, b) in helpmod.HELP.items():
            self.assertTrue(t and "<p>" in b, k)

    def test_automation_help_explains_how(self):
        t, b = helpmod.HELP["tc.state"]
        for frag in ("미자동화 TC 를 자동화하려면", "고른 TC 로 스크립트 초안 생성", "한 번 실행해 보기", "승인", "PR", "covers", "exclusions.yaml"):
            self.assertIn(frag, b)

    def test_js_carries_table(self):
        js = helpmod.js()
        m = re.search(r"var H=(\{.*?\});\n", js, re.S)
        self.assertIsNotNone(m)
        data = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(set(data), set(helpmod.HELP))
        self.assertIn("help-modal", js)

    def test_button_and_whoami_page(self):
        self.assertIn('data-help="tc.state"', ui.h("tc.state"))
        h = ui.whoami_page(["bebe", "중곤"], current="bebe", next_url="/apis?domain=room")
        self.assertIn("누구세요?", h)
        self.assertIn('value="/apis?domain=room"', h)
        self.assertEqual(h.count('name="operator"'), 2)
        self.assertIn('class="primary"', h)
        page = ui.page("t", "<p>x</p>", operator="bebe")
        self.assertIn("/static/help.js", page)
        self.assertIn("바꾸기", page)
        self.assertIn("고르기", ui.page("t", "<p>x</p>", operator=""))


if __name__ == "__main__":
    unittest.main()
