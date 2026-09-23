"""Hermes 초안 생성 — 근거 조립 → 호출 → 결정론 검증 → 스크립트 초안. docs/qa-platform-tc.md §7.

원칙: Hermes 는 플랫폼이 넣어 준 근거(TC 레코드·OpenAPI 발췌·PRD 절 본문)만으로 쓴다. 위키 도구를 쓰게 하지 않는다 —
그래야 "근거 = 프롬프트에 있던 것" 이 성립하고, 아래 검증이 그 근거와 대조할 수 있다.
검증을 통과한 것만 스크립트 초안(drafts)에 들어간다. 버린 것은 사유와 함께 감사 로그에 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import re

import yaml

from . import hermes
from .cases import _TC, Case, CaseError, _validate, audit
from .config import Config
from .spec import SpecData
from .wiki import Wiki

WRITE = ("POST", "PUT", "PATCH", "DELETE")
CLEANUP_HINT = re.compile(r"cancel|withdraw|delete|leave|skip", re.I)
_FIXTURE = re.compile(r"\{\{\s*fixture\.([^}\s]+)\s*\}\}")
_ACTOR = re.compile(r"\{\{\s*actor\.([^.\s}]+)\.memberId\s*\}\}")

DRAFT_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 아래에 주어진 근거(TC 레코드, OpenAPI 발췌, PRD 절 본문)만으로 "
    "dev 서버에서 실행할 API 스크립트 초안을 YAML 로 쓴다. 근거에 없는 사실은 지어내지 말고 `TODO:` 로 남긴다. 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나, 최상위는 `cases:` 목록. 설명 문장은 블록 밖에 두지 말고 아예 쓰지 않는다.\n"
    "2. 스크립트마다 `covers:` 를 쓴다. 값은 요청한 TC id 의 부분집합이어야 한다. 단계에도 `covers:` 를 달아 어느 단계가 어느 TC 를 덮는지 밝힌다.\n"
    "3. API 계약 TC(`op.X:E####`)를 덮는 단계는 그 op 의 method·path 를 부르고 `expect.error_code` 가 그 코드여야 한다. "
    "`op.X:2xx` 를 덮는 단계는 `expect.status` 가 2xx 여야 한다.\n"
    "4. 거절 TC(`G.x#n`)는 `must_pass_first` 의 앞 검사들을 모두 통과하는 상태를 먼저 만든 뒤에 n 번째 검사만 걸리게 한다.\n"
    "5. 쓰기 스크립트(POST/PUT/PATCH/DELETE)는 자기가 만든 데이터를 자기가 닫는 정리 단계(취소·철회·삭제)로 끝난다. 만든 데이터의 title 은 `[QA]` 로 시작한다.\n"
    "6. 로그인이 필요하면 `actor:` 에 주어진 테스트 계정 이름만 쓴다. 픽스처는 주어진 키만 `{{fixture.키}}` 로 쓴다.\n"
    "7. expect 는 status · result · error_code · json(경로→값) · exists(경로 목록) 5종만. 치환은 {{var}} {{actor.X.memberId}} {{fixture.키}} {{date:+N}} {{uuid}} {{rand}} 만.\n"
    "8. id 는 `<도메인>.<kebab-case>`, suite 는 sanity(쓰기) 또는 smoke(읽기 전용). title 은 한국어 한 문장."
)


# ---------------------------------------------------------------------------------------------
# 근거 조립
# ---------------------------------------------------------------------------------------------
def assemble(*, cfg: Config, catalog, spec: SpecData | None, wiki: Wiki, tc_ids: list[str], example: Case | None) -> tuple[str, str]:
    """(프롬프트 본문, 프롬프트 해시). 같은 근거로 다시 만들면 해시가 같다 — 초안끼리 비교하는 열쇠."""
    recs = [catalog.records[t] for t in tc_ids if t in catalog.records]
    parts = ["# 요청한 TC (이 목록의 부분집합만 covers 에 쓴다)"]
    for r in recs:
        slim = {k: r.get(k) for k in ("id", "layer", "kind", "domain", "title", "gate", "command", "actor", "expect_hint", "binding", "source") if r.get(k) not in (None, [], {})}
        if r["layer"] == "contract":
            slim["expect_hint"] = {k: v for k, v in r["expect_hint"].items() if k != "example"}
        parts.append("```json\n" + json.dumps(slim, ensure_ascii=False, indent=1) + "\n```")

    ops: list[str] = []
    for r in recs:
        b = r.get("binding") or {}
        for o in (b.get("operations") or []) + ([r["operation"]] if r.get("operation") else []):
            if o not in ops:
                ops.append(o)
    if spec and ops:
        parts.append("# OpenAPI 발췌 (dev 브랜치 계약)")
        for o in ops:
            op = spec.ops.get(o)
            if not op:
                parts.append(f"- {o}: OpenAPI 에 없음 (TODO)")
                continue
            block = {"operationId": op.id, "method": op.method, "path": op.path, "summary": op.summary,
                     "request_example": op.request_example,
                     "success": {st: ex for st, ex in op.success.items()},
                     "errors": {code: {"status": i.get("status"), "message": i.get("message"), "example": i.get("example")} for code, i in op.errors.items()}}
            parts.append("```json\n" + json.dumps(block, ensure_ascii=False, indent=1)[:6000] + "\n```")

    seen: set[tuple[str, str]] = set()
    prd_parts = []
    for r in recs:
        for ref in r.get("prd") or []:
            key = (ref["doc"], ref["section"])
            if key in seen:
                continue
            seen.add(key)
            text = wiki.prd_section(ref["doc"], ref["section"], max_lines=80) if wiki.available else None
            prd_parts.append(f"## PRD/{ref['doc']} §{ref['section']}\n" + (text or "(본문 없음)"))
    if prd_parts:
        parts.append("# PRD 절 본문 (기획 정본)\n" + "\n\n".join(prd_parts))

    parts.append("# 사용할 수 있는 것\n"
                 f"- 테스트 계정(actor) 이름: {', '.join(sorted(cfg.actors)) or '(없음 — 로그인 스크립트는 actor 를 비워 두고 TODO 로 표시)'}\n"
                 f"- 픽스처 키: {', '.join(sorted(cfg.fixtures)) or '(없음)'}\n"
                 f"- 대상: {cfg.target_base_url} (dev). 응답 규약 {{result, data, error{{code}}}}.")
    if example is not None:
        parts.append("# 잘 만든 스크립트 예시 (형식 참고)\n```yaml\n" + example.to_yaml().strip() + "\n```")
    parts.append("# 출력\n요청한 TC 를 검증하는 스크립트 1개 이상을 ```yaml 블록 하나로.")
    text = "\n\n".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------------------------
# 출력 파싱 · 검증
# ---------------------------------------------------------------------------------------------
def parse_output(text: str) -> list[dict]:
    blocks = re.findall(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S) or [text]
    out: list[dict] = []
    for b in blocks:
        try:
            doc = yaml.safe_load(b)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("cases"), list):
            out.extend(x for x in doc["cases"] if isinstance(x, dict))
        elif isinstance(doc, list):
            out.extend(x for x in doc if isinstance(x, dict))
        elif isinstance(doc, dict) and doc.get("id"):
            out.append(doc)
    return out


def validate(raw: dict, *, requested: list[str], catalog, cfg: Config, existing_ids: set[str], actors: dict | None = None) -> tuple[Case | None, list[str], list[str]]:
    known = actors if actors is not None else cfg.actors     # SSM 고정 계정 + 플랫폼이 만든 QA 회원(App.all_actors)
    """docs/qa-platform-tc.md §7.2. 반환 (스크립트|None, 버린 사유, 경고)."""
    errors: list[str] = []
    warnings: list[str] = []
    raw = dict(raw)
    if isinstance(raw.get("id"), str) and raw["id"] in existing_ids:
        raw["id"] = raw["id"] + "-draft"
        warnings.append(f"id 가 기존 스크립트와 겹쳐 '{raw['id']}' 로 바꿨다")
    try:
        case = _validate(raw, "<hermes>")
    except CaseError as e:
        return None, [f"형식: {e}"], []
    if not case.covers:
        return None, ["covers 가 비어 있다"], []
    extra = [t for t in case.covers if t not in requested]
    if extra:
        return None, [f"요청하지 않은 TC 를 덮는다고 주장: {', '.join(extra)}"], []
    audit({case.id: case}, catalog)
    errors.extend(case.audit["errors"])
    warnings.extend(case.audit["warnings"])
    text = case.to_yaml()
    for name in {case.actor} | {s.get("actor") for s in case.steps} | set(_ACTOR.findall(text)):
        if name and known and name not in known:
            errors.append(f"없는 테스트 계정 {name}")
        elif name and not known:
            warnings.append(f"테스트 계정 {name} — 이 환경에 QA_ACTORS 가 없어 확인 못 함")
    for key in set(_FIXTURE.findall(text)):
        if cfg.fixtures and key not in cfg.fixtures:
            errors.append(f"없는 픽스처 키 {key}")
        elif not cfg.fixtures:
            warnings.append(f"픽스처 {key} — 이 환경에 QA_FIXTURES 가 없어 확인 못 함")
    writes = [i for i, s in enumerate(case.steps) if s["request"]["method"] in WRITE and s["request"]["method"] != "DELETE"]
    if writes:
        last = case.steps[-1]["request"]
        if not (last["method"] == "DELETE" or CLEANUP_HINT.search(last.get("path") or "")):
            warnings.append("쓰기 스크립트인데 마지막 단계가 정리(취소·철회·삭제)로 보이지 않는다")
        for i in writes:
            body = case.steps[i]["request"].get("body")
            if isinstance(body, dict) and isinstance(body.get("title"), str) and not body["title"].startswith("[QA]"):
                warnings.append(f"step {i + 1} 의 title 이 [QA] 로 시작하지 않는다")
    if errors:
        return None, errors, warnings
    return case, [], warnings


def validate_manual_tc(text: str) -> tuple[list[dict], list[str]]:
    """수동 TC 제안(kind tc) YAML — manual-tc.yaml 의 `cases:` 형식인지. 반환 (항목, 오류)."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as ex:
        return [], [f"YAML 파싱 실패: {ex}"]
    items = doc.get("cases") if isinstance(doc, dict) else doc
    if not isinstance(items, list) or not items:
        return [], ["`cases:` 목록이 비어 있다"]
    errors, out, seen = [], [], set()
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            errors.append(f"{i}번째 항목은 맵이어야 한다"); continue
        tid = str(it.get("id") or "")
        if not _TC.match(tid) or not tid.startswith(("PRD.", "OPS.")):
            errors.append(f"{i}번째 id 형식 오류: {tid!r} (PRD.문서.절#n 또는 OPS.영역.이름#n)")
        elif tid in seen:
            errors.append(f"id 중복: {tid}")
        seen.add(tid)
        for k in ("title", "when", "then"):
            if not isinstance(it.get(k), str) or not it[k].strip():
                errors.append(f"{tid or i}: {k} 필요")
        if tid.startswith("PRD.") and not (it.get("doc") and it.get("section")):
            errors.append(f"{tid}: PRD 항목은 doc·section 필요")
        out.append(it)
    return out, errors


# ---------------------------------------------------------------------------------------------
# 오케스트레이션
# ---------------------------------------------------------------------------------------------
def generate(*, cfg: Config, catalog, spec: SpecData | None, wiki: Wiki, tc_ids: list[str], example: Case | None,
             existing_ids: set[str]) -> dict:
    """반환 {prompt_hash, raw, accepted: [(Case, warnings)], rejected: [(raw_id, errors)], model}."""
    prompt, phash = assemble(cfg=cfg, catalog=catalog, spec=spec, wiki=wiki, tc_ids=tc_ids, example=example)
    raw = hermes.chat(cfg, DRAFT_SYSTEM, prompt, session_prefix="qa-draft", timeout=max(cfg.hermes_timeout, 180))
    accepted, rejected = [], []
    for d in parse_output(raw):
        case, errors, warnings = validate(d, requested=tc_ids, catalog=catalog, cfg=cfg, existing_ids=existing_ids)
        if case:
            accepted.append((case, warnings))
        else:
            rejected.append((str(d.get("id") or "?"), errors))
    return {"prompt_hash": phash, "prompt_chars": len(prompt), "raw": raw, "accepted": accepted, "rejected": rejected, "model": cfg.hermes_model}


# ---------------------------------------------------------------------------------------------
# 바뀐 TC 에 맞게 스크립트 다시 쓰기 (docs/qa-platform-hermes.md §3.3, P4c)
# ---------------------------------------------------------------------------------------------
REVISE_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 이미 있는 API 테스트 스크립트(YAML) 하나를, 그것이 검증하는 TC 가 바뀐 만큼만 고친다. 한국어로 쓴다.\n\n"
    "규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나, 스크립트 맵 하나(`cases:` 목록 아님). id 는 바꾸지 않는다.\n"
    "2. 바뀐 TC 와 관련된 단계·expect·covers 만 고친다. 바뀌지 않은 단계는 글자 하나도 건드리지 않는다.\n"
    "3. 사라진 TC id 는 covers 에서 뺀다. 대체 후보가 주어지면 그중 맞는 것을 넣고, 없으면 그 단계의 covers 를 비운다.\n"
    "4. 새 기대값(status·error_code 등)은 주어진 '변경 후' 레코드와 OpenAPI 발췌에서만 가져온다. 근거에 없는 것은 `TODO:` 주석 대신 값을 바꾸지 말고 그대로 둔다.\n"
    "5. covers 는 주어진 허용 목록의 부분집합이어야 한다.\n"
    "6. 고친 이유를 YAML 맨 위 주석 한 줄(`# 변경: …`)로 적는다."
)


def _candidates(removed: str, catalog, changes: dict) -> list[str]:
    """사라진 TC 의 대체 후보 — 같은 변경 배치에서 추가됐고 id 앞부분(#·: 앞)이 같은 것. 없으면 지금 TC 목록에서 앞부분이 같은 것."""
    stem = removed.split("#")[0] if "#" in removed else removed.rsplit(":", 1)[0]
    at = (changes.get(removed) or {}).get("at")
    same_batch = [i for i, ch in changes.items() if ch.get("kind") == "added" and ch.get("at") == at and i in catalog.records and (i.split("#")[0] if "#" in i else i.rsplit(":", 1)[0]) == stem]
    if same_batch:
        return sorted(same_batch)
    return sorted(i for i in catalog.records if i != removed and (i.split("#")[0] if "#" in i else i.rsplit(":", 1)[0]) == stem)[:6]


def assemble_revision(*, cfg: Config, catalog, spec: SpecData | None, wiki: Wiki, case: Case, drift: list[dict], changes: dict) -> tuple[str, str, list[str]]:
    """(프롬프트, 근거 해시, 허용 covers). 허용 = 현재 covers − 사라진 TC + 대체 후보."""
    removed = [d["id"] for d in drift if d.get("kind") == "removed"]
    allowed = [t for t in case.covers if t not in removed]
    parts = ["# 현재 스크립트 (이것을 고친다)\n```yaml\n" + case.to_yaml().strip() + "\n```"]
    ops: list[str] = []
    prd_refs: list[tuple[str, str]] = []
    for d in drift:
        tid = d["id"]
        cur = catalog.records.get(tid)
        before = d.get("before")
        if d.get("kind") == "removed":
            cands = _candidates(tid, catalog, changes)
            for c in cands:
                if c not in allowed:
                    allowed.append(c)
            parts.append(f"# 사라진 TC {tid}\n변경 전:\n```json\n{json.dumps(before, ensure_ascii=False, indent=1) if before else '(스냅샷 없음)'}\n```\n"
                         f"대체 후보: {', '.join(cands) or '없음 — 이 TC 를 검증하던 단계의 covers 를 비운다'}")
            for c in cands:
                r = catalog.records.get(c) or {}
                parts.append(f"## 대체 후보 {c}\n```json\n{json.dumps(_slim(r), ensure_ascii=False, indent=1)}\n```")
                _collect(r, ops, prd_refs)
        else:
            parts.append(f"# 바뀐 TC {tid} ({d.get('kind')})\n변경 전:\n```json\n{json.dumps(before, ensure_ascii=False, indent=1) if before else '(스냅샷 없음)'}\n```\n"
                         f"변경 후:\n```json\n{json.dumps(_slim(cur), ensure_ascii=False, indent=1) if cur else '(TC 목록에 없음)'}\n```")
            _collect(cur or {}, ops, prd_refs)
    if spec and ops:
        parts.append("# OpenAPI 발췌 (dev 브랜치 계약)")
        for o in ops:
            op = spec.ops.get(o)
            if not op:
                parts.append(f"- {o}: OpenAPI 에 없음")
                continue
            block = {"operationId": op.id, "method": op.method, "path": op.path, "request_example": op.request_example,
                     "success": dict(op.success), "errors": {code: {"status": i.get("status"), "message": i.get("message")} for code, i in op.errors.items()}}
            parts.append("```json\n" + json.dumps(block, ensure_ascii=False, indent=1)[:6000] + "\n```")
    seen: set = set()
    prd_parts = []
    for doc, sec in prd_refs:
        if (doc, sec) in seen:
            continue
        seen.add((doc, sec))
        text = wiki.prd_section(doc, sec, max_lines=80) if wiki.available else None
        prd_parts.append(f"## PRD/{doc} §{sec}\n" + (text or "(본문 없음)"))
    if prd_parts:
        parts.append("# 새 PRD 절 본문 (기획 정본)\n" + "\n\n".join(prd_parts))
    parts.append("# 허용되는 covers\n" + (", ".join(allowed) or "(없음)"))
    parts.append("# 출력\n같은 id 의 스크립트 하나를 ```yaml 블록 하나로. 바뀐 부분만.")
    text = "\n\n".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], allowed


def _slim(r: dict) -> dict:
    out = {k: r.get(k) for k in ("id", "layer", "kind", "domain", "title", "gate", "command", "actor", "binding", "source", "prd") if r.get(k) not in (None, [], {}, "")}
    hint = r.get("expect_hint")
    if isinstance(hint, dict):
        out["expect_hint"] = {k: v for k, v in hint.items() if k != "example"}
    elif hint:
        out["expect_hint"] = hint
    return out


def _collect(r: dict, ops: list, prd_refs: list) -> None:
    b = r.get("binding") or {}
    for o in (b.get("operations") or []):
        if o not in ops:
            ops.append(o)
    for ref in r.get("prd") or []:
        prd_refs.append((ref["doc"], ref["section"]))


def revise(*, cfg: Config, catalog, spec: SpecData | None, wiki: Wiki, case: Case, drift: list[dict], changes: dict, existing_ids: set[str]) -> dict:
    """반환 {prompt_hash, raw, allowed, accepted: (Case, warnings)|None, errors, model}. id 는 원본으로 고정한다."""
    prompt, phash, allowed = assemble_revision(cfg=cfg, catalog=catalog, spec=spec, wiki=wiki, case=case, drift=drift, changes=changes)
    raw_text = hermes.chat(cfg, REVISE_SYSTEM, prompt, session_prefix="qa-revise", timeout=max(cfg.hermes_timeout, 180))
    docs = parse_output(raw_text)
    if not docs:
        return {"prompt_hash": phash, "raw": raw_text, "allowed": allowed, "accepted": None, "errors": ["출력에서 스크립트 YAML 을 찾지 못했다"], "model": cfg.hermes_model}
    d = dict(docs[0])
    d["id"] = case.id                      # 규칙 1 — 원본 id 유지 (사람이 파일을 바꿔치기한다)
    c, errors, warnings = validate(d, requested=allowed, catalog=catalog, cfg=cfg, existing_ids=existing_ids - {case.id})
    return {"prompt_hash": phash, "raw": raw_text, "allowed": allowed, "accepted": (c, warnings) if c else None, "errors": errors, "model": cfg.hermes_model}


# ---------------------------------------------------------------------------------------------
# PRD 절에서 수동 작성 TC 제안 (docs/qa-platform-hermes.md §3 트리 4, P4d). MCP 도구 qa_manual_tc_propose 와 버튼이 같이 쓴다
# ---------------------------------------------------------------------------------------------
PROPOSE_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 주어진 PRD 절 본문에서, SSOT 로 형식화되지 않아 자동으로 뽑히지 않은 확인 항목(테스트 케이스)을 골라낸다. 한국어로 쓴다.\n\n"
    "규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나, 최상위는 `items:` 목록. 항목은 title(한 문장, ~할 수 있다/~이다 꼴)·given·when(요청이나 행동)·then(기대 결과) 네 키, 선택으로 operations(OpenAPI operationId 목록).\n"
    "2. 본문에 적힌 것만 쓴다. 추측한 규칙이나 수치는 넣지 않는다. 이미 주어진 '기존 TC' 와 같은 내용은 다시 내지 않는다.\n"
    "3. API 로 확인할 수 있는 것을 우선하되, 화면·운영 기준도 된다. 많아도 8개, 없으면 빈 목록."
)


def build_manual_tc(*, catalog, doc: str, section: str, items: list, domain: str | None, wiki: Wiki | None) -> tuple[list[dict], list[str], str]:
    """items(title·given·when·then·operations) → manual-tc.yaml 형식 레코드. 번호는 기존 다음부터. 반환 (레코드, 경고, 도메인).

    형식 오류는 ValueError. 도메인이 없으면 같은 문서의 기존 수동 TC 에서, 그것도 없으면 other."""
    from .cases import _TC
    from .wiki import doc_slug
    slug = doc_slug(str(doc))
    sec = str(section).strip().rstrip(".")
    prefix = f"PRD.{slug}.{sec}#"
    existing = [r for r in catalog.records.values() if r["layer"] == "manual" and r["id"].startswith(prefix)]
    n0 = max([int(r["id"].split("#")[-1]) for r in existing if r["id"].split("#")[-1].isdigit()] or [0])
    if not domain:
        same_doc = [r for r in catalog.records.values() if r["layer"] == "manual" and r["id"].startswith(f"PRD.{slug}.")]
        domain = same_doc[0]["domain"] if same_doc else "other"
    warnings: list[str] = []
    if wiki is not None and wiki.available and not wiki.prd_path(str(doc)):
        warnings.append(f"PRD 문서 '{doc}' 를 위키 체크아웃에서 찾지 못했다 — 문서 이름을 확인")
    elif wiki is not None and wiki.available and wiki.prd_section(str(doc), sec, max_lines=5) is None:
        warnings.append(f"PRD/{doc} 에 §{sec} 헤딩이 없다")
    out = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict) or not all(isinstance(it.get(k), str) and it[k].strip() for k in ("title", "when", "then")):
            raise ValueError(f"items[{i}]: title·when·then 은 비어 있지 않은 문자열")
        rec = {"id": f"{prefix}{n0 + i}", "doc": str(doc), "section": sec, "domain": str(domain), "title": it["title"].strip()}
        if it.get("given"):
            rec["given"] = str(it["given"]).strip()
        rec["when"] = it["when"].strip()
        rec["then"] = it["then"].strip()
        ops = [str(o) for o in (it.get("operations") or []) if str(o).strip()]
        if ops:
            rec["operations"] = ops
        if not _TC.match(rec["id"]):
            raise ValueError(f"만들어진 id 가 형식에 안 맞는다: {rec['id']} (doc·section 확인)")
        out.append(rec)
    return out, warnings, str(domain)


def propose_manual_tc(*, cfg: Config, catalog, wiki: Wiki, doc: str, section: str, domain: str | None) -> dict:
    """PRD 절 본문 → Hermes → items. 반환 {prompt_hash, raw, items, records, warnings, domain, model}. 본문이 없으면 ValueError."""
    if not wiki.available:
        raise ValueError("위키 체크아웃이 없다 (QA_WIKI_DIR) — PRD 를 읽을 수 없다")
    if not wiki.prd_path(doc):
        raise ValueError(f"PRD 문서를 찾지 못했다: {doc}")
    sec = str(section).strip().rstrip(".")
    text = wiki.prd_section(doc, sec, max_lines=150)
    if text is None:
        raise ValueError(f"PRD/{doc} 에 §{sec} 헤딩이 없다")
    from .wiki import doc_slug
    prefix = f"PRD.{doc_slug(doc)}.{sec}#"
    existing = [r for r in catalog.records.values() if r["layer"] == "manual" and r["id"].startswith(prefix)]
    parts = [f"# PRD/{doc} §{sec} 본문\n{text}"]
    if existing:
        parts.append("# 기존 TC (이 절에서 이미 뽑힌 것 — 다시 내지 않는다)\n" + "\n".join(f"- {r['id']}: {r['title']}" for r in existing))
    parts.append("# 출력\n```yaml\nitems:\n  - title: …\n    given: …\n    when: …\n    then: …\n    operations: [operationId]\n```")
    prompt = "\n\n".join(parts)
    phash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]
    raw = hermes.chat(cfg, PROPOSE_SYSTEM, prompt, session_prefix="qa-propose", timeout=max(cfg.hermes_timeout, 180))
    items: list[dict] = []
    for b in re.findall(r"```(?:ya?ml)?\s*\n(.*?)```", raw, re.S) or [raw]:
        try:
            doc_y = yaml.safe_load(b)
        except yaml.YAMLError:
            continue
        if isinstance(doc_y, dict) and isinstance(doc_y.get("items"), list):
            items = [x for x in doc_y["items"] if isinstance(x, dict)]
            break
        if isinstance(doc_y, list):
            items = [x for x in doc_y if isinstance(x, dict)]
            break
    items = items[:8]
    records, warnings, dom = ([], [], domain or "other") if not items else build_manual_tc(catalog=catalog, doc=doc, section=sec, items=items, domain=domain, wiki=wiki)
    return {"prompt_hash": phash, "raw": raw, "items": items, "records": records, "warnings": warnings, "domain": dom, "model": cfg.hermes_model}
