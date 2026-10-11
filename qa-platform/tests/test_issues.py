"""백엔드 구현 실수를 Linear 이슈로 (docs/qa-platform-v2.md §17)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import httpx, issues as I  # noqa: E402
from qa.cases import parse_one  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.linear import Linear, LinearError  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


class FakeLinear:
    """api.linear.app/graphql 흉내. triage 를 켜고 끌 수 있다."""

    def __init__(self, triage=False):
        self.triage, self.created, self.comments, self.states = triage, [], [], {}

    def __call__(self, method, url, headers=None, body=None, timeout=30, **kw):
        if "api.linear.app" not in url:
            return httpx.HttpResult(404, {}, "", 1)
        q, v = body["query"], body.get("variables") or {}
        if "teams(" in q:
            states = [{"id": "s-back", "name": "Backlog", "type": "backlog"}, {"id": "s-done", "name": "Done", "type": "completed"}]
            if self.triage:
                states.append({"id": "s-tri", "name": "Triage", "type": "triage"})
            data = {"teams": {"nodes": [{"id": "team-1", "key": "MOI", "name": "100", "states": {"nodes": states},
                                         "labels": {"nodes": [{"id": "l-bug", "name": "Bug"}, {"id": "l-be", "name": "Backend"}, {"id": "l-plan", "name": "기획"}]},
                                         "projects": {"nodes": [{"id": "p-1", "name": "회원 및 프로필"}]}}]},
                    "issueLabels": {"nodes": []}}
        elif "issueCreate" in q:
            n = len(self.created) + 600
            self.created.append(v["input"])
            iss = {"id": f"u-{n}", "identifier": f"MOI-{n}", "url": f"https://linear.app/x/MOI-{n}", "title": v["input"]["title"], "state": {"name": "Backlog", "type": "backlog"}}
            self.states[iss["id"]] = {"name": "Backlog", "type": "backlog"}
            data = {"issueCreate": {"success": True, "issue": iss}}
        elif "commentCreate" in q:
            self.comments.append(v["input"])
            data = {"commentCreate": {"success": True}}
        elif "issues(" in q:
            data = {"issues": {"nodes": [{"id": i, "identifier": "MOI-" + i[2:], "url": "u", "state": self.states[i]} for i in v["ids"] if i in self.states]}}
        else:
            raise AssertionError(q)
        return httpx.HttpResult(200, {}, json.dumps({"data": data}), 1)


DRAFT = """```json
{"kind": "bug", "reason": "규칙표는 이용 제한 회원의 등록을 막는데 201 이 왔다",
 "title": "이용 제한 회원이 이력서를 등록할 수 있음",
 "body": "## Context\\nr-1 · resume.account-active\\n\\n## Problem\\n201\\n\\n## Proposal\\n막는다\\n\\n## Acceptance Criteria\\n- [ ] E1002\\n- [ ] 활성 회원은 201\\n\\n## Verification\\n스크립트\\n\\n## Out of Scope\\n- 없음"}
```"""


class LinearClientTest(unittest.TestCase):
    def setUp(self):
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig

    def test_backlog_when_no_triage_and_labels_checked(self):
        net = FakeLinear(triage=False)
        httpx.request = net
        lin = Linear("lin_api_test")
        st = lin.start_state()
        self.assertEqual(st["id"], "s-back")
        self.assertIn("Triage 가 꺼져", st["note"])
        iss = lin.create_issue(title="[QA] t", description="d", labels=["Bug", "Backend"], project="회원 및 프로필")
        self.assertEqual(iss["identifier"], "MOI-600")
        self.assertEqual(net.created[0], {"teamId": "team-1", "title": "[QA] t", "description": "d", "stateId": "s-back",
                                          "labelIds": ["l-bug", "l-be"], "projectId": "p-1"})          # 담당자는 넣지 않는다
        with self.assertRaises(LinearError):
            lin.create_issue(title="[QA] t", description="d", labels=["없는 라벨"], project=None)

    def test_triage_preferred(self):
        httpx.request = FakeLinear(triage=True)
        self.assertEqual(Linear("k").start_state()["id"], "s-tri")

    def test_no_token(self):
        with self.assertRaises(LinearError):
            Linear("").start_state()


class PureTest(unittest.TestCase):
    def test_parse(self):
        out = I.parse(DRAFT)
        self.assertEqual((out["kind"], out["title"]), ("bug", "[QA] 이용 제한 회원이 이력서를 등록할 수 있음"))      # 접두어를 붙인다
        self.assertEqual(I.parse('{"kind": "not_backend", "reason": "스크립트 기대가 문서와 다르다"}')["kind"], "not_backend")
        with self.assertRaises(ValueError):
            I.parse('{"kind": "bug", "title": "[QA] x", "body": "## Context 만"}')                              # 수락 조건 절이 없다
        with self.assertRaises(ValueError):
            I.parse('{"kind": "maybe"}')

    def test_eligibility_and_spread(self):
        fail = {"verdict": "fail", "response": {"status": 404, "json": {"error": {"code": "E1010"}}}, "request": {}}
        failing = {1: fail, 2: dict(fail), 3: dict(fail), 4: dict(fail), 5: dict(fail), 6: {"verdict": "fail", "response": {"status": 201}, "request": {}}}
        self.assertEqual(I.spread(1, failing), 4)
        self.assertEqual(I.spread(6, failing), 0)

        class C:
            audit = {"status": "ok"}
        self.assertEqual(I.eligibility({"verdict": "fail"}, fail, C(), 0), [])
        self.assertIn("공용 데이터", I.eligibility({"verdict": "fail"}, fail, C(), 4)[0])
        self.assertIn("판정이 error", I.eligibility({"verdict": "error"}, fail, C(), 0)[0])
        C.audit = {"status": "error", "errors": ["step 1: API 문서에 없는 요청"]}
        self.assertIn("검사에 걸린다", I.eligibility({"verdict": "fail"}, fail, C(), 0)[0])


class FlowTest(unittest.TestCase):
    CASE = """
id: resume.account-active
title: 이용 제한 회원은 이력서를 등록하지 못한다
suite: sanity
variant: 회원-및-프로필/S2/account-active
covers: [op.createRoom:200]
actor: qa-guest
steps:
  - name: 이용 제한 계정으로 이력서 등록 시도
    request: {method: POST, path: /v1/rooms, body: {title: x}}
    expect: {status: 409, error_code: E1002}
    covers: [op.createRoom:200]
"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.net = FakeLinear(triage=False)
        httpx.request = self.net
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC), "QA_SCENARIOS_DIR": str(Path(self.tmp.name, "none")),
                               "QA_OPERATORS": "bebe", "HERMES_API_KEY": "test", "QA_LINEAR_TOKEN": "lin_api_test",
                               "QA_PUBLIC_URL": "https://qa.test"}))
        self.asked = []

        def asker(cfg, system, prompt, **kw):
            self.asked.append(prompt)
            return DRAFT
        self.app.jobs.asker = asker
        c = parse_one(self.CASE, "t")
        c.audit = {"status": "ok", "errors": [], "warnings": []}
        self.app.cases = {c.id: c}

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def _failed_run(self):
        c = self.app.cases["resume.account-active"]
        rid = self.app.store.create_run(trigger="sprint-smoke", operator="bebe", suite=None, env="dev", base_url="https://api.test", ref=None, sha=None,
                                        pr_number=None, meta={}, cases=[c])
        rc = self.app.store.list_run_cases(rid)[0]
        self.app.store.update_run_case(rc["id"], verdict="fail", error="error_code 기대 E1002 실제 없음")
        self.app.store.add_step(rc["id"], 0, "이용 제한 계정으로 이력서 등록 시도", {"method": "POST", "path": "/v1/rooms", "url": "https://api.test/v1/rooms", "body": {"title": "x"}},
                                {"status": 201, "json": {"result": "SUCCESS", "data": {"roomId": "r"}}},
                                [{"check": "status", "expected": 409, "actual": 201, "ok": False}], "fail", 3, "status 기대 409 실제 201")
        return self.app.store.get_run(rid), self.app.store.get_run_case(rc["id"])

    def test_draft_create_and_dedupe(self):
        run, rc = self._failed_run()
        with self.assertRaises(BadRequest):
            self.app.job_issue_drafts(run, ["999"], "bebe")
        job = self.app.job_issue_drafts(run, [str(rc["id"])], "bebe", sync=True)
        self.assertEqual(job.status, "done", job.error)
        self.assertIn("## 실제 응답", self.asked[0])                                                 # 근거를 넘겼다
        self.assertIn("op.createRoom:200", self.asked[0])
        d = self.app.store.list_issue_drafts(run_id=run["id"])[0]
        self.assertEqual((d["status"], d["kind"], d["labels"], d["project"]), ("draft", "bug", ["Bug", "Backend"], "회원 및 프로필"))
        self.assertEqual(self.net.created, [])                                                      # 초안만. 이슈는 사람이 누를 때

        res = self.app.create_linear_issues(run["id"], [{"id": d["id"], "title": "이용 제한 회원 이력서", "body": d["body"], "labels": ["Bug", "Backend"], "project": "회원 및 프로필"}], "bebe")
        self.assertEqual([c["id"] for c in res["created"]], ["MOI-600"])
        self.assertEqual(res["state"], "Backlog")
        made = self.net.created[0]
        self.assertEqual(made["title"], "[QA] 이용 제한 회원 이력서")
        self.assertIn("## QA 근거", made["description"])                                             # 플랫폼이 근거를 붙인다
        self.assertIn(run["id"], made["description"])
        self.assertIn("bebe 가 만들었다", made["description"])
        self.assertNotIn("assigneeId", made)
        self.assertEqual(self.app.store.get_issue_draft(d["id"])["linear_id"], "MOI-600")
        self.assertIn("issue.create", [x["action"] for x in self.app.store.list_events(20)])
        self.assertEqual(self.app.issues_by_case(["resume.account-active"])["resume.account-active"]["linear_id"], "MOI-600")

        # 같은 테스트 조건이 다시 실패하면 새로 쓰지 않고 열린 이슈에 잇는다
        run2, rc2 = self._failed_run()
        self.app.job_issue_drafts(run2, [str(rc2["id"])], "bebe", sync=True)
        d2 = self.app.store.list_issue_drafts(run_id=run2["id"])[0]
        self.assertEqual((d2["status"], d2["linear_id"]), ("linked", "MOI-600"))
        self.assertEqual(len(self.asked), 1)                                                        # Hermes 를 다시 부르지 않았다
        self.assertEqual(self.app.comment_linked_issue(run2["id"], d2["id"], "bebe"), "MOI-600")
        self.assertIn(run2["id"], self.net.comments[0]["body"])

        # 이슈가 닫히면 같은 조건이라도 새 초안을 쓴다
        self.net.states["u-600"] = {"name": "Done", "type": "completed"}
        self.app._issue_states.clear()
        run3, rc3 = self._failed_run()
        self.app.job_issue_drafts(run3, [str(rc3["id"])], "bebe", sync=True)
        self.assertEqual(self.app.store.list_issue_drafts(run_id=run3["id"])[0]["status"], "draft")

    def test_screens(self):
        from qa import ui
        run, rc = self._failed_run()
        html = ui.run_detail(run, self.app.store.list_run_cases(run["id"]), {rc["id"]: self.app.store.list_steps(rc["id"])}, operators=["bebe"], operator="bebe",
                             checklist=[], public_url="", issues={}, n_drafts=0)
        self.assertIn('id="issue-form"', html)
        self.assertIn(f'form="issue-form" name="rc" value="{rc["id"]}"', html)
        self.app.job_issue_drafts(run, [str(rc["id"])], "bebe", sync=True)
        drafts = self.app.store.list_issue_drafts(run_id=run["id"])
        page = ui.issue_drafts(run, drafts, operator="bebe", linear_ok=True, linear_note="팀에 Triage 가 꺼져", projects=["회원 및 프로필"])
        self.assertIn(f'name="title_{drafts[0]["id"]}"', page)
        self.assertIn("고른 초안을 Linear 에 만들기", page)
        self.assertIn("Triage 가 꺼져", page)
        self.assertIn("disabled", ui.issue_drafts(run, drafts, operator="bebe", linear_ok=False, linear_note=None, projects=[]).split("Linear 에 만들기")[0][-200:])

    def test_blocked_and_not_backend(self):
        run, rc = self._failed_run()
        self.app.cases["resume.account-active"].audit = {"status": "error", "errors": ["step 1: API 문서에 없는 요청"]}
        self.app.job_issue_drafts(run, [str(rc["id"])], "bebe", sync=True)
        d = self.app.store.list_issue_drafts(run_id=run["id"])[0]
        self.assertEqual(d["status"], "blocked")
        self.assertIn("검사에 걸린다", d["reason"])
        self.assertEqual(self.asked, [])                                                            # 걸리면 Hermes 를 부르지 않는다

        self.app.cases["resume.account-active"].audit = {"status": "ok"}
        self.app.jobs.asker = lambda cfg, system, prompt, **kw: '{"kind": "not_backend", "reason": "문서상 201 이 맞다"}'
        run2, rc2 = self._failed_run()
        self.app.job_issue_drafts(run2, [str(rc2["id"])], "bebe", sync=True)
        d2 = self.app.store.list_issue_drafts(run_id=run2["id"])[0]
        self.assertEqual((d2["status"], d2["kind"]), ("blocked", "not_backend"))
        self.assertIn("문서상 201", d2["reason"])

    def test_needs_token_to_create(self):
        run, rc = self._failed_run()
        self.app.job_issue_drafts(run, [str(rc["id"])], "bebe", sync=True)
        d = self.app.store.list_issue_drafts(run_id=run["id"])[0]
        self.app.linear.token = ""
        with self.assertRaises(BadRequest):
            self.app.create_linear_issues(run["id"], [{"id": d["id"]}], "bebe")
        self.assertEqual(self.app.discard_issue_drafts(run["id"], [d["id"]], "bebe"), 1)
        self.assertEqual(self.app.store.get_issue_draft(d["id"])["status"], "discarded")


if __name__ == "__main__":
    unittest.main()
