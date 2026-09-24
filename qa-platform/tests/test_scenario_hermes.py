"""Hermes 로 케이스 채우기·케이스에서 스크립트 만들기 (docs/qa-platform-scenarios.md §7, §14 6단계)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import BadRequest  # noqa: E402
from qa import httpx, ui  # noqa: E402
from qa import scenarios as S  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402

GOOD = """```yaml
feature: 룸 생성
scenarios:
  - id: S1
    actor: qa-guest
    gates:
      R6: [G.room.update]
      R4: [G.room.create]
    variants:
      - key: happy
        kind: happy
        title: Hermes 가 바꾼 제목 (무시돼야 한다)
      - key: schedule-not-passed
        kind: reject
        at: R6
        title: 지난 시각으로는 룸을 만들 수 없어 E1407 로 거절된다
        then: E1407
        checks: [G.room.create#schedule-not-passed]
      - key: qna-type-only
        kind: reject
        at: R6
        title: 질의응답형이 아니면 거절된다
        checks: [G.room.create#qna-type-only]
        mode: manual
```"""
BAD = GOOD.replace("at: R6\n        title: 지난", "at: R999\n        title: 지난")
SCRIPT = """```yaml
cases:
  - id: room.create-headcount-range
    title: 최대 모집 인원이 최소 진행 인원보다 작으면 E1402 로 거절된다
    suite: sanity
    variant: 룸-생성/S9/엉뚱
    domains: [room]
    actor: qa-host
    covers: ["G.room.create#headcount-range"]
    steps:
      - name: 인원이 거꾸로인 룸 생성
        covers: ["G.room.create#headcount-range", "op.createRoom:E1402"]
        request:
          method: POST
          path: /v1/rooms
          body: { postingId: "{{fixture.postingId}}", jobRoleId: "{{fixture.jobRoleId}}", round: FIRST, type: JOB, method: ONLINE,
                  minParticipants: 4, maxParticipants: 2, schedule: { date: "{{date:+7}}", startTime: "14:00", durationMinutes: 90 },
                  title: "[QA] 인원 거꾸로 {{rand}}", resumeId: "{{fixture.qa-host.resumeId}}", resumePublic: true }
        expect: { status: 400, error_code: E1402 }
```"""


class Router:
    """GitHub 은 FakeGitHub 로, 그 밖(Hermes)은 준비한 답을 차례로."""

    def __init__(self, gh, replies):
        self.gh, self.replies, self.bodies = gh, list(replies), []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        if url.startswith("https://api.github.com/"):
            if "/contents/" not in url:                     # 배포 목록 같은 다른 GitHub API 는 오프라인
                return httpx.HttpResult(0, {}, "", 1, error="offline")
            return self.gh(method, url, headers=headers, body=body, timeout=timeout)
        self.bodies.append(body)
        text = self.replies.pop(0) if self.replies else ""
        return httpx.HttpResult(200, {}, json.dumps({"choices": [{"message": {"content": text}}]}), 1)


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class HermesScenarioTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        httpx.request = Router(self.gh, [])
        self.app = make_app(self.tmp.name)

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def reply(self, *texts):
        httpx.request = Router(self.gh, texts)
        return httpx.request

    def s1(self):
        return self.app.features["룸-생성"].scenario("S1")

    def test_fill_merges_without_overwriting(self):
        r = self.reply(GOOD)
        out = self.app.fill_scenarios("룸-생성", operator="bebe")
        self.assertEqual(out["added"], 2)
        prompt = r.bodies[0]["messages"][-1]["content"]
        for frag in ("# PRD 2장", "R143", "G.room.create#schedule-not-passed", "E1407", "아직 테스트가 없는 거절 조건", "headcount-range", "POST /v1/rooms"):
            self.assertIn(frag, prompt)
        s1 = self.s1()
        self.assertEqual(s1.variant("happy").title, "온라인 룸을 만들면 모집 중으로 열리고 상세의 방장이 본인이다")    # 사람이 쓴 것은 그대로
        self.assertEqual(s1.variant("schedule-not-passed").raw["written_by"], "hermes")
        self.assertEqual(s1.variant("qna-type-only").mode, "manual")
        self.assertEqual((s1.actor, s1.gates), ("qa-host", {"R6": ["G.room.create"], "R143": ["G.room.create_batch"], "R4": ["G.room.create"]}))   # 비어 있던 단계만
        put = self.gh.puts[-1]
        self.assertEqual(put["path"], "qa-platform/scenarios/룸-생성.yaml")
        self.assertIn("룸-생성 케이스 채우기 (Hermes", put["message"])
        d = self.app.store.get_draft(out["id"])
        self.assertEqual((d["kind"], d["source"], d["case_id"]), ("scenario", "hermes-scenario", "룸-생성"))
        self.assertTrue(d["prompt_hash"])
        ev = [x for x in self.app.store.list_events(10) if x["action"] == "hermes.generate"][0]
        self.assertEqual((ev["detail"]["source"], ev["detail"]["added"]), ("hermes-scenario", 2))
        ov, chk = self.app.scenario_view()
        f = next(x for x in ov if x["slug"] == "룸-생성")
        page = ui.variant_page(f, f["scenarios"][0], next(v for v in f["scenarios"][0]["variants"] if v["variant"].key == "schedule-not-passed"),
                               check=chk, tc_records={}, history=[], step=None, operator="bebe", hermes=True)
        self.assertIn("Hermes 작성", page)
        # 사람이 폼으로 한 번 저장하면 표시가 떨어진다 (§7)
        raw = dict(self.s1().variant("schedule-not-passed").raw)
        self.assertTrue(self.app.save_scenario({"feature": "룸 생성", "scenario": "S1", "action": "variant", "original_key": raw["key"], "variant": raw}, operator="bebe")["ok"])
        self.assertNotIn("written_by", self.s1().variant("schedule-not-passed").raw)
        # 한 번 더 채우면 새로 더할 것이 없다 — 커밋하지 않는다
        n = len(self.gh.puts)
        self.reply(GOOD)
        self.assertEqual(self.app.fill_scenarios("룸-생성", operator="bebe")["added"], 0)
        self.assertEqual(len(self.gh.puts), n)

    def test_fill_retries_once_then_fails(self):
        r = self.reply(BAD, GOOD)
        self.assertEqual(self.app.fill_scenarios("룸-생성", operator="bebe")["added"], 2)
        self.assertEqual(len(r.bodies), 2)
        self.assertIn("앞 출력이 검증에서 막혔다", r.bodies[1]["messages"][-1]["content"])
        self.assertIn("R999", r.bodies[1]["messages"][-1]["content"])
        acts = [x["action"] for x in self.app.store.list_events(10)]
        self.assertIn("hermes.rejected_by_validation", acts)
        n = len(self.gh.puts)
        self.reply(BAD.replace("schedule-not-passed", "past-schedule"), BAD.replace("schedule-not-passed", "past-schedule"))
        with self.assertRaises(BadRequest) as cm:
            self.app.fill_scenarios("룸-생성", operator="bebe")
        self.assertIn("검증을 못 넘겼다", str(cm.exception))
        self.assertEqual(len(self.gh.puts), n)
        self.reply("설명만 있고 YAML 이 없다", "여전히 없다")
        with self.assertRaises(BadRequest):
            self.app.fill_scenarios("룸-생성", operator="bebe")

    def test_fill_accepts_cases_key(self):
        """2026-09-24 실제 실패: Hermes 가 화면 이름을 따라 variants: 대신 cases: 로 썼다."""
        self.reply(GOOD.replace("    variants:", "    title: 시나리오 제목도 붙였다\n    cases:"))
        self.assertEqual(self.app.fill_scenarios("룸-생성", operator="bebe")["added"], 2)
        self.assertEqual(self.gh.puts[-1]["path"], "qa-platform/scenarios/룸-생성.yaml")       # 한글 파일 이름도 URL 에 인코딩돼 저장된다

    def test_fill_new_feature_creates_file(self):
        self.reply("```yaml\nfeature: 룸 탐색\nscenarios:\n  - id: S1\n    variants:\n      - {key: happy, kind: happy, title: 조건으로 룸을 찾는다}\n```")
        out = self.app.fill_scenarios("룸-탐색", operator="bebe")
        self.assertEqual(out["added"], 1)
        self.assertIn("qa-platform/scenarios/룸-탐색.yaml", self.gh.files)
        self.assertEqual(self.app.features["룸-탐색"].scenario("S1").variant("happy").raw["written_by"], "hermes")

    def test_script_from_variant(self):
        r = self.reply(SCRIPT)
        from qa import hermes
        self.app.jobs.asker = lambda cfg, system, prompt, *, session_prefix, **kw: hermes.chat(cfg, system, prompt, session_prefix=session_prefix)   # 작업도 같은 가짜 Hermes 로
        job = self.app.job_variant_script("룸-생성/S1/headcount-range", "bebe", sync=True)
        self.assertEqual(job.status, "done", job.error)
        prompt = r.bodies[0]["messages"][-1]["content"]
        for frag in ("이 스크립트가 구현할 케이스 룸-생성/S1/headcount-range", "분기·거절이 일어나는 단계: R6 입력 내용을 확인하고 룸을 생성한다.", "전제: minParticipants 4",
                     "setup.room-with-application", "G.room.create#headcount-range"):
            self.assertIn(frag, prompt)
        self.assertIn("uses: {setup: 카드 id", r.bodies[0]["messages"][0]["content"])
        c = self.app.cases["room.create-headcount-range"]
        self.assertEqual((c.variant, c.raw.get("written_by")), ("룸-생성/S1/headcount-range", "hermes"))    # variant 는 플랫폼이 박는다
        ov, _ = self.app.scenario_view()
        v = next(v for f in ov for s in f["scenarios"] for v in s["variants"] if v["id"] == "룸-생성/S1/headcount-range")
        self.assertEqual(v["state"], "auto")
        self.assertEqual(job.result["links"][0]["href"], "/cases/room.create-headcount-range")
        with self.assertRaises(BadRequest):
            self.app.job_variant_script("룸-생성/S1/pasted-posting", "bebe", sync=True)       # checks 없음
        with self.assertRaises(BadRequest):
            self.app.job_variant_script("룸-생성/S1/nope", "bebe", sync=True)

    def test_buttons(self):
        ov, chk = self.app.scenario_view()
        f = next(x for x in ov if x["slug"] == "룸-생성")
        page = ui.feature_page(f, check=chk, gate_names={}, prd_url=None, operator="bebe", hermes=True)
        self.assertIn('action="/features/fill"', page)
        self.assertIn('value="룸-생성"', page)
        off = ui.feature_page(f, check=chk, gate_names={}, prd_url=None, operator="bebe", hermes=False)
        self.assertIn("HERMES_API_KEY 가 없다", off)
        s1 = f["scenarios"][0]
        pasted = next(v for v in s1["variants"] if v["variant"].key == "pasted-posting")
        vp = ui.variant_page(f, s1, pasted, check=chk, tc_records={}, history=[], step=None, operator="bebe", hermes=True)
        self.assertIn('action="/features/script"', vp)
        self.assertIn("확인할 테스트 조건(checks)을 먼저 적는다", vp)


class MergeTest(unittest.TestCase):
    def test_merge_keeps_existing(self):
        text = (ROOT / "scenarios" / "룸-생성.yaml").read_text(encoding="utf-8")
        op = {"feature": "룸 생성", "scenario": "*", "action": "merge", "scenarios": [
            {"id": "S2", "actor": "qa-guest", "gates": {"R146": ["G.room.nope"], "R144": ["G.room.update"]},
             "variants": [{"key": "cancel", "kind": "extra", "title": "덮어쓰면 안 된다"}, {"key": "new-one", "kind": "extra", "title": "새것", "written_by": "hermes"}]}]}
        ft = S.parse_feature(yaml.safe_load(S.apply_op(text, op)), "룸-생성.yaml")
        s2 = ft.scenario("S2")
        self.assertEqual(s2.actor, "qa-host")
        self.assertEqual(s2.gates["R146"], ["G.room.update"])
        self.assertEqual(s2.gates["R144"], ["G.room.update"])
        self.assertEqual(s2.variant("cancel").kind, "branch")
        self.assertEqual([v.key for v in s2.variants][-1], "new-one")
        self.assertEqual(S.op_target(op), "룸-생성")


if __name__ == "__main__":
    unittest.main()
