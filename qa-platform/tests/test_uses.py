"""전제 재사용 `uses:` (docs/qa-platform-scenarios.md §8) — 로더 펼치기·검증·스냅샷·판정·커버리지·폼·화면."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import editor, httpx, ui  # noqa: E402
from qa.cases import audit, bake_inputs, load_dir, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"

CARD_OPEN = {
    "id": "setup.open", "title": "모집 중인 룸", "suite": "setup", "actor": "qa-host",
    "inputs": {"title": {"label": "룸 제목", "default": "[QA] 준비", "required": True}, "size": {"label": "정원", "default": 4}},
    "outputs": ["roomId"],
    "steps": [{"name": "룸 생성", "request": {"method": "POST", "path": "/v1/rooms", "body": {"title": "{{input.title}} {{rand}}", "maxParticipants": "{{input.size}}"}},
               "expect": {"status": 200}, "save": {"roomId": "data.roomId"}}],
}
CARD_APPLIED = {     # 카드끼리 uses — 바깥 카드의 입력을 안쪽 카드로 넘긴다
    "id": "setup.applied", "title": "신청 들어온 룸", "suite": "setup", "actor": "qa-host",
    "uses": {"setup": "setup.open", "with": {"title": "{{input.title}}"}},
    "inputs": {"title": {"label": "룸 제목", "default": "[QA] 신청 룸"}},
    "outputs": ["roomId", "applicationId"],
    "steps": [{"name": "참가자 신청", "actor": "qa-guest", "request": {"method": "POST", "path": "/v1/rooms/{{roomId}}/applications", "body": {"note": "[QA]"}},
               "expect": {"status": 201}, "save": {"applicationId": "data.applicationId"}}],
}
SCRIPT = {
    "id": "room.confirm-under-min", "title": "최소 인원 미달이면 확정이 거절된다", "suite": "sanity", "actor": "qa-guest",
    "uses": {"setup": "setup.applied", "with": {"title": "[QA] 확정 거절"}},
    "steps": [
        {"name": "수락 없이 확정", "actor": "qa-host", "request": {"method": "POST", "path": "/v1/rooms/{{roomId}}/confirmation"}, "expect": {"status": 409}},
        {"name": "정리", "actor": "qa-host", "covers": ["op.cancelRoom:200"], "request": {"method": "POST", "path": "/v1/rooms/{{roomId}}/cancellation"}, "expect": {"status": 200}},
    ],
}


def write_cases(d: Path, items: list[dict]):
    d.mkdir(parents=True, exist_ok=True)
    (d / "all.yaml").write_text(yaml.safe_dump({"cases": items}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def clone(x):
    return json.loads(json.dumps(x, ensure_ascii=False))


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, items):
        write_cases(self.dir, items)
        return load_dir(self.dir)

    def test_expands_nested_cards_in_front(self):
        cases, errors = self.load([CARD_OPEN, CARD_APPLIED, SCRIPT])
        self.assertEqual(errors, [])
        c = cases["room.confirm-under-min"]
        self.assertEqual([s["name"] for s in c.steps], ["룸 생성", "참가자 신청", "수락 없이 확정", "정리"])
        self.assertEqual([s.get("given") for s in c.steps], ["setup.applied", "setup.applied", None, None])
        self.assertEqual([s["actor"] for s in c.steps[:2]], ["qa-host", "qa-guest"])      # 카드 actor 가 박힌다 — 스크립트 기본(qa-guest)이 새지 않는다
        self.assertEqual(c.steps[0]["request"]["body"]["title"], "[QA] 확정 거절 {{rand}}")   # with 가 두 겹을 지나 박힌다
        self.assertEqual(c.steps[0]["request"]["body"]["maxParticipants"], 4)                 # 안 넘긴 입력은 기본값, 타입 유지
        self.assertEqual(c.covers, ["op.cancelRoom:200"])                                     # 전제 단계는 커버리지에 없다
        self.assertEqual(len(c.own_steps), 2)
        self.assertIn("uses", c.raw)                                                          # 파일 모양은 펼치지 않는다
        self.assertEqual(len(c.raw["steps"]), 2)
        self.assertNotIn("given", c.to_yaml())
        # 카드 자신도 펼쳐진다 (준비 작업 화면에서 버튼으로 돌 때)
        applied = cases["setup.applied"]
        self.assertEqual([s.get("given") for s in applied.steps], ["setup.open", None])
        self.assertEqual(applied.steps[0]["request"]["body"]["title"], "{{input.title}} {{rand}}")
        baked = bake_inputs(applied, {"title": "[QA] 버튼"})
        self.assertEqual(baked.steps[0]["request"]["body"]["title"], "[QA] 버튼 {{rand}}")   # 바깥 카드 입력이 전제 단계까지 들어간다
        self.assertEqual(baked.outputs, ["roomId", "applicationId"])

    def test_shorthand_and_snapshot_does_not_expand_twice(self):
        s = clone(SCRIPT)
        s["uses"] = "setup.open"
        cases, errors = self.load([CARD_OPEN, s])
        self.assertEqual(errors, [])
        c = cases[s["id"]]
        self.assertEqual(c.uses, {"setup": "setup.open"})
        snap = c.run_yaml()
        self.assertIn("given_by", snap)
        self.assertNotIn("uses:", snap)
        again = parse_one(snap, "run")
        self.assertEqual(len(again.steps), 3)
        self.assertEqual(again.steps[0]["given"], "setup.open")
        # 카드가 바뀌면 스크립트 해시도 바뀐다 (실행한 단계가 달라지므로)
        card2 = clone(CARD_OPEN)
        card2["steps"][0]["expect"]["status"] = 201
        cases2, _ = self.load([card2, s])
        self.assertNotEqual(cases2[s["id"]].hash, c.hash)

    def test_errors(self):
        def err(items, frag):
            cases, errors = self.load(items)
            self.assertTrue(any(frag in x for x in errors), (frag, errors))
            return cases
        s = clone(SCRIPT)
        s["uses"] = {"setup": "setup.nope"}
        self.assertNotIn(s["id"], err([CARD_OPEN, s], "테스트 데이터 만들기 카드 setup.nope 가 없다"))
        s["uses"] = {"setup": "room.other"}
        other = {"id": "room.other", "title": "t", "suite": "manual", "steps": [{"request": {"method": "GET", "path": "/v1/rooms"}}]}
        err([other, s], "suite setup")
        s["uses"] = {"setup": "setup.open", "with": {"nope": 1}}
        err([CARD_OPEN, s], "입력칸이 아니다")
        s["uses"] = {"setup": "setup.open", "with": {"title": "{{input.title}}"}}          # sanity 에는 입력칸이 없다
        err([CARD_OPEN, s], "input.*")
        req = clone(CARD_OPEN)
        req["inputs"]["title"] = {"label": "룸 제목", "required": True}
        s["uses"] = {"setup": "setup.open"}
        err([req, s], "필수")
        a, b = clone(CARD_APPLIED), clone(CARD_OPEN)
        b["uses"] = {"setup": "setup.applied"}
        err([a, b], "돌고 돈다")
        s["uses"] = {"setup": "setup.open", "x": 1}
        err([CARD_OPEN, s], "모르는 키")
        s["uses"] = clone(SCRIPT["uses"])
        s["steps"][0]["given"] = "setup.open"
        err([CARD_OPEN, CARD_APPLIED, s], "로더가 붙인다")
        bad_out = clone(CARD_APPLIED)
        bad_out["outputs"] = ["roomId", "nope"]
        err([CARD_OPEN, bad_out], "outputs")

    def test_audit_ignores_given_steps(self):
        s = clone(SCRIPT)
        s["covers"] = ["op.createRoom:200"]          # 룸 생성은 전제 카드가 부른다 — 이 스크립트가 확인한 것이 아니다
        cases, _ = self.load([CARD_OPEN, CARD_APPLIED, s])
        c = cases[s["id"]]

        class Cat:
            records = {
                "op.createRoom:200": {"id": "op.createRoom:200", "layer": "contract", "kind": "success", "expect_hint": {"method": "POST", "path": "/v1/rooms"}},
                "op.cancelRoom:200": {"id": "op.cancelRoom:200", "layer": "contract", "kind": "success", "expect_hint": {"method": "POST", "path": "/v1/rooms/{roomId}/cancellation"}},
            }
        audit({c.id: c}, Cat())
        self.assertTrue(any("op.createRoom:200" in x and "부르는 단계가 없다" in x for x in c.audit["errors"]), c.audit)
        self.assertFalse(any("op.cancelRoom:200" in x for x in c.audit["errors"]))


class FakeHttp:
    def __init__(self, apply_status=201):
        self.sent = []
        self.apply_status = apply_status

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.sent.append((method, url, body))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok"}}), 3)
        if method == "POST" and url.endswith("/v1/rooms"):
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"roomId": "room-9"}}), 10)
        if url.endswith("/applications"):
            return httpx.HttpResult(self.apply_status, {}, json.dumps({"result": "SUCCESS", "data": {"applicationId": "app-1"}}), 5)
        if url.endswith("/confirmation"):
            return httpx.HttpResult(409, {}, json.dumps({"result": "ERROR", "error": {"code": "E1431"}}), 5)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cdir = Path(self.tmp.name, "cases")
        write_cases(cdir, [CARD_OPEN, CARD_APPLIED, SCRIPT])
        env = {"QA_DATA_DIR": self.tmp.name, "QA_CASES_DIR": str(cdir), "QA_SPEC_FILE": str(SPEC_FIXTURE),
               "QA_ACTORS": json.dumps({"qa-host": "m1", "qa-guest": "m2"}), "QA_PUBLIC_URL": "https://qa.test"}
        self.app = App(Config(env))
        self._orig = httpx.request

    def tearDown(self):
        httpx.request = self._orig
        self.tmp.cleanup()

    def run_script(self, http):
        httpx.request = http
        rid = self.app.create_run(trigger="manual", operator="bebe", case_ids=[SCRIPT["id"]], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                                  reason="", basis="", extra={}, session_hash=None, ip=None, notify=False, enqueue=False)
        self.app.runner.execute(rid)
        rc = self.app.store.list_run_cases(rid)[0]
        return rid, rc, self.app.store.list_steps(rc["id"])

    def test_given_steps_run_first(self):
        self.assertEqual(self.app.case_errors, [])
        http = FakeHttp()
        rid, rc, steps = self.run_script(http)
        self.assertEqual([s["name"] for s in steps], ["룸 생성", "참가자 신청", "수락 없이 확정", "정리"])
        self.assertEqual(rc["verdict"], "pass")
        self.assertIn("given_by", rc["case_yaml"])                                # 스냅샷에 펼친 단계가 남는다
        self.assertEqual([s["request"].get("given") for s in steps], ["setup.applied", "setup.applied", None, None])
        self.assertEqual([s["request"]["actor"] for s in steps], ["qa-host", "qa-guest", "qa-host", "qa-host"])
        sent_room = [b for m, u, b in http.sent if u.endswith("/v1/rooms")][0]
        self.assertTrue(sent_room["title"].startswith("[QA] 확정 거절 "))
        run = self.app.store.get_run(rid)
        page = ui.run_detail(run, [rc], {rc["id"]: steps}, operators=["bebe"], operator="bebe", checklist=[], public_url="")
        self.assertIn('<details class="given" >', page)                           # 통과하면 접혀 있다

    def test_own_failure_is_fail(self):
        class Ok(FakeHttp):
            def __call__(self, method, url, headers=None, body=None, timeout=30):
                if url.endswith("/confirmation"):
                    return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)
                return super().__call__(method, url, headers, body, timeout)
        rid, rc, steps = self.run_script(Ok())
        self.assertEqual(rc["verdict"], "fail")                                   # 확인하려던 규칙이 틀린 것 — 오류가 아니다
        self.assertNotIn("전제", rc["error"])

    def test_given_failure_is_error(self):
        rid, rc, steps = self.run_script(FakeHttp(apply_status=409))
        self.assertEqual(rc["verdict"], "error")
        self.assertIn("전제 준비 실패(setup.applied)", rc["error"])
        self.assertEqual(len(steps), 2)
        run = self.app.store.get_run(rid)
        self.assertEqual(run["verdict"], "error")
        page = ui.run_detail(run, [rc], {rc["id"]: steps}, operators=["bebe"], operator="bebe", checklist=[], public_url="")
        self.assertIn("테스트 데이터 만들기 카드", page)
        self.assertIn('class="given" open', page)                                # 실패하면 펼쳐 보인다

    def test_setup_run_of_nested_card(self):
        httpx.request = FakeHttp()
        rid = self.app.setup_run("setup.applied", {"title": "[QA] 버튼"}, operator="bebe", session_hash=None, ip=None)
        run = self.app.store.get_run(rid)
        self.assertEqual(run["verdict"], "pass")
        self.assertEqual(self.app.setup_outputs(run), {"roomId": "room-9", "applicationId": "app-1"})

    def test_case_page_and_editor(self):
        c = self.app.cases[SCRIPT["id"]]
        page = ui.case_detail(c, [])
        self.assertIn('href="/cases/setup.applied"', page)
        self.assertIn("단계 2개를 먼저 돈다", page)
        ctx = self.app.editor_context()
        applied = [x for x in ctx["setups"] if x["id"] == "setup.applied"][0]
        self.assertEqual((applied["outputs"], applied["uses"]), (["roomId", "applicationId"], "setup.open"))
        # 폼 상태 왕복
        st = editor.to_state(c.raw)
        self.assertEqual(st["uses"], {"setup": "setup.applied", "with": {"title": "[QA] 확정 거절"}})
        self.assertEqual(len(st["steps"]), 2)
        raw = editor.from_state(st)
        self.assertEqual(raw["uses"], {"setup": "setup.applied", "with": {"title": "[QA] 확정 거절"}})
        st["uses"]["with"]["title"] = ""                                          # 비우면 with 에서 빠진다 (카드 기본값)
        self.assertEqual(editor.from_state(st)["uses"], {"setup": "setup.applied"})
        self.assertEqual(editor.unsupported(c.raw), [])
        # 폼 검증은 지금 스크립트로 uses 를 펼쳐 본다
        st["uses"]["setup"] = "setup.nope"
        st["id"] = "room.new-one"
        res = self.app.form_case(st, mode="new", original_id=None, draft_id=None, operator="bebe", dry=True)
        self.assertFalse(res["ok"])
        self.assertTrue(any("setup.nope" in x for x in res["errors"]), res["errors"])
        st["uses"]["setup"] = "setup.open"
        res = self.app.form_case(st, mode="new", original_id=None, draft_id=None, operator="bebe", dry=True)
        self.assertTrue(res["ok"], res["errors"])
        self.assertIn("uses:", res["yaml"])


if __name__ == "__main__":
    unittest.main()
