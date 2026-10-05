"""sqlite 저장소 — 런·단계·감사 로그·초안·Hermes 대화. 스크립트 정본은 여기 없다. docs/qa-platform.md §9."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT,
  trigger TEXT NOT NULL, operator TEXT NOT NULL, suite TEXT, env TEXT, base_url TEXT,
  ref TEXT, sha TEXT, pr_number INTEGER, status TEXT NOT NULL DEFAULT 'queued',
  verdict TEXT, total INTEGER DEFAULT 0, passed INTEGER DEFAULT 0, failed INTEGER DEFAULT 0,
  errored INTEGER DEFAULT 0, skipped INTEGER DEFAULT 0, meta TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_cases (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, ord INTEGER NOT NULL,
  case_id TEXT NOT NULL, case_title TEXT NOT NULL, case_suite TEXT NOT NULL, case_hash TEXT NOT NULL,
  case_yaml TEXT NOT NULL, verdict TEXT NOT NULL DEFAULT 'queued', duration_ms INTEGER,
  error TEXT, triage TEXT, triaged_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_cases_run ON run_cases(run_id, ord);
CREATE INDEX IF NOT EXISTS ix_run_cases_case ON run_cases(case_id, id);
CREATE TABLE IF NOT EXISTS run_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_case_id INTEGER NOT NULL, ord INTEGER NOT NULL,
  name TEXT NOT NULL, request TEXT NOT NULL, response TEXT, checks TEXT NOT NULL,
  verdict TEXT NOT NULL, duration_ms INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_steps_case ON run_steps(run_case_id, ord);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, operator TEXT NOT NULL,
  session_hash TEXT, ip TEXT, action TEXT NOT NULL, target TEXT, detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_events_at ON events(at DESC);
CREATE TABLE IF NOT EXISTS drafts (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, operator TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft', source TEXT NOT NULL, domain TEXT, yaml TEXT NOT NULL, note TEXT
);
-- Hermes 대화 (docs/qa-platform-hermes.md §5). 대화 하나 = Hermes 세션 키 하나. 메시지는 전부 남긴다.
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, operator TEXT NOT NULL, title TEXT,
  session_key TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'open',
  turns INTEGER NOT NULL DEFAULT 0, drafts INTEGER NOT NULL DEFAULT 0, last_response_id TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, at TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
  tool_calls TEXT NOT NULL DEFAULT '[]', draft_ids TEXT NOT NULL DEFAULT '[]', ms INTEGER, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_chat_messages_chat ON chat_messages(chat_id, id);
"""
# P2b 에서 늘어난 초안 열. 이미 만들어진 DB 에는 ALTER 로 더한다 (sqlite 는 IF NOT EXISTS 가 없다).
DRAFT_COLUMNS = {"case_id": "TEXT", "tc_ids": "TEXT NOT NULL DEFAULT '[]'", "validation": "TEXT NOT NULL DEFAULT '{}'",
                 "prompt_hash": "TEXT", "run_id": "TEXT", "decided_by": "TEXT", "decided_at": "TEXT",
                 # P4: kind case(스크립트 YAML) | tc(서술 TC 제안 — manual-tc.yaml 에 사람이 옮긴다)
                 "kind": "TEXT NOT NULL DEFAULT 'case'",
                 # 폼 편집 (docs/qa-platform-editor.md): kind 에 case-delete · tc-delete 가 더해졌다. 승인 때 main 에 바로 커밋한 결과
                 "commit_sha": "TEXT", "commit_url": "TEXT", "file": "TEXT"}
# P5b: 단계가 부른 OpenAPI operationId. 기록 시점에 박아 두어 스펙이 바뀌어도 과거 기록의 해석이 안 바뀐다(런 불변).
# 이전 행은 NULL — 조회 때 method/path 로 폴백 매칭(app.py), 백필하지 않는다. docs/qa-platform-api.md §6.
STEP_COLUMNS = {"op_id": "TEXT"}
# 플랫폼이 dev 전용 API(POST /v1/dev/members)로 만든 QA 테스트 회원. 이름(label)이 테스트 계정 이름처럼 쓰인다 — actor: qa-3
# Hermes 작업 (docs/qa-platform-progress.md) — 초안 생성·TC 제안·고치기·실패 분석을 뒤에서 돌린 기록. 진행 중 상태는 메모리,
# 이 표는 새로 고침·재시작 뒤 결과를 찾는 용도. 서버가 재시작되면 끝나지 않은 작업은 interrupted 로 닫는다(다시 돌리지 않는다).
JOBS_SQL = """CREATE TABLE IF NOT EXISTS hermes_jobs (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, operator TEXT NOT NULL, label TEXT, status TEXT NOT NULL, stage TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, info TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT '{}',
  error TEXT, text TEXT, back TEXT
);
CREATE INDEX IF NOT EXISTS ix_hermes_jobs_created ON hermes_jobs(created_at);
"""
# Sanity (docs/qa-platform-v2.md §4, §9.1) — PR 하나를 스펙대로 확인한 한 번. 다섯 단계의 결과를 JSON 으로 쌓는다.
SANITY_SQL = """CREATE TABLE IF NOT EXISTS sanity (
  id TEXT PRIMARY KEY, pr_number INTEGER NOT NULL, pr_title TEXT, sha TEXT, operator TEXT NOT NULL, status TEXT NOT NULL,
  step INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT,
  scope TEXT NOT NULL DEFAULT '{}', findings TEXT NOT NULL DEFAULT '[]', log TEXT NOT NULL DEFAULT '[]', run_id TEXT, job_id TEXT, error TEXT
);
CREATE INDEX IF NOT EXISTS ix_sanity_pr ON sanity(pr_number, created_at);
"""
# 대상 서버 (docs/qa-platform-v2.md §13) — dev 는 설정값이 기본이고 여기에는 더한 것만. settings 는 담당자별 고른 대상 같은 작은 값.
TARGETS_SQL = """CREATE TABLE IF NOT EXISTS targets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL, actors TEXT NOT NULL DEFAULT '{}', operator TEXT NOT NULL,
  created_at TEXT NOT NULL, deleted_at TEXT, probe TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
"""
INBOX_SQL = """CREATE TABLE IF NOT EXISTS inbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, base_url TEXT NOT NULL, actor TEXT, address TEXT,
  type TEXT, title TEXT, body TEXT, link TEXT, event_id TEXT, received_at TEXT NOT NULL, raw TEXT NOT NULL DEFAULT '',
  dedup TEXT UNIQUE, run_case_id INTEGER, step_ord INTEGER
);
CREATE INDEX IF NOT EXISTS ix_inbox_at ON inbox(received_at DESC);
CREATE INDEX IF NOT EXISTS ix_inbox_actor ON inbox(base_url, actor, received_at);
CREATE TABLE IF NOT EXISTS receivers (
  base_url TEXT NOT NULL, actor TEXT NOT NULL, member_id TEXT, email TEXT, push_token TEXT, credentials TEXT,
  enabled INTEGER NOT NULL DEFAULT 0, status TEXT, error TEXT, last_at TEXT, operator TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (base_url, actor)
);
"""
QA_MEMBERS_SQL = """CREATE TABLE IF NOT EXISTS qa_members (
  member_id TEXT PRIMARY KEY, label TEXT NOT NULL UNIQUE, nickname TEXT, email TEXT, created_at TEXT NOT NULL, operator TEXT NOT NULL
);"""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_run_id() -> str:
    return "r-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)


class Store:
    def __init__(self, path: Path | str):
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        with self._lock:
            self._db.executescript(SCHEMA)
            have = {r[1] for r in self._db.execute("PRAGMA table_info(drafts)").fetchall()}
            for col, decl in DRAFT_COLUMNS.items():
                if col not in have:
                    self._db.execute(f"ALTER TABLE drafts ADD COLUMN {col} {decl}")
            have = {r[1] for r in self._db.execute("PRAGMA table_info(run_steps)").fetchall()}
            for col, decl in STEP_COLUMNS.items():
                if col not in have:
                    self._db.execute(f"ALTER TABLE run_steps ADD COLUMN {col} {decl}")
            self._db.execute("CREATE INDEX IF NOT EXISTS ix_run_steps_op ON run_steps(op_id, id)")
            self._db.executescript(QA_MEMBERS_SQL)
            self._db.executescript(JOBS_SQL)
            self._db.executescript(SANITY_SQL)
            self._db.executescript(TARGETS_SQL)
            self._db.executescript(INBOX_SQL)
            # 2026-10-05: + 주소가 아닌 팀 메일 주소로 온 메일을 담던 버그로 들어온 행을 지운다(공용 메일함의 팀 메일)
            self._db.execute("DELETE FROM inbox WHERE channel='email' AND (address IS NULL OR instr(address, '+') = 0)")

    # ---- 공통 --------------------------------------------------------------
    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def _one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self._q(sql, args)
        return rows[0] if rows else None

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            return cur.lastrowid or 0

    # ---- runs ----------------------------------------------------------------
    def create_run(self, *, trigger: str, operator: str, suite: str | None, env: str, base_url: str,
                   ref: str | None, sha: str | None, pr_number: int | None, meta: dict, cases: list) -> str:
        rid = new_run_id()
        with self._lock:
            self._x(
                "INSERT INTO runs(id,created_at,trigger,operator,suite,env,base_url,ref,sha,pr_number,status,total,meta)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,'queued',?,?)",
                (rid, now_iso(), trigger, operator, suite, env, base_url, ref, sha, pr_number, len(cases),
                 json.dumps(meta, ensure_ascii=False)),
            )
            for i, c in enumerate(cases):
                self._x(
                    "INSERT INTO run_cases(run_id,ord,case_id,case_title,case_suite,case_hash,case_yaml)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (rid, i, c.id, c.title, c.suite, c.hash, c.run_yaml()),
                )
        return rid

    def get_run(self, rid: str) -> dict | None:
        r = self._one("SELECT * FROM runs WHERE id=?", (rid,))
        if r:
            r["meta"] = json.loads(r["meta"] or "{}")
        return r

    def list_runs(self, limit: int = 50, trigger: str | None = None, exclude: tuple = ()) -> list[dict]:
        if trigger:
            rows = self._q("SELECT * FROM runs WHERE trigger=? ORDER BY created_at DESC LIMIT ?", (trigger, limit))
        elif exclude:
            marks = ",".join("?" for _ in exclude)
            rows = self._q(f"SELECT * FROM runs WHERE trigger NOT IN ({marks}) ORDER BY created_at DESC LIMIT ?", (*exclude, limit))
        else:
            rows = self._q("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,))
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
        return rows

    def runs_since(self, iso: str, trigger: str) -> list[dict]:
        return self._q("SELECT id,created_at,verdict,status FROM runs WHERE trigger=? AND created_at>=? ORDER BY created_at DESC",
                       (trigger, iso))

    def runs_for_sha(self, sha: str) -> list[dict]:
        return self._q("SELECT id,created_at,verdict,status,trigger FROM runs WHERE sha=? ORDER BY created_at DESC", (sha,))

    def update_run(self, rid: str, **fields):
        if "meta" in fields and isinstance(fields["meta"], dict):
            fields["meta"] = json.dumps(fields["meta"], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE runs SET {cols} WHERE id=?", (*fields.values(), rid))

    def merge_run_meta(self, rid: str, patch: dict):
        with self._lock:
            r = self.get_run(rid)
            if not r:
                return
            m = r["meta"]
            m.update(patch)
            self.update_run(rid, meta=m)

    def queued_runs(self) -> list[str]:
        return [r["id"] for r in self._q("SELECT id FROM runs WHERE status='queued' ORDER BY created_at")]

    # ---- run_cases / steps ----------------------------------------------------
    def list_run_cases(self, rid: str) -> list[dict]:
        return self._q("SELECT * FROM run_cases WHERE run_id=? ORDER BY ord", (rid,))

    def get_run_case(self, rcid: int) -> dict | None:
        return self._one("SELECT * FROM run_cases WHERE id=?", (rcid,))

    def update_run_case(self, rcid: int, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE run_cases SET {cols} WHERE id=?", (*fields.values(), rcid))

    def add_step(self, rcid: int, ord_: int, name: str, request: dict, response: dict | None,
                 checks: list, verdict: str, duration_ms: int, error: str | None, op_id: str | None = None) -> int:
        return self._x(
            "INSERT INTO run_steps(run_case_id,ord,name,request,response,checks,verdict,duration_ms,error,op_id)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (rcid, ord_, name, json.dumps(request, ensure_ascii=False),
             json.dumps(response, ensure_ascii=False) if response is not None else None,
             json.dumps(checks, ensure_ascii=False), verdict, duration_ms, error, op_id),
        )

    _STEP_CALL_SQL = ("SELECT s.id, s.op_id, s.name, s.verdict, s.duration_ms, s.error, s.request, s.response, s.checks,"
                      " rc.case_id, rc.case_title, r.id AS run_id, r.trigger, r.operator, r.created_at"
                      " FROM run_steps s JOIN run_cases rc ON rc.id=s.run_case_id JOIN runs r ON r.id=rc.run_id ")

    @staticmethod
    def _call_row(r: dict) -> dict:
        req = json.loads(r["request"]) if r.get("request") else {}
        resp = json.loads(r["response"]) if r.get("response") else None
        checks = json.loads(r["checks"]) if r.get("checks") else []
        return {"step_id": r["id"], "op_id": r.get("op_id"), "name": r["name"], "verdict": r["verdict"], "duration_ms": r["duration_ms"], "error": r["error"],
                "method": req.get("method"), "path": req.get("path"), "url": req.get("url"), "query": req.get("query"), "body": req.get("body"), "actor": req.get("actor"),
                "status": (resp or {}).get("status"), "checks": checks,
                "case_id": r["case_id"], "case_title": r["case_title"], "run_id": r["run_id"], "trigger": r["trigger"], "operator": r["operator"], "created_at": r["created_at"]}

    def calls_for_op(self, op_id: str, limit: int = 20) -> list[dict]:
        """이 API 를 부른 단계(최신순) — API 상세의 "최근 호출" (docs/qa-platform-api.md §5.2). op_id 가 박힌 행만."""
        return [self._call_row(r) for r in self._q(self._STEP_CALL_SQL + "WHERE s.op_id=? ORDER BY s.id DESC LIMIT ?", (op_id, limit))]

    def calls_unresolved(self, limit: int = 300) -> list[dict]:
        """op_id 가 없는 옛 단계(최신순 일부) — 조회 때 method/path 로 폴백 매칭할 재료."""
        return [self._call_row(r) for r in self._q(self._STEP_CALL_SQL + "WHERE s.op_id IS NULL ORDER BY s.id DESC LIMIT ?", (limit,))]

    def last_call_by_op(self) -> dict[str, dict]:
        """op_id 별 가장 최근 단계 (API 목록의 "마지막 호출" 열)."""
        rows = self._q(self._STEP_CALL_SQL + "WHERE s.id IN (SELECT MAX(id) FROM run_steps WHERE op_id IS NOT NULL GROUP BY op_id)")
        return {r["op_id"]: self._call_row(r) for r in rows}

    def list_steps(self, rcid: int) -> list[dict]:
        rows = self._q("SELECT * FROM run_steps WHERE run_case_id=? ORDER BY ord", (rcid,))
        for r in rows:
            r["request"] = json.loads(r["request"])
            r["response"] = json.loads(r["response"]) if r["response"] else None
            r["checks"] = json.loads(r["checks"])
            if r["request"].get("method") == "NOTIFY":       # 알림 기다리기 단계가 받은 알림 (docs/qa-platform-v2.md §15.4)
                r["inbox"] = self.inbox_for_step(rcid, r["ord"])
        return rows

    def case_history(self, case_id: str, limit: int = 10) -> list[dict]:
        return self._q(
            "SELECT rc.id, rc.run_id, rc.verdict, rc.duration_ms, rc.error, r.created_at, r.trigger, r.operator, r.sha"
            " FROM run_cases rc JOIN runs r ON r.id=rc.run_id WHERE rc.case_id=? ORDER BY rc.id DESC LIMIT ?",
            (case_id, limit),
        )

    def recent_case_results(self, limit: int = 20) -> dict[str, list[dict]]:
        """스크립트별 최근 N회 결과(최신순): verdict · duration_ms · case_hash. 통계 배지(docs/qa-platform-api.md §5.5) 재료. 대기·진행 중은 뺀다."""
        rows = self._q(
            "SELECT case_id, verdict, duration_ms, case_hash FROM ("
            " SELECT case_id, verdict, duration_ms, case_hash, ROW_NUMBER() OVER (PARTITION BY case_id ORDER BY id DESC) AS rn"
            " FROM run_cases WHERE verdict NOT IN ('queued','running')) WHERE rn<=? ORDER BY case_id, rn", (limit,))
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["case_id"], []).append(r)
        return out

    def recent_op_results(self, limit: int = 20) -> dict[str, list[dict]]:
        """API(op_id)별 최근 N회 단계 결과(최신순). op_id 가 박힌 단계만(옛 NULL 행은 제외)."""
        rows = self._q(
            "SELECT op_id, verdict, duration_ms FROM ("
            " SELECT op_id, verdict, duration_ms, ROW_NUMBER() OVER (PARTITION BY op_id ORDER BY id DESC) AS rn"
            " FROM run_steps WHERE op_id IS NOT NULL) WHERE rn<=? ORDER BY op_id, rn", (limit,))
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["op_id"], []).append(r)
        return out

    # ---- QA 테스트 회원 (dev 전용 API 로 만든 것) --------------------------------
    def add_qa_member(self, *, member_id: str, label: str, nickname: str | None, email: str | None, operator: str) -> None:
        self._x("INSERT OR REPLACE INTO qa_members(member_id,label,nickname,email,created_at,operator) VALUES(?,?,?,?,?,?)",
                (member_id, label, nickname, email, now_iso(), operator))

    def list_qa_members(self) -> list[dict]:
        return self._q("SELECT * FROM qa_members ORDER BY created_at")

    def qa_member_map(self) -> dict[str, str]:
        """label → member_id. 테스트 계정 목록(cfg.actors)에 합쳐 쓴다."""
        return {r["label"]: r["member_id"] for r in self._q("SELECT label, member_id FROM qa_members")}

    def delete_qa_member(self, member_id: str) -> None:
        self._x("DELETE FROM qa_members WHERE member_id=?", (member_id,))

    def last_verdicts(self) -> dict[str, dict]:
        """스크립트별 마지막 판정 (목록 화면용)."""
        rows = self._q(
            "SELECT rc.case_id, rc.verdict, rc.run_id, r.created_at FROM run_cases rc JOIN runs r ON r.id=rc.run_id"
            " WHERE rc.id IN (SELECT MAX(id) FROM run_cases WHERE verdict NOT IN ('queued','running') GROUP BY case_id)"
        )
        return {r["case_id"]: r for r in rows}

    # ---- events (감사 로그) -----------------------------------------------------
    def add_event(self, *, operator: str, action: str, target: str | None, detail: dict | None = None,
                  session_hash: str | None = None, ip: str | None = None) -> int:
        return self._x(
            "INSERT INTO events(at,operator,session_hash,ip,action,target,detail) VALUES(?,?,?,?,?,?,?)",
            (now_iso(), operator, session_hash, ip, action, target, json.dumps(detail or {}, ensure_ascii=False)),
        )

    def list_events(self, limit: int = 200, operator: str | None = None, action: str | None = None) -> list[dict]:
        where, args = [], []
        if operator:
            where.append("operator=?"); args.append(operator)
        if action:
            where.append("action=?"); args.append(action)
        sql = "SELECT * FROM events" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
        rows = self._q(sql, (*args, limit))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    def events_between(self, start_iso: str, end_iso: str, action: str | None = None) -> list[dict]:
        """시각대 안의 이벤트(오름차순). 채팅 턴 동안 들어온 mcp.call 을 묶어 보여 줄 때 쓴다."""
        sql, args = "SELECT * FROM events WHERE at>=? AND at<=?", [start_iso, end_iso]
        if action:
            sql += " AND action=?"; args.append(action)
        rows = self._q(sql + " ORDER BY id", tuple(args))
        for r in rows:
            r["detail"] = json.loads(r["detail"] or "{}")
        return rows

    def event_actions(self) -> list[str]:
        return [r["action"] for r in self._q("SELECT DISTINCT action FROM events ORDER BY action")]

    # ---- Hermes 작업 ----------------------------------------------------------------------
    def add_job(self, job: dict):
        self._x("INSERT INTO hermes_jobs(id,kind,operator,label,status,stage,created_at,back) VALUES(?,?,?,?,?,?,?,?)",
                (job["id"], job["kind"], job["operator"], job.get("label"), job["status"], job.get("stage"), job["created_at"],
                 json.dumps(job.get("back") or {}, ensure_ascii=False)))

    def update_job(self, jid: str, **fields):
        for k in ("info", "result"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], ensure_ascii=False, default=str)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE hermes_jobs SET {cols} WHERE id=?", (*fields.values(), jid))

    @staticmethod
    def _job(r: dict) -> dict:
        for k in ("info", "result", "back"):
            try:
                r[k] = json.loads(r.get(k) or "{}")
            except ValueError:
                r[k] = {}
        return r

    def get_job(self, jid: str) -> dict | None:
        r = self._one("SELECT * FROM hermes_jobs WHERE id=?", (jid,))
        return self._job(r) if r else None

    def list_jobs(self, limit: int = 100, active_only: bool = False) -> list[dict]:
        where = "WHERE status IN ('queued','running')" if active_only else ""
        return [self._job(r) for r in self._q(f"SELECT id,kind,operator,label,status,stage,created_at,started_at,finished_at,info,result,error,back FROM hermes_jobs {where} ORDER BY created_at DESC LIMIT ?", (limit,))]

    def interrupt_jobs(self) -> int:
        return self._x("UPDATE hermes_jobs SET status='interrupted', error='서버 재시작으로 중단', finished_at=? WHERE status IN ('queued','running')", (now_iso(),))

    # ---- drafts (스크립트 초안, docs/qa-platform-tc.md §7.3) -------------------------------------
    def add_draft(self, *, operator: str, source: str, domain: str | None, yaml_text: str, note: str | None,
                  case_id: str | None = None, tc_ids: list | None = None, validation: dict | None = None,
                  prompt_hash: str | None = None, kind: str = "case") -> str:
        did = "d-" + secrets.token_hex(4)
        t = now_iso()
        self._x("INSERT INTO drafts(id,created_at,updated_at,operator,source,domain,yaml,note,case_id,tc_ids,validation,prompt_hash,kind)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (did, t, t, operator, source, domain, yaml_text, note, case_id, json.dumps(tc_ids or [], ensure_ascii=False),
                 json.dumps(validation or {}, ensure_ascii=False), prompt_hash, kind))
        return did

    @staticmethod
    def _draft(r: dict) -> dict:
        r["tc_ids"] = json.loads(r.get("tc_ids") or "[]")
        r["validation"] = json.loads(r.get("validation") or "{}")
        return r

    def get_draft(self, did: str) -> dict | None:
        r = self._one("SELECT * FROM drafts WHERE id=?", (did,))
        return self._draft(r) if r else None

    def update_draft(self, did: str, **fields):
        for k in ("tc_ids", "validation"):
            if k in fields and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        fields["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE drafts SET {cols} WHERE id=?", (*fields.values(), did))

    def list_drafts(self, status: str | None = None, limit: int = 200) -> list[dict]:
        if status:
            rows = self._q("SELECT * FROM drafts WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, limit))
        else:
            rows = self._q("SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._draft(r) for r in rows]

    def list_changes(self, *, case_id: str | None = None, tc_id: str | None = None, limit: int = 5) -> list[dict]:
        """저장된 변경(status approved) 중 이 스크립트·테스트 조건에 대한 것, 최신순. 화면의 "최근 변경" 에 쓴다."""
        if case_id:
            rows = self._q("SELECT * FROM drafts WHERE status='approved' AND case_id=? ORDER BY decided_at DESC LIMIT ?", (case_id, limit))
        else:
            rows = self._q("SELECT * FROM drafts WHERE status='approved' AND kind IN ('tc','tc-delete') AND tc_ids LIKE ? ORDER BY decided_at DESC LIMIT ?",
                           ("%" + json.dumps(tc_id, ensure_ascii=False) + "%", limit))
        return [self._draft(r) for r in rows]

    def draft_counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self._q("SELECT status, COUNT(*) n FROM drafts GROUP BY status")}

    # ---- chats (Hermes 대화, docs/qa-platform-hermes.md §3.2) ------------------------------------
    def add_chat(self, *, operator: str, title: str | None, context: dict | None) -> str:
        cid = "c-" + secrets.token_hex(4)
        t = now_iso()
        self._x("INSERT INTO chats(id,created_at,updated_at,operator,title,session_key,context) VALUES(?,?,?,?,?,?,?)",
                (cid, t, t, operator, title, f"qa-chat-{cid}", json.dumps(context or {}, ensure_ascii=False)))
        return cid

    @staticmethod
    def _chat(r: dict) -> dict:
        r["context"] = json.loads(r.get("context") or "{}")
        return r

    def get_chat(self, cid: str) -> dict | None:
        r = self._one("SELECT * FROM chats WHERE id=?", (cid,))
        return self._chat(r) if r else None

    def update_chat(self, cid: str, **fields):
        if "context" in fields and not isinstance(fields["context"], str):
            fields["context"] = json.dumps(fields["context"], ensure_ascii=False)
        fields.setdefault("updated_at", now_iso())
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE chats SET {cols} WHERE id=?", (*fields.values(), cid))

    def list_chats(self, limit: int = 100) -> list[dict]:
        return [self._chat(r) for r in self._q("SELECT * FROM chats ORDER BY updated_at DESC LIMIT ?", (limit,))]

    def add_chat_message(self, cid: str, *, role: str, content: str, tool_calls: list | None = None, draft_ids: list | None = None,
                         ms: int | None = None, error: str | None = None) -> int:
        return self._x("INSERT INTO chat_messages(chat_id,at,role,content,tool_calls,draft_ids,ms,error) VALUES(?,?,?,?,?,?,?,?)",
                       (cid, now_iso(), role, content, json.dumps(tool_calls or [], ensure_ascii=False), json.dumps(draft_ids or [], ensure_ascii=False), ms, error))

    def list_chat_messages(self, cid: str) -> list[dict]:
        rows = self._q("SELECT * FROM chat_messages WHERE chat_id=? ORDER BY id", (cid,))
        for r in rows:
            r["tool_calls"] = json.loads(r["tool_calls"] or "[]")
            r["draft_ids"] = json.loads(r["draft_ids"] or "[]")
        return rows

    # ---- Sanity (docs/qa-platform-v2.md §9.1) ---------------------------------
    _SANITY_JSON = ("scope", "findings", "log")

    def add_sanity(self, *, pr_number: int, pr_title: str | None, sha: str | None, operator: str) -> str:
        sid = "s-" + secrets.token_hex(5)
        at = now_iso()
        self._x("INSERT INTO sanity (id, pr_number, pr_title, sha, operator, status, step, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (sid, pr_number, pr_title, sha, operator, "queued", 0, at, at))
        return sid

    def _sanity(self, r: dict | None) -> dict | None:
        if r:
            for k in self._SANITY_JSON:
                r[k] = json.loads(r[k] or ("{}" if k == "scope" else "[]"))
        return r

    def get_sanity(self, sid: str) -> dict | None:
        return self._sanity(self._one("SELECT * FROM sanity WHERE id=?", (sid,)))

    def update_sanity(self, sid: str, **fields):
        fields["updated_at"] = now_iso()
        for k in self._SANITY_JSON:
            if k in fields:
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._x(f"UPDATE sanity SET {cols} WHERE id=?", (*fields.values(), sid))

    def latest_sanity(self) -> dict[int, dict]:
        """PR 번호 → 가장 최근 Sanity."""
        out: dict[int, dict] = {}
        for r in self._q("SELECT * FROM sanity ORDER BY created_at DESC"):
            out.setdefault(r["pr_number"], self._sanity(r))
        return out

    def list_sanity(self, pr_number: int) -> list[dict]:
        return [self._sanity(r) for r in self._q("SELECT * FROM sanity WHERE pr_number=? ORDER BY created_at DESC", (pr_number,))]

    def interrupt_sanity(self) -> int:
        """재시작 때 돌던 Sanity 를 멈춤으로 닫는다(다시 돌리지 않는다 — 사람이 다시 누른다)."""
        return self._x("UPDATE sanity SET status='interrupted', updated_at=? WHERE status IN ('queued','running')", (now_iso(),))

    # ---- 대상 서버 · 설정 (docs/qa-platform-v2.md §13) --------------------------
    def add_target(self, *, name: str, base_url: str, actors: dict, operator: str, probe: dict) -> str:
        tid = "t-" + secrets.token_hex(4)
        self._x("INSERT INTO targets (id, name, base_url, actors, operator, created_at, probe) VALUES (?,?,?,?,?,?,?)",
                (tid, name, base_url, json.dumps(actors, ensure_ascii=False), operator, now_iso(), json.dumps(probe, ensure_ascii=False)))
        return tid

    @staticmethod
    def _target(r: dict | None) -> dict | None:
        if r:
            r["actors"] = json.loads(r["actors"] or "{}")
            r["probe"] = json.loads(r["probe"] or "{}")
        return r

    def list_targets(self) -> list[dict]:
        return [self._target(r) for r in self._q("SELECT * FROM targets WHERE deleted_at IS NULL ORDER BY created_at")]

    def get_target(self, tid: str) -> dict | None:
        return self._target(self._one("SELECT * FROM targets WHERE id=? AND deleted_at IS NULL", (tid,)))

    def delete_target(self, tid: str) -> None:
        self._x("UPDATE targets SET deleted_at=? WHERE id=?", (now_iso(), tid))

    def get_setting(self, key: str) -> str | None:
        r = self._one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else None

    def set_setting(self, key: str, value: str) -> None:
        self._x("INSERT INTO settings (key, value, updated_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, now_iso()))

    # ---- 알림함 (docs/qa-platform-v2.md §15) ---------------------------------
    def add_inbox(self, *, channel: str, base_url: str, actor: str | None, address: str | None, type: str | None, title: str | None,
                  body: str | None, link: str | None, event_id: str | None, raw: str, dedup: str, received_at: str | None = None) -> int | None:
        """받은 알림 한 건. dedup 이 같으면 다시 넣지 않는다(FCM 재전달, 메일함을 다시 읽을 때)."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO inbox (channel, base_url, actor, address, type, title, body, link, event_id, received_at, raw, dedup) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (channel, base_url, actor, address, type, title, body, link, event_id, received_at or now_iso(), raw, dedup))
            return cur.lastrowid if cur.rowcount else None

    def list_inbox(self, *, base_url: str | None = None, actor: str | None = None, channel: str | None = None, type: str | None = None,
                   address: str | None = None, since: str | None = None, after_id: int = 0, limit: int = 200) -> list[dict]:
        sql, args = "SELECT * FROM inbox WHERE id > ?", [after_id]
        for col, v in (("base_url", base_url), ("actor", actor), ("channel", channel), ("type", type), ("address", address)):
            if v:
                sql += f" AND {col}=?"
                args.append(v)
        if since:
            sql += " AND received_at >= ?"
            args.append(since)
        return self._q(sql + " ORDER BY id DESC LIMIT ?", (*args, limit))

    def get_inbox(self, iid: int) -> dict | None:
        return self._one("SELECT * FROM inbox WHERE id=?", (iid,))

    def link_inbox(self, ids: list[int], run_case_id: int, step_ord: int) -> None:
        for i in ids:
            self._x("UPDATE inbox SET run_case_id=?, step_ord=? WHERE id=? AND run_case_id IS NULL", (run_case_id, step_ord, i))

    def inbox_for_step(self, run_case_id: int, step_ord: int) -> list[dict]:
        return self._q("SELECT * FROM inbox WHERE run_case_id=? AND step_ord=? ORDER BY id", (run_case_id, step_ord))

    def prune_inbox(self, before: str) -> None:
        """오래된 알림을 지운다. 실행 결과에 붙은 것은 그 실행이 남아 있는 동안 둔다."""
        self._x("DELETE FROM inbox WHERE received_at < ? AND (run_case_id IS NULL OR run_case_id NOT IN (SELECT id FROM run_cases))", (before,))

    def get_receiver(self, base_url: str, actor: str) -> dict | None:
        return self._one("SELECT * FROM receivers WHERE base_url=? AND actor=?", (base_url, actor))

    def list_receivers(self, base_url: str | None = None) -> list[dict]:
        if base_url:
            return self._q("SELECT * FROM receivers WHERE base_url=? ORDER BY actor", (base_url,))
        return self._q("SELECT * FROM receivers ORDER BY base_url, actor")

    def save_receiver(self, base_url: str, actor: str, **fields) -> None:
        cur = self.get_receiver(base_url, actor) or {}
        row = {**{k: cur.get(k) for k in ("member_id", "email", "push_token", "credentials", "enabled", "status", "error", "last_at", "operator")}, **fields}
        self._x("INSERT OR REPLACE INTO receivers (base_url, actor, member_id, email, push_token, credentials, enabled, status, error, last_at, operator, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (base_url, actor, row["member_id"], row["email"], row["push_token"], row["credentials"], int(row["enabled"] or 0), row["status"],
                 row["error"], row["last_at"], row["operator"], now_iso()))
