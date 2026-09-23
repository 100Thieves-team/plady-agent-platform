"""TC 카탈로그 — 기획 문서(SSOT·PRD)와 API 계약(OpenAPI)에서 결정론적으로 파생한다. docs/qa-platform-tc.md §4.

세 층:
  policy    상태-SSOT.yaml → render_tests.cases() (team-wiki-v2 의 함수를 import, 복제 없음)
              거절 `G.room.create#8` · 성공 `C.room.create`
  contract  OpenAPI → op 별 성공 응답 `op.createRoom:200` · 문서화된 에러 코드 `op.createRoom:E1402`
  manual    사람이 적은 서술 TC `PRD.룸-탐색.4.2#1` · `OPS.platform.health#1` (qa-platform/catalog/manual-tc.yaml)

바인딩(bindings.yaml)이 SSOT command ↔ operationId, 게이트 검사 ↔ 에러 코드를 잇는다. 1:1 이 아니다.
제외(exclusions.yaml)는 자동화 못 하는 TC 를 사유와 함께 뺀다 — 분모에서 빼되 화면에는 남긴다.

카탈로그는 DB 에 넣지 않는다. 입력 버전(SSOT·OpenAPI·바인딩·제외·서술 TC 해시)으로 캐시하고,
직전 캐시와 레코드 해시를 비교해 변경 이력(changes.json)을 쌓는다 — 케이스 화면의 드리프트 배지가 이걸 본다.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .spec import Spec, SpecData
from .wiki import Wiki, WikiError, file_hash

LAYERS = ("policy", "contract", "manual")

# SSOT owner(한글) → 도메인 슬러그. render_tests.OWNER_PKG 와 같되, 모듈이 없을 때의 폴백.
OWNER_SLUG = {"룸": "room", "참여": "participation", "참가 신청": "application", "출석": "attendance",
              "회원": "member", "이력서": "resume", "질문": "question", "방명록": "guestbook", "후기": "review"}

# OpenAPI 경로 세그먼트 → 도메인. 마지막으로 매칭되는 세그먼트가 이긴다 (/v1/rooms/{id}/applications → application).
PATH_DOMAIN = {
    "rooms": "room", "room-progresses": "room", "progress-rails": "room", "rounds": "room",
    "applications": "application", "participants": "participation", "attendances": "attendance",
    "members": "member", "nicknames": "member", "profile": "member", "auth": "auth", "web-push-subscriptions": "member",
    "resumes": "resume", "resume-submissions": "resume",
    "questions": "question", "question-sets": "question", "question-comments": "question", "question-comment-types": "question",
    "follow-ups": "question", "follow-up-questions": "question", "question-records": "question",
    "closing-responses": "question", "closing-questions": "question",
    "final-feedbacks": "participation", "self-feedbacks": "participation", "round-feedbacks": "participation",
    "feedback-disclosures": "participation",
    "comments": "guestbook", "reviews": "review", "review-skips": "review", "review-targets": "review", "received-reviews": "review",
    "terms": "catalog", "job-roles": "catalog", "regions": "catalog", "job-postings": "catalog", "companies": "catalog",
    "actuator": "platform",
    "dev": "qa-dev",          # /v1/dev/… 백엔드 dev 전용 QA 데이터 API (PR #135) — TC 목록에는 안 넣고 API 호출 화면에만
}


def domain_of_path(path: str) -> str:
    d = "other"
    for seg in path.split("/"):
        if seg and not seg.startswith("{") and seg in PATH_DOMAIN:
            d = PATH_DOMAIN[seg]
    return d


def _h(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------------------------
# 입력 파일 (레포 qa-platform/catalog/)
# ---------------------------------------------------------------------------------------------
@dataclass
class Inputs:
    bindings: dict = field(default_factory=dict)     # {"commands": {cmd: op|[op]}, "checks": {"G.x#n": "E####"}}
    exclusions: list = field(default_factory=list)   # [{id|prefix|match, reason}]
    manual: list = field(default_factory=list)       # [{id, doc?, section?, title, given, when, then, source?}]
    hashes: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


def load_inputs(catalog_dir: Path) -> Inputs:
    inp = Inputs()
    for name, key in (("bindings.yaml", "bindings"), ("exclusions.yaml", "exclusions"), ("manual-tc.yaml", "manual")):
        p = Path(catalog_dir) / name
        if not p.is_file():
            inp.hashes[key] = "none"
            continue
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            inp.hashes[key] = file_hash(p)
        except (OSError, yaml.YAMLError) as e:
            inp.errors.append(f"{name}: {e}")
            inp.hashes[key] = "error"
            continue
        if key == "bindings":
            cmds = doc.get("commands") or {}
            inp.bindings = {"commands": {k: (v if isinstance(v, list) else [v]) for k, v in cmds.items() if v},
                            "checks": {str(k): str(v) for k, v in (doc.get("checks") or {}).items() if v}}
        elif key == "exclusions":
            inp.exclusions = [x for x in (doc.get("exclusions") or []) if isinstance(x, dict) and x.get("reason")]
        else:
            inp.manual = [x for x in (doc.get("cases") or []) if isinstance(x, dict) and x.get("id")]
    return inp


# ---------------------------------------------------------------------------------------------
# 카탈로그
# ---------------------------------------------------------------------------------------------
@dataclass
class Catalog:
    records: dict                      # id -> record dict
    versions: dict                     # {ssot, openapi, bindings, exclusions, manual, wiki_head}
    built_at: str
    warnings: list = field(default_factory=list)   # 바인딩 노후·스펙 누락 등 (구조 불일치, §6.4)

    @property
    def key(self) -> str:
        v = self.versions
        return f"{v.get('ssot')}-{v.get('openapi')}-{v.get('bindings')}-{v.get('exclusions')}-{v.get('manual')}"

    def domains(self) -> list[str]:
        order = ["room", "application", "participation", "attendance", "member", "auth", "resume", "question",
                 "guestbook", "review", "catalog", "platform", "other"]
        seen = {r["domain"] for r in self.records.values()}
        return [d for d in order if d in seen] + sorted(seen - set(order))

    def counts(self) -> dict:
        out = {"total": len(self.records), "excluded": 0, "by_layer": {}, "by_domain": {}}
        for r in self.records.values():
            out["by_layer"][r["layer"]] = out["by_layer"].get(r["layer"], 0) + 1
            out["by_domain"][r["domain"]] = out["by_domain"].get(r["domain"], 0) + 1
            if r.get("excluded"):
                out["excluded"] += 1
        return out

    def to_json(self) -> dict:
        return {"records": self.records, "versions": self.versions, "built_at": self.built_at, "warnings": self.warnings}

    def by_operation(self) -> dict[str, list[str]]:
        """operationId → 그 API 에 걸린 TC id 목록 (API 계약 TC 는 `operation`, 비즈니스 규칙·수동 작성 TC 는 `binding.operations`).
        API 별로 모아 보기(docs/qa-platform-api.md §5.2)와 호출 카드의 QA 배지가 쓴다. 처음 부를 때 한 번 계산해 둔다."""
        cached = getattr(self, "_by_op", None)
        if cached is not None:
            return cached
        out: dict[str, list[str]] = {}
        for rid, r in sorted(self.records.items()):
            ops = [r["operation"]] if r.get("operation") else list((r.get("binding") or {}).get("operations") or [])
            for op in ops:
                out.setdefault(op, []).append(rid)
        self._by_op = out
        return out

    @classmethod
    def from_json(cls, d: dict) -> "Catalog":
        return cls(records=d["records"], versions=d["versions"], built_at=d["built_at"], warnings=d.get("warnings") or [])


def _exclusion_for(rec: dict, exclusions: list) -> str | None:
    for x in exclusions:
        if x.get("id") and x["id"] == rec["id"]:
            return x["reason"]
        if x.get("prefix") and rec["id"].startswith(x["prefix"]):
            return x["reason"]
        m = x.get("match")
        if isinstance(m, dict) and m and all(rec.get(k) == v for k, v in m.items()):
            return x["reason"]
    return None


def build(*, ssot: dict | None, ssot_hash: str | None, rt_mod, spec: SpecData | None, inputs: Inputs,
          wiki: Wiki | None = None, wiki_head: str | None = None) -> Catalog:
    """순수 함수에 가깝게: 같은 입력이면 같은 레코드. wiki 는 PRD 링크 생성에만 쓴다."""
    records: dict[str, dict] = {}
    warnings: list[str] = list(inputs.errors)
    owner_slug = dict(OWNER_SLUG)
    if rt_mod is not None and hasattr(rt_mod, "OWNER_PKG"):
        owner_slug.update(rt_mod.OWNER_PKG)
    bind_cmds: dict[str, list[str]] = inputs.bindings.get("commands") or {}
    bind_checks: dict[str, str] = inputs.bindings.get("checks") or {}

    def prd_refs(sources: list) -> list[dict]:
        out = []
        for s in sources or []:
            if not isinstance(s, str):
                continue
            parsed = Wiki.parse_source(s)
            if parsed:
                doc, sec = parsed
                out.append({"doc": doc, "section": sec, "url": wiki.prd_url(doc) if wiki else None})
        return out

    # ---- policy (SSOT) ------------------------------------------------------------------
    if ssot is not None and rt_mod is not None:
        cmd_actor = {c.get("id"): c.get("actor") for c in (ssot.get("commands") or []) if isinstance(c, dict)}
        for c in rt_mod.cases(ssot):
            owner = c.get("owner") or ""
            domain = owner_slug.get(owner) or (c["gate"].split(".")[1] if c.get("gate", "").count(".") >= 2 else "other")
            cmd = c.get("command")
            ops = bind_cmds.get(cmd, []) if cmd else []
            if c["kind"] == "거절":
                rid = f'{c["gate"]}#{c["check"]}'
                # 에러 코드: SSOT `error` 가 채워져 있으면 그것이 정본, 비어 있는 동안만 bindings.checks (§4.4)
                ssot_code = str(c.get("error") or "").strip()
                ssot_code = ssot_code if ssot_code and ssot_code.upper() != "TBD" else None
                bound = bind_checks.get(rid)
                if ssot_code and bound and ssot_code != bound:
                    warnings.append(f"{rid}: SSOT error {ssot_code} 와 bindings.checks {bound} 가 다르다 — SSOT 를 쓴다. bindings 에서 지워도 된다")
                elif ssot_code and bound:
                    warnings.append(f"{rid}: SSOT 가 error {ssot_code} 를 채웠다 — bindings.checks 의 같은 항목은 지워도 된다")
                code = ssot_code or bound
                rec = {
                    "id": rid, "layer": "policy", "kind": "reject", "domain": domain,
                    "title": rt_mod.reject_name(c), "gate": c["gate"], "gate_name": c.get("gate_name"),
                    "command": cmd, "actor": cmd_actor.get(cmd),
                    "expect_hint": {"cond": c.get("cond"), "message": c.get("message"), "must_pass_first": c.get("must_pass_first") or [],
                                    "check": c["check"], "of": c.get("of")},
                    "binding": ({"operations": ops, "error_code": code, "error_source": ("ssot" if ssot_code else "bindings") if code else None}
                                if (ops or code) else None),
                    "source": c.get("source") or [],
                }
            else:
                rec = {
                    "id": cmd, "layer": "policy", "kind": "success", "domain": domain,
                    "title": rt_mod.success_name(c), "gate": c["gate"], "gate_name": c.get("gate_name"),
                    "command": cmd, "actor": cmd_actor.get(cmd), "transition": c.get("transition"),
                    "expect_hint": {"writes": c.get("writes") or [], "cascades": c.get("cascades") or [], "idempotent": c.get("idempotent")},
                    "binding": {"operations": ops} if ops else None,
                    "source": c.get("source") or [],
                }
            rec["prd"] = prd_refs(rec["source"])
            records[rec["id"]] = rec
        for cmd, ops in bind_cmds.items():
            if cmd not in cmd_actor:
                warnings.append(f"bindings.commands: SSOT 에 없는 command {cmd}")
        for rid in bind_checks:
            if rid not in records:
                warnings.append(f"bindings.checks: 카탈로그에 없는 검사 {rid}")

    # ---- contract (OpenAPI) ------------------------------------------------------------
    if spec is not None:
        op_cmds: dict[str, list[str]] = {}
        for cmd, ops in bind_cmds.items():
            for op in ops:
                op_cmds.setdefault(op, []).append(cmd)
        for op in spec.ops.values():
            if not op.path.startswith("/v1/") and not op.path.startswith("/actuator"):
                continue
            if op.path.startswith("/v1/dev/"):
                continue     # dev 전용 QA 데이터 API 는 검증 대상이 아니다 — TC 를 만들지 않는다
            domain = domain_of_path(op.path)
            base = {"method": op.method, "path": op.path}
            for status, example in sorted(op.success.items()):
                rid = f"op.{op.id}:{status}"
                records[rid] = {
                    "id": rid, "layer": "contract", "kind": "success", "domain": domain,
                    "title": f"{op.summary or op.id} — {status}", "operation": op.id,
                    "expect_hint": dict(base, status=int(status) if status.isdigit() else status, example=example),
                    "binding": {"commands": op_cmds.get(op.id, [])} if op_cmds.get(op.id) else None,
                    "source": [f"OpenAPI {op.method} {op.path}"], "prd": [],
                }
            for code, info in sorted(op.errors.items()):
                rid = f"op.{op.id}:{code}"
                records[rid] = {
                    "id": rid, "layer": "contract", "kind": "reject", "domain": domain,
                    "title": f"{op.summary or op.id} 거절 — {code} {info.get('message') or ''}".strip(), "operation": op.id,
                    "expect_hint": dict(base, status=info.get("status"), error_code=code, message=info.get("message"), example=info.get("example")),
                    "binding": {"commands": op_cmds.get(op.id, [])} if op_cmds.get(op.id) else None,
                    "source": [f"OpenAPI {op.method} {op.path}"], "prd": [],
                }
        # 바인딩 검증 (§4.4, §6.4)
        for cmd, ops in bind_cmds.items():
            for o in ops:
                if o not in spec.ops:
                    warnings.append(f"bindings.commands: OpenAPI 에 없는 operationId {o} ({cmd})")
        for rid, code in bind_checks.items():
            rec = records.get(rid)
            if not rec:
                continue
            ops = (rec.get("binding") or {}).get("operations") or []
            for o in ops:
                op = spec.ops.get(o)
                if op and code not in op.errors:
                    warnings.append(f"{rid}: 바인딩 코드 {code} 가 OpenAPI {o} 의 응답 예시에 없다 (스펙 누락일 수 있음)")

    # ---- manual (사람이 적은 서술 TC) ------------------------------------------------------
    for t in inputs.manual:
        rid = str(t["id"])
        doc, sec = str(t.get("doc") or ""), str(t.get("section") or "")
        source = [str(x) for x in (t.get("source") or [])]
        if doc and sec:
            source.insert(0, f"PRD/{doc} §{sec}")
        records[rid] = {
            "id": rid, "layer": "manual", "kind": str(t.get("kind") or "manual"), "domain": str(t.get("domain") or "other"),
            "title": str(t.get("title") or rid), "actor": t.get("actor"),
            "expect_hint": {k: t.get(k) for k in ("given", "when", "then") if t.get(k)},
            "binding": {"operations": list(t.get("operations") or [])} if t.get("operations") else None,
            "source": source,
            "prd": [{"doc": doc, "section": sec, "url": wiki.prd_url(doc) if wiki else None}] if doc else [],
        }

    # ---- 제외 · 해시 ----------------------------------------------------------------------
    for rec in records.values():
        rec["excluded"] = _exclusion_for(rec, inputs.exclusions)
        rec["hash"] = _h({k: rec.get(k) for k in ("title", "expect_hint", "binding", "source", "kind", "domain")})

    versions = {"ssot": ssot_hash, "openapi": spec.hash if spec else None, "bindings": inputs.hashes.get("bindings"),
                "exclusions": inputs.hashes.get("exclusions"), "manual": inputs.hashes.get("manual"), "wiki_head": wiki_head}
    return Catalog(records=records, versions=versions, built_at=_now(), warnings=warnings)


def snapshot(rec: dict | None) -> dict | None:
    """변경 이력에 남길 레코드 요약 — 다시 쓰기(P4c)가 '전/후' 를 보여 줄 만큼만."""
    if not rec:
        return None
    out = {k: rec.get(k) for k in ("layer", "domain", "title", "gate", "command", "binding", "source", "prd", "excluded") if rec.get(k) not in (None, [], {}, "")}
    hint = rec.get("expect_hint")
    if isinstance(hint, dict):
        out["expect_hint"] = {k: v for k, v in hint.items() if k != "example"}
    elif hint:
        out["expect_hint"] = hint
    return out


def diff(prev: Catalog | None, cur: Catalog) -> dict:
    if prev is None:
        return {"changed": [], "added": [], "removed": []}
    changed = [i for i, r in cur.records.items() if i in prev.records and prev.records[i].get("hash") != r.get("hash")]
    added = [i for i in cur.records if i not in prev.records]
    removed = [i for i in prev.records if i not in cur.records]
    return {"changed": sorted(changed), "added": sorted(added), "removed": sorted(removed)}


# ---------------------------------------------------------------------------------------------
# 서비스: 입력 버전을 보고 필요할 때만 다시 계산, 캐시·변경 이력 파일
# ---------------------------------------------------------------------------------------------
class CatalogService:
    def __init__(self, *, wiki: Wiki, spec: Spec, catalog_dir: Path, data_dir: Path, check_interval: int = 30):
        self.wiki = wiki
        self.spec = spec
        self.catalog_dir = Path(catalog_dir)
        self.cache_dir = Path(data_dir) / "catalog"
        self.check_interval = check_interval
        self._lock = threading.RLock()
        self._cur: Catalog | None = None
        self._last_check = 0.0
        self.last_error: str | None = None
        self.changes: dict = self._read_json(self.cache_dir / "changes.json") or {}   # tc id -> {at, kind, ssot, openapi}
        self.last_diff: dict = {"changed": [], "added": [], "removed": []}
        latest = self._read_json(self.cache_dir / "latest.json")
        if latest and (self.cache_dir / f"{latest.get('key')}.json").is_file():
            try:
                self._cur = Catalog.from_json(self._read_json(self.cache_dir / f"{latest['key']}.json"))
            except Exception:
                self._cur = None

    @staticmethod
    def _read_json(p: Path):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _write_json(self, p: Path, obj):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
            tmp.replace(p)
        except OSError:
            pass

    @property
    def current(self) -> Catalog | None:
        return self._cur

    def _input_versions(self, spec: SpecData | None) -> dict:
        inp_hashes = {}
        for name, key in (("bindings.yaml", "bindings"), ("exclusions.yaml", "exclusions"), ("manual-tc.yaml", "manual")):
            p = self.catalog_dir / name
            try:
                inp_hashes[key] = file_hash(p) if p.is_file() else "none"
            except OSError:
                inp_hashes[key] = "error"
        return {"ssot": self.wiki.ssot_hash() if self.wiki.available else None, "openapi": spec.hash if spec else None, **inp_hashes}

    def get(self, force: bool = False) -> Catalog | None:
        """현재 카탈로그. 입력이 바뀌었을 때만 다시 계산한다 (읽기이므로 사람 트리거 원칙 밖)."""
        with self._lock:
            now = time.monotonic()
            if self._cur is not None and not force and now - self._last_check < self.check_interval:
                return self._cur
            self._last_check = now
            spec = self.spec.get(force=force)
            want = self._input_versions(spec)
            if self._cur is not None and not force and all(self._cur.versions.get(k) == v for k, v in want.items()):
                return self._cur
            try:
                cat = self.rebuild(spec)
            except Exception as e:
                self.last_error = f"카탈로그 계산 실패: {e}"
                return self._cur
            self.last_error = None
            return cat

    def rebuild(self, spec: SpecData | None = None) -> Catalog:
        ssot, ssot_hash, rt = None, None, None
        errors = []
        if self.wiki.available:
            try:
                ssot, ssot_hash = self.wiki.read_ssot()
                rt = self.wiki.render_tests()
            except WikiError as e:
                errors.append(str(e))
                ssot, rt = None, None
        else:
            errors.append("위키 체크아웃이 없다 (QA_WIKI_DIR) — 정책 TC 없음")
        if spec is None:
            errors.append(self.spec.last_error or "OpenAPI 없음 — 계약 TC 없음")
        inputs = load_inputs(self.catalog_dir)
        cat = build(ssot=ssot, ssot_hash=ssot_hash, rt_mod=rt, spec=spec, inputs=inputs, wiki=self.wiki, wiki_head=self.wiki.head())
        cat.warnings = errors + cat.warnings
        if not cat.records and self._cur is not None:
            raise RuntimeError("; ".join(errors) or "레코드 0건")
        d = diff(self._cur, cat)
        if self._cur is not None and cat.key != self._cur.key:
            at = cat.built_at
            for kind in ("changed", "removed", "added"):
                for i in d[kind]:
                    # before = 변경 전 레코드 요약(added 는 없음). 다시 쓰기(P4c)가 Hermes 에게 전/후를 보여 주는 재료
                    self.changes[i] = {"at": at, "kind": kind, "ssot": cat.versions.get("ssot"), "openapi": cat.versions.get("openapi"),
                                       "before": snapshot(self._cur.records.get(i)) if kind != "added" else None}
            self._write_json(self.cache_dir / "changes.json", self.changes)
            self.last_diff = d
        self._cur = cat
        self._write_json(self.cache_dir / f"{cat.key}.json", cat.to_json())
        self._write_json(self.cache_dir / "latest.json", {"key": cat.key, "versions": cat.versions, "built_at": cat.built_at})
        return cat

    def drift_for(self, tc_ids: list[str], reviewed_at: str | None) -> list[dict]:
        """케이스가 덮는 TC 중 마지막 검토 이후에 바뀐 것. reviewed_at 이 없으면 기록된 변경 전부."""
        out = []
        for i in tc_ids:
            ch = self.changes.get(i)
            if not ch:
                continue
            if reviewed_at and ch["at"] <= reviewed_at:
                continue
            out.append(dict(ch, id=i))
        return out

    def summary(self) -> dict:
        c = self._cur
        return {"records": len(c.records) if c else 0, "versions": c.versions if c else None, "built_at": c.built_at if c else None,
                "error": self.last_error, "warnings": len(c.warnings) if c else 0}
