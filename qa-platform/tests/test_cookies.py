"""계정별 쿠키 보관과 expect.cookies (docs/qa-platform-v2.md §16.3)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from qa import httpx  # noqa: E402
from qa.cases import CaseError, parse_one  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.editor import from_state, to_state  # noqa: E402
from qa.runner import Runner, cookie_state, evaluate, parse_set_cookie  # noqa: E402
from qa.store import Store  # noqa: E402

ACCESS = "ACCESS_TOKEN=a1; Path=/; Max-Age=1800; HttpOnly; Secure; SameSite=Lax"
REFRESH = "REFRESH_TOKEN=r1; Path=/v1/auth; Max-Age=1209600; HttpOnly"
RESTORE = "RESTORE_TOKEN=s1; Path=/v1/auth; Max-Age=600; HttpOnly"
EXPIRE_ACCESS = "ACCESS_TOKEN=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
EXPIRE_REFRESH = "REFRESH_TOKEN=; Path=/v1/auth; Max-Age=0"


class ParseTest(unittest.TestCase):
    def test_parse_and_state(self):
        self.assertEqual(parse_set_cookie(REFRESH), {"name": "REFRESH_TOKEN", "value": "r1", "path": "/v1/auth", "cleared": False})
        self.assertTrue(parse_set_cookie(EXPIRE_ACCESS)["cleared"])
        self.assertEqual(cookie_state([ACCESS, REFRESH], "ACCESS_TOKEN"), "set")
        self.assertEqual(cookie_state([EXPIRE_ACCESS], "ACCESS_TOKEN"), "cleared")
        self.assertEqual(cookie_state([ACCESS], "RESTORE_TOKEN"), "absent")

    def test_evaluate_cookies(self):
        out = evaluate({"status": 200, "cookies": {"ACCESS_TOKEN": "set", "RESTORE_TOKEN": "absent"}}, 200, {}, [ACCESS])
        self.assertTrue(all(c["ok"] for c in out))
        bad = evaluate({"cookies": {"ACCESS_TOKEN": "cleared"}}, 200, {}, [ACCESS])
        self.assertEqual((bad[0]["check"], bad[0]["path"], bad[0]["actual"], bad[0]["ok"]), ("cookie", "ACCESS_TOKEN", "set", False))

    def test_result_reads_all_set_cookie_headers(self):
        r = httpx.HttpResult(200, {"Set-Cookie": [ACCESS, REFRESH]}, "{}", 1)
        self.assertEqual(len(r.set_cookies), 2)
        self.assertEqual(httpx.HttpResult(200, {"set-cookie": ACCESS}, "{}", 1).set_cookies, [ACCESS])

    def test_case_validation(self):
        parse_one("id: x\ntitle: t\nsuite: smoke\ncovers: ['op.authLogout:200']\nsteps:\n"
                  "  - {cookie_jar: member, actor: null, request: {method: POST, path: /v1/auth/logout}, expect: {cookies: {ACCESS_TOKEN: cleared}}}\n")
        with self.assertRaises(CaseError):
            parse_one("id: x\ntitle: t\nsuite: smoke\ncovers: ['op.authLogout:200']\nsteps:\n"
                      "  - {request: {method: POST, path: /v1/auth/logout}, expect: {cookies: {ACCESS_TOKEN: gone}}}\n")
        with self.assertRaises(CaseError):
            parse_one("id: x\ntitle: t\nsuite: smoke\ncovers: ['op.authLogout:200']\nsteps:\n"
                      "  - {cookie_jar: '회원', request: {method: POST, path: /v1/auth/logout}}\n")

    def test_editor_round_trip(self):
        raw = {"id": "x", "title": "t", "suite": "smoke", "domains": [], "actor": "qa-host", "steps": [
            {"name": "로그인", "cookie_jar": "member", "request": {"method": "POST", "path": "/v1/dev/members/m/social-login"},
             "expect": {"status": 200, "cookies": {"RESTORE_TOKEN": "set"}}},
            {"name": "복구", "actor": None, "cookie_jar": "member", "request": {"method": "POST", "path": "/v1/auth/restoration"},
             "expect": {"status": "4xx"}},
        ]}
        back = from_state(to_state(raw))
        self.assertEqual(back["steps"][0]["cookie_jar"], "member")
        self.assertNotIn("actor", back["steps"][0])
        self.assertEqual(back["steps"][0]["expect"]["cookies"], {"RESTORE_TOKEN": "set"})
        self.assertIsNone(back["steps"][1]["actor"])
        self.assertEqual(back["steps"][1]["expect"]["status"], "4xx")


class FakeCookieHttp:
    """경로별로 Set-Cookie 를 돌려주고 받은 Cookie 헤더를 기록한다."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1].split("?")[0]
        self.calls.append((method, path, dict(headers or {})))
        status, js, cookies = self.table.get((method, path), (404, {"result": "ERROR"}, []))
        return httpx.HttpResult(status, {}, json.dumps(js), 1, set_cookies=cookies)


class JarRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["QA_DATA_DIR"] = self.tmp.name
        os.environ["QA_ACTORS"] = json.dumps({"qa-host": "member-1"})
        self.cfg = Config()
        self.store = Store(self.cfg.db_path)
        self.orig = httpx.request

    def tearDown(self):
        httpx.request = self.orig
        for k in ("QA_DATA_DIR", "QA_ACTORS"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def test_jar_flow(self):
        ok = {"result": "SUCCESS", "data": {}}
        fake = FakeCookieHttp({
            ("POST", "/v1/auth/dev-sessions"): (200, {"result": "SUCCESS", "data": {"accessToken": "tok"}}, []),
            ("POST", "/v1/dev/members/m9/social-login"): (200, {"result": "SUCCESS", "data": {"outcome": "LOGGED_IN"}}, [ACCESS, REFRESH]),
            ("GET", "/v1/members/me"): (200, ok, []),
            ("POST", "/v1/auth/logout"): (200, ok, [EXPIRE_ACCESS, EXPIRE_REFRESH]),
        })
        httpx.request = fake
        c = parse_one(
            "id: j\ntitle: t\nsuite: smoke\ncovers: ['op.authLogout:200']\nactor: qa-host\nsteps:\n"
            "  - name: 로그인\n    cookie_jar: member\n    request: {method: POST, path: /v1/dev/members/m9/social-login}\n"
            "    expect: {status: 200, cookies: {ACCESS_TOKEN: set, REFRESH_TOKEN: set}}\n"
            "  - name: 내 정보\n    actor: null\n    cookie_jar: member\n    request: {method: GET, path: /v1/members/me}\n    expect: {status: 200}\n"
            "  - name: 로그아웃\n    actor: null\n    cookie_jar: member\n    request: {method: POST, path: /v1/auth/logout}\n"
            "    expect: {status: 200, cookies: {ACCESS_TOKEN: cleared, REFRESH_TOKEN: cleared}}\n"
            "  - name: 로그아웃 뒤\n    actor: null\n    cookie_jar: member\n    request: {method: GET, path: /v1/members/me}\n    expect: {status: 200}\n")
        runner = Runner(self.cfg, self.store, {"j": c})
        rid = self.store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="https://api.test",
                                    ref="dev", sha=None, pr_number=None, meta={}, cases=[c])
        runner.execute(rid)
        rc = self.store.list_run_cases(rid)[0]
        self.assertEqual(rc["verdict"], "pass", rc["error"])
        calls = [x for x in fake.calls if x[1] != "/v1/auth/dev-sessions"]
        self.assertEqual(calls[0][2].get("Authorization"), "Bearer tok")           # 로그인 도구는 QA 계정 토큰으로
        self.assertEqual(calls[1][2].get("Cookie"), "ACCESS_TOKEN=a1")             # /v1/auth 경로 쿠키는 붙지 않는다
        self.assertNotIn("Authorization", calls[1][2])
        self.assertEqual(calls[2][2].get("Cookie"), "ACCESS_TOKEN=a1; REFRESH_TOKEN=r1")
        self.assertNotIn("Cookie", calls[3][2])                                     # 만료된 쿠키는 저장소에서 빠진다
        steps = self.store.list_steps(rc["id"])
        self.assertEqual(steps[2]["request"]["headers"]["Cookie"], "ACCESS_TOKEN=***; REFRESH_TOKEN=***")
        self.assertEqual(steps[0]["response"]["set_cookies"][1], {"name": "REFRESH_TOKEN", "path": "/v1/auth", "cleared": False})
        self.assertNotIn("a1", json.dumps(steps, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
