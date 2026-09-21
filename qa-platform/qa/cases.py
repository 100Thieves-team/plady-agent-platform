"""케이스 YAML 로드·검증·선택. 정본은 git (qa-platform/cases/). docs/qa-platform.md §8.

파일 하나에 케이스 하나(맵) 또는 `cases: [...]` 목록. 로드 실패는 파일 단위로 보고하고
나머지는 계속 읽는다 — 케이스 하나가 깨졌다고 플랫폼이 못 뜨면 안 된다.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SUITES = ("smoke", "sanity", "manual")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
EXPECT_KEYS = ("status", "result", "error_code", "json", "exists")
_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")


class CaseError(ValueError):
    pass


@dataclass
class Case:
    id: str
    title: str
    suite: str
    steps: list
    domains: list = field(default_factory=list)
    operations: list = field(default_factory=list)
    source: list = field(default_factory=list)
    actor: str | None = None
    description: str = ""
    raw: dict = field(default_factory=dict)
    file: str = ""
    hash: str = ""

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.raw, allow_unicode=True, sort_keys=False)

    def needs_actor(self) -> bool:
        return bool(self.actor) or any(s.get("actor") for s in self.steps)


def _validate(d: dict, file: str) -> Case:
    if not isinstance(d, dict):
        raise CaseError(f"{file}: 케이스는 맵이어야 한다")
    cid = d.get("id")
    if not isinstance(cid, str) or not _ID.match(cid):
        raise CaseError(f"{file}: id 가 없거나 형식이 틀렸다 (소문자·숫자·점·하이픈): {cid!r}")
    title = d.get("title")
    if not isinstance(title, str) or not title.strip():
        raise CaseError(f"{file}:{cid}: title 필요")
    suite = d.get("suite")
    if suite not in SUITES:
        raise CaseError(f"{file}:{cid}: suite 는 {SUITES} 중 하나: {suite!r}")
    steps = d.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CaseError(f"{file}:{cid}: steps 는 비어 있지 않은 목록")
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            raise CaseError(f"{file}:{cid}: step {i} 는 맵")
        s.setdefault("name", f"step {i}")
        req = s.get("request")
        if not isinstance(req, dict):
            raise CaseError(f"{file}:{cid}: step {i} request 필요")
        m = str(req.get("method", "")).upper()
        if m not in METHODS:
            raise CaseError(f"{file}:{cid}: step {i} method 는 {METHODS}: {req.get('method')!r}")
        req["method"] = m
        p = req.get("path")
        if not isinstance(p, str) or not p.startswith("/"):
            raise CaseError(f"{file}:{cid}: step {i} path 는 '/' 로 시작: {p!r}")
        exp = s.get("expect") or {}
        if not isinstance(exp, dict):
            raise CaseError(f"{file}:{cid}: step {i} expect 는 맵")
        bad = [k for k in exp if k not in EXPECT_KEYS]
        if bad:
            raise CaseError(f"{file}:{cid}: step {i} expect 에 모르는 키 {bad} (허용: {EXPECT_KEYS})")
        if "json" in exp and not isinstance(exp["json"], dict):
            raise CaseError(f"{file}:{cid}: step {i} expect.json 은 경로→값 맵")
        if "exists" in exp and not isinstance(exp["exists"], list):
            raise CaseError(f"{file}:{cid}: step {i} expect.exists 는 경로 목록")
        s["expect"] = exp
        save = s.get("save") or {}
        if not isinstance(save, dict):
            raise CaseError(f"{file}:{cid}: step {i} save 는 변수→경로 맵")
        s["save"] = save
    for k in ("domains", "operations", "source"):
        v = d.get(k) or []
        if not isinstance(v, list):
            raise CaseError(f"{file}:{cid}: {k} 는 목록")
        d[k] = [str(x) for x in v]
    canonical = yaml.safe_dump(d, allow_unicode=True, sort_keys=True).encode("utf-8")
    return Case(
        id=cid, title=title.strip(), suite=suite, steps=steps,
        domains=d["domains"], operations=d["operations"], source=d["source"],
        actor=d.get("actor"), description=str(d.get("description") or ""),
        raw=d, file=file, hash=hashlib.sha256(canonical).hexdigest()[:16],
    )


def load_dir(path: Path) -> tuple[dict[str, Case], list[str]]:
    """반환: (id→Case, 오류 메시지 목록). 중복 id 는 오류."""
    cases: dict[str, Case] = {}
    errors: list[str] = []
    for f in sorted(Path(path).glob("*.y*ml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            errors.append(f"{f.name}: YAML 파싱 실패: {e}")
            continue
        items = doc.get("cases") if isinstance(doc, dict) and "cases" in doc else [doc]
        if not isinstance(items, list):
            errors.append(f"{f.name}: cases 는 목록")
            continue
        for item in items:
            try:
                c = _validate(item, f.name)
            except CaseError as e:
                errors.append(str(e))
                continue
            if c.id in cases:
                errors.append(f"{f.name}: 중복 id {c.id} (먼저 {cases[c.id].file})")
                continue
            cases[c.id] = c
    return cases, errors


def parse_one(text: str, file: str = "<inline>") -> Case:
    return _validate(yaml.safe_load(text), file)


def select(cases: dict[str, Case], suite: str | None = None, ids: list[str] | None = None,
           domains: list[str] | None = None, operations: list[str] | None = None) -> list[Case]:
    """suite / ids / domains / operations 는 각각 필터. domains·operations 는 OR 로 합친다."""
    out = []
    dset = set(domains or [])
    oset = set(operations or [])
    for c in cases.values():
        if suite and c.suite != suite:
            continue
        if ids is not None and c.id not in ids:
            continue
        if (dset or oset) and not (dset & set(c.domains) or oset & set(c.operations)):
            continue
        out.append(c)
    return sorted(out, key=lambda c: c.id)
