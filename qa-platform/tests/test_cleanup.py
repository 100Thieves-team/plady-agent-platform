"""정리 단계와 남은 데이터 (2026-09-25 guestbook.post-happy 사고) — always 정리 단계, 실패해도 값 저장, {{time:rand}}, 실패 분석의 규칙표 설명."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa import editor, hermes, httpx, ui  # noqa: E402
from qa.cases import CaseError, load_dir, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.templating import Context  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"

SCRIPT = {
    "id": "room.leftover", "title": "남은 확정 룸", "suite": "sanity", "actor": "qa-host", "covers": ["op.createRoom:200"],
    "steps": [
        {"name": "룸 생성", "request": {"method": "POST", "path": "/v1/rooms", "body": {"title": "[QA] x", "schedule": {"startTime": "{{time:rand}}"}}},
         "expect": {"status": 200, "json": {"data.status": "RECRUITING"}}, "save": {"roomId": "data.roomId"}},
        {"name": "방명록 글쓰기", "request": {"method": "POST", "path": "/v1/rooms/{{roomId}}/comments"}, "expect": {"status": 200}},
        {"name": "정리", "always": True, "request": {"method": "DELETE", "path": "/v1/dev/rooms/{{roomId}}"}, "expect": {"status": 200}},
        {"name": "없는 값으로 정리", "always": True, "request": {"method": "DELETE", "path": "/v1/dev/rooms/{{nope}}"}, "expect": {"status": 200}},
    ],
}


class FakeHttp:
    def __init__(self, status="CONFIRMED"):
        self.sent, self.status = [], status

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.sent.append((method, url, body))
        if url.endswith("/v1/auth/dev-sessions"):
            return httpx.HttpResult(200, {}, json.dumps({"data": {"accessToken": "tok"}}), 3)
        if method == "POST" and url.endswith("/v1/rooms"):     # 멱등 생성이 남은 확정 룸을 돌려준다
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"roomId": "room-old", "status": self.status}}), 5)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


class CleanupRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cdir = Path(self.tmp.name, "cases")
        cdir.mkdir()
        (cdir / "x.yaml").write_text(yaml.safe_dump({"cases": [SCRIPT]}, allow_unicode=True, sort_keys=False), encoding="utf-8")
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_CASES_DIR": str(cdir), "QA_SPEC_FILE": str(SPEC_FIXTURE),
                               "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_SCENARIOS_DIR": str(Path(self.tmp.name, "none"))}))
        self._orig = httpx.request

    def tearDown(self):
        httpx.request = self._orig
        self.tmp.cleanup()

    def run_it(self, http):
        httpx.request = http
        rid = self.app.create_run(trigger="manual", operator="bebe", case_ids=["room.leftover"], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                                  reason="", basis="", extra={}, session_hash=None, ip=None, notify=False, enqueue=False)
        self.app.runner.execute(rid)
        rc = self.app.store.list_run_cases(rid)[0]
        return rid, rc, self.app.store.list_steps(rc["id"])

    def test_cleanup_runs_after_failure_with_saved_id(self):
        self.assertEqual(self.app.case_errors, [])
        http = FakeHttp()
        rid, rc, steps = self.run_it(http)
        self.assertEqual(rc["verdict"], "fail")                                              # 판정은 처음 실패(상태가 CONFIRMED)가 정한다
        self.assertIn("RECRUITING", rc["error"])
        self.assertEqual([(s["name"], s["verdict"]) for s in steps], [("룸 생성", "fail"), ("정리", "pass"), ("없는 값으로 정리", "skipped")])
        self.assertEqual([m for m, u, b in http.sent if "/v1/dev/rooms/" in u], ["DELETE"])
        self.assertTrue(any(u.endswith("/v1/dev/rooms/room-old") for m, u, b in http.sent))  # 검증이 틀려도 roomId 를 저장해 지웠다
        self.assertTrue(steps[1]["request"]["after_failure"])
        self.assertIn("앞 단계가 실패해 값이 없어", steps[2]["error"])
        start = [b for m, u, b in http.sent if u.endswith("/v1/rooms")][0]["schedule"]["startTime"]
        self.assertRegex(start, r"^(09|1\d|20):[0-5]0$")
        run = self.app.store.get_run(rid)
        page = ui.run_detail(run, [rc], {rc["id"]: steps}, operators=["bebe"], operator="bebe", checklist=[], public_url="")
        self.assertIn("실패 뒤 정리", page)

    def test_pass_runs_everything(self):
        rid, rc, steps = self.run_it(FakeHttp(status="RECRUITING"))
        self.assertEqual([s["name"] for s in steps][:3], ["룸 생성", "방명록 글쓰기", "정리"])
        self.assertEqual(rc["verdict"], "error")                                             # 통과 흐름에서 없는 변수는 여전히 오류다


class FormatTest(unittest.TestCase):
    def test_always_and_time(self):
        with self.assertRaises(CaseError):
            parse_one(yaml.safe_dump(dict(SCRIPT, steps=[dict(SCRIPT["steps"][2], always="yes")])))
        c = parse_one(yaml.safe_dump(dict(SCRIPT, steps=[dict(SCRIPT["steps"][2], always=False)])))
        self.assertNotIn("always", c.steps[0])
        st = editor.to_state(SCRIPT)
        self.assertEqual([s["always"] for s in st["steps"]], [False, False, True, True])
        raw = editor.from_state(dict(st, suite="sanity"))
        self.assertEqual([s.get("always") for s in raw["steps"]], [None, None, True, True])
        self.assertEqual(editor.unsupported(SCRIPT), [])
        times = {Context().resolve("time:rand") for _ in range(200)}
        self.assertTrue(all(re.match(r"^(09|1\d|20):[0-5]0$", t) for t in times) and len(times) > 20)

    def test_seed_cleanup_steps_always(self):
        cases, errors = load_dir(ROOT / "cases")
        self.assertEqual(errors, [])
        for cid in ("room.create", "room.apply-and-withdraw", "guestbook.post-happy"):
            self.assertTrue(cases[cid].own_steps[-1].get("always"), cid)
        body = cases["setup.room-open"].steps[0]["request"]["body"]
        self.assertEqual(body["schedule"]["startTime"], "{{time:rand}}")


class TriageTest(unittest.TestCase):
    def test_rules_in_prompt(self):
        sent = []

        def fake(method, url, headers=None, body=None, timeout=30):
            sent.append(body)
            return httpx.HttpResult(200, {}, json.dumps({"choices": [{"message": {"content": "분류: 환경"}}]}), 1)
        orig, httpx.request = httpx.request, fake
        try:
            cfg = Config({"QA_DATA_DIR": "/tmp", "HERMES_API_KEY": "k"})
            hermes.triage(cfg, {"trigger": "manual", "base_url": "u"}, {"case_id": "x", "case_title": "t", "verdict": "fail", "case_yaml": "id: x"}, [],
                          rules="- 명령 C.room.create 룸 생성 · 멱등(같은 요청이면 새로 만들지 않는다)")
        finally:
            httpx.request = orig
        msgs = sent[0]["messages"]
        self.assertIn("## 관련 규칙표", msgs[-1]["content"])
        self.assertIn("버그로 분류하지 않는다", msgs[0]["content"])


if __name__ == "__main__":
    unittest.main()
