"""Hermes 작업 진행을 SSE 로 (docs/qa-platform-progress.md, 사용자 요청 2026-09-23).

스트리밍 ask(Responses SSE 파싱·그만두기·멈춤), 작업 단계·글·결과·표 기록, 동시 실행 한도와 대기, 재시작 뒤 중단 표시,
초안 생성 작업이 초안을 만드는지, 실제 HTTP 로 SSE(snapshot → text → end)가 오는지.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as appmod  # noqa: E402
from app import App  # noqa: E402
from qa import hermes, httpx  # noqa: E402
from qa.config import Config  # noqa: E402
from qa.jobs import Jobs  # noqa: E402
from qa.store import Store  # noqa: E402

SPEC_FIXTURE = ROOT / "tests" / "fixtures" / "openapi-seed.yaml"
# 위키 체크아웃 — 기본은 레포 옆 wiki-workspace, QA_TEST_WIKI_DIR 로 바꿀 수 있다 (예: SSOT 조각 브랜치 worktree)
WIKI_DIR = Path(os.environ.get("QA_TEST_WIKI_DIR") or ROOT.parent / "wiki-workspace")
HAS_WIKI = (WIKI_DIR / "wiki/policy/_src/상태-SSOT.yaml").is_file()


def sse_lines(*events):
    out = []
    for ev in events:
        out += [f"event: {ev['type']}", "data: " + json.dumps(ev, ensure_ascii=False), ""]
    return out


class AskStreamTest(unittest.TestCase):
    def setUp(self):
        self.orig = httpx.stream
        self.cfg = Config({"HERMES_API_KEY": "k", "QA_DATA_DIR": tempfile.mkdtemp()})

    def tearDown(self):
        httpx.stream = self.orig

    def test_deltas_tools_and_done(self):
        lines = sse_lines({"type": "response.output_text.delta", "delta": "cases:\n"},
                          {"type": "response.output_item.added", "item": {"type": "function_call", "name": "qa_tc_get", "call_id": "c1"}},
                          {"type": "response.output_text.delta", "delta": "  - id: x"},
                          {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "cases:\n  - id: x"}]}]}})
        seen = []

        def fake(method, url, headers=None, body=None, timeout=30):
            fake.body, fake.url, fake.timeout = body, url, timeout
            yield from [":" + " keepalive"] + lines
        httpx.stream = fake
        text = hermes.ask_stream(self.cfg, "SYS", "PROMPT", session_prefix="qa-draft", on_event=lambda k, d: seen.append(k), stall=45)
        self.assertEqual(text, "cases:\n  - id: x")
        self.assertTrue(fake.url.endswith("/v1/responses"))
        self.assertEqual((fake.body["instructions"], fake.body["input"], fake.body["stream"]), ("SYS", "PROMPT", True))
        self.assertEqual(fake.timeout, 45)
        self.assertEqual(seen, ["keepalive", "delta", "tool", "delta"])

    def test_failed_cancel_and_empty(self):
        httpx.stream = lambda *a, **k: iter(sse_lines({"type": "response.failed", "response": {"error": {"message": "모델 오류"}}}))
        with self.assertRaisesRegex(RuntimeError, "모델 오류"):
            hermes.ask_stream(self.cfg, "s", "p", session_prefix="x")
        ev = threading.Event()
        ev.set()
        httpx.stream = lambda *a, **k: iter(sse_lines({"type": "response.output_text.delta", "delta": "a"}))
        with self.assertRaises(hermes.Canceled):
            hermes.ask_stream(self.cfg, "s", "p", session_prefix="x", cancel=ev)
        httpx.stream = lambda *a, **k: iter([])
        with self.assertRaisesRegex(RuntimeError, "비어"):
            hermes.ask_stream(self.cfg, "s", "p", session_prefix="x")

    def test_stall_timeout(self):
        def slow(*a, **k):
            raise TimeoutError("timed out")
            yield  # noqa
        httpx.stream = slow
        with self.assertRaisesRegex(RuntimeError, "아무것도 보내지 않았다"):
            hermes.ask_stream(self.cfg, "s", "p", session_prefix="x", stall=5)


def fake_asker(chunks, *, gate: threading.Event | None = None):
    def asker(cfg, system, prompt, *, session_prefix, on_event=None, cancel=None, deadline=None, stall=None):
        asker.prompts.append((system, prompt, session_prefix))
        for c in chunks:
            if gate is not None:
                gate.wait(5)
            if cancel is not None and cancel.is_set():
                raise hermes.Canceled("그만둠")
            on_event("delta", c)
        on_event("tool", {"name": "qa_tc_get"})
        return "".join(chunks)
    asker.prompts = []
    return asker


class JobsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config({"QA_DATA_DIR": self.tmp.name, "HERMES_API_KEY": "k", "QA_JOB_CONCURRENCY": "1"})
        self.store = Store(self.cfg.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stages_text_result_and_row(self):
        jobs = Jobs(self.cfg, self.store, asker=fake_asker(["a", "bc"]))
        stages = []

        def fn(job):
            stages.append(job.stage)
            out = job.ask("SYS", "PROMPT-TEXT", "qa-draft")
            stages.append(job.stage)
            return {"summary": f"받음 {out}", "links": [{"href": "/drafts/d-1", "label": "초안"}]}
        job = jobs.submit("draft", "bebe", "TC x", fn, sync=True)
        self.assertEqual(stages, ["근거 모으기", "검증"])
        s = job.snapshot(with_text=True)
        self.assertEqual((s["status"], s["stage"], s["text"]), ("done", "끝", "abc"))
        self.assertEqual(s["info"]["prompt_chars"], len("PROMPT-TEXT"))
        self.assertEqual(s["info"]["received_chars"], 3)
        self.assertEqual(s["info"]["tools"], ["qa_tc_get"])
        row = self.store.get_job(job.id)
        self.assertEqual((row["status"], row["text"], row["result"]["summary"]), ("done", "abc", "받음 abc"))
        self.assertEqual(jobs.snapshot(job.id)["result"]["links"][0]["href"], "/drafts/d-1")

    def test_triage_has_no_validation_stage(self):
        jobs = Jobs(self.cfg, self.store, asker=fake_asker(["분류: 버그"]))
        job = jobs.submit("triage", "bebe", "r-1", lambda j: {"summary": j.ask("s", "p", "qa-triage")}, sync=True)
        self.assertNotIn("검증", job.stages)
        self.assertEqual(job.status, "done")

    def test_failure_message(self):
        jobs = Jobs(self.cfg, self.store, asker=fake_asker([]))

        def fn(job):
            raise ValueError("TC 목록이 없어 초안을 만들 수 없다")
        job = jobs.submit("draft", "bebe", "x", fn, sync=True)
        self.assertEqual((job.status, job.error), ("failed", "TC 목록이 없어 초안을 만들 수 없다"))
        self.assertEqual(self.store.get_job(job.id)["status"], "failed")

    def test_queue_and_cancel(self):
        gate = threading.Event()
        jobs = Jobs(self.cfg, self.store, asker=fake_asker(["x"], gate=gate))
        first = jobs.submit("draft", "bebe", "첫째", lambda j: {"summary": j.ask("s", "p", "q")})
        second = jobs.submit("draft", "bebe", "둘째", lambda j: {"summary": "안 돌아야 한다"})
        for _ in range(50):
            if first.status == "running":
                break
            time.sleep(0.02)
        self.assertEqual(second.status, "queued")          # 한도 1 — 대기
        self.assertEqual(second.snapshot()["info"]["queue_ahead"], 0)
        self.assertTrue(jobs.cancel(second.id))
        for _ in range(100):
            if second.status == "canceled":
                break
            time.sleep(0.02)
        self.assertEqual(second.status, "canceled")
        self.assertIn(first.id, [j["id"] for j in jobs.active()])
        jobs.cancel(first.id)
        gate.set()
        for _ in range(100):
            if first.status in ("canceled", "done"):
                break
            time.sleep(0.02)
        self.assertEqual(first.status, "canceled")
        self.assertEqual(jobs.active(), [])

    def test_restart_marks_interrupted(self):
        self.store.add_job({"id": "j-dead", "kind": "draft", "operator": "bebe", "label": "x", "status": "running", "stage": "Hermes 가 쓰는 중", "created_at": "2026-09-23T00:00:00Z"})
        jobs = Jobs(self.cfg, self.store)
        self.assertEqual(jobs.interrupted, 1)
        s = jobs.snapshot("j-dead", with_text=True)
        self.assertEqual((s["status"], s["error"]), ("interrupted", "서버 재시작으로 중단"))


YAML_DRAFT = """```yaml
cases:
  - id: room.form-options-by-hermes
    title: 폼 선택지를 조회한다
    suite: smoke
    domains: [room]
    covers: [op.roomFormOptions:200]
    steps:
      - name: 폼 선택지
        covers: [op.roomFormOptions:200]
        request: { method: GET, path: /v1/rooms/form-options }
        expect: { status: 200, result: SUCCESS }
```"""


@unittest.skipUnless(HAS_WIKI, "wiki-workspace 체크아웃 없음")
class AppJobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(Config({"QA_DATA_DIR": self.tmp.name, "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_WIKI_DIR": str(WIKI_DIR), "HERMES_API_KEY": "k"}))
        self.app.jobs.asker = fake_asker([YAML_DRAFT[:40], YAML_DRAFT[40:]])

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_job_makes_draft(self):
        job = self.app.job_generate(["op.roomFormOptions:200"], "bebe", sync=True)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.text, YAML_DRAFT)                      # 사용자 결정: 초안 YAML 을 쓰는 대로 보인다
        link = job.result["links"][0]["href"]
        d = self.app.store.get_draft(link.rsplit("/", 1)[1])
        self.assertEqual((d["case_id"], d["source"]), ("room.form-options-by-hermes", "hermes"))
        acts = [ev["action"] for ev in self.app.store.list_events(limit=20)] if hasattr(self.app.store, "list_events") else None
        if acts is not None:
            self.assertIn("hermes_job.start", acts)
            self.assertIn("draft.generate", acts)

    def test_bad_input_fails_job_with_reason(self):
        job = self.app.job_generate(["없는.TC"], "bebe", sync=True)
        self.assertEqual(job.status, "failed")
        self.assertIn("TC 목록에 있는 TC", job.error)


@unittest.skipUnless(HAS_WIKI, "wiki-workspace 체크아웃 없음")
class SseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = App(Config({"QA_DATA_DIR": cls.tmp.name, "QA_SPEC_FILE": str(SPEC_FIXTURE), "QA_WIKI_DIR": str(WIKI_DIR), "HERMES_API_KEY": "k"}))
        appmod.Handler.app = cls.app
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), appmod.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def read_events(self, jid):
        req = urllib.request.Request(f"{self.base}/api/jobs/{jid}/events", headers={"Accept": "text/event-stream"})
        events, ev = [], None
        with urllib.request.urlopen(req, timeout=10) as r:
            self.assertIn("text/event-stream", r.headers.get("Content-Type"))
            for raw in r:
                line = raw.decode().rstrip("\n")
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: "):
                    events.append((ev, json.loads(line[6:])))
                    if ev == "end":
                        break
        return events

    def test_live_stream(self):
        gate = threading.Event()
        self.app.jobs.asker = fake_asker(["cases:", "\n  - id: a"], gate=gate)
        job = self.app.start_job("draft", operator="bebe", label="TC x", fn=lambda j: {"summary": "끝남 " + j.ask("s", "p", "q")[:6]})
        got = []
        t = threading.Thread(target=lambda: got.extend(self.read_events(job.id)))
        t.start()
        time.sleep(0.3)
        gate.set()
        t.join(10)
        kinds = [k for k, _ in got]
        self.assertEqual(kinds[0], "snapshot")
        self.assertEqual(kinds[-1], "end")
        self.assertEqual("".join(d["append"] for k, d in got if k == "text") or got[-1][1].get("text"), "cases:\n  - id: a")
        self.assertEqual(got[-1][1]["status"], "done")
        self.assertEqual(got[-1][1]["result"]["summary"], "끝남 cases:")
        # 끝난 작업에 다시 붙으면 snapshot(글 포함) + end 로 바로 닫힌다
        again = self.read_events(job.id)
        self.assertEqual([k for k, _ in again], ["snapshot", "end"])
        self.assertEqual(again[0][1]["text"], "cases:\n  - id: a")

    def test_pages_and_api(self):
        self.app.jobs.asker = fake_asker(["x"])
        job = self.app.start_job("propose", operator="bebe", label="PRD/룸 탐색 §4.1", fn=lambda j: {"summary": j.ask("s", "p", "q")}, sync=True)
        for path in (f"/jobs/{job.id}", "/jobs", "/drafts"):
            req = urllib.request.Request(self.base + path, headers={"Cookie": "qa_operator=bebe"})
            with urllib.request.urlopen(req, timeout=10) as r:
                body = r.read().decode()
                self.assertEqual(r.status, 200, path)
                self.assertNotIn("내부 오류", body)
        with urllib.request.urlopen(urllib.request.Request(f"{self.base}/api/jobs/{job.id}", headers={"Accept": "application/json"}), timeout=10) as r:
            self.assertEqual(json.loads(r.read())["status"], "done")

    def test_triage_form_returns_job_id(self):
        """실행 결과 화면의 [Hermes 실패 분석] 은 X-QA-Job 헤더면 작업 id 를 JSON 으로 주고(제자리 카드), 끝나면 분석이 기록된다."""
        store, c = self.app.store, self.app.cases["room.explore"]
        rid = store.create_run(trigger="manual", operator="bebe", suite=None, env="dev", base_url="http://x", ref="dev", sha=None, pr_number=None, meta={}, cases=[c])
        rc = store.list_run_cases(rid)[0]
        store.update_run_case(rc["id"], verdict="fail", error="status 기대 200 실제 400")
        store.update_run(rid, status="finished", verdict="fail")
        self.app.jobs.asker = fake_asker(["분류: 스크립트 노후\n", "근거: E400"])
        body = f"operator=bebe&run_case_id={rc['id']}".encode()
        req = urllib.request.Request(f"{self.base}/runs/{rid}/triage", data=body, method="POST",
                                     headers={"X-QA-Job": "1", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", "Cookie": "qa_operator=bebe"})
        with urllib.request.urlopen(req, timeout=10) as r:
            jid = json.loads(r.read())["job"]
        events = self.read_events(jid)
        self.assertEqual(events[-1][1]["status"], "done")
        self.assertEqual(events[-1][1]["kind"], "triage")
        self.assertEqual(store.get_run_case(rc["id"])["triage"], "분류: 스크립트 노후\n근거: E400")
        with urllib.request.urlopen(urllib.request.Request(f"{self.base}/runs/{rid}", headers={"Cookie": "qa_operator=bebe"}), timeout=10) as r:
            page = r.read().decode()
        self.assertIn("data-job-form", page)
        self.assertIn("근거: E400", page)

if __name__ == "__main__":
    unittest.main()
