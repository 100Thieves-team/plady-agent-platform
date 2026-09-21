"""Hermes 초안 생성 — 근거 조립 → 호출 → 결정론 검증 → 케이스 초안. docs/qa-platform-tc.md §7.

원칙: Hermes 는 플랫폼이 넣어 준 근거(TC 레코드·OpenAPI 발췌·PRD 절 본문)만으로 쓴다. 위키 도구를 쓰게 하지 않는다 —
그래야 "근거 = 프롬프트에 있던 것" 이 성립하고, 아래 검증이 그 근거와 대조할 수 있다.
검증을 통과한 것만 케이스 초안(drafts)에 들어간다. 버린 것은 사유와 함께 감사 로그에 남긴다.
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
    "dev 서버에서 실행할 API 케이스 초안을 YAML 로 쓴다. 근거에 없는 사실은 지어내지 말고 `TODO:` 로 남긴다. 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나, 최상위는 `cases:` 목록. 설명 문장은 블록 밖에 두지 말고 아예 쓰지 않는다.\n"
    "2. 케이스마다 `covers:` 를 쓴다. 값은 요청한 TC id 의 부분집합이어야 한다. 단계에도 `covers:` 를 달아 어느 단계가 어느 TC 를 덮는지 밝힌다.\n"
    "3. 계약 TC(`op.X:E####`)를 덮는 단계는 그 op 의 method·path 를 부르고 `expect.error_code` 가 그 코드여야 한다. "
    "`op.X:2xx` 를 덮는 단계는 `expect.status` 가 2xx 여야 한다.\n"
    "4. 거절 TC(`G.x#n`)는 `must_pass_first` 의 앞 검사들을 모두 통과하는 상태를 먼저 만든 뒤에 n 번째 검사만 걸리게 한다.\n"
    "5. 쓰기 케이스(POST/PUT/PATCH/DELETE)는 자기가 만든 데이터를 자기가 닫는 정리 단계(취소·철회·삭제)로 끝난다. 만든 데이터의 title 은 `[QA]` 로 시작한다.\n"
    "6. 로그인이 필요하면 `actor:` 에 주어진 테스트 계정 이름만 쓴다. 픽스처는 주어진 키만 `{{fixture.키}}` 로 쓴다.\n"
    "7. expect 는 status · result · error_code · json(경로→값) · exists(경로 목록) 5종만. 치환은 {{var}} {{actor.X.memberId}} {{fixture.키}} {{date:+N}} {{uuid}} {{rand}} 만.\n"
    "8. id 는 `<도메인>.<kebab-case>`, suite 는 sanity(쓰기) 또는 smoke(읽기 전용). title 은 한국어 한 문장."
)


# ---------------------------------------------------------------------------------------------
# 근거 조립
# ---------------------------------------------------------------------------------------------
def assemble(*, cfg: Config, catalog, spec: SpecData | None, wiki: Wiki, tc_ids: list[str], example: Case | None) -> tuple[str, str]:
    """(프롬프트 본문, 근거 해시). 같은 근거로 다시 만들면 해시가 같다 — 초안끼리 비교하는 열쇠."""
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
                 f"- 테스트 계정(actor) 이름: {', '.join(sorted(cfg.actors)) or '(없음 — 로그인 케이스는 actor 를 비워 두고 TODO 로 표시)'}\n"
                 f"- 픽스처 키: {', '.join(sorted(cfg.fixtures)) or '(없음)'}\n"
                 f"- 대상: {cfg.target_base_url} (dev). 응답 규약 {{result, data, error{{code}}}}.")
    if example is not None:
        parts.append("# 잘 만든 케이스 예시 (형식 참고)\n```yaml\n" + example.to_yaml().strip() + "\n```")
    parts.append("# 출력\n요청한 TC 를 덮는 케이스 1개 이상을 ```yaml 블록 하나로.")
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


def validate(raw: dict, *, requested: list[str], catalog, cfg: Config, existing_ids: set[str]) -> tuple[Case | None, list[str], list[str]]:
    """docs/qa-platform-tc.md §7.2. 반환 (케이스|None, 버린 사유, 경고)."""
    errors: list[str] = []
    warnings: list[str] = []
    raw = dict(raw)
    if isinstance(raw.get("id"), str) and raw["id"] in existing_ids:
        raw["id"] = raw["id"] + "-draft"
        warnings.append(f"id 가 기존 케이스와 겹쳐 '{raw['id']}' 로 바꿨다")
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
        if name and cfg.actors and name not in cfg.actors:
            errors.append(f"없는 테스트 계정 {name}")
        elif name and not cfg.actors:
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
            warnings.append("쓰기 케이스인데 마지막 단계가 정리(취소·철회·삭제)로 보이지 않는다")
        for i in writes:
            body = case.steps[i]["request"].get("body")
            if isinstance(body, dict) and isinstance(body.get("title"), str) and not body["title"].startswith("[QA]"):
                warnings.append(f"step {i + 1} 의 title 이 [QA] 로 시작하지 않는다")
    if errors:
        return None, errors, warnings
    return case, [], warnings


def validate_manual_tc(text: str) -> tuple[list[dict], list[str]]:
    """서술 TC 제안(kind tc) YAML — manual-tc.yaml 의 `cases:` 형식인지. 반환 (항목, 오류)."""
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
