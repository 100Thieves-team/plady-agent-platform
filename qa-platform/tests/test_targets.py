"""대상 서버 고르기 (docs/qa-platform-v2.md §13) — 기본 dev, [+ 대상 추가], 담당자별 선택, live·내부 주소 막기, 대상별 테스트 계정·토큰."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import httpx, targets as T, ui  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
LOCAL = "https://abc.trycloudflare.com"


class Server:
    """dev 와 등록한 대상을 흉내 — 어느 주소로 무엇이 갔는지 적는다."""

    def __init__(self):
        self.sent = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.sent.append((method, url, body))
        if url.endswith("/actuator/health"):
            return httpx.HttpResult(200, {}, '{"status":"UP"}', 1)
        if url.endswith("/v1/auth/dev-sessions"):
            if not body:
                return httpx.HttpResult(400, {}, '{"result":"ERROR","error":{"code":"E400"}}', 1)
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"accessToken": "tok-" + body["memberId"]}}), 1)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"status": "ACTIVE", "memberId": "x"}}), 1)


class CheckTest(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(T.check("abc.trycloudflare.com/", allow_local=True), "https://abc.trycloudflare.com")
        for bad, frag in (("https://api.moimyeon.plady.io", "live"), ("ftp://x.io", "http"), ("https://x.io/v1", "경로")):
            with self.assertRaises(T.TargetError) as cm:
                T.check(bad, allow_local=True)
            self.assertIn(frag, str(cm.exception))
        for internal in ("http://localhost:8080", "https://localhost:8080", "https://hermes-gateway:8642", "https://127.0.0.1", "https://169.254.169.254"):
            with self.assertRaises(T.TargetError, msg=internal):
                T.check(internal, allow_local=False)                 # 운영 플랫폼에서는 서버 자신·내부를 막는다
        self.assertEqual(T.check("http://localhost:8080", allow_local=True), "http://localhost:8080")   # 노트북 플랫폼은 된다


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.orig_resolve = T._resolve
        T._resolve = lambda host, port: [(2, 1, 6, "", ("104.16.0.1", 0))]         # 터널 주소는 공개 IP
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.srv = Server()
        httpx.request = self.srv
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC), "QA_SCENARIOS_DIR": str(Path(self.tmp.name, "none")),
                               "QA_ACTORS": json.dumps({"qa-host": "dev-host-0001", "qa-guest": "dev-guest-0001"}), "QA_OPERATORS": "bebe,yuje"}))

    def tearDown(self):
        httpx.request = self.orig
        T._resolve = self.orig_resolve
        self.tmp.cleanup()

    def run_member_me(self, operator):
        rid = self.app.create_run(trigger="manual", operator=operator, case_ids=["member.me"], sha=None, ref=None, pr_number=None, deploy_run_id=None,
                                  reason="", basis="", extra={}, session_hash=None, ip=None, notify=False, enqueue=False)
        self.app.runner.execute(rid)
        return self.app.store.get_run(rid)

    def test_add_select_and_run_against_target(self):
        self.assertEqual(self.app.target_for("bebe")["name"], "dev")
        with self.assertRaises(BadRequest):
            self.app.add_target(name="로컬", base_url="http://localhost:8080", actors={}, operator="bebe")     # 운영 설정(공개 주소)이라 막힌다
        with self.assertRaises(BadRequest):
            self.app.add_target(name="로컬", base_url=LOCAL, actors={"qa-host": "zz"}, operator="bebe")         # 회원 id 형식
        t = self.app.add_target(name="준서 로컬", base_url=LOCAL, actors={"qa-host": "a1b2c3d4-0001", "qa-guest": ""}, operator="bebe")
        self.assertEqual((t["probe"]["health"]["status"], t["probe"]["dev_sessions"]["status"]), (200, 400))
        self.assertEqual(t["actors"], {"qa-host": "a1b2c3d4-0001"})
        with self.assertRaises(BadRequest):
            self.app.add_target(name="다른 이름", base_url=LOCAL + "/", actors={}, operator="bebe")               # 같은 주소
        self.app.select_target(t["id"], operator="bebe")
        self.assertEqual(self.app.target_for("bebe")["base_url"], LOCAL)
        self.assertEqual(self.app.target_for("yuje")["name"], "dev")                                              # 담당자별
        run = self.run_member_me("bebe")
        self.assertEqual((run["base_url"], run["meta"]["target"]), (LOCAL, "준서 로컬"))
        sess = [b for m, u, b in self.srv.sent if u == LOCAL + "/v1/auth/dev-sessions" and b]
        self.assertEqual(sess[-1], {"memberId": "a1b2c3d4-0001"})                                                # 그 대상의 회원 id
        self.assertTrue(any(u.startswith(LOCAL + "/v1/members/me") for m, u, b in self.srv.sent))
        run2 = self.run_member_me("yuje")
        self.assertEqual(run2["base_url"], "https://api.dev.moimyeon.plady.io")
        self.assertEqual([b for m, u, b in self.srv.sent if u.endswith("dev.moimyeon.plady.io/v1/auth/dev-sessions")][-1], {"memberId": "dev-host-0001"})
        self.assertEqual(self.app.runner.actors.member_id("qa-guest", LOCAL), "dev-guest-0001")                  # 비우면 dev 와 같은 id
        acts = [x["action"] for x in self.app.store.list_events(20)]
        for a in ("target.add", "target.select"):
            self.assertIn(a, acts)
        page = ui.page("x", "<p>b</p>", active="home", operator="bebe", target=self.app.target_for("bebe"), targets=self.app.targets())
        self.assertIn("지금 대상은 <b>준서 로컬</b>", page)
        self.assertIn('<option value="' + t["id"] + '" selected>준서 로컬</option>', page)
        self.assertIn("abc.trycloudflare.com", page)
        self.app.remove_target(t["id"], operator="bebe")
        self.assertEqual(self.app.target_for("bebe")["name"], "dev")                                              # 지우면 dev 로
        with self.assertRaises(BadRequest):
            self.app.remove_target("dev", operator="bebe")

    def test_local_platform_allows_localhost(self):
        a = App(Config({"QA_DATA_DIR": self.tmp.name + "/b", "QA_SPEC_FILE": str(SPEC), "QA_PUBLIC_URL": "http://localhost:8800", "QA_OPERATORS": "bebe",
                        "QA_SCENARIOS_DIR": str(Path(self.tmp.name, "none"))}))
        self.assertTrue(a.cfg.allow_local_targets)
        t = a.add_target(name="로컬", base_url="http://localhost:8080", actors={}, operator="bebe")
        self.assertEqual(t["base_url"], "http://localhost:8080")
        self.assertIn("노트북에서 떠 있어", ui.targets_page(a.targets(), current=a.target_for("bebe"), operator="bebe", allow_local=True, actor_names=["qa-host"]))


if __name__ == "__main__":
    unittest.main()
