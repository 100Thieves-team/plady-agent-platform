"""돌리면 안 되거나 늘 틀리는 스크립트를 막는다 (2026-10-08 실행 r-20261008-055618-ee5d: qa-guest 탈퇴, TODO 경로, 리다이렉트)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from qa import httpx  # noqa: E402
from qa.cases import parse_one, safety_errors  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.drafts import fit_status  # noqa: E402
from qa.runner import Runner  # noqa: E402
from qa.store import Store  # noqa: E402


def case(steps: str, actor: str | None = "qa-guest"):
    head = "id: x\ntitle: t\nsuite: sanity\ncovers: ['op.memberWithdraw:200']\n" + (f"actor: {actor}\n" if actor else "")
    return parse_one(head + "steps:\n" + steps)


class SafetyTest(unittest.TestCase):
    def test_withdraw_shared_account_blocked(self):
        bad = case("  - request: {method: DELETE, path: /v1/members/me}\n    covers: ['op.memberWithdraw:200']\n")
        self.assertTrue(any("공용 테스트 계정" in e for e in safety_errors(bad)))
        ok = case("  - request: {method: POST, path: /v1/dev/members}\n    save: {memberToken: data.accessToken}\n"
                  "  - actor: null\n    request: {method: DELETE, path: /v1/members/me, headers: {Authorization: 'Bearer {{memberToken}}'}}\n"
                  "    covers: ['op.memberWithdraw:200']\n")
        self.assertEqual(safety_errors(ok), [])

    def test_shared_data_and_dev_tools_blocked(self):
        bad = case("  - request: {method: DELETE, path: '/v1/members/me/resumes/{{fixture.qa-guest.resumeId}}'}\n"
                   "  - request: {method: POST, path: '/v1/dev/members/{{actor.qa-guest.memberId}}/reset'}\n"
                   "  - request: {method: POST, path: '/v1/dev/members/{{actor.qa-guest.memberId}}/status', body: {status: RESTRICTED}}\n")
        errs = safety_errors(bad)
        self.assertEqual(len(errs), 3, errs)
        self.assertIn("공용 픽스처", errs[0])
        self.assertIn("dev 회원 도구", errs[1])
        ok = case("  - request: {method: POST, path: /v1/dev/members}\n    save: {memberId: data.memberId}\n"
                  "  - request: {method: POST, path: '/v1/dev/members/{{memberId}}/status', body: {status: RESTRICTED}}\n"
                  "  - request: {method: GET, path: '/v1/members/me/resumes/{{fixture.qa-guest.resumeId}}'}\n"
                  "  - request: {method: POST, path: /v1/dev/members/social-signup}\n")
        self.assertEqual(safety_errors(ok), [])

    def test_unsaved_variable(self):
        bad = case("  - request: {method: PUT, path: '/v1/reviews/{{reviewId}}'}\n")
        self.assertTrue(any("save 하지 않은 변수 {{reviewId}}" in e for e in safety_errors(bad)))
        ok = case("  - request: {method: POST, path: /v1/reviews}\n    save: {reviewId: data.reviewId}\n"
                  "  - request: {method: PUT, path: '/v1/reviews/{{reviewId}}', body: {d: '{{date:+1}}', a: '{{actor.qa-host.memberId}}', r: '{{rand}}'}}\n")
        self.assertEqual(safety_errors(ok), [])

    def test_incomplete_and_volatile(self):
        c = case("  - request: {method: PATCH, path: /TODO/닉네임}\n    covers: ['op.memberWithdraw:200']\n"
                 "  - request: {method: GET, path: /v1/rooms/1}\n    expect: {json: {data.title: '[QA] t {{rand}}'}}\n"
                 "  - request: {method: POST, path: /v1/members/me/resumes, form: {file: x}}\n")
        errs = " | ".join(safety_errors(c))
        self.assertIn("경로가 완성되지 않았다", errs)
        self.assertIn("실행마다 바뀌는 값", errs)
        self.assertIn("form", errs)

    def test_fit_status(self):
        class Op:
            def __init__(self, errors):
                self.errors = errors

        class Spec:
            ops = {"createRoom": Op({"E1402": {"status": 400}})}

            def op_for(self, m, p):
                return self.ops["createRoom"] if (m, p) == ("POST", "/v1/rooms") else None
        raw = {"steps": [{"request": {"method": "POST", "path": "/v1/rooms"}, "expect": {"status": 409, "error_code": "E1402"}},
                         {"request": {"method": "POST", "path": "/v1/rooms"}, "expect": {"status": 400, "error_code": "E1425"}}]}
        out = fit_status(raw, Spec())
        self.assertEqual([s["expect"]["status"] for s in out["steps"]], [400, "4xx"])


class _Redirect(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(302)
        self.send_header("Location", "/elsewhere")
        self.send_header("Set-Cookie", "A=1; Path=/")
        self.send_header("Set-Cookie", "B=2; Path=/v1/auth")
        self.end_headers()

    def log_message(self, *a):
        pass


class RunnerSafetyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["QA_DATA_DIR"] = self.tmp.name
        os.environ["QA_ACTORS"] = json.dumps({"qa-host": "m1", "qa-guest": "m2"})
        self.cfg = Config()
        self.store = Store(self.cfg.db_path)
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        for k in ("QA_DATA_DIR", "QA_ACTORS"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_no_redirect(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), _Redirect)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            r = httpx.request("GET", f"http://127.0.0.1:{srv.server_address[1]}/oauth2/authorization/google", follow_redirects=False)
            self.assertEqual(r.status, 302)
            self.assertEqual(len(r.set_cookies), 2)
        finally:
            srv.shutdown()

    def test_runner_refuses_withdraw_and_defaults_dev_actor(self):
        calls = []

        def fake(method, url, headers=None, body=None, timeout=30, follow_redirects=True):
            calls.append((method, url, dict(headers or {}), follow_redirects))
            if url.endswith("/v1/auth/dev-sessions"):
                return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "tok"}}), 1)
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 1)
        httpx.request = fake
        c = parse_one("id: x\ntitle: t\nsuite: sanity\ncovers: ['op.memberWithdraw:200']\nsteps:\n"
                      "  - name: 정리\n    request: {method: DELETE, path: '/v1/dev/rooms/r1'}\n    expect: {status: 200}\n"
                      "  - name: 탈퇴\n    actor: qa-guest\n    request: {method: DELETE, path: /v1/members/me}\n    covers: ['op.memberWithdraw:200']\n")
        runner = Runner(self.cfg, self.store, {"x": c})
        rid = self.store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=[c])
        runner.execute(rid)
        rc = self.store.list_run_cases(rid)[0]
        self.assertEqual(rc["verdict"], "error")
        self.assertIn("공용 테스트 계정", rc["error"])
        sent = [x for x in calls if "/dev-sessions" not in x[1]]
        self.assertEqual(len(sent), 1)                                   # 탈퇴 요청은 보내지 않았다
        self.assertEqual(sent[0][2].get("Authorization"), "Bearer tok")   # dev 도구는 기본 테스트 계정으로
        self.assertIs(sent[0][3], False)                                 # 리다이렉트를 따라가지 않는다


    def test_runner_refuses_shared_fixture_delete_and_dev_reset(self):
        os.environ["QA_FIXTURES"] = json.dumps({"qa-guest.resumeId": "res-shared-0001"})
        self.cfg = Config()
        os.environ.pop("QA_FIXTURES")
        calls = []

        def fake(method, url, headers=None, body=None, timeout=30, follow_redirects=True):
            calls.append((method, url))
            if url.endswith("/v1/auth/dev-sessions"):
                return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "tok"}}), 1)
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"resumes": [{"resumeId": "res-shared-0001"}]}}), 1)
        httpx.request = fake
        # 치환 전에는 공용 데이터인 줄 모르는 경로: 목록에서 꺼낸 id 로 지우기, 회원 id 를 글자로 쓴 dev 초기화
        c = parse_one("id: x\ntitle: t\nsuite: sanity\ncovers: ['op.memberWithdraw:200']\nactor: qa-guest\nsteps:\n"
                      "  - request: {method: GET, path: /v1/members/me/resumes}\n    save: {rid: 'data.resumes[0].resumeId'}\n"
                      "  - request: {method: DELETE, path: '/v1/members/me/resumes/{{rid}}'}\n    covers: ['op.memberWithdraw:200']\n")
        c2 = parse_one("id: y\ntitle: t\nsuite: sanity\ncovers: ['op.memberWithdraw:200']\nactor: qa-host\nsteps:\n"
                       "  - request: {method: POST, path: /v1/dev/members/m2/reset}\n    covers: ['op.memberWithdraw:200']\n")
        runner = Runner(self.cfg, self.store, {"x": c, "y": c2})
        rid = self.store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=[c, c2])
        runner.execute(rid)
        rcs = self.store.list_run_cases(rid)
        self.assertEqual([r["verdict"] for r in rcs], ["error", "error"])
        self.assertIn("공용 픽스처", rcs[0]["error"])
        self.assertIn("dev 회원 도구", rcs[1]["error"])
        self.assertFalse([m for m, u in calls if m in ("DELETE",) or u.endswith("/reset")])       # 보내지 않았다


if __name__ == "__main__":
    unittest.main()
