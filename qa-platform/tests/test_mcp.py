"""QA MCP 서버 (docs/qa-platform-hermes.md §3.1) — JSON-RPC 처리·인증·도구 14종·감사 로그.

실제 App 을 띄운다(러너 스레드는 시작하지 않는다). 카탈로그는 레포 안의 wiki-workspace 체크아웃 + OpenAPI 시드에서.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.mcp_server import TOOLS  # noqa: E402

# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"

GOOD_CASE = """
id: room.create-limit-reject
title: 활성 룸이 3개면 네 번째 생성은 E1427 로 거절된다
suite: sanity
domains: [room]
actor: qa-host
covers: ["G.room.create#duplicate-slot-left"]
steps:
  - name: 4번째 생성
    covers: ["G.room.create#duplicate-slot-left"]
    request: { method: POST, path: /v1/rooms, body: { postingId: "{{fixture.postingId}}", title: "[QA] x" } }
    expect: { status: 409, error_code: E1427 }
"""


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class McpServerTest(unittest.TestCase):
    TOKEN = "t-secret"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_MCP_TOKEN": self.TOKEN,
               "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_FIXTURES": json.dumps({"postingId": 1}), "QA_PUBLIC_URL": "https://qa.test"}
        self.app = App(Config(env))
        self.app.current_catalog()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    # -- helpers --
    def rpc(self, method, params=None, *, id_=True):
        self.n += 1
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if id_:
            msg["id"] = self.n
        return self.app.mcp.handle(json.dumps(msg).encode())

    def call(self, name, **args):
        status, resp = self.rpc("tools/call", {"name": name, "arguments": args})
        self.assertEqual(status, 200)
        res = resp["result"]
        text = res["content"][0]["text"]
        return (json.loads(text) if not res.get("isError") else text), res.get("isError", False)

    # -- 프로토콜 --
    def test_auth(self):
        m = self.app.mcp
        self.assertTrue(m.enabled)
        self.assertTrue(m.authorized("Bearer " + self.TOKEN))
        self.assertTrue(m.authorized("bearer " + self.TOKEN))
        self.assertFalse(m.authorized("Bearer nope"))
        self.assertFalse(m.authorized(None))
        self.assertFalse(m.authorized(self.TOKEN))
        off = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC_FIXTURE)}))
        self.assertFalse(off.mcp.enabled)
        self.assertFalse(off.mcp.authorized("Bearer "))

    def test_initialize_list_ping_notification(self):
        status, resp = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        self.assertEqual(status, 200)
        self.assertEqual(resp["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", resp["result"]["capabilities"])
        self.assertIn("사람이 화면 버튼", resp["result"]["instructions"])
        status, resp = self.rpc("initialize", {"protocolVersion": "1999-01-01"})
        self.assertEqual(resp["result"]["protocolVersion"], "2025-03-26")
        status, resp = self.rpc("notifications/initialized", id_=False)
        self.assertEqual((status, resp), (202, None))
        status, resp = self.rpc("ping")
        self.assertEqual(resp["result"], {})
        status, resp = self.rpc("tools/list")
        names = [t["name"] for t in resp["result"]["tools"]]
        self.assertEqual(len(names), 14)
        # 실행·전송·발행·승인 도구는 없다 (원칙 ①)
        for bad in ("run_create", "run_start", "send", "publish", "approve", "reject", "apply", "write", "execute", "cancel"):
            self.assertFalse(any(bad in n for n in names), names)
        for t in TOOLS:
            self.assertEqual(t["inputSchema"]["type"], "object")
        status, resp = self.rpc("resources/list")
        self.assertEqual(resp["error"]["code"], -32601)
        status, resp = self.app.mcp.handle(b"not json")
        self.assertEqual((status, resp["error"]["code"]), (400, -32700))
        status, resp = self.app.mcp.handle(json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "method": "x"}]).encode())
        self.assertEqual(status, 200)
        self.assertEqual(len(resp), 1)

    def test_unknown_tool_and_bad_args(self):
        text, err = self.call("qa_nope")
        self.assertTrue(err)
        self.assertIn("없는 도구", text)
        text, err = self.call("qa_tc_get", bogus=1)
        self.assertTrue(err)
        self.assertIn("인자 오류", text)
        ev = self.app.store.list_events(5, None, "mcp.call")
        self.assertEqual(ev[0]["operator"], "hermes")
        self.assertFalse(ev[0]["detail"]["ok"])

    # -- 읽기 --
    def test_catalog_search_and_tc_get(self):
        res, err = self.call("qa_catalog_search", domain="room", layer="policy", only="uncovered", limit=5)
        self.assertFalse(err)
        self.assertLessEqual(res["returned"], 5)
        self.assertGreater(res["total"], res["returned"])
        for it in res["items"]:
            self.assertEqual((it["domain"], it["layer"], it["state"]), ("room", "policy", "uncovered"))
            self.assertNotIn("example", it.get("expect_hint") or {})
        res, _ = self.call("qa_catalog_search", q="createRoom", layer="contract")
        self.assertTrue(all("createroom" in (it["id"] + json.dumps(it.get("binding") or {})).lower() for it in res["items"]))
        res, _ = self.call("qa_catalog_search", only="covered", limit=200)
        self.assertTrue(all(it["covered_by"] for it in res["items"]))
        res, err = self.call("qa_tc_get", id="G.room.create#duplicate-slot-left")
        self.assertFalse(err)
        self.assertEqual(res["record"]["id"], "G.room.create#duplicate-slot-left")
        self.assertEqual(res["url"], "https://qa.test/catalog/tc?id=G.room.create#duplicate-slot-left")
        self.assertTrue(res["prd"] and res["prd"][0]["text"], "PRD 절 본문이 붙어야 한다")
        text, err = self.call("qa_tc_get", id="G.room.create")
        self.assertTrue(err)
        self.assertIn("비슷한 id", text)
        self.assertIn("G.room.create#duplicate-slot-left", text)

    def test_coverage_changes_cases(self):
        res, err = self.call("qa_coverage")
        self.assertFalse(err)
        self.assertIn("room", res["matrix"])
        self.assertEqual(res["cases"]["total"], len(self.app.cases))
        res, _ = self.call("qa_changes", limit=10)
        self.assertIn("items", res)
        res, err = self.call("qa_case_list", domain="room", suite="smoke")
        self.assertFalse(err)
        self.assertTrue(res["items"] and all(i["suite"] == "smoke" for i in res["items"]))
        cid = res["items"][0]["id"]
        res, err = self.call("qa_case_get", id=cid)
        self.assertFalse(err)
        self.assertIn("steps:", res["yaml"])
        self.assertEqual(res["url"], f"https://qa.test/cases/{cid}")
        text, err = self.call("qa_case_get", id="room.nope")
        self.assertTrue(err)

    def test_spec_and_prd(self):
        res, err = self.call("qa_spec_op", operationId="createRoom")
        self.assertFalse(err)
        self.assertEqual((res["method"], res["path"]), ("POST", "/v1/rooms"))
        self.assertIn("op.createRoom:200", res["tc_ids"])
        text, err = self.call("qa_spec_op", operationId="createroo")
        self.assertTrue(err)
        self.assertIn("createRoom", text)
        res, err = self.call("qa_prd_section", doc="룸 생성", section="4.7")
        self.assertFalse(err)
        self.assertTrue(res["text"].startswith("#"))
        text, err = self.call("qa_prd_section", doc="없는 문서", section="1")
        self.assertTrue(err)
        text, err = self.call("qa_prd_section", doc="룸 생성", section="99.99")
        self.assertTrue(err)

    def test_run_tools_with_masking(self):
        from qa.cases import parse_one
        case = parse_one("id: t.one\ntitle: t\nsuite: manual\nsteps:\n  - request: {method: GET, path: /v1/x}\n")
        rid = self.app.store.create_run(trigger="manual", operator="bebe", suite="manual", env="dev", base_url="http://x", ref=None, sha=None,
                                        pr_number=None, meta={"basis": "b", "_flash": ["x", "y"]}, cases=[case])
        rc = self.app.store.list_run_cases(rid)[0]
        self.app.store.add_step(rc["id"], 0, "s", {"method": "GET", "path": "/v1/x", "headers": {"Authorization": "Bearer ***"}},
                                {"status": 200, "json": {"memberId": "12345678-1234-1234-1234-123456789abc"}}, [], "pass", 3, None)
        res, err = self.call("qa_run_list", trigger="manual", limit=5)
        self.assertFalse(err)
        self.assertEqual(res["items"][0]["id"], rid)
        res, err = self.call("qa_run_get", id=rid, with_steps=True)
        self.assertFalse(err)
        self.assertNotIn("_flash", res["meta"])
        step = res["cases"][0]["steps"][0]
        self.assertNotIn("Authorization", step["request"])
        self.assertIn("12345678-…", step["response"]["body"])
        self.assertNotIn("123456789abc", step["response"]["body"])

    # -- 제안 --
    def test_draft_create_update(self):
        res, err = self.call("qa_draft_create", yaml=GOOD_CASE, reason="테스트")
        self.assertFalse(err, res)
        self.assertEqual(len(res["created"]), 1)
        did = res["created"][0]["id"]
        d = self.app.store.get_draft(did)
        self.assertEqual((d["source"], d["operator"], d["kind"], d["note"], d["status"]), ("hermes-chat", "hermes", "case", "테스트", "draft"))
        self.assertEqual(d["tc_ids"], ["G.room.create#duplicate-slot-left"])
        # 요청하지 않은/없는 TC → 버림
        bad = GOOD_CASE.replace('covers: ["G.room.create#duplicate-slot-left"]', 'covers: ["G.room.create#99"]')
        res, err = self.call("qa_draft_create", yaml=bad)
        self.assertFalse(err)
        self.assertEqual(len(res["created"]), 0)
        self.assertEqual(len(res["rejected"]), 1)
        text, err = self.call("qa_draft_create", yaml="just: nonsense")
        self.assertTrue(err)
        # 갱신: 잘못된 YAML 이면 검증 오류가 초안에 남되 status 는 draft
        res, err = self.call("qa_draft_update", id=did, yaml=bad)
        self.assertFalse(err)
        self.assertEqual(res["validation"]["status"], "error")
        res, err = self.call("qa_draft_update", id=did, yaml=GOOD_CASE)
        self.assertNotEqual(res["validation"]["status"], "error")
        self.app.store.update_draft(did, status="approved")
        text, err = self.call("qa_draft_update", id=did, yaml=GOOD_CASE)
        self.assertTrue(err)
        acts = [e["action"] for e in self.app.store.list_events(50)]
        self.assertIn("draft.generate", acts)
        self.assertIn("draft.save", acts)
        self.assertIn("mcp.call", acts)

    def test_manual_tc_propose(self):
        res, err = self.call("qa_manual_tc_propose", doc="룸 탐색", section="4.1",
                             items=[{"title": "t1", "when": "GET /v1/rooms", "then": "200"}, {"title": "t2", "given": "g", "when": "w", "then": "t", "operations": ["rooms"]}])
        self.assertFalse(err, res)
        self.assertEqual(res["kind"], "tc")
        # 기존 PRD.룸-탐색.4.1#1 다음 번호부터
        self.assertEqual(res["tc_ids"], ["PRD.룸-탐색.4.1#2", "PRD.룸-탐색.4.1#3"])
        d = self.app.store.get_draft(res["id"])
        self.assertEqual((d["kind"], d["domain"]), ("tc", "room"))
        self.assertIn("cases:", d["yaml"])
        # 서술 TC 제안은 갱신도 tc 형식으로 검증
        res2, err = self.call("qa_draft_update", id=res["id"], yaml="cases:\n  - id: bad\n    title: x\n")
        self.assertEqual(res2["validation"]["status"], "error")
        text, err = self.call("qa_manual_tc_propose", doc="룸 탐색", section="4.1", items=[{"title": "", "when": "w", "then": "t"}])
        self.assertTrue(err)


if __name__ == "__main__":
    unittest.main()
