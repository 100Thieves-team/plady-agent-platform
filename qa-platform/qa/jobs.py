"""Hermes 작업 — 오래 걸리는 Hermes 호출을 뒤에서 돌리고 진행 단계를 SSE 로 보여 준다. docs/qa-platform-progress.md.

- 작업은 사람이 버튼을 눌렀을 때만 생긴다. 재시도도 사람이 한다. 재시작 때 끝나지 않은 작업은 interrupted 로 닫는다.
- 동시에 도는 작업은 QA_JOB_CONCURRENCY(기본 2)건, 나머지는 대기. 대화 위젯은 이 제한 밖이다.
- 진행 상태는 메모리(Job)에 두고 SSE 가 읽는다. 단계가 바뀔 때와 끝날 때 hermes_jobs 표에 쓴다.
- 작업 함수 fn(job) 은 job.ask 를 drafts.generate 등의 ask 로 넘긴다. 반환은 {"summary": str, "links": [{href, label}]}.
"""
from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime, timezone

from . import hermes
from .config import Config

KINDS = {"draft": "Hermes 가 스크립트 쓰기", "scenario": "Hermes 가 케이스 채우기", "propose": "수동 작성 테스트 조건 제안", "revise": "바뀐 테스트 조건에 맞게 고치기", "triage": "Hermes 실패 분석"}
STAGES_FULL = ["대기", "근거 모으기", "Hermes 에게 보냄", "Hermes 가 쓰는 중", "검증하고 저장", "끝"]
STAGES_SHORT = ["대기", "근거 모으기", "Hermes 에게 보냄", "Hermes 가 쓰는 중", "끝"]
TERMINAL = ("done", "failed", "canceled", "interrupted")
STATUS_KO = {"queued": "대기", "running": "도는 중", "done": "끝", "failed": "실패", "canceled": "그만둠", "interrupted": "중단"}
TEXT_LIMIT = 200_000
KEEP = 200


def _iso(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts or time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Job:
    def __init__(self, mgr: "Jobs", kind: str, operator: str, label: str, back: dict | None):
        self.mgr = mgr
        self.id = "j-" + secrets.token_hex(4)
        self.kind = kind
        self.operator = operator
        self.label = label
        self.back = back or {}
        self.stages = STAGES_SHORT if kind == "triage" else STAGES_FULL
        self.stage = "대기"
        self.status = "queued"
        self.info: dict = {"tools": []}
        self.text = ""
        self.result: dict = {}
        self.error: str | None = None
        self.created = time.time()
        self.started: float | None = None
        self.finished: float | None = None
        self.last_recv: float | None = None
        self.cancel = threading.Event()
        self.version = 0

    # ---- 작업 스레드가 부른다 ----
    def _bump(self, persist: bool = False):
        with self.mgr.cond:
            self.version += 1
            self.mgr.cond.notify_all()
        if persist:
            self.mgr.persist(self)

    def set_stage(self, stage: str, **info):
        self.stage = stage
        self.info.update(info)
        self._bump(persist=True)

    def _on_event(self, kind: str, data):
        self.last_recv = time.time()
        if kind == "delta":
            if self.stage != "Hermes 가 쓰는 중":
                self.stage = "Hermes 가 쓰는 중"
                self.mgr.persist(self)
            if len(self.text) < TEXT_LIMIT:
                self.text += data
            self.info["received_chars"] = self.info.get("received_chars", 0) + len(data)
        elif kind == "tool":
            self.info["tools"] = (self.info.get("tools") or []) + [str((data or {}).get("name") or "?")]
        self._bump()

    def ask(self, system: str, prompt: str, session_prefix: str) -> str:
        """drafts.generate 등에 넘기는 ask. 단계: Hermes 에게 보냄 → 쓰는 중 → (검증)."""
        if self.cancel.is_set():
            raise hermes.Canceled("그만둠")
        self.set_stage("Hermes 에게 보냄", prompt_chars=len(prompt))
        cfg = self.mgr.cfg
        text = self.mgr.asker(cfg, system, prompt, session_prefix=session_prefix, on_event=self._on_event, cancel=self.cancel,
                              deadline=(self.started or time.time()) - time.time() + time.monotonic() + cfg.job_timeout, stall=cfg.job_stall)
        if len(self.text) < len(text):       # 스트리밍이 조각을 안 준 경우에도 받은 글은 보인다
            self.text = text[:TEXT_LIMIT]
        self.info["received_chars"] = len(text)
        self.set_stage("검증하고 저장" if "검증하고 저장" in self.stages else "끝")
        return text

    # ---- 읽기 ----
    def snapshot(self, with_text: bool = False) -> dict:
        now = time.time()
        d = {"id": self.id, "kind": self.kind, "kind_ko": KINDS.get(self.kind, self.kind), "operator": self.operator, "label": self.label,
             "status": self.status, "status_ko": STATUS_KO.get(self.status, self.status), "stage": self.stage, "stages": self.stages,
             "info": dict(self.info, queue_ahead=self.mgr.queue_ahead(self) if self.status == "queued" else 0),
             "created_at": _iso(self.created), "started_at": _iso(self.started) if self.started else None,
             "finished_at": _iso(self.finished) if self.finished else None,
             "elapsed": int((self.finished or now) - (self.started or self.created)),
             "since_recv": int(now - self.last_recv) if self.last_recv else None, "timeout": self.mgr.cfg.job_timeout,
             "result": self.result, "error": self.error, "back": self.back, "version": self.version, "text_len": len(self.text)}
        if with_text:
            d["text"] = self.text
        return d


class Jobs:
    def __init__(self, cfg: Config, store, asker=None):
        self.cfg = cfg
        self.store = store
        self.asker = asker or hermes.ask_stream
        self.cond = threading.Condition()
        self.jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._slots = threading.Semaphore(max(1, cfg.job_concurrency))
        self.interrupted = store.interrupt_jobs()

    def submit(self, kind: str, operator: str, label: str, fn, *, back: dict | None = None, sync: bool = False) -> Job:
        """작업을 만들고 스레드에서 돌린다. sync=True 는 테스트용 — 호출한 스레드에서 끝까지 돌린다."""
        job = Job(self, kind, operator, label, back)
        with self.cond:
            self.jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > KEEP:
                old = self._order.pop(0)
                if self.jobs.get(old) and self.jobs[old].status in TERMINAL:
                    self.jobs.pop(old, None)
        self.store.add_job({"id": job.id, "kind": kind, "operator": operator, "label": label, "status": job.status, "stage": job.stage,
                            "created_at": _iso(job.created), "back": job.back})
        if sync:
            self._run(job, fn)
        else:
            threading.Thread(target=self._run, args=(job, fn), name=f"job-{job.id}", daemon=True).start()
        return job

    def _run(self, job: Job, fn):
        got = False
        try:
            while not job.cancel.is_set():
                if self._slots.acquire(timeout=0.5):
                    got = True
                    break
                job._bump()                     # 대기 순번 갱신
            if not got:
                self._end(job, "canceled", error="대기 중에 그만뒀다")
                return
            job.status = "running"
            job.started = time.time()
            job.set_stage("근거 모으기")
            result = fn(job) or {}
            if job.cancel.is_set():
                self._end(job, "canceled", error="그만뒀다 — 결과를 저장하지 않았다")
                return
            job.result = result
            self._end(job, "done")
        except hermes.Canceled:
            self._end(job, "canceled", error="그만뒀다 — 결과를 저장하지 않았다")
        except Exception as ex:           # BadRequest 포함 — 메시지를 그대로 보여 준다
            self._end(job, "failed", error=str(ex)[:1000] or type(ex).__name__)
        finally:
            if got:
                self._slots.release()

    def _end(self, job: Job, status: str, error: str | None = None):
        job.status = status
        job.error = error
        job.finished = time.time()
        if status == "done":
            job.stage = "끝"
        job._bump(persist=True)

    def persist(self, job: Job):
        self.store.update_job(job.id, status=job.status, stage=job.stage, info=job.info, result=job.result, error=job.error,
                              started_at=_iso(job.started) if job.started else None,
                              finished_at=_iso(job.finished) if job.finished else None,
                              text=job.text if job.status in TERMINAL else None)

    def queue_ahead(self, job: Job) -> int:
        with self.cond:
            ids = [i for i in self._order if self.jobs.get(i) and self.jobs[i].status == "queued"]
        return ids.index(job.id) if job.id in ids else 0

    def get(self, jid: str) -> Job | None:
        return self.jobs.get(jid)

    def snapshot(self, jid: str, with_text: bool = False) -> dict | None:
        """메모리에 있으면 그것, 없으면(재시작 뒤·오래된 작업) 표에서."""
        j = self.jobs.get(jid)
        if j is not None:
            return j.snapshot(with_text)
        r = self.store.get_job(jid)
        if not r:
            return None
        stages = STAGES_SHORT if r["kind"] == "triage" else STAGES_FULL
        return {"id": r["id"], "kind": r["kind"], "kind_ko": KINDS.get(r["kind"], r["kind"]), "operator": r["operator"], "label": r.get("label"),
                "status": r["status"], "status_ko": STATUS_KO.get(r["status"], r["status"]), "stage": r.get("stage"), "stages": stages,
                "info": r.get("info") or {}, "created_at": r["created_at"], "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
                "elapsed": None, "since_recv": None, "timeout": self.cfg.job_timeout, "result": r.get("result") or {}, "error": r.get("error"),
                "back": r.get("back") or {}, "version": 0, "text_len": len(r.get("text") or ""), **({"text": r.get("text") or ""} if with_text else {})}

    def wait(self, job: Job, version: int, timeout: float) -> bool:
        """version 이 바뀔 때까지 기다린다. 바뀌었으면 True."""
        with self.cond:
            return self.cond.wait_for(lambda: job.version != version, timeout=timeout)

    def cancel(self, jid: str) -> bool:
        j = self.jobs.get(jid)
        if j is None or j.status in TERMINAL:
            return False
        j.cancel.set()
        j._bump()
        return True

    def active(self) -> list[dict]:
        with self.cond:
            js = [self.jobs[i] for i in self._order if i in self.jobs]
        return [j.snapshot() for j in reversed(js) if j.status not in TERMINAL]
