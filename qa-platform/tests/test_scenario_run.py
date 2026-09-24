"""7단계 (docs/qa-platform-scenarios.md §10, §11) — 케이스 골라 실행, 결과·보고서 묶기, PRD·규칙표 변경 표시, [Hermes 로 다시 맞추기]."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import app as appmod  # noqa: E402
from app import BadRequest  # noqa: E402
from qa import httpx, report, ui  # noqa: E402
from qa import scenarios as S  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402
from test_scenario_hermes import Router  # noqa: E402

SLUG = "룸-생성"
Q = quote(SLUG)


def seeded_gh(mutate=None):
    gh = FakeGitHub()
    for p in (ROOT / "scenarios").glob("*.yaml"):
        text = p.read_text(encoding="utf-8")
        if mutate and p.stem == SLUG:
            text = mutate(text)
        gh.files[f"qa-platform/scenarios/{p.name}"] = text
    return gh


def stale_r6(text: str) -> str:
    """S1 의 R6 지문을 옛 값으로 — PRD R6 문장이 지난 저장 뒤 바뀐 것처럼."""
    return re.sub(r"(\n      R6: )[0-9a-f]{8}", r"\g<1>00000000", text, count=1)


class GroupTest(unittest.TestCase):
    def test_group_run_cases(self):
        feats, _ = S.load_dir(ROOT / "scenarios")
        rc = lambda i, cid, variant=None: {"id": i, "case_id": cid, "case_title": cid, "case_suite": "sanity", "verdict": "pass" if i != 2 else "fail",  # noqa: E731
                                           "error": None, "case_yaml": f"id: {cid}\n" + (f"variant: {variant}\n" if variant else "")}
        rcs = [rc(1, "room.cancel", "룸-생성/S2/cancel"), rc(2, "room.create", "룸-생성/S1/happy"), rc(3, "auth.x"), rc(4, "room.old", "룸-생성/S1/gone")]
        groups, rest = S.group_run_cases(rcs, feats, {(SLUG, "S1"): "방장이 룸을 만든다"})
        self.assertEqual([g["id"] for g in groups], ["룸-생성/S1/happy", "룸-생성/S2/cancel", "룸-생성/S1/gone"])    # 파일 순서, 모르는 것은 뒤
        self.assertEqual((groups[0]["scenario_title"], groups[0]["kind"]), ("방장이 룸을 만든다", "happy"))
        self.assertIn("지금 시나리오 파일에 없다", groups[2]["title"])
        self.assertEqual([r["case_id"] for r in rest], ["auth.x"])
        md = report.render({"id": "r-1", "created_at": "2026-09-24T00:00:00Z", "trigger": "manual", "operator": "bebe", "passed": 2, "failed": 1, "errored": 0,
                            "skipped": 0, "total": 4, "verdict": "fail", "status": "finished"}, rcs, coverage=None, catalog=None, public_url="https://qa", sprint=None,
                           groups=(groups, rest))
        self.assertIn("## 시나리오별 결과", md)
        self.assertIn("| 룸 생성 | S1 방장이 룸을 만든다 | 온라인 룸을 만들면 모집 중으로 열리고 상세의 방장이 본인이다 | fail |", md)
        self.assertIn("### 시나리오에 연결되지 않은 스크립트", md)
        page = ui.run_detail({"id": "r-1", "status": "finished", "verdict": "fail", "trigger": "manual", "operator": "bebe", "created_at": "2026-09-24T00:00:00Z",
                              "passed": 2, "failed": 1, "errored": 0, "skipped": 0, "total": 4, "meta": {}, "base_url": "u", "sha": None, "pr_number": None},
                             [dict(r, duration_ms=1, case_hash="h") for r in rcs], {}, operators=["bebe"], operator="bebe", checklist=[], public_url="",
                             groups=(groups, rest))
        self.assertLess(page.index("온라인 룸을 만들면"), page.index("시나리오에 연결되지 않은 스크립트"))
        self.assertLess(page.index("/cases/room.create"), page.index("/cases/auth.x"))


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = seeded_gh(stale_r6)
        httpx.request = Router(self.gh, [])
        self.app = make_app(self.tmp.name)

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def s(self, sid="S1"):
        ov, _ = self.app.scenario_view()
        f = next(x for x in ov if x["slug"] == SLUG)
        return f, next(x for x in f["scenarios"] if x["id"] == sid)

    def test_seed_has_basis_and_no_drift(self):
        feats, _ = S.load_dir(ROOT / "scenarios")
        self.assertTrue(all(s.basis for f in feats.values() for s in f.scenarios))
        self.assertIn("G.room.create#headcount-range", feats[SLUG].scenario("S1").basis)     # gates 에 적은 게이트의 검사까지
        self.assertFalse(any(k.startswith("op.") for f in feats.values() for s in f.scenarios for k in s.basis))   # API 계약은 넣지 않는다
        f, s2 = self.s("S2")
        self.assertEqual(s2["drift"], {"changed": [], "removed": [], "added": []})

    def test_drift_shown_then_acknowledged(self):
        f, s = self.s()
        self.assertEqual([x["id"] for x in s["drift"]["changed"]], ["R6"])
        self.assertEqual(s["drift"]["changed"][0]["text"], "입력 내용을 확인하고 룸을 생성한다.")
        self.assertEqual(f["counts"]["drift"], 1)
        page = ui.feature_page(f, check={}, gate_names={}, prd_url=None, operator="bebe", hermes=True)
        for frag in ("지난 저장 뒤 PRD·규칙표가 바뀌었다", "R6</span> 바뀜", 'action="/features/realign"', "변경 확인만 하기"):
            self.assertIn(frag, page)
        self.assertIn("PRD·규칙표 바뀜 1", ui.scenario_tree(self.app.scenario_view()[0]))
        v = next(v for v in s["variants"] if v["variant"].key == "headcount-range")
        self.assertIn("기대는 R6 가 바뀌었다", ui.variant_page(f, s, v, check={}, tc_records={}, history=[], step=None, operator="bebe"))
        out = self.app.save_scenario({"feature": "룸 생성", "scenario": "S1", "action": "basis"}, operator="bebe")
        self.assertTrue(out["ok"], out)
        self.assertIn("PRD·규칙표 변경 확인", self.gh.puts[-1]["message"])
        self.assertEqual(self.s()[1]["drift"]["changed"], [])
        self.assertEqual(self.app.save_scenario({"feature": "룸 생성", "scenario": "S1", "action": "basis"}, operator="bebe")["errors"], ["바뀐 내용이 없다"])

    def test_form_save_records_basis(self):
        raw = dict(self.app.features[SLUG].scenario("S1").variant("batch").raw, title="고친 제목")
        self.assertTrue(self.app.save_scenario({"feature": "룸 생성", "scenario": "S1", "action": "variant", "original_key": "batch", "variant": raw}, operator="bebe")["ok"])
        self.assertEqual(self.s()[1]["drift"]["changed"], [])                                # 폼 저장도 지금 문장을 새로 적는다

    def test_realign_only_touches_affected_cases(self):
        reply = """```yaml
id: S1
gates:
  R6: [G.room.create]
  R4: [G.room.update]
variants:
  - key: headcount-range
    kind: reject
    at: R6
    title: 최소·최대 인원이 맞지 않으면 E1402 로 거절된다
    checks: [G.room.create#headcount-range]
  - key: happy
    kind: happy
    title: 바꾸면 안 되는 케이스
```"""
        r = Router(self.gh, [reply])
        httpx.request = r
        out = self.app.realign_scenario(SLUG, "S1", operator="bebe")
        self.assertEqual(out["keys"], ["headcount-range"])
        prompt = r.bodies[0]["messages"][-1]["content"]
        self.assertIn("바뀜 R6: 입력 내용을 확인하고 룸을 생성한다.", prompt)
        self.assertIn("# 고쳐도 되는 케이스 key\nheadcount-range", prompt)
        s1 = self.app.features[SLUG].scenario("S1")
        self.assertEqual((s1.variant("headcount-range").title, s1.variant("headcount-range").raw.get("written_by")),
                         ("최소·최대 인원이 맞지 않으면 E1402 로 거절된다", "hermes"))
        self.assertEqual(s1.variant("happy").title, "온라인 룸을 만들면 모집 중으로 열리고 상세의 방장이 본인이다")      # 걸리지 않은 케이스는 그대로
        self.assertNotIn("R4", s1.gates)                                                     # 바뀌지 않은 요구의 gates 도 그대로
        self.assertEqual(self.s()[1]["drift"]["changed"], [])
        self.assertIn("다시 맞추기 (Hermes)", self.gh.puts[-1]["message"])
        with self.assertRaises(BadRequest):
            self.app.realign_scenario(SLUG, "S1", operator="bebe")                            # 이제 바뀐 것이 없다


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class RouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.orig = httpx.request
        cls.gh = seeded_gh()
        httpx.request = Router(cls.gh, [])
        cls.app = make_app(cls.tmp.name)
        appmod.Handler.app = cls.app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        httpx.request = cls.orig
        cls.tmp.cleanup()

    def get(self, path):
        req = urllib.request.Request(self.base + path, headers={"Cookie": "qa_operator=bebe", "Accept": "text/html"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as ex:
            return ex.code, ex.read().decode()

    def test_pages(self):
        for path in ("/", "/features", f"/features/{Q}", f"/features/{Q}/S1/happy", f"/features/{Q}/S1/new", f"/features/{Q}/S1/edit",
                     f"/features/{Q}/S1/happy/edit", "/cases", "/guide"):
            st, body = self.get(path)
            self.assertEqual(st, 200, path)
            self.assertNotIn("내부 오류", body, path)
        st, body = self.get("/features")
        self.assertIn('form="scn-run"', body)
        self.assertIn("고른 케이스 실행", body)

    def test_picked_cases_open_run_confirmation(self):
        st, body = self.get("/runs/new?trigger=manual&case_ids=" + quote("room.create,room.cancel") + "&case_ids=room.creation-limit")
        self.assertEqual(st, 200)
        self.assertIn("시나리오 화면에서 고른 케이스의 스크립트 3개", body)
        for cid in ("room.create", "room.cancel", "room.creation-limit"):
            self.assertIn(f'value="{cid}" checked', body)
        self.assertNotIn('value="room.apply-and-withdraw" checked', body)

    def test_run_page_grouped(self):
        rid = self.app.create_run(trigger="manual", operator="bebe", case_ids=["room.create", "auth.me-without-token"], sha=None, ref=None, pr_number=None,
                                  deploy_run_id=None, reason="", basis="", extra={}, session_hash=None, ip=None, notify=False, enqueue=False)
        st, body = self.get(f"/runs/{rid}")
        self.assertEqual(st, 200)
        self.assertLess(body.index("온라인 룸을 만들면"), body.index("시나리오에 연결되지 않은 스크립트"))


if __name__ == "__main__":
    unittest.main()
