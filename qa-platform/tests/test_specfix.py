"""스펙 확인에서 위키 수정까지 (docs/qa-platform-v2.md §14) — 정하면 Hermes 수정안, 플랫폼 검증, 사람이 [위키에 반영], 다시 점검은 사람이."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import BadRequest  # noqa: E402
from qa import httpx, sanity as S, specfix as F  # noqa: E402
from test_editor import HAS_WIKI, WIKI_DIR, FakeGitHub, make_app  # noqa: E402
from test_sanity import CHECK, FIND, Backend  # noqa: E402

MCP = "http://mcp-proxy:18765/mcp"
ANCHOR = "수정하지 않고 모집 중인 룸을 취소한다."
FIX = ('```json\n{"summary": "R147 룸 취소를 방장 나가기로 바꾼다", "edits": [{"path": "raw/product/룸-생성.md", "find": "' + ANCHOR +
       '", "replace": "방장이 나가면 가장 먼저 참여한 참여자에게 위임하고, 후임이 없을 때만 룸이 취소된다(PR #138 DR-002)."}]}\n```')


class WithMcp(Backend):
    """Backend + llm-wiki MCP 흉내 (JSON-RPC). 부른 도구를 적는다."""

    def __init__(self, gh):
        super().__init__(gh)
        self.tools = []

    def __call__(self, method, url, headers=None, body=None, timeout=30):
        if url == MCP:
            if body.get("method") == "tools/call":
                self.tools.append((body["params"]["name"], body["params"]["arguments"]))
                res = {"content": [{"type": "text", "text": json.dumps({"commit": "c0ffee"})}]}
            else:
                res = {}
            if "id" not in body:
                return httpx.HttpResult(202, {}, "", 1)
            return httpx.HttpResult(200, {"Content-Type": "application/json"}, json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": res}), 1)
        return super().__call__(method, url, headers=headers, body=body, timeout=timeout)


def hermes(replies: dict):
    def ask(cfg, system, prompt, *, session_prefix, on_event=None, cancel=None, deadline=None, stall=None):
        if system == S.FIND_SYSTEM:
            return FIND
        if system == S.CHECK_SYSTEM:
            return CHECK
        if system == F.SYSTEM:
            return replies["fix"].pop(0) if replies["fix"] else ""
        return ""
    return ask


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class UnitTest(unittest.TestCase):
    def test_edits_and_validation(self):
        root = Path(WIKI_DIR)
        paths = F.allowed_paths(root, ["룸 생성"])
        self.assertEqual(paths[:2], ["raw/product/룸-생성.md", "wiki/policy/_src/기능/룸-생성.yaml"])
        self.assertNotIn("wiki/policy/_src/상태-SSOT.yaml", paths)                       # 조립본은 고칠 수 없다
        before = {p: (root / p).read_text(encoding="utf-8") for p in paths}
        for edit, frag in (({"path": "raw/product/룸-생성.md", "find": "없는 문장", "replace": "x"}, "0번"),
                           ({"path": "raw/product/룸-생성.md", "find": "`R", "replace": "x"}, "번 나온다"),
                           ({"path": "wiki/policy/_src/상태-SSOT.yaml", "find": "a", "replace": "b"}, "고칠 수 없는 파일")):
            with self.assertRaises(F.SpecFixError) as cm:
                F.apply_edits(before, [edit], paths)
            self.assertIn(frag, str(cm.exception))
        after = F.apply_edits(before, [{"path": "raw/product/룸-생성.md", "find": ANCHOR + " `R147`", "replace": "지운다."}], paths)
        with self.assertRaises(F.SpecFixError) as cm:
            F.validate(root, before, after)
        self.assertIn("R147", str(cm.exception))                                             # 요구 id 는 지우지 않는다
        y = "wiki/policy/_src/기능/룸-생성.yaml"
        bad = dict(before, **{y: before[y] + "\n  - : [\n"})
        with self.assertRaises(F.SpecFixError):
            F.validate(root, before, bad)
        ok = dict(before, **{y: before[y].rstrip("\n") + "\n# PR #138 메모\n"})
        F.validate(root, before, ok)                                                          # 조립 검사(assemble·check) 통과
        self.assertEqual(F.uri_of(y), "policy/_src/기능/룸-생성.yaml")
        self.assertEqual(F.docs_of({"spec": "「룸 생성」 S2 R147"}, ["룸 생성", "룸 탐색"]), ["룸 생성"])


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        self.net = WithMcp(gh)
        httpx.request = self.net
        self.app = make_app(self.tmp.name)
        self.app.cfg.wiki_mcp_url, self.app.cfg.wiki_mcp_token = MCP, "t"
        self.replies = {"fix": [FIX]}
        self.app.jobs.asker = hermes(self.replies)
        self.app.spec.get().ops.pop("cancelRoom")

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def finding(self, sid, kind="mismatch"):
        return next(f for f in self.app.store.get_sanity(sid)["findings"] if f["kind"] == kind)

    def test_decide_propose_apply_then_recheck_by_hand(self):
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        mm = self.finding(sid)
        self.app.sanity_resolve(sid, mm["id"], choice="recommended", note="", operator="bebe", sync=True)
        mm = self.finding(sid)
        pr = mm["proposal"]
        self.assertEqual(pr["status"], "ready")
        self.assertEqual([x["path"] for x in pr["files"]], ["raw/product/룸-생성.md"])
        self.assertIn("-\t- 분기: " + ANCHOR, pr["files"][0]["diff"])
        self.assertIn("후임이 없을 때만 룸이 취소된다", pr["files"][0]["diff"])
        self.assertEqual(self.net.tools, [])                                                   # 반영 전에는 위키에 닿지 않는다
        missing = self.finding(sid, "missing_api")
        with self.assertRaises(BadRequest):
            self.app.sanity_propose(sid, missing["id"], operator="bebe", sync=True)          # 없어진 API 는 수정안 대상이 아니다
        out = self.app.sanity_apply(sid, [mm["id"]], operator="bebe")
        self.assertEqual(out["files"], ["raw/product/룸-생성.md"])
        name, args = self.net.tools[0]
        self.assertEqual((name, args["mode"], args["changes"][0]["path"]), ("wiki_apply", "archive", "raw/product/룸-생성.md"))
        self.assertIn("후임이 없을 때만 룸이 취소된다", args["changes"][0]["content"])
        self.assertIn("`R147`", args["changes"][0]["content"])
        self.assertEqual(args["message"], "spec: R147 룸 취소를 방장 나가기로 바꾼다 — PR #138 Sanity (qa-platform, bebe)")
        s = self.app.store.get_sanity(sid)
        self.assertEqual(self.finding(sid)["proposal"]["status"], "applied")
        self.assertEqual(s["status"], "needs_spec")                                            # 다시 점검은 사람이 따로 누른다
        with self.assertRaises(BadRequest):
            self.app.sanity_apply(sid, [mm["id"]], operator="bebe")
        acts = [x["action"] for x in self.app.store.list_events(40)]
        for a in ("sanity.finding.resolve", "sanity.spec.propose", "sanity.spec.apply"):
            self.assertIn(a, acts)
        from qa import ui_sanity
        page = ui_sanity.sanity_page(self.app.sanity_prs(), {**self.app.sanity_pr(138), "sanity": s}, s, operator="bebe", target="x", hermes=True,
                                     cases=[], run=None, history=[s])
        self.assertIn("위키에 반영했어요", page)

    def test_stale_proposal_is_refused(self):
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        mm = self.finding(sid)
        self.app.sanity_resolve(sid, mm["id"], choice="other", note="취소는 그대로 두고 문구만 다듬는다", operator="bebe", sync=True)
        p = self.finding(sid)["proposal"]
        p["edits"][0]["find"] = "그사이 사라진 문장"                                               # 수정안을 만든 뒤 위키가 바뀐 것처럼
        self.app._update_finding(sid, mm["id"], proposal=p)
        with self.assertRaises(BadRequest) as cm:
            self.app.sanity_apply(sid, [mm["id"]], operator="bebe")
        self.assertIn("다시 만들기", str(cm.exception))
        self.assertEqual(self.net.tools, [])
        self.app.sanity_discard(sid, mm["id"], operator="bebe")
        self.assertEqual(self.finding(sid)["proposal"]["status"], "discarded")

    def test_failed_proposal_after_retry(self):
        self.replies["fix"] = ["모르겠다", '```json\n{"summary": "x", "edits": [{"path": "raw/product/룸-생성.md", "find": "없는 문장", "replace": "y"}]}\n```']
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        mm = self.finding(sid)
        self.app.sanity_resolve(sid, mm["id"], choice="recommended", note="", operator="bebe", sync=True)
        p = self.finding(sid)["proposal"]
        self.assertEqual(p["status"], "failed")
        self.assertIn("0번", p["error"])


if __name__ == "__main__":
    unittest.main()
