"""폼으로 스크립트·수동 작성 테스트 조건 만들기·고치기·지우기 — 폼 상태 ⇄ YAML, 사람 검증, 승인 때 바꿀 파일 계획. docs/qa-platform-editor.md.

폼 상태(JSON, 브라우저 EDITOR_JS 가 만든다)가 정본이다. 저장하면 서버가 스크립트 맵(raw)으로 바꿔 기존 초안 흐름에 넣는다.
값 칸은 문자열로 온다. `{{...}}` 는 그대로 문자열, 그 밖에는 JSON 으로 읽히면 그 값(200 · true · null · "문자열"), 아니면 문자열.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import date

import yaml

from .cases import _TC, CaseError, _validate, audit
from .drafts import CLEANUP_HINT, WRITE, _ACTOR, _FIXTURE

CASE_KEYS = ("id", "title", "suite", "variant", "description", "domains", "operations", "covers", "source", "actor", "reviewed", "written_by", "uses", "inputs", "outputs", "steps")
STEP_KEYS = ("name", "actor", "covers", "request", "expect", "save")
REQ_KEYS = ("method", "path", "query", "body")
EXPECT_KEYS = ("status", "result", "error_code", "json", "exists")
_SLUG = re.compile(r"[^a-z0-9]+")
_WHEN = re.compile(r"\b([A-Z][A-Z0-9_]+)\s*일 때")


class FormError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# 값 칸 ⇄ 값
# ---------------------------------------------------------------------------------------------
def cell_to_value(s):
    """폼 칸 문자열 → YAML 값."""
    if s is None:
        return None
    if not isinstance(s, str):
        return s
    t = s.strip()
    if t == "":
        return ""
    if t.startswith("{{"):
        return t
    try:
        return json.loads(t)
    except ValueError:
        return t


def value_to_cell(v) -> str:
    """YAML 값 → 폼 칸 문자열. 숫자처럼 보이는 문자열("200")은 따옴표를 붙여 타입을 지킨다."""
    if isinstance(v, str):
        if v.startswith("{{"):
            return v
        try:
            json.loads(v)
            return json.dumps(v, ensure_ascii=False)
        except ValueError:
            return v
    return json.dumps(v, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------------------------
# 스크립트 raw ⇄ 폼 상태
# ---------------------------------------------------------------------------------------------
def unsupported(raw: dict) -> list[str]:
    """폼으로 표현 못 하는 키. 있으면 폼을 열지 않고 YAML 로 고치라고 안내한다."""
    out = [f"스크립트 키 {k}" for k in raw if k not in CASE_KEYS]
    for i, s in enumerate(raw.get("steps") or [], 1):
        if not isinstance(s, dict):
            out.append(f"단계 {i} 가 맵이 아니다")
            continue
        out += [f"단계 {i} 키 {k}" for k in s if k not in STEP_KEYS]
        out += [f"단계 {i} request.{k}" for k in (s.get("request") or {}) if k not in REQ_KEYS]
        out += [f"단계 {i} expect.{k}" for k in (s.get("expect") or {}) if k not in EXPECT_KEYS]
    return out


def to_state(raw: dict) -> dict:
    st = {"id": raw.get("id") or "", "title": raw.get("title") or "", "suite": raw.get("suite") or "sanity", "variant": raw.get("variant") or "",
          "description": raw.get("description") or "", "domains": list(raw.get("domains") or []), "source": list(raw.get("source") or []),
          "actor": raw.get("actor") or "", "covers": list(raw.get("covers") or []),
          "inputs": [{"name": k, "label": (v or {}).get("label", "") if isinstance(v, dict) else "", "default": value_to_cell((v or {}).get("default") if isinstance(v, dict) else v) if ((v or {}).get("default") if isinstance(v, dict) else v) is not None else "",
                      "required": bool((v or {}).get("required")) if isinstance(v, dict) else False, "hint": (v or {}).get("hint", "") if isinstance(v, dict) else ""}
                     for k, v in (raw.get("inputs") or {}).items()],
          "outputs": list(raw.get("outputs") or []), "uses": _uses_state(raw.get("uses")), "steps": []}
    step_covers = {t for s in raw.get("steps") or [] if isinstance(s, dict) for t in (s.get("covers") or [])}
    st["covers"] = [t for t in st["covers"] if t not in step_covers]     # 단계 covers 는 단계에만 보인다 (로더가 합친다)
    for s in raw.get("steps") or []:
        req = s.get("request") or {}
        exp = s.get("expect") or {}
        body = req.get("body")
        st["steps"].append({
            "name": s.get("name") or "", "actor": s.get("actor") or "", "covers": list(s.get("covers") or []),
            "method": str(req.get("method") or "GET").upper(), "path": req.get("path") or "",
            "query": [{"k": k, "v": value_to_cell(v)} for k, v in (req.get("query") or {}).items()],
            "body": "" if body is None else json.dumps(body, ensure_ascii=False, indent=2, default=str),
            "expect": {"status": str(exp.get("status", "")) if exp.get("status") is not None else "", "result": exp.get("result") or "",
                       "error_code": exp.get("error_code") or "",
                       "json": [{"path": k, "value": value_to_cell(v)} for k, v in (exp.get("json") or {}).items()],
                       "exists": list(exp.get("exists") or [])},
            "save": [{"name": k, "path": v} for k, v in (s.get("save") or {}).items()],
        })
    return st


def _uses_state(u) -> dict:
    """uses → 폼 상태 {setup, with: {입력: 칸 문자열}}. `uses: setup.x` 축약도 받는다."""
    if isinstance(u, str):
        u = {"setup": u}
    if not isinstance(u, dict):
        return {"setup": "", "with": {}}
    return {"setup": str(u.get("setup") or ""),
            "with": {str(k): ("" if v is None else value_to_cell(v)) for k, v in (u.get("with") or {}).items()}}


def _strs(v) -> list[str]:
    if isinstance(v, str):
        v = v.split(",")
    return [str(x).strip() for x in (v or []) if str(x).strip()]


def from_state(st: dict, *, op_of=None) -> dict:
    """폼 상태 → 스크립트 raw(키 순서 고정). 형식이 틀린 칸은 FormError(사람이 읽을 메시지)."""
    if not isinstance(st, dict):
        raise FormError("폼 상태가 맵이 아니다")
    raw: dict = {"id": str(st.get("id") or "").strip(), "title": str(st.get("title") or "").strip(), "suite": str(st.get("suite") or "").strip()}
    if str(st.get("variant") or "").strip():
        raw["variant"] = str(st["variant"]).strip()
    if str(st.get("description") or "").strip():
        raw["description"] = str(st["description"]).strip()
    steps, ops, paths = [], [], []
    for i, s in enumerate(st.get("steps") or [], 1):
        method = str(s.get("method") or "GET").upper()
        path = str(s.get("path") or "").strip()
        req: dict = {"method": method, "path": path}
        q = {str(r.get("k")).strip(): cell_to_value(r.get("v")) for r in s.get("query") or [] if str(r.get("k") or "").strip()}
        if q:
            req["query"] = q
        body_text = str(s.get("body") or "").strip()
        if body_text:
            try:
                req["body"] = json.loads(body_text)
            except ValueError as ex:
                raise FormError(f"단계 {i} 본문이 JSON 이 아니다: {ex}") from None
        e = s.get("expect") or {}
        exp: dict = {}
        if str(e.get("status") or "").strip():
            try:
                exp["status"] = int(str(e["status"]).strip())
            except ValueError:
                raise FormError(f"단계 {i} 상태 코드는 숫자: {e['status']!r}") from None
        if str(e.get("result") or "").strip():
            exp["result"] = str(e["result"]).strip()
        if str(e.get("error_code") or "").strip():
            exp["error_code"] = str(e["error_code"]).strip()
        js = {str(r.get("path")).strip(): cell_to_value(r.get("value")) for r in e.get("json") or [] if str(r.get("path") or "").strip()}
        if js:
            exp["json"] = js
        ex = _strs(e.get("exists"))
        if ex:
            exp["exists"] = ex
        step: dict = {"name": str(s.get("name") or "").strip() or f"step {i}"}
        if str(s.get("actor") or "").strip():
            step["actor"] = str(s["actor"]).strip()
        cov = _strs(s.get("covers"))
        if cov:
            step["covers"] = cov
        step["request"] = req
        if exp:
            step["expect"] = exp
        sv = {str(r.get("name")).strip(): str(r.get("path") or "").strip() for r in s.get("save") or [] if str(r.get("name") or "").strip()}
        if sv:
            step["save"] = sv
        steps.append(step)
        paths.append(path)
        oid = op_of(method, path) if op_of else None
        if oid and oid not in ops:
            ops.append(oid)
    domains = _strs(st.get("domains"))
    raw["domains"] = domains
    if ops:
        raw["operations"] = ops
    covers = _strs(st.get("covers"))
    if covers:
        raw["covers"] = covers
    src = _strs(st.get("source"))
    if src:
        raw["source"] = src
    if str(st.get("actor") or "").strip():
        raw["actor"] = str(st["actor"]).strip()
    if st.get("reviewed"):
        raw["reviewed"] = st["reviewed"]
    u = st.get("uses") or {}
    if isinstance(u, dict) and str(u.get("setup") or "").strip():
        w = {str(k).strip(): cell_to_value(v) for k, v in (u.get("with") or {}).items() if str(k).strip() and str(v or "").strip()}
        raw["uses"] = {"setup": str(u["setup"]).strip(), **({"with": w} if w else {})}
    inputs = {}
    for r in st.get("inputs") or []:
        n = str(r.get("name") or "").strip()
        if not n:
            continue
        spec = {"label": str(r.get("label") or n).strip()}
        if str(r.get("default") or "").strip():
            spec["default"] = cell_to_value(r.get("default"))
        if r.get("required"):
            spec["required"] = True
        if str(r.get("hint") or "").strip():
            spec["hint"] = str(r["hint"]).strip()
        inputs[n] = spec
    if inputs:
        raw["inputs"] = inputs
    outs = _strs(st.get("outputs"))
    if outs:
        raw["outputs"] = outs
    raw["steps"] = steps
    return raw


def suggest_id(domain: str, title: str) -> str:
    slug = _SLUG.sub("-", (title or "").lower()).strip("-")[:40] or "new"
    return f"{domain or 'misc'}.{slug}"


# ---------------------------------------------------------------------------------------------
# 사람이 쓴 스크립트 검증 — Hermes 초안 검증(drafts.validate)과 달리 id 를 바꾸지 않고, setup 은 covers 없이도 된다
# ---------------------------------------------------------------------------------------------
def validate_case(raw: dict, *, catalog, cfg, actors: dict, existing_ids: set[str], library: dict | None = None):
    """(Case|None, 오류, 경고). library(지금 스크립트)를 주면 uses 를 펼쳐 테스트 데이터 만들기 카드·입력칸까지 확인한다."""
    try:
        case = _validate(copy.deepcopy(raw), "<form>", library)
    except CaseError as ex:
        return None, [str(ex).replace("<form>:", "").strip()], []
    errors, warnings = [], []
    if case.id in existing_ids:
        errors.append(f"id {case.id} 는 이미 있는 스크립트다 — 다른 id 를 쓰거나 그 스크립트를 폼으로 고친다")
    if catalog is not None:
        audit({case.id: case}, catalog)
        errors += case.audit["errors"]
        warnings += case.audit["warnings"]
    text = case.to_yaml()
    for name in {case.actor} | {s.get("actor") for s in case.steps} | set(_ACTOR.findall(text)):
        if name and "{{" not in name and actors and name not in actors:
            errors.append(f"없는 테스트 계정 {name}")
    for key in set(_FIXTURE.findall(text)):
        if cfg.fixtures and key not in cfg.fixtures:
            errors.append(f"없는 픽스처 키 {key}")
    if case.suite == "sanity" and any(s["request"]["method"] in WRITE for s in case.steps):
        last = case.steps[-1]["request"]
        if not (last["method"] == "DELETE" or CLEANUP_HINT.search(last.get("path") or "")):
            warnings.append("쓰기 스크립트인데 마지막 단계가 정리(취소·철회·삭제)로 보이지 않는다")
    for i, s in enumerate(case.own_steps, 1):
        body = s["request"].get("body")
        if s["request"]["method"] in WRITE and isinstance(body, dict) and isinstance(body.get("title"), str) and not body["title"].startswith("[QA]"):
            warnings.append(f"단계 {i} 의 title 이 [QA] 로 시작하지 않는다 — 나중에 찾아 지우기 어렵다")
    return (None if errors else case), errors, warnings


def body_warnings(raw: dict, spec) -> list[str]:
    """스키마와 대조한 본문 경고 — 필수 필드 누락, 스키마에 없는 필드. 설명에 조건이 있는 필드는 설명을 같이 보여 준다."""
    out = []
    if spec is None:
        return out
    for i, s in enumerate(raw.get("steps") or [], 1):
        req = s.get("request") or {}
        body = req.get("body")
        op = spec.op_for(req.get("method") or "", req.get("path") or "")
        if not op or not op.body_fields or not isinstance(body, dict):
            continue
        names = {f["name"]: f for f in op.body_fields}
        for f in op.body_fields:
            if f["required"] and f["name"] not in body:
                out.append(f"단계 {i} 본문에 필수 필드 {f['name']} 가 없다")
        for k in body:
            if k not in names:
                out.append(f"단계 {i} 본문의 {k} 는 {op.id} 스키마에 없다")
            elif body[k] is not None:
                m = _WHEN.search(names[k]["description"])
                if m and m.group(1) not in {str(v) for v in body.values()}:
                    out.append(f"단계 {i} 본문 {k}: {m.group(1)} 일 때만 쓰는 필드인데 본문에 {m.group(1)} 가 없다 — 스키마 설명 \"{names[k]['description']}\"")
    return out


# ---------------------------------------------------------------------------------------------
# 수동 작성 TC
# ---------------------------------------------------------------------------------------------
def manual_record(f: dict, *, tc_id: str | None) -> dict:
    """폼 칸 → manual-tc.yaml 항목. tc_id 가 없으면 번호는 저장 때 build_manual_tc 가 붙인다(여기선 자리만)."""
    rec = {"id": tc_id or "", "doc": str(f.get("doc") or "").strip(), "section": str(f.get("section") or "").strip().rstrip("."),
           "domain": str(f.get("domain") or "").strip() or "other", "title": str(f.get("title") or "").strip()}
    if str(f.get("given") or "").strip():
        rec["given"] = str(f["given"]).strip()
    rec["when"] = str(f.get("when") or "").strip()
    rec["then"] = str(f.get("then") or "").strip()
    ops = _strs(f.get("operations"))
    if ops:
        rec["operations"] = ops
    if rec["id"].startswith("OPS."):
        rec.pop("doc", None)
        rec.pop("section", None)
        if str(f.get("source") or "").strip():
            rec["source"] = str(f["source"]).strip()
    return rec


def next_manual_id(prefix: str, taken: list[str]) -> str:
    n = max([int(t.rsplit("#", 1)[-1]) for t in taken if t.startswith(prefix) and t.rsplit("#", 1)[-1].isdigit()] or [0])
    return f"{prefix}{n + 1}"


# ---------------------------------------------------------------------------------------------
# 승인 때 바꿀 파일 — (레포 안 상대 경로, text|None → text, 요약)
# ---------------------------------------------------------------------------------------------
def today() -> str:
    return date.today().isoformat()


def plan_case(d: dict, *, cases: dict, operator: str):
    """변경 기록(kind case · case-delete) → (rel, change, summary, case_id). reviewed 는 오늘·저장한 사람으로 올린다.
    Hermes 가 쓴 것(source hermes*)은 written_by: hermes 를 달고, 사람이 폼으로 저장하면 뗀다 (docs/qa-platform-scenarios.md §7)."""
    from .repo import RepoError, append_item, ids_in, replace_item
    kind = d.get("kind") or "case"
    if kind == "case-unlink":          # 변형·시나리오를 지워 "시나리오 밖" 으로 돌린다 — reviewed 는 건드리지 않는다
        c = cases.get(d.get("case_id"))
        if not c:
            raise RepoError(f"스크립트 {d.get('case_id')} 가 지금 목록에 없다")
        raw = {k: v for k, v in c.raw.items() if k != "variant"}
        return f"cases/{c.file}", (lambda text: replace_item(text or "", c.id, raw)), f"{c.id} 의 variant 떼기", c.id
    if kind == "case-delete":
        c = cases.get(d.get("case_id"))
        if not c:
            raise RepoError(f"지울 스크립트 {d.get('case_id')} 가 지금 목록에 없다")
        return f"cases/{c.file}", (lambda text: replace_item(text or "", c.id, None)), f"{c.id} 삭제", c.id
    raw = yaml.safe_load(d["yaml"])
    if not isinstance(raw, dict) or not raw.get("id"):
        raise RepoError("초안 YAML 이 스크립트 맵이 아니다")
    raw = {k: raw[k] for k in CASE_KEYS if k in raw} | {k: v for k, v in raw.items() if k not in CASE_KEYS}
    raw["reviewed"] = {"at": today(), "by": operator}
    raw.pop("written_by", None)
    if str(d.get("source") or "").startswith("hermes"):
        raw["written_by"] = "hermes"
    order = [k for k in CASE_KEYS if k in raw] + [k for k in raw if k not in CASE_KEYS]
    raw = {k: raw[k] for k in order}
    cid = raw["id"]
    if cid in cases:
        c = cases[cid]
        return f"cases/{c.file}", (lambda text: replace_item(text or "", cid, raw)), f"{cid} 수정", cid
    fname = "setup.yaml" if raw.get("suite") == "setup" else f"{(raw.get('domains') or ['misc'])[0]}.yaml"

    def add(text):
        if text and cid in ids_in(text):
            raise RepoError(f"main 의 {fname} 에 {cid} 가 이미 있다 — 스크립트 다시 읽기 뒤 폼으로 고친다")
        return append_item(text, raw, header=f"# {raw.get('domains', ['misc'])[0] if raw.get('suite') != 'setup' else 'setup'} — QA 플랫폼 폼으로 만든 파일.\n")
    return f"cases/{fname}", add, f"{cid} 추가", cid


def plan_tc(d: dict, *, covered_by: dict) -> tuple:
    """수동 테스트 조건 초안(kind tc · tc-delete) → (rel, change, summary, ids). 폼으로 고친 것은 id 로 바꾸고, 새 것은 번호가 겹치면 다음 번호로."""
    from .repo import RepoError, append_item, ids_in, replace_item
    doc = yaml.safe_load(d["yaml"]) or {}
    items = doc.get("cases") if isinstance(doc, dict) else doc
    if not isinstance(items, list) or not items:
        raise RepoError("초안에 테스트 조건 항목이 없다")
    kind = d.get("kind") or "tc"
    rel = "catalog/manual-tc.yaml"
    if kind == "tc-delete":
        tid = str(items[0].get("id"))
        if covered_by.get(tid):
            raise RepoError(f"{tid} 를 검증하는 스크립트가 있다: {', '.join(covered_by[tid])} — 먼저 그 스크립트의 covers 에서 뺀다")
        return rel, (lambda text: replace_item(text or "", tid, None)), f"{tid} 삭제", [tid]
    edit = d.get("source") == "form-edit"
    hermes = str(d.get("source") or "").startswith("hermes")
    final_ids: list[str] = []

    def change(text):
        text = text or "cases: []\n"
        final_ids.clear()
        for it in items:
            it = dict(it)
            if hermes:
                it["written_by"] = "hermes"
            if edit:
                text = replace_item(text, str(it["id"]), it)
            else:
                taken = ids_in(text)
                if str(it.get("id")) in taken or not it.get("id"):
                    prefix = str(it.get("id") or "").rsplit("#", 1)[0] + "#"
                    it["id"] = next_manual_id(prefix, taken)
                if not _TC.match(it["id"]):
                    raise RepoError(f"테스트 조건 id 형식 오류: {it['id']}")
                text = append_item(text, it)
            final_ids.append(it["id"])
        return text
    return rel, change, ("수정 " if edit else "추가 ") + ", ".join(str(i.get("id")) for i in items), final_ids
