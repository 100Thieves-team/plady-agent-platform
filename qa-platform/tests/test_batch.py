"""[스크립트 한꺼번에 만들기] — 스크립트 없는 케이스를 차례로 만든다."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app import BadRequest  # noqa: E402
from qa import httpx  # noqa: E402
from test_editor import HAS_WIKI, FakeGitHub, make_app  # noqa: E402


@unittest.skipUnless(HAS_WIKI, "위키 체크아웃 없음")
class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.orig = httpx.request
        self.gh = FakeGitHub()
        for p in (ROOT / "scenarios").glob("*.yaml"):
            self.gh.files[f"qa-platform/scenarios/{p.name}"] = p.read_text(encoding="utf-8")
        httpx.request = self.gh
        self.app = make_app(self.tmp.name)
        self.app.cfg.operators = ["bebe"]
        self.app.cfg.hermes_key = "test"
        self.app.cases = {k: v for k, v in self.app.cases.items() if not v.variant}      # 모든 케이스가 '스크립트 없음' 이 되게

    def tearDown(self):
        httpx.request = self.orig
        self.tmp.cleanup()

    def test_batch(self):
        vids = self.app.untested_variants()
        self.assertGreaterEqual(len(vids), 4)
        seen = []

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None, replace=None, rewrite_note=None):
            seen.append(variant)
            n = len(seen)
            if n == 2:
                return {"saved": [], "rejected": [("x", ["covers 가 틀렸다"])]}
            if n == 3:
                raise RuntimeError("Hermes 응답 없음")
            return {"saved": [{"id": f"d-{n}"}], "rejected": []}
        self.app.generate_cases = fake
        with self.assertRaises(BadRequest):
            self.app.job_batch_scripts("bebe", slug="없는-기능")
        job = self.app.job_batch_scripts("bebe", sync=True)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(seen, vids)                                  # 한 건씩 차례로, 실패해도 다음 건으로
        b = job.info["batch"]
        self.assertEqual((b["total"], b["saved"], b["rejected"], b["failed"]), (len(vids), len(vids) - 2, 1, 1))
        self.assertIn(f"스크립트 저장 {len(vids) - 2}개", job.result["summary"])
        self.assertIn(f"===== 1/{len(vids)} {vids[0]} =====", job.text)
        self.assertIn("hermes.batch_draft", [x["action"] for x in self.app.store.list_events(20)])

    def test_cancel_keeps_saved(self):
        vids = self.app.untested_variants()
        holder = {}

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None, replace=None, rewrite_note=None):
            if variant == vids[1]:
                holder["job"].cancel.set()                            # 두 번째 건을 쓰는 중에 사람이 그만둔다
            return {"saved": [{"id": "d-1"}], "rejected": []}
        self.app.generate_cases = fake
        orig_submit = self.app.jobs.submit

        def submit(kind, operator, label, fn, **kw):
            def wrapped(job):
                holder["job"] = job
                return fn(job)
            return orig_submit(kind, operator, label, wrapped, **kw)
        self.app.jobs.submit = submit
        job = self.app.job_batch_scripts("bebe", sync=True)
        self.assertEqual(job.status, "canceled")
        self.assertIn("그때까지 저장한 것은 남는다", job.error)
        self.assertEqual(job.info["batch"]["saved"], 2)

    def test_blocked_scripts_are_rewritten_in_place(self):
        from qa.cases import parse_one
        vid = next(v for v, r in self.app.batch_targets())                          # 지금 스크립트 없는 케이스 하나에
        blocked = parse_one(f"id: x.blocked\ntitle: t\nsuite: sanity\nvariant: {vid}\ncovers: ['op.rooms:200']\nsteps:\n"
                            "  - request: {method: GET, path: /TODO/x}\n    covers: ['op.rooms:200']\n")
        blocked.audit = {"status": "error", "errors": ["step 1: 경로가 완성되지 않았다"], "warnings": []}     # 검사에 걸린 스크립트를 둔다
        self.app.cases["x.blocked"] = blocked
        self.assertIn((vid, "x.blocked"), self.app.batch_targets())
        got = {}

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None, replace=None, rewrite_note=None):
            got[variant] = replace
            return {"saved": [{"id": "d-1"}], "rejected": []}
        self.app.generate_cases = fake
        self.app.job_batch_scripts("bebe", slug=vid.split("/")[0], sync=True)
        self.assertEqual(got[vid], "x.blocked")                                       # 같은 id 로 다시 쓰게 넘긴다

    def test_notify_missing_scripts_are_rewritten_with_note(self):
        from qa.cases import parse_one
        vid = next(v for v, r in self.app.batch_targets())
        c = parse_one(f"id: x.no-notify\ntitle: t\nsuite: sanity\nvariant: {vid}\ncovers: ['op.createRoomComment:200']\nactor: qa-host\nsteps:\n"
                      "  - request: {method: POST, path: '/v1/rooms/{{roomId}}/comments', body: {content: hi}}\n    covers: ['op.createRoomComment:200']\n"
                      "    expect: {status: 200}\n")
        c.audit = {"status": "ok", "errors": [], "warnings": []}
        self.app.cases["x.no-notify"] = c
        self.app.op_of = lambda m, p: "createRoomComment" if p.endswith("/comments") else None
        self.assertEqual(self.app.notify_gaps(), {"x.no-notify": [("createRoomComment", "ROOM_COMMENT_POSTED")]})
        self.assertIn((vid, "x.no-notify"), self.app.notify_targets())
        self.assertNotIn(vid, [v for v, _ in self.app.batch_targets()])                # 스크립트가 있으니 '없음' 은 아니다
        got = {}

        def fake(*, tc_ids, operator, session_hash, ip, ask=None, variant=None, replace=None, rewrite_note=None):
            got[variant] = (replace, rewrite_note)
            return {"saved": [{"id": "d-1"}], "rejected": []}
        self.app.generate_cases = fake
        self.app.job_batch_scripts("bebe", slug=vid.split("/")[0], sync=True)
        replace, note = got[vid]
        self.assertEqual(replace, "x.no-notify")                                      # 같은 id 로 다시 쓴다
        self.assertIn("ROOM_COMMENT_POSTED", note)                                    # 빠진 알림과
        self.assertIn("id: x.no-notify", note)                                        # 지금 스크립트를 보여 준다

    def test_manual_variant_scripts_held(self):
        from types import SimpleNamespace
        manual = next(f"{slug}/{s.id}/{v.key}" for slug, ft in self.app.features.items() for s in ft.scenarios for v in s.variants if v.mode == "manual")
        auto = next(f"{slug}/{s.id}/{v.key}" for slug, ft in self.app.features.items() for s in ft.scenarios for v in s.variants if v.mode != "manual")
        a, b, c = SimpleNamespace(id="a", variant=auto), SimpleNamespace(id="b", variant=manual), SimpleNamespace(id="c", variant=None)
        keep, held = self.app.split_manual_variant_cases([a, b, c])
        self.assertEqual(([x.id for x in keep], [x.id for x in held]), (["a", "c"], ["b"]))     # 백엔드 미구현 등 수동 케이스의 스크립트는 스위트에서 뺀다


if __name__ == "__main__":
    unittest.main()
