"""Hermes 채팅창 (docs/qa-platform-hermes.md §3.2) — /v1/responses 파싱·체이닝·404 폴백·첨부·초안 링크·감사 로그."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import App, BadRequest  # noqa: E402
from qa import chat as chatmod  # noqa: E402
from qa import hermes, httpx  # noqa: E402
from qa.config import Config  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
WIKI_DIR = ROOT.parent / "wiki-workspace"


def _resp(rid: str, text: str, calls: list | None = None) -> dict:
    out = []
    for i, (name, args, output) in enumerate(calls or []):
        out.append({"type": "function_call", "name": name, "arguments": json.dumps(args, ensure_ascii=False), "call_id": f"call_{i}"})
        out.append({"type": "function_call_output", "call_id": f"call_{i}", "output": output})
    out.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
    return {"id": rid, "object": "response", "status": "completed", "output": out, "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}


class FakeHermes:
    def __init__(self):
        self.requests: list[dict] = []
        self.queue: list[tuple[int, dict]] = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        self.requests.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        status, js = self.queue.pop(0) if self.queue else (200, _resp("resp_default", "ok"))
        return httpx.HttpResult(status, {}, json.dumps(js), 1)


class ParseTest(unittest.TestCase):
    def test_parse_response_pairs_calls(self):
        data = _resp("r1", "답", [("qa_coverage", {}, '{"total": 3}'), ("qa_tc_get", {"id": "x"}, "없다")])
        p = hermes.parse_response(data)
        self.assertEqual((p["id"], p["text"]), ("r1", "답"))
        self.assertEqual([c["name"] for c in p["tool_calls"]], ["qa_coverage", "qa_tc_get"])
        self.assertEqual(p["tool_calls"][1]["output"], "없다")
        self.assertEqual(hermes.parse_response({"output": []})["text"], "")

    def test_draft_ids_only_from_draft_tools(self):
        calls = [{"name": "mcp_qa_draft_create", "output": '{"created":[{"id":"d-0123abcd"}]}'}, {"name": "qa_run_get", "output": "d-ffffffff 는 무시"}]
        self.assertEqual(chatmod.draft_ids_from(calls), ["d-0123abcd"])


@unittest.skipUnless((WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file(), "wiki-workspace 체크아웃 없음")
class ChatFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_WIKI_DIR": str(WIKI_DIR), "QA_SPEC_FILE": str(SPEC_FIXTURE), "HERMES_API_KEY": "k",
                               "HERMES_API_URL": "http://hermes:8642", "QA_PUBLIC_URL": "https://qa.test", "QA_CHAT_MAX_TURNS": "2"}))
        self.fake = FakeHermes()
        self.orig = httpx.request
        httpx.request = self.fake

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_first_turn_has_system_and_attachment_then_chains(self):
        did = self.app.store.add_draft(operator="hermes", source="hermes-chat", domain="room", yaml_text="id: x", note=None)
        cid = self.app.chat_create(operator="bebe", context={"tc": "G.room.create#8"}, session_hash=None, ip=None)
        chat = self.app.store.get_chat(cid)
        self.assertEqual((chat["title"], chat["session_key"]), ("TC G.room.create#8", f"qa-chat-{cid}"))
        self.fake.queue.append((200, _resp("resp_1", "초안 d-… 만들었다", [("qa_tc_get", {"id": "G.room.create#8"}, "{}"),
                                                                        ("qa_draft_create", {"yaml": "..."}, json.dumps({"created": [{"id": did}]}))])))
        reply = self.app.chat_send(chat, "케이스 써 줘", operator="bebe", session_hash="s", ip="1.1.1.1")
        req = self.fake.requests[-1]
        self.assertTrue(req["url"].endswith("/v1/responses"))
        self.assertEqual(req["headers"]["X-Hermes-Session-Key"], f"qa-chat-{cid}")
        self.assertIn("QA 엔지니어", req["body"]["instructions"])
        self.assertIn("https://qa.test", req["body"]["instructions"])
        self.assertTrue(req["body"]["input"].startswith("[첨부: TC G.room.create#8]"))
        self.assertTrue(req["body"]["input"].endswith("케이스 써 줘"))
        self.assertNotIn("previous_response_id", req["body"])
        self.assertEqual(req["timeout"], 180)
        self.assertEqual(reply["draft_ids"], [did])
        self.assertEqual([c["name"] for c in reply["tool_calls"]], ["qa_tc_get", "qa_draft_create"])
        chat = self.app.store.get_chat(cid)
        self.assertEqual((chat["turns"], chat["drafts"], chat["last_response_id"]), (1, 1, "resp_1"))
        msgs = self.app.store.list_chat_messages(cid)
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[0]["content"], "케이스 써 줘")        # 첨부는 저장 본문에 안 붙는다 — 화면엔 사람이 쓴 말만
        self.assertEqual(msgs[1]["draft_ids"], [did])
        # 두 번째 턴: 새 메시지만 + previous_response_id, 시스템 프롬프트 없음
        self.fake.queue.append((200, _resp("resp_2", "네")))
        self.app.chat_send(chat, "고마워", operator="bebe", session_hash="s", ip="1.1.1.1")
        req = self.fake.requests[-1]
        self.assertEqual(req["body"]["previous_response_id"], "resp_1")
        self.assertNotIn("instructions", req["body"])
        self.assertEqual(req["body"]["input"], "고마워")
        # 턴 한도(2) 도달
        chat = self.app.store.get_chat(cid)
        with self.assertRaises(BadRequest):
            self.app.chat_send(chat, "더", operator="bebe", session_hash=None, ip=None)
        ev = [x for x in self.app.store.list_events(20) if x["action"] in ("chat.create", "chat.send")]
        self.assertEqual(len(ev), 3)
        self.assertEqual(ev[0]["detail"]["tools"], [])
        self.assertEqual(ev[1]["detail"]["drafts"], [did])

    def test_lru_eviction_falls_back_to_history(self):
        cid = self.app.chat_create(operator="bebe", context={}, session_hash=None, ip=None)
        self.fake.queue.append((200, _resp("resp_1", "첫 답")))
        self.app.chat_send(self.app.store.get_chat(cid), "첫 질문", operator="bebe", session_hash=None, ip=None)
        self.fake.queue.append((404, {"error": {"message": "Previous response not found: resp_1"}}))
        self.fake.queue.append((200, _resp("resp_9", "이어서")))
        reply = self.app.chat_send(self.app.store.get_chat(cid), "둘째", operator="bebe", session_hash=None, ip=None)
        self.assertIsNone(reply["error"])
        req = self.fake.requests[-1]
        self.assertEqual(req["body"]["conversation_history"], [{"role": "user", "content": "첫 질문"}, {"role": "assistant", "content": "첫 답"}])
        self.assertIn("instructions", req["body"])
        self.assertNotIn("previous_response_id", req["body"])
        self.assertEqual(self.app.store.get_chat(cid)["last_response_id"], "resp_9")

    def test_hermes_failure_is_recorded_not_raised(self):
        cid = self.app.chat_create(operator="bebe", context={}, session_hash=None, ip=None)
        self.fake.queue.append((500, {"error": "boom"}))
        reply = self.app.chat_send(self.app.store.get_chat(cid), "질문", operator="bebe", session_hash=None, ip=None)
        self.assertIn("Hermes 호출 실패", reply["content"])
        self.assertTrue(reply["error"])
        msgs = self.app.store.list_chat_messages(cid)
        self.assertEqual(msgs[1]["error"], reply["error"])
        self.assertIsNone(self.app.store.get_chat(cid)["last_response_id"])
        # 다음 턴은 새 대화처럼 시스템 프롬프트를 다시 넣고, 실패 턴은 기록에서 뺀다
        self.assertEqual(chatmod._history(msgs), [{"role": "user", "content": "질문"}])

    def test_guards(self):
        with self.assertRaises(BadRequest):
            self.app.chat_create(operator="nobody", context={}, session_hash=None, ip=None)
        cid = self.app.chat_create(operator="bebe", context={"run": "r-none"}, session_hash=None, ip=None)
        chat = self.app.store.get_chat(cid)
        self.assertIsNone(chat["title"])
        with self.assertRaises(BadRequest):
            self.app.chat_send(chat, "   ", operator="bebe", session_hash=None, ip=None)
        self.app.store.update_chat(cid, status="closed")
        with self.assertRaises(BadRequest):
            self.app.chat_send(self.app.store.get_chat(cid), "x", operator="bebe", session_hash=None, ip=None)
        self.app.store.update_chat(cid, status="open", updated_at="2020-01-01T00:00:00Z")
        self.assertTrue(self.app.chat_stale(self.app.store.get_chat(cid)))


if __name__ == "__main__":
    unittest.main()
