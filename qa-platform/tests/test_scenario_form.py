"""시나리오 폼 (docs/qa-platform-scenarios.md §9, §14 5단계) — 변경 적용, 검증으로 막기, main 커밋, 지우면 스크립트를 시나리오 밖으로."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from qa import httpx, ui  # noqa: E402
from qa import scenarios as S  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402

TEXT = (ROOT / "scenarios" / "룸-생성.yaml").read_text(encoding="utf-8")
NEW_REJECT = {"key": "schedule-not-passed", "kind": "reject", "at": "R6", "title": "지난 시각이면 E1407 로 거절된다",
              "given": "", "then": "E1407", "checks": "G.room.create#schedule-not-passed", "mode": "auto"}


def op(action, **kw):
    return {"feature": "룸 생성", "scenario": kw.pop("scenario", "S1"), "action": action, **kw}


class ApplyOpTest(unittest.TestCase):
    def feature(self, text):
        return S.parse_feature(yaml.safe_load(text), "룸-생성.yaml")

    def test_add_edit_delete_variant(self):
        out = S.apply_op(TEXT, op("variant", variant=NEW_REJECT))
        self.assertTrue(out.startswith("# 「룸 생성」"))                                  # 머리 주석이 남는다
        s1 = self.feature(out).scenario("S1")
        v = s1.variant("schedule-not-passed")
        self.assertEqual((v.kind, v.at, v.checks, v.mode, v.given), ("reject", "R6", ["G.room.create#schedule-not-passed"], "auto", ""))
        self.assertNotIn("mode: auto", out)                                               # 기본값·빈 칸은 적지 않는다
        self.assertEqual(len(s1.variants), 6)
        out2 = S.apply_op(out, op("variant", original_key="schedule-not-passed", variant=dict(NEW_REJECT, title="고친 제목", mode="manual")))
        v2 = self.feature(out2).scenario("S1").variant("schedule-not-passed")
        self.assertEqual((v2.title, v2.mode), ("고친 제목", "manual"))
        self.assertEqual([x.key for x in self.feature(out2).scenario("S1").variants][-1], "schedule-not-passed")   # 제자리에서 바뀐다
        out3 = S.apply_op(out2, op("variant-delete", key="schedule-not-passed"))
        self.assertEqual(out3, TEXT)                                                      # 넣고 지우면 원래 파일 그대로

    def test_scenario_gates_keep_variants_and_new_scenario(self):
        out = S.apply_op(TEXT, op("scenario", actor="qa-guest", gates={"R6": ["G.room.create"], "R4": ["G.room.create"], "R5": []}))
        s1 = self.feature(out).scenario("S1")
        self.assertEqual((s1.actor, s1.gates), ("qa-guest", {"R6": ["G.room.create"], "R4": ["G.room.create"]}))
        self.assertEqual(len(s1.variants), 5)
        out = S.apply_op(None, {"feature": "룸 탐색", "scenario": "S1", "action": "variant", "variant": {"key": "happy", "kind": "happy", "title": "조건으로 찾는다"}})
        ft = S.parse_feature(yaml.safe_load(out), "룸-탐색.yaml")
        self.assertEqual((ft.feature, [v.key for v in ft.scenario("S1").variants]), ("룸 탐색", ["happy"]))
        self.assertTrue(out.startswith("# 「룸 탐색」"))
        out = S.apply_op(TEXT, op("scenario-delete", scenario="S2"))
        self.assertEqual([s.id for s in self.feature(out).scenarios], ["S1"])

    def test_errors(self):
        for o, frag in ((op("variant", variant=dict(NEW_REJECT, key="happy")), "이미 있다"),
                        (op("variant", original_key="gone", variant=NEW_REJECT), "그사이 지워졌다"),
                        (op("variant", variant=dict(NEW_REJECT, key="new")), "화면 주소"),
                        (op("variant", variant=dict(NEW_REJECT, at="")), "at"),
                        (op("variant-delete", key="nope"), "없다"),
                        (op("variant-delete", scenario="S7", key="x"), "없다")):
            with self.assertRaises(S.ScenarioError) as cm:
                S.apply_op(TEXT, o)
            self.assertIn(frag, str(cm.exception))


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        httpx.request = self.gh
        self.app = make_app(self.tmp.name)

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_save_variant_commits_and_applies(self):
        self.assertEqual(self.app.scenarios_dir, self.app.repo.local / "scenarios")
        out = self.app.save_scenario(op("variant", variant=NEW_REJECT), operator="bebe")
        self.assertTrue(out["ok"], out)
        put = self.gh.puts[-1]
        self.assertEqual(put["path"], "qa-platform/scenarios/룸-생성.yaml")
        self.assertIn("룸-생성/S1/schedule-not-passed 추가", put["message"])
        self.assertIn("[skip ci]", put["message"])
        self.assertIn("schedule-not-passed", self.app.features["룸-생성"].scenario("S1").raw["variants"][-1]["key"])   # 플랫폼에 바로
        d = self.app.store.get_draft(out["id"])
        self.assertEqual((d["kind"], d["case_id"], d["status"], d["tc_ids"]), ("scenario", "룸-생성/S1/schedule-not-passed", "approved", ["G.room.create#schedule-not-passed"]))
        self.assertIn("scenario.save", [x["action"] for x in self.app.store.list_events(5)])
        self.assertEqual(self.app.change_link(out)["href"], "/features/%EB%A3%B8-%EC%83%9D%EC%84%B1/S1/schedule-not-passed")
        ov, _ = self.app.scenario_view()
        rej = [r["id"] for f in ov if f["slug"] == "룸-생성" for s in f["scenarios"] if s["id"] == "S1" for r in s["untested_rejects"]]
        self.assertNotIn("G.room.create#schedule-not-passed", rej)                          # 이제 테스트 없는 거절 규칙이 아니다

    def test_validation_blocks_save(self):
        n = len(self.gh.puts)
        out = self.app.save_scenario(op("variant", variant=dict(NEW_REJECT, at="R146")), operator="bebe")     # S2 의 단계
        self.assertFalse(out["ok"])
        self.assertTrue(any("R146" in x for x in out["errors"]), out)
        out = self.app.save_scenario(op("variant", variant=dict(NEW_REJECT, checks="G.room.create#nope")), operator="bebe")
        self.assertTrue(any("TC 목록에 없다" in x for x in out["errors"]), out)
        out = self.app.save_scenario(op("scenario", gates={"R6": ["G.room.nope"]}), operator="bebe")
        self.assertFalse(out["ok"])
        self.assertEqual(len(self.gh.puts), n)                                              # 커밋하지 않았다

    def test_concurrent_edit_is_kept(self):
        """폼을 연 뒤 main 이 바뀌어도 그 변경은 사라지지 않는다 — 변경 하나를 최신 파일에 다시 적용한다."""
        other = S.apply_op(self.gh.files["qa-platform/scenarios/룸-생성.yaml"], op("variant", scenario="S2", variant={"key": "update-host-only", "kind": "reject", "at": "R146", "title": "방장만", "checks": "G.room.update#host-only"}))
        self.gh.files["qa-platform/scenarios/룸-생성.yaml"] = other
        out = self.app.save_scenario(op("variant", variant=NEW_REJECT), operator="bebe")
        self.assertTrue(out["ok"], out)
        text = self.gh.files["qa-platform/scenarios/룸-생성.yaml"]
        self.assertIn("update-host-only", text)
        self.assertIn("schedule-not-passed", text)

    def test_delete_unlinks_scripts(self):
        before = self.app.cases["room.cancel-not-recruiting"].reviewed
        out = self.app.save_scenario(op("variant-delete", scenario="S2", key="room-recruiting"), operator="bebe", note="다시 만든다")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["unlinked"], ["room.cancel-not-recruiting"])
        paths = [p["path"] for p in self.gh.puts[-2:]]
        self.assertEqual(paths, ["qa-platform/scenarios/룸-생성.yaml", "qa-platform/cases/room.yaml"])
        self.assertIn("다시 만든다", self.gh.puts[-2]["message"])
        c = self.app.cases["room.cancel-not-recruiting"]
        self.assertIsNone(c.variant)                                                        # 스크립트는 남고 시나리오 밖으로
        self.assertEqual(c.reviewed, before)
        self.assertIsNone(self.app.features["룸-생성"].scenario("S2").variant("room-recruiting"))
        acts = [x["action"] for x in self.app.store.list_events(5)]
        self.assertIn("scenario.delete", acts)
        _, chk = self.app.scenario_view()
        self.assertEqual(chk["errors"], [])
        out = self.app.save_scenario(op("scenario-delete", scenario="S2"), operator="bebe")
        self.assertEqual(out["unlinked"], ["room.cancel"])
        self.assertIsNone(self.app.features["룸-생성"].scenario("S2"))

    def test_pages(self):
        ov, chk = self.app.scenario_view()
        f = next(x for x in ov if x["slug"] == "룸-생성")
        s1 = f["scenarios"][0]
        page = ui.feature_page(f, check=chk, gate_names=self.app.gate_names(), prd_url=None, operator="bebe")
        self.assertIn("/features/%EB%A3%B8-%EC%83%9D%EC%84%B1/S1/new?kind=reject&amp;at=R6&amp;key=account-active", page)   # [변형으로 추가]
        self.assertIn("시나리오 고치기", page)
        self.assertIn("key=update.host-only", page)                                          # 게이트 둘에 같은 key 면 게이트 이름을 앞에
        self.assertIn("key=cancel.host-only", page)
        self.assertIn('action="/features/delete"', page)
        vf = ui.variant_form(f, s1, {"kind": "reject", "at": "R6", "key": "account-active", "checks": ["G.room.create#account-active"]}, mode="new",
                             operator="bebe", tc_options=self.app.tc_options())
        for frag in ('name="key"', 'value="account-active"', '<option value="R6" selected>', 'G.room.create#account-active', 'action="/features/save"'):
            self.assertIn(frag, vf)
        sf = ui.scenario_form(f, s1, operator="bebe", actors=[], gate_options=sorted(self.app.gate_names().items()))
        self.assertIn('<option value="qa-host" selected>', sf)                               # 계정 목록에 없어도 지금 값은 지킨다
        self.assertIn('name="gate.R6" class="mono" list="dl-scn-gates" value="G.room.create"', sf)
        v = s1["variants"][0]
        vp = ui.variant_page(f, s1, v, check=chk, tc_records={}, history=[], step=None, operator="bebe")
        self.assertIn("/S1/happy/edit", vp)
        self.assertIn("room.create 는 지우지 않는다", vp)


if __name__ == "__main__":
    unittest.main()
