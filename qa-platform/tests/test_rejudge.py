"""'사람이 확인' 줄이기 (docs/qa-platform-v2.md §16) — Hermes 가 API 연결·에러 코드·API 없음을 채우고, 수동 케이스를 다시 판정한다."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

from app import BadRequest  # noqa: E402
from qa import binding_ai, httpx, runner  # noqa: E402
from qa import scenarios as S  # noqa: E402
from qa.catalog import load_inputs  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402


class Op:
    def __init__(self, method, path, errors=()):
        self.method, self.path, self.summary, self.errors = method, path, "", {c: {} for c in errors}


class Spec:
    ops = {"createRoom": Op("POST", "/v1/rooms", ["E1402", "E400"]), "memberWithdraw": Op("DELETE", "/v1/members/me", ["E1014"]),
           "createQaMember": Op("POST", "/v1/dev/members")}


class UnitTest(unittest.TestCase):
    def test_validate_keeps_only_real_ops_and_codes(self):
        cmds = [{"id": "C.member.withdraw"}, {"id": "C.participation.kick"}, {"id": "C.x.y"}]
        checks = [{"id": "G.member.withdraw#a", "command": "C.member.withdraw"}, {"id": "G.room.create#b", "command": "C.room.create"},
                  {"id": "G.room.create#c", "command": "C.room.create"}]
        out = {"commands": {"C.member.withdraw": "memberWithdraw", "C.x.y": ["createQaMember"], "C.nope": ["createRoom"]},
               "checks": {"G.member.withdraw#a": "E1014", "G.room.create#b": "E1402", "G.room.create#c": "E9999"},
               "no_api": {"C.participation.kick": "참여자를 내보내는 끝점이 없다"}}
        acc, why = binding_ai.validate(out, spec=Spec(), commands=cmds, checks=checks, current={"commands": {"C.room.create": ["createRoom"]}})
        self.assertEqual(acc["commands"], {"C.member.withdraw": ["memberWithdraw"]})              # dev 전용 API·목록 밖 명령은 버린다
        self.assertEqual(acc["checks"], {"G.member.withdraw#a": "E1014", "G.room.create#b": "E1402"})  # 그 API 의 에러 예시에 있는 코드만
        self.assertEqual(acc["no_api"], {"C.participation.kick": "참여자를 내보내는 끝점이 없다"})
        self.assertTrue(any("E9999" in w for w in why))

    def test_apply_appends_and_keeps_comments(self):
        src = ("# SSOT ↔ API 바인딩. 테스트용 고정 본문\n\ncommands:\n  # 룸\n  C.room.create: createRoom\n\n"
               "# 게이트 검사 → 에러 코드\nchecks:\n  \"G.room.create#login-required\": E1102\n")
        out = binding_ai.apply(src, {"commands": {"C.member.withdraw": ["memberWithdraw"]}, "checks": {"G.member.withdraw#a": "E1014"},
                                     "no_api": {"C.participation.kick": "끝점이 없다"}})
        self.assertTrue(out.startswith(src.split("\n", 1)[0]))
        d = yaml.safe_load(out)
        self.assertEqual((d["commands"]["C.member.withdraw"], d["checks"]["G.member.withdraw#a"], d["no_api"]["C.participation.kick"]),
                         ("memberWithdraw", "E1014", "끝점이 없다"))
        self.assertEqual(d["commands"]["C.room.create"], "createRoom")                           # 있던 줄은 그대로
        self.assertIn("# SSOT ↔ API 바인딩", out)
        tmp = tempfile.TemporaryDirectory()
        Path(tmp.name, "bindings.yaml").write_text(out, encoding="utf-8")
        self.assertEqual(load_inputs(Path(tmp.name)).bindings["no_api"], {"C.participation.kick": "끝점이 없다"})
        tmp.cleanup()

    def test_status_4xx(self):
        checks = runner.evaluate({"status": "4xx", "result": "ERROR"}, 409, {"result": "ERROR", "error": {"code": "E1999"}})
        self.assertTrue(all(c["ok"] for c in checks))
        self.assertFalse(runner.evaluate({"status": "4xx"}, 200, {})[0]["ok"])


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            text = p.read_text(encoding="utf-8")
            # 운영 데이터는 이미 다시 판정됐다. 판정 전 모양(수동 이유 없음)으로 되돌려 흐름을 본다
            text = re.sub(r"\n +manual_reason: [a-z_]+", "", text)
            if p.stem == "룸-탐색":
                text = text.replace("checks: [G.application.enter#login-required]\n", "checks: [G.application.enter#login-required]\n        mode: manual\n")
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = text
        httpx.request = self.gh
        self.app = make_app(self.tmp.name)
        self.app.cfg.operators = ["bebe"]

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def manual(self):
        return {f"{slug}/{s.id}/{v.key}": v for slug, ft in self.app.features.items() for s in ft.scenarios for v in s.variants if v.mode == "manual"}

    def test_rejudge(self):
        before = self.manual()
        self.assertIn("회원-및-프로필/S2/own-profile-only", before)
        cmds, checks = self.app.binding_targets()
        self.assertTrue(cmds or checks)

        def ask(system, prompt, prefix):
            if system == binding_ai.SYSTEM:
                kick = next((c["id"] for c in cmds if "kick" in c["id"]), None)
                return "```json\n" + json.dumps({"commands": {}, "checks": {}, "no_api": {kick: "참여자를 내보내는 끝점이 없다"} if kick else {}}) + "\n```"
            pend = [ln.split(" · ")[0][2:] for ln in prompt.split("\n") if ln.startswith("- ") and "/S" in ln.split(" · ")[0]]
            out = {}
            for vid in pend:
                if vid.endswith("own-profile-only"):
                    out[vid] = {"mode": "manual", "manual_reason": "structural", "why": "/me 만 받는다"}
                elif vid.endswith("/pasted-posting"):
                    out[vid] = {"mode": "manual", "manual_reason": "ui"}
                elif vid == "룸-탐색/S1/login-required":
                    out[vid] = {"mode": "auto", "checks": ["G.application.submit#login-required"]}   # 다른 게이트로 바꾸려 한다
            return "```json\n" + json.dumps(out) + "\n```"
        with self.assertRaises(BadRequest):
            self.app.rejudge_manual(operator="", ask=ask)
        res = self.app.rejudge_manual(operator="bebe", ask=ask)
        after = self.manual()
        self.assertEqual(after["회원-및-프로필/S2/own-profile-only"].manual_reason, "structural")
        self.assertIn("룸-탐색/S1/login-required", after)                                       # 확인 대상을 다른 규칙으로 바꾸는 판정은 버린다
        self.assertEqual(after["룸-탐색/S1/login-required"].checks, ["G.application.enter#login-required"])
        kicks = [k for k in after if "/kick." in k or k.endswith("/target-joined") or k.endswith("/target-not-host")]
        if any("kick" in c["id"] for c in cmds):
            self.assertTrue(kicks and all(after[k].manual_reason == "no_api" for k in kicks))     # API 없음은 결정론으로
            self.assertIn("no_api:", self.gh.files["qa-platform/catalog/bindings.yaml"])
        self.assertTrue(res["changed"])
        ov, _ = self.app.scenario_view()
        st = {v["id"]: v["state"] for f in ov for s in f["scenarios"] for v in s["variants"]}
        self.assertEqual(st["회원-및-프로필/S2/own-profile-only"], "na")
        acts = [x["action"] for x in self.app.store.list_events(40)]
        self.assertIn("scenario.rejudge", acts)


if __name__ == "__main__":
    unittest.main()
