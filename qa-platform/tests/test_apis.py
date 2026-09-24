"""API 별로 모아 보기 P5b (docs/qa-platform-api.md §5.1·§5.2·§6) — 단계 기록의 op_id, 최근 호출, 목록·상세 집계, 화면, MCP 도구, 대화 첨부."""
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
from qa import httpx, ui  # noqa: E402
from qa import chat as chatmod  # noqa: E402
from qa.config import Config  # noqa: E402

# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"


class FakeHttp:
    """dev 대신 응답하는 가짜 — termsList 는 200, roomDetail 은 404 E1410."""
    def __call__(self, method, url, headers=None, body=None, timeout=30):
        if "/v1/terms" in url:
            return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {"terms": [{"termsId": "t-1"}]}}), 12)
        if "/v1/rooms/" in url:
            return httpx.HttpResult(404, {}, json.dumps({"result": "ERROR", "error": {"code": "E1410"}}), 8)
        return httpx.HttpResult(200, {}, json.dumps({"result": "SUCCESS", "data": {}}), 5)


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class ApiViewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        env = {"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_MCP_TOKEN": "t",
               "QA_ACTORS": json.dumps({"qa-host": "m1"}), "QA_FIXTURES": json.dumps({"postingId": 1}), "QA_PUBLIC_URL": "https://qa.test"}
        self.app = App(Config(env))
        self.app.current_catalog()
        self._orig = httpx.request
        httpx.request = FakeHttp()

    def tearDown(self):
        httpx.request = self._orig
        self.tmp.cleanup()

    def _send(self, op_id, path_params=None):
        return self.app.explorer_send(op_id=op_id, path_params=path_params or {}, query={}, body_text="", actor=None, operator="bebe", session_hash=None, ip="127.0.0.1")

    def test_step_records_op_id_and_recent_calls(self):
        rid = self._send("termsList")
        rcs = self.app.store.list_run_cases(rid)
        st = self.app.store.list_steps(rcs[0]["id"])[0]
        self.assertEqual(st["op_id"], "termsList")                          # 러너가 op id 를 박았다
        self._send("roomDetail", {"roomId": "abc"})
        calls = self.app.store.calls_for_op("roomDetail")
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0]["status"], calls[0]["run_id"] != rid, calls[0]["trigger"]), (404, True, "explorer"))
        self.assertEqual(self.app.store.last_call_by_op()["termsList"]["run_id"], rid)

    def test_unresolved_old_rows_match_by_path(self):
        """op_id 가 NULL 인 옛 행(이 배포 전 기록)은 조회 때 method/path 로 폴백 — 백필 없음."""
        rid = self._send("termsList")
        self.app.store._x("UPDATE run_steps SET op_id=NULL")
        self.assertEqual(self.app.store.calls_for_op("termsList"), [])
        d = self.app.api_detail("termsList")
        self.assertEqual([c["run_id"] for c in d["recent_calls"]], [rid])
        rows, _ = self.app.api_overview()
        row = next(r for r in rows if r["id"] == "termsList")
        self.assertEqual(row["last"]["run_id"], rid)

    def test_overview_rows(self):
        rows, cat = self.app.api_overview()
        self.assertIsNotNone(cat)
        ids = {r["id"] for r in rows}
        self.assertIn("createRoom", ids)
        cr = next(r for r in rows if r["id"] == "createRoom")
        self.assertGreater(cr["layers"]["policy"], 0)                       # bindings 로 걸린 비즈니스 규칙 TC
        self.assertGreater(cr["layers"]["contract"], 0)
        self.assertEqual(cr["tc"], cr["covered"] + cr["excluded"] + cr["uncovered"])
        self.assertGreaterEqual(cr["scripts"], 1)                            # cases/room.yaml 이 POST /v1/rooms 를 부른다
        self.assertEqual(cr["domain"], "room")
        self.assertIsNone(cr["last"])

    def test_detail_structure_and_script_declaration_note(self):
        d = self.app.api_detail("createRoom")
        self.assertEqual(d["op"]["method"], "POST")
        self.assertTrue(d["tcs"]["contract"] and d["tcs"]["policy"])
        s = next(x for x in d["scripts"] if x["id"] == "room.create")
        self.assertTrue(s["steps"] and s["declared"])
        self.assertIn("_룸_생성", d["docs_url"])                              # REST Docs 절 앵커 추정
        self.assertIsNone(self.app.api_detail("nope"))

    def test_pages_render(self):
        rows, cat = self.app.api_overview()
        gap = [r for r in rows if not r["scripts"]]        # 아무 스크립트도 안 부르는 op → "부르는 스크립트 없음" 필터(커버리지 공백)에 남는다
        used = [r for r in rows if r["scripts"]]
        self.assertTrue(gap and used)
        h = ui.apis_list(rows, domains=cat.domains(), domain="", only="noscript", q="/", spec_hash="abc", spec_source="file", docs_url="https://d/")
        self.assertIn("호출하는 스크립트 없음", h)
        self.assertIn(f'/apis/{gap[0]["id"]}"', h)
        self.assertNotIn(f'/apis/{used[0]["id"]}"', h)
        self._send("termsList")
        d = self.app.api_detail("termsList")
        h = ui.api_detail(d, operators=["bebe"], operator="bebe", hermes=False)
        for frag in ("호출해 보기", "/chat/new?op=termsList", "이 API 의 테스트 조건", "호출하는 스크립트", "최근 호출", "같은 요청으로 열기", "catalog.terms"):
            self.assertIn(frag, h)

    def test_mcp_tool_and_chat_context(self):
        self._send("termsList")
        status, resp = self.app.mcp.handle(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                                       "params": {"name": "qa_api_get", "arguments": {"operationId": "termsList"}}}).encode())
        out = json.loads(resp["result"]["content"][0]["text"])
        self.assertEqual(out["op"]["id"], "termsList")
        self.assertEqual(len(out["recent_calls"]), 1)
        self.assertNotIn("body", out["recent_calls"][0])                     # 요청·응답 본문은 안 넘긴다
        self.assertNotIn("ids", out["qa"])
        self.assertEqual(out["url"], "https://qa.test/apis/termsList")
        status, resp = self.app.mcp.handle(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                       "params": {"name": "qa_api_get", "arguments": {"operationId": "roomDeta"}}}).encode())
        self.assertTrue(resp["result"].get("isError"))
        self.assertIn("roomDetail", resp["result"]["content"][0]["text"])
        text, title = chatmod.context_block(self.app, {"op": "termsList"})
        self.assertIn("qa_api_get", text)
        self.assertEqual(title, "API termsList")
        self.assertIn("/apis/termsList", ui._ctx_label({"op": "termsList"}))


if __name__ == "__main__":
    unittest.main()
