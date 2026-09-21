"""sqlite 저장소 — 런·단계·감사 로그·초안. 케이스 정본은 여기 없다. docs/qa-platform.md §9."""
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
"""
# P2b 에서 늘어난 초안 열. 이미 만들어진 DB 에는 ALTER 로 더한다 (sqlite 는 IF NOT EXISTS 가 없다).
DRAFT_COLUMNS = {"case_id": "TEXT", "tc_ids": "TEXT NOT NULL DEFAULT '[]'", "validation": "TEXT NOT NULL DEFAULT '{}'",
                 "prompt_hash": "TEXT", "run_id": "TEXT", "decided_by": "TEXT", "decided_at": "TEXT",
                 # P4: kind case(케이스 YAML) | tc(서술 TC 제안 — manual-tc.yaml 에 사람이 옮긴다)
                 "kind": "TEXT NOT NULL DEFAULT 'case'"}


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
                    (rid, i, c.id, c.title, c.suite, c.hash, c.to_yaml()),
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
                 checks: list, verdict: str, duration_ms: int, error: str | None) -> int:
        return self._x(
            "INSERT INTO run_steps(run_case_id,ord,name,request,response,checks,verdict,duration_ms,error)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (rcid, ord_, name, json.dumps(request, ensure_ascii=False),
             json.dumps(response, ensure_ascii=False) if response is not None else None,
             json.dumps(checks, ensure_ascii=False), verdict, duration_ms, error),
        )

    def list_steps(self, rcid: int) -> list[dict]:
        rows = self._q("SELECT * FROM run_steps WHERE run_case_id=? ORDER BY ord", (rcid,))
        for r in rows:
            r["request"] = json.loads(r["request"])
            r["response"] = json.loads(r["response"]) if r["response"] else None
            r["checks"] = json.loads(r["checks"])
        return rows

    def case_history(self, case_id: str, limit: int = 10) -> list[dict]:
        return self._q(
            "SELECT rc.id, rc.run_id, rc.verdict, rc.duration_ms, rc.error, r.created_at, r.trigger, r.operator, r.sha"
            " FROM run_cases rc JOIN runs r ON r.id=rc.run_id WHERE rc.case_id=? ORDER BY rc.id DESC LIMIT ?",
            (case_id, limit),
        )

    def last_verdicts(self) -> dict[str, dict]:
        """케이스별 마지막 판정 (목록 화면용)."""
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

    # ---- drafts (케이스 초안, docs/qa-platform-tc.md §7.3) -------------------------------------
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

    def draft_counts(self) -> dict[str, int]:
        return {r["status"]: r["n"] for r in self._q("SELECT status, COUNT(*) n FROM drafts GROUP BY status")}
