"""시나리오 읽기 (docs/qa-platform-scenarios.md §5, §6.1, §12) — PRD 2장 파서, 파일 형식, 결정론 검증, 상태·테스트 없는 거절 규칙, 화면."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import editor, ui  # noqa: E402
from qa import scenarios as S  # noqa: E402
from qa.cases import CaseError, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.wiki import Wiki  # noqa: E402

WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"

PRD = """# 룸 생성

## 1. 개요

본문 `R90`

## 2. 사용자 시나리오

### 시나리오 S1: 방장이 룸을 만든다

1. 사용자가 룸 생성을 시작한다. `R1`
2. 채용 공고를 선택한다. `R2`
\t- 분기: 목록에 공고가 없으면 링크를 붙인다. `R3`

> 🔄 인용은 건너뛴다 `R77`

3. 입력 내용을 확인하고 룸을 생성한다. `R6`

### 시나리오 S2: 방장이 룸을 취소한다

1. 방장이 룸을 연다. `R10`
\t- 분기: 룸을 취소한다. `R11`

### 대표 사용자

- 누군가 `R99`

## 3. 기능

1. 다른 절 `R20`
"""

FEATURE = {
    "feature": "룸 생성",
    "scenarios": [
        {"id": "S1", "actor": "qa-host", "gates": {"R6": ["G.room.create"]},
         "variants": [
             {"key": "happy", "kind": "happy", "title": "만들면 열린다", "checks": ["C.room.create"]},
             {"key": "pasted", "kind": "branch", "at": "R3", "title": "링크로 만든다", "mode": "manual"},
             {"key": "headcount", "kind": "reject", "at": "R6", "title": "인원이 틀리면 E1402", "checks": ["G.room.create#headcount-range"]},
         ]},
    ],
}


class FakeCatalog:
    def __init__(self):
        self.records = {
            "C.room.create": {"id": "C.room.create", "kind": "success", "title": "룸 생성 성공"},
            "G.room.create#headcount-range": {"id": "G.room.create#headcount-range", "gate": "G.room.create", "kind": "reject", "title": "인원", "binding": {"error_code": "E1402"}},
            "G.room.create#schedule-not-passed": {"id": "G.room.create#schedule-not-passed", "gate": "G.room.create", "kind": "reject", "title": "지난 일정", "binding": {"error_code": "E1407"}},
            "G.room.create#title-required": {"id": "G.room.create#title-required", "gate": "G.room.create", "kind": "reject", "title": "제목", "binding": {}},
            "G.room.create#login-required": {"id": "G.room.create#login-required", "gate": "G.room.create", "kind": "reject", "title": "로그인", "binding": {"error_code": "E1102"}, "excluded": "화면에서만"},
            "G.room.cancel#host-only": {"id": "G.room.cancel#host-only", "gate": "G.room.cancel", "kind": "reject", "title": "방장만", "binding": {"error_code": "E1406"}},
            "C.room.cancel": {"id": "C.room.cancel", "kind": "success", "title": "취소", "excluded": "사람이 본다"},
        }

    def canonical(self, tid):
        return {"G.room.create#6": "G.room.create#headcount-range"}.get(tid, tid)


def script(cid, variant, covers):
    return parse_one(yaml.safe_dump({"id": cid, "title": "t", "suite": "sanity", "variant": variant, "covers": covers,
                                     "steps": [{"request": {"method": "GET", "path": "/v1/rooms"}}]}, allow_unicode=True))


class PrdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name, "raw", "product")
        d.mkdir(parents=True)
        (d / "룸-생성.md").write_text(PRD, encoding="utf-8")
        (d / "_index.md").write_text("# 목차", encoding="utf-8")
        self.wiki = Wiki(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_chapter2_parsed(self):
        self.assertEqual(self.wiki.prd_docs(), ["룸 생성"])
        sc = self.wiki.prd_scenarios("룸 생성")
        self.assertEqual([(s["id"], s["title"]) for s in sc], [("S1", "방장이 룸을 만든다"), ("S2", "방장이 룸을 취소한다")])
        self.assertEqual([(x["no"], x["req"], x["branch"], x["parent"]) for x in sc[0]["steps"]],
                         [(1, "R1", False, None), (2, "R2", False, None), (None, "R3", True, 2), (3, "R6", False, None)])   # 인용 줄·대표 사용자·다른 장은 빠진다
        self.assertEqual(sc[0]["steps"][2]["text"], "목록에 공고가 없으면 링크를 붙인다.")
        self.assertEqual(self.wiki.prd_scenarios("없는 문서"), [])

    @unittest.skipUnless((WIKI_DIR / "raw/product/룸-생성.md").is_file(), "위키 체크아웃 없음")
    def test_real_wiki_every_prd_has_s1(self):
        w = Wiki(WIKI_DIR)
        for doc in w.prd_docs():
            sc = w.prd_scenarios(doc)
            self.assertTrue(sc and sc[0]["id"] == "S1", doc)
            self.assertTrue(all(st["req"] for s in sc for st in s["steps"]), doc)      # 2장 줄은 모두 요구 id 가 있다


class FormatTest(unittest.TestCase):
    def bad(self, mutate, frag, file="<inline>"):
        d = json.loads(json.dumps(FEATURE, ensure_ascii=False))
        mutate(d)
        with self.assertRaises(S.ScenarioError) as cm:
            S.parse_feature(d, file)
        self.assertIn(frag, str(cm.exception))

    def test_ok_and_errors(self):
        ft = S.parse_feature(json.loads(json.dumps(FEATURE)), "룸-생성.yaml")
        self.assertEqual((ft.slug, ft.scenario("S1").variant("pasted").mode), ("룸-생성", "manual"))
        self.bad(lambda d: None, "파일 이름", file="room.yaml")
        self.bad(lambda d: d["scenarios"][0].update(id="1"), "S1, S2")
        self.bad(lambda d: d["scenarios"].append(dict(d["scenarios"][0])), "두 번")
        self.bad(lambda d: d["scenarios"][0]["variants"].append({"key": "happy", "kind": "extra", "title": "t"}), "겹친다")
        self.bad(lambda d: d["scenarios"][0]["variants"][2].pop("at"), "at")
        self.bad(lambda d: d["scenarios"][0]["variants"][0].update(kind="other"), "kind")
        self.bad(lambda d: d["scenarios"][0]["variants"][0].update(checks=["nope"]), "TC id")
        self.bad(lambda d: d["scenarios"][0].update(gates={"R6": ["room.create"]}), "게이트 id")
        self.bad(lambda d: d["scenarios"][0].update(gates={"6": ["G.room.create"]}), "요구 id")
        self.bad(lambda d: d["scenarios"][0]["variants"][0].update(mode="later"), "mode")

    def test_script_variant_format(self):
        self.assertEqual(script("room.x", "룸-생성/S1/happy", ["C.room.create"]).variant, "룸-생성/S1/happy")
        with self.assertRaises(CaseError):
            script("room.x", "룸-생성/happy", ["C.room.create"])
        st = editor.to_state({"id": "room.x", "variant": "룸-생성/S1/happy", "steps": []})
        self.assertEqual(st["variant"], "룸-생성/S1/happy")
        self.assertEqual(editor.from_state(dict(st, suite="sanity"))["variant"], "룸-생성/S1/happy")
        self.assertNotIn("variant", editor.from_state(dict(st, suite="sanity", variant=" ")))

    def test_load_dir(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "룸-생성.yaml").write_text(yaml.safe_dump(FEATURE, allow_unicode=True), encoding="utf-8")
            Path(d, "잘못.yaml").write_text("feature: 룸 탐색\n", encoding="utf-8")
            feats, errors = S.load_dir(Path(d))
            self.assertEqual(list(feats), ["룸-생성"])
            self.assertTrue(any("파일 이름" in x for x in errors))
        self.assertEqual(S.load_dir(Path("/nope")), ({}, []))


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name, "raw", "product")
        d.mkdir(parents=True)
        (d / "룸-생성.md").write_text(PRD, encoding="utf-8")
        Path(self.tmp.name, "wiki/policy/_src").mkdir(parents=True)
        Path(self.tmp.name, "wiki/policy/_src/상태-SSOT.yaml").write_text("gates: []\n", encoding="utf-8")   # available
        self.wiki = Wiki(self.tmp.name)
        self.cat = FakeCatalog()

    def tearDown(self):
        self.tmp.cleanup()

    def feats(self, mutate=None):
        d = json.loads(json.dumps(FEATURE, ensure_ascii=False))
        if mutate:
            mutate(d)
        return {"룸-생성": S.parse_feature(d, "룸-생성.yaml")}

    def test_clean(self):
        cases = {"room.a": script("room.a", "룸-생성/S1/happy", ["C.room.create"])}
        r = S.check(self.feats(), wiki=self.wiki, catalog=self.cat, cases=cases)
        self.assertEqual((r["errors"], r["warnings"]), ([], []))

    def test_errors(self):
        def m(d):
            d["scenarios"].append({"id": "S9", "variants": []})
            d["scenarios"][0]["gates"]["R10"] = ["G.room.nope"]
            d["scenarios"][0]["variants"][1]["at"] = "R11"          # S2 의 단계
            d["scenarios"][0]["variants"][0]["checks"].append("G.room.create#6")   # 옛 번호 id 는 별칭으로 받는다
            d["scenarios"][0]["variants"][0]["checks"].append("op.createRoom:200")
        cases = {"room.b": script("room.b", "룸-생성/S1/gone", ["C.room.create"])}
        r = S.check(self.feats(m), wiki=self.wiki, catalog=self.cat, cases=cases)
        text = "\n".join(r["errors"])
        for frag in ("S9 가 PRD 2장에 없다", "gates 의 R10 가 그 시나리오의 단계에 없다", "G.room.nope 가 TC 목록에 없다",
                     "S1/pasted 의 at R11", "op.createRoom:200 가 TC 목록에 없다", "variant 룸-생성/S1/gone 가 시나리오 파일에 없다"):
            self.assertIn(frag, text)
        self.assertNotIn("G.room.create#6", text)
        self.assertEqual(r["scripts"], {"room.b": ["variant 룸-생성/S1/gone 가 시나리오 파일에 없다"]})

    def test_warnings(self):
        def m(d):
            v = d["scenarios"][0]["variants"][2]
            v["checks"] = ["G.room.create#headcount-range", "G.room.cancel#host-only"]
        cases = {"room.c": script("room.c", "룸-생성/S1/headcount", ["G.room.create#headcount-range"]),
                 "room.d": script("room.d", "룸-생성/S1/headcount", ["G.room.create#headcount-range"])}
        r = S.check(self.feats(m), wiki=self.wiki, catalog=self.cat, cases=cases)
        text = "\n".join(r["warnings"])
        for frag in ("G.room.cancel#host-only 가 R6 단계의 gates 밖", "검사 2개를 한 변형이", "스크립트 2개가 구현한다", "covers 에 변형이 확인할 G.room.cancel#host-only 가 없다"):
            self.assertIn(frag, text)
        self.assertEqual(r["errors"], [])

    def test_state_rejects_overview(self):
        def m(d):
            d["scenarios"][0]["variants"].append({"key": "cancel", "kind": "extra", "title": "취소", "checks": ["C.room.cancel"]})
        feats = self.feats(m)
        cases = {"room.a": script("room.a", "룸-생성/S1/happy", ["C.room.create"])}
        last = {"room.a": {"verdict": "pass", "run_id": "r-1", "created_at": "2026-09-24T00:00:00Z"}}
        ov = S.overview(feats, wiki=self.wiki, catalog=self.cat, cases=cases, last=last)
        self.assertEqual([f["feature"] for f in ov], ["룸 생성"])
        f = ov[0]
        self.assertEqual([s["id"] for s in f["scenarios"]], ["S1", "S2"])            # PRD 에만 있는 S2 도 "변형 없음" 으로 실린다
        st = {v["variant"].key: v["state"] for v in f["scenarios"][0]["variants"]}
        self.assertEqual(st, {"happy": "auto", "pasted": "manual", "headcount": "untested", "cancel": "excluded"})
        self.assertEqual(f["counts"] | {}, {"auto": 1, "manual": 1, "excluded": 1, "untested": 1, "variants": 4, "rejects": 2, "pass": 1, "fail": 0})
        rej = f["scenarios"][0]["untested_rejects"]                                  # 확인 중인 headcount·제외된 login 은 빠진다
        self.assertEqual([(r["id"], r["mode"]) for r in rej], [("G.room.create#schedule-not-passed", "auto"), ("G.room.create#title-required", "manual")])
        self.assertEqual(f["scenarios"][1]["variants"], [])
        # 화면
        html = ui.scenario_tree(ov, errors=["x.yaml: 틀림"])
        for frag in ("룸 생성", "변형 없음", "테스트 없는 거절 규칙 2", "/features/%EB%A3%B8-%EC%83%9D%EC%84%B1/S1/happy", "시나리오 파일 오류"):
            self.assertIn(frag, html)
        chk = S.check(feats, wiki=self.wiki, catalog=self.cat, cases=cases)
        page = ui.feature_page(f, check=chk, gate_names={"G.room.create": "룸 생성 가능"}, prd_url="https://w/raw/product/룸-생성/")
        for frag in ("G.room.create#title-required", "사람이 확인으로 시작", "룸 생성 가능", "분기: 목록에 공고가 없으면"):
            self.assertIn(frag, page)
        v = f["scenarios"][0]["variants"][2]
        vp = ui.variant_page(f, f["scenarios"][0], v, check=chk, tc_records=self.cat.records, history=[], step={"text": "입력 내용을 확인하고 룸을 생성한다."})
        self.assertIn("R6", vp)
        self.assertIn("/cases/new?variant=%EB%A3%B8-%EC%83%9D%EC%84%B1%2FS1%2Fheadcount&tc=G.room.create%23headcount-range", vp)
        self.assertEqual([x["id"] for x in ui.variants_of_tc(ov, "C.room.create")], ["룸-생성/S1/happy"])


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "위키 체크아웃 없음")
class SeedTest(unittest.TestCase):
    """레포의 시나리오 파일(룸 생성, 룸 참여)과 옮긴 스크립트가 지금 위키·TC 목록과 맞는다 (§13)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE),
                               "QA_ACTORS": json.dumps({"qa-host": "m1"})}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_clean_and_migrated(self):
        self.assertEqual(self.app.scenario_errors, [])
        ov, chk = self.app.scenario_view()
        self.assertEqual((chk["errors"], chk["warnings"]), ([], []))
        self.assertEqual(sorted(self.app.features), ["룸-생성", "룸-참여-및-참여자-관리"])
        vmap = {c.id: c.variant for c in self.app.cases.values() if c.variant}
        self.assertEqual(vmap, {"room.create": "룸-생성/S1/happy", "room.creation-limit": "룸-생성/S1/creation-limit", "room.cancel": "룸-생성/S2/cancel",
                                "room.cancel-not-recruiting": "룸-생성/S2/room-recruiting", "room.apply-and-withdraw": "룸-참여-및-참여자-관리/S1/withdraw"})
        self.assertNotIn("room.create-and-cancel", self.app.cases)
        self.assertEqual(self.app.cases["room.cancel-not-recruiting"].covers, ["G.room.cancel#room-recruiting", "op.cancelRoom:E1410"])   # E1419 검사와 어긋나던 것을 바로잡았다
        f = next(x for x in ov if x["slug"] == "룸-생성")
        self.assertGreater(f["counts"]["rejects"], 0)
        self.assertEqual(len(ov), len(self.app.wiki.prd_docs()))
        ctx = self.app.editor_context()
        self.assertIn("룸-생성/S1/happy", [v["id"] for v in ctx["variants"]])


if __name__ == "__main__":
    unittest.main()
