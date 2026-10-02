"""스펙 확인에서 위키 수정까지 (docs/qa-platform-v2.md §14) — 정하면 Hermes 수정안, 플랫폼 검증, 사람이 [위키에 반영], 다시 점검은 사람이.
반영은 줄 단위 3-way merge, PRD 를 고치면 index.yaml 기준 날짜를 올린다(§14.5)."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
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
        cited = F.citing(root, ["룸 진행 마무리 및 출석"], ["R63"])
        self.assertTrue({"C.room.complete", "T.room.complete", "X.complete.record_attendance"} <= {c["id"] for c in cited})
        self.assertEqual({c["req"] for c in cited}, {"R63"})
        self.assertIn("wiki/policy/_src/공통.yaml", F.allowed_paths(root, ["룸 진행 마무리 및 출석"], [c["path"] for c in cited]))
        md = "raw/product/룸-진행-마무리-및-출석.md"
        b = {md: (root / md).read_text(encoding="utf-8"), "wiki/policy/_src/공통.yaml": (root / "wiki/policy/_src/공통.yaml").read_text(encoding="utf-8")}
        line = next(ln for ln in b[md].splitlines() if ln.endswith("`R63`"))
        a = dict(b, **{md: b[md].replace(line, line.replace("완료된다.", "완료된다(PR #1)."), 1)})
        rows = F.prd_cited(root, b, a)
        self.assertEqual([r["req"] for r in rows], ["R63"])
        self.assertFalse(any(x["edited"] for x in rows[0]["records"]))                                     # 규칙표는 안 고쳤다
        c = "wiki/policy/_src/공통.yaml"
        a[c] = b[c].replace("    MVP 흐름의 출석 기록이다.", "    MVP 흐름의 출석 기록이다(PR #1).", 1)
        edited = {x["id"] for x in F.prd_cited(root, b, a)[0]["records"] if x["edited"]}
        self.assertEqual(edited, {"X.complete.record_attendance"})                                          # 고친 기록만 표시

    def test_merge3(self):
        base = "a\nb\nc\nd\n"
        self.assertEqual(F.merge3(base, "a\nB\nc\nd\n", "a\nb\nC\nd\n"), "a\nB\nC\nd\n")          # 붙은 줄을 따로 고치면 합친다
        self.assertEqual(F.merge3(base, "a\nB\nc\nd\n", "a\nB\nc\nd\n"), "a\nB\nc\nd\n")          # 똑같이 고쳤다
        self.assertEqual(F.merge3(base, "a\nb\nc\nd\nx\n", "y\na\nb\nc\nd\n"), "y\na\nb\nc\nd\nx\n")
        self.assertEqual(F.merge3(base, "a\nb2\nc\nd\n", "a\nb\nc\nd\n"), "a\nb2\nc\nd\n")       # 수정안이 안 고친 파일
        with self.assertRaises(F.Conflict):
            F.merge3(base, "a\nB\nc\nd\n", "a\nX\nc\nd\n", "p")                                    # 같은 줄을 다르게
        with self.assertRaises(F.Conflict):
            F.merge3(base, "a\nb\nb2\nc\nd\n", "a\nb\nb3\nc\nd\n")                                  # 같은 자리에 서로 다른 줄을 넣는다

    def test_bump_baseline(self):
        idx = (Path(WIKI_DIR) / F.INDEX).read_text(encoding="utf-8")
        now = datetime(2026, 10, 2, 15, 4, tzinfo=F.KST)
        out = F.bump_baseline(idx, ["룸 생성"], now)
        self.assertIn('    "룸 생성": "2026-10-02 15:04"\n', out)
        self.assertIn("룸 생성: https://", out)                                                             # 문서_링크 는 그대로
        self.assertEqual(len(out.splitlines()), len(idx.splitlines()))
        self.assertIn('"룸 생성": "2026-10-02 15:04:00"', F.bump_baseline(out, ["룸 생성"], now))          # 같은 분이면 초까지
        self.assertEqual(F.doc_of_prd("raw/product/룸-진행-마무리-및-출석.md", idx), "룸 진행 마무리 및 출석")


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class CombineTest(unittest.TestCase):
    """같은 문서를 고친 수정안 둘 — 문맥이 겹쳐도 다른 줄이면 함께 반영, 같은 줄이면 충돌, 반영 뒤 남은 수정안은 지금 파일 기준으로."""
    PRD = "raw/product/룸-생성.md"
    L1 = "3. 룸의 제목·설명·면접 정보·진행 방식·모집 인원·진행 일정을 수정한다. `R146`"
    L2 = "\t- 분기: 수정하지 않고 모집 중인 룸을 취소한다. `R147`"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ("raw/product", "wiki/policy/_src", "tools/policy-renderer"):
            shutil.copytree(Path(WIKI_DIR) / d, self.root / d)
        self.blobs = F.Blobs(self.root / "blobs")
        self.base = (self.root / self.PRD).read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def prop(self, find, replace):
        after = self.base.replace(find, replace, 1)
        return {"summary": replace[:20], "edits": [{"path": self.PRD, "find": find, "replace": replace}],
                "base": {self.PRD: self.blobs.put(self.base)}, "after": {self.PRD: self.blobs.put(after)}}

    def test_overlapping_context_different_lines(self):
        a = self.prop(self.L1 + "\n" + self.L2, self.L1.replace("수정한다.", "수정한다(PR #1).") + "\n" + self.L2)   # find 에 R147 줄까지 넣었다
        b = self.prop(self.L2, self.L2.replace("취소한다.", "취소한다(PR #1)."))
        c = self.prop(self.L1, self.L1.replace("수정한다.", "고친다."))
        self.assertEqual(F.apply_edits({self.PRD: F.apply_edits({self.PRD: self.base}, a["edits"], [self.PRD])[self.PRD]}, b["edits"], [self.PRD])[self.PRD].count("(PR #1)"), 2)
        with self.assertRaises(F.SpecFixError):                                                            # 옛 찾아 바꾸기는 a 뒤에 c 가 실패한다
            F.apply_edits(F.apply_edits({self.PRD: self.base}, a["edits"], [self.PRD]), c["edits"], [self.PRD])
        now = datetime(2026, 10, 2, 15, 4, tzinfo=F.KST)
        before, after, conflicts = F.combine(self.root, [a, b, c], self.blobs, now=now)
        self.assertEqual(list(conflicts), [2])                                                            # c 만 같은 줄 충돌
        self.assertIn("수정한다(PR #1).", after[self.PRD])
        self.assertIn("취소한다(PR #1).", after[self.PRD])
        self.assertIn('"룸 생성": "2026-10-02 15:04"', after[F.INDEX])                                      # PRD 를 고쳐서 기준 날짜를 올린다
        self.assertNotEqual(before[F.INDEX], after[F.INDEX])
        for p in (self.PRD, F.INDEX):                                                                     # a·b 를 반영한 뒤
            (self.root / p).write_text(after[p], encoding="utf-8")
        with self.assertRaises(F.Conflict):
            F.rebase(c, {self.PRD: after[self.PRD]}, self.blobs)
        d = self.prop("2. 자신이 방장인 모집 중인 룸을 연다. `R145`", "2. 자신이 방장인 모집 중인 룸을 연다(PR #2). `R145`")
        r = F.rebase(d, {self.PRD: after[self.PRD]}, self.blobs)                                          # 남은 수정안은 지금 파일 기준으로
        diff = r["files"][0]["diff"]
        self.assertIn("+2. 자신이 방장인 모집 중인 룸을 연다(PR #2).", diff)
        self.assertNotIn("-3. 룸의 제목", diff)
        self.assertEqual(self.blobs.get(r["base"][self.PRD]), after[self.PRD])
        _, after2, conflicts2 = F.combine(self.root, [r], self.blobs, now=now)
        self.assertEqual(conflicts2, {})
        self.assertIn("수정한다(PR #1).", after2[self.PRD])
        self.assertIn('"룸 생성": "2026-10-02 15:04:00"', after2[F.INDEX])                                 # 같은 분에 또 올리면 초까지


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
        self.app.blobs = F.Blobs(Path(self.tmp.name) / "specfix")

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
        self.assertTrue(pr["after"] and self.app.blobs.get(pr["base"]["raw/product/룸-생성.md"]))          # 원래 파일·고친 파일을 저장
        self.assertEqual([c["req"] for c in pr["cited"]], ["R147"])
        out = self.app.sanity_apply(sid, [mm["id"]], operator="bebe")
        self.assertEqual(out["files"], ["raw/product/룸-생성.md", "wiki/policy/_src/index.yaml"])
        self.assertEqual([n for n, _ in self.net.tools], ["wiki_apply", "wiki_content_write", "wiki_content_commit"])   # PRD 다음 기준 날짜
        name, args = self.net.tools[0]
        self.assertEqual((name, args["mode"], args["changes"][0]["path"]), ("wiki_apply", "archive", "raw/product/룸-생성.md"))
        self.assertIn("후임이 없을 때만 룸이 취소된다", args["changes"][0]["content"])
        self.assertIn("`R147`", args["changes"][0]["content"])
        self.assertEqual(args["message"], "spec: R147 룸 취소를 방장 나가기로 바꾼다 — PR #138 Sanity (qa-platform, bebe)")
        idx = self.net.tools[1][1]
        self.assertEqual(idx["uri"], "policy/_src/index.yaml")
        self.assertNotIn('"룸 생성": "2026-09-24"', idx["content"])
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

    def test_same_line_conflict_is_remade(self):
        self.replies["fix"] = [FIX, FIX]
        sid = self.app.sanity_start(138, operator="bebe", sync=True)
        mm = self.finding(sid)
        self.app.sanity_resolve(sid, mm["id"], choice="other", note="취소는 그대로 두고 문구만 다듬는다", operator="bebe", sync=True)
        p = self.finding(sid)["proposal"]
        path = "raw/product/룸-생성.md"
        base = self.app.blobs.get(p["base"][path]).replace(ANCHOR, "그사이 다른 사람이 고친 문장.")           # 만든 뒤 같은 줄을 누가 고친 것처럼
        p["base"][path] = self.app.blobs.put(base)
        self.app._update_finding(sid, mm["id"], proposal=p)
        out = self.app.sanity_apply(sid, [mm["id"]], operator="bebe", sync=True)
        self.assertEqual((out["count"], out["remade"], out["files"]), (0, 1, []))
        self.assertEqual(self.net.tools, [])                                                                # 위키에는 쓰지 않았다
        p = self.finding(sid)["proposal"]
        self.assertEqual(p["status"], "ready")
        self.assertIn("서로 다르게 고친다", p["remade"])                                                      # 지금 위키 기준으로 다시 만들었다
        self.assertIn("sanity.spec.conflict", [x["action"] for x in self.app.store.list_events(40)])
        from qa import ui_sanity
        s = self.app.store.get_sanity(sid)
        page = ui_sanity.sanity_page(self.app.sanity_prs(), {**self.app.sanity_pr(138), "sanity": s}, s, operator="bebe", target="x", hermes=True,
                                     cases=[], run=None, history=[s])
        self.assertIn("다시 만들었어요", page)
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
