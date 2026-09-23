"""케이스 YAML 로드·검증·선택. 정본은 git (qa-platform/cases/). docs/qa-platform.md §8.

파일 하나에 케이스 하나(맵) 또는 `cases: [...]` 목록. 로드 실패는 파일 단위로 보고하고
나머지는 계속 읽는다 — 케이스 하나가 깨졌다고 플랫폼이 못 뜨면 안 된다.

`covers`(docs/qa-platform-tc.md §5): 케이스·단계가 덮는 TC id. smoke·sanity 는 필수. 형식 검증은 여기서,
카탈로그와의 대조(id 실재, method·path·코드 일치)는 `audit()` 에서 — 카탈로그 없이도 로드는 된다.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SUITES = ("smoke", "sanity", "manual", "setup")   # setup = 준비 작업(버튼 하나로 테스트 데이터 만들기, docs/qa-platform-api.md §5.4)
_INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_INPUT_EXPR = re.compile(r"\{\{\s*input\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
EXPECT_KEYS = ("status", "result", "error_code", "json", "exists")
_ID = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
# TC id: G.room.create#duplicate-slot-left · C.room.create · op.createRoom:E1402 · op.createRoom:200 · PRD.룸-탐색.4.2#1
# 게이트 검사는 key(G.room.create#offline-region-required, 2026-09-23~) 또는 예전 순서 번호(G.room.create#5)
_TC = re.compile(r"^(?:[GC]\.[a-z_]+\.[a-z_]+(?:#(?:\d+|[a-z][a-z0-9]*(?:-[a-z0-9]+)*))?|op\.[A-Za-z0-9_]+:(?:E\d{3,4}|\d{3})|(?:PRD|OPS)\.[^\s#]+#\d+)$")


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
    covers: list = field(default_factory=list)       # 케이스가 덮는 TC id (단계 covers 의 합집합 포함)
    reviewed: dict | None = None                     # {at: ISO 날짜, by: 운영자} — 드리프트 배지를 이 시각 이후 변경만 보이게
    inputs: dict = field(default_factory=dict)       # setup 전용: 화면 입력 {name: {label, default, required}} → {{input.name}}
    outputs: list = field(default_factory=list)      # setup 전용: 끝나면 화면에 돌려줄 save 변수 이름
    raw: dict = field(default_factory=dict)
    file: str = ""
    hash: str = ""
    audit: dict = field(default_factory=lambda: {"status": "unchecked", "errors": [], "warnings": []})

    @property
    def blocked(self) -> bool:
        """카탈로그 대조에서 오류가 난 케이스는 스위트에서 뺀다 (선언이 거짓이다)."""
        return self.audit.get("status") == "error"

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
        s["covers"] = _tc_list(s.get("covers"), f"{file}:{cid}: step {i}")
    for k in ("domains", "operations", "source"):
        v = d.get(k) or []
        if not isinstance(v, list):
            raise CaseError(f"{file}:{cid}: {k} 는 목록")
        d[k] = [str(x) for x in v]
    step_covers = [t for s in steps for t in s["covers"]]
    covers = _tc_list(d.get("covers"), f"{file}:{cid}")
    for t in step_covers:
        if t not in covers:
            covers.append(t)
    if suite in ("smoke", "sanity") and not covers:
        raise CaseError(f"{file}:{cid}: {suite} 케이스는 covers(덮는 TC id)가 하나 이상 필요하다")
    d["covers"] = covers
    # ---- 준비 작업(setup): inputs · outputs (docs/qa-platform-api.md §5.4). 다른 스위트는 사람 입력 없이 돌아야 하므로 inputs 금지
    inputs_raw = d.get("inputs") or None       # 빈 맵은 없는 것과 같다 (스냅샷 재검증이 걸리지 않게)
    if inputs_raw is not None and suite != "setup":
        raise CaseError(f"{file}:{cid}: inputs 는 suite setup 에서만 쓴다 (다른 스위트는 사람 입력 없이 돌아야 한다)")
    inputs: dict = {}
    if inputs_raw is not None:
        if not isinstance(inputs_raw, dict):
            raise CaseError(f"{file}:{cid}: inputs 는 이름→{{label, default, required}} 맵")
        for name, spec in inputs_raw.items():
            if not isinstance(name, str) or not _INPUT_NAME.match(name):
                raise CaseError(f"{file}:{cid}: inputs 이름은 영문·숫자·밑줄: {name!r}")
            if not isinstance(spec, dict):
                spec = {"default": spec}
            bad = [k for k in spec if k not in ("label", "default", "required", "hint")]
            if bad:
                raise CaseError(f"{file}:{cid}: inputs.{name} 에 모르는 키 {bad} (허용: label, default, required, hint)")
            inputs[name] = {"label": str(spec.get("label") or name), "default": spec.get("default"), "required": bool(spec.get("required", False)),
                            "hint": str(spec.get("hint") or "")}
    used = {m.group(1) for s in steps for m in _INPUT_EXPR.finditer(json.dumps(s, ensure_ascii=False, default=str))}
    missing = sorted(used - set(inputs))
    if missing:
        raise CaseError(f"{file}:{cid}: 단계가 쓰는 {{{{input.*}}}} 가 inputs 에 없다: {missing}")
    if inputs:
        d["inputs"] = inputs
    else:
        d.pop("inputs", None)
    outputs_raw = d.get("outputs") or []
    if not isinstance(outputs_raw, list):
        raise CaseError(f"{file}:{cid}: outputs 는 save 변수 이름 목록")
    saved = {k for s in steps for k in (s.get("save") or {})}
    outputs = [str(x) for x in outputs_raw]
    unknown = [x for x in outputs if x not in saved]
    if unknown:
        raise CaseError(f"{file}:{cid}: outputs 는 어떤 단계의 save 에 있는 변수여야 한다: {unknown}")
    if outputs:
        d["outputs"] = outputs
    else:
        d.pop("outputs", None)
    reviewed = d.get("reviewed")
    if reviewed is not None:
        if not isinstance(reviewed, dict) or not reviewed.get("at"):
            raise CaseError(f"{file}:{cid}: reviewed 는 {{at: 날짜, by: 운영자}} 맵")
        reviewed["at"] = str(reviewed["at"])
    canonical = yaml.safe_dump(d, allow_unicode=True, sort_keys=True).encode("utf-8")
    return Case(
        id=cid, title=title.strip(), suite=suite, steps=steps,
        domains=d["domains"], operations=d["operations"], source=d["source"],
        actor=d.get("actor"), description=str(d.get("description") or ""), covers=covers, reviewed=reviewed,
        inputs=inputs, outputs=outputs,
        raw=d, file=file, hash=hashlib.sha256(canonical).hexdigest()[:16],
    )


def _coerce_input(raw: str, default):
    """폼은 문자열만 준다 — 기본값의 타입(정수·실수·불린)을 따라 되돌린다. 안 맞으면 문자열 그대로."""
    if isinstance(default, bool):
        return raw.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(default, int):
        try:
            return int(raw.strip())
        except ValueError:
            return raw
    if isinstance(default, float):
        try:
            return float(raw.strip())
        except ValueError:
            return raw
    return raw


def bake_inputs(case: Case, values: dict) -> Case:
    """준비 작업의 화면 입력을 스크립트에 박아 새 Case 를 만든다 — 실행 기록의 스냅샷에 실제 값이 남는다(docs/qa-platform-api.md §5.4).
    `{{input.x}}` 가 값 전체면 타입을 지키고, 문자열 일부면 문자열로 끼운다. 다른 치환(`{{roomId}}` 등)은 건드리지 않는다."""
    if case.suite != "setup":
        raise CaseError(f"{case.id}: 준비 작업(setup) 스크립트가 아니다")
    final: dict = {}
    for name, spec in case.inputs.items():
        raw = values.get(name)
        raw = "" if raw is None else str(raw)
        if raw.strip() == "":
            if spec["required"] and spec["default"] in (None, ""):
                raise CaseError(f"{case.id}: 입력 '{spec['label']}' 은 필수다")
            final[name] = spec["default"] if spec["default"] is not None else ""
        else:
            final[name] = _coerce_input(raw, spec["default"])

    def walk(v):
        if isinstance(v, str):
            m = _INPUT_EXPR.fullmatch(v.strip())
            if m:
                return final[m.group(1)]
            return _INPUT_EXPR.sub(lambda mm: str(final[mm.group(1)]), v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    raw = json.loads(json.dumps(case.raw, ensure_ascii=False, default=str))
    raw["steps"] = walk(raw["steps"])
    raw.pop("inputs", None)
    raw["input_values"] = final       # 스냅샷에 남기는 입력값 (사람이 실행 기록에서 본다)
    return _validate(raw, f"setup:{case.id}")


def _tc_list(v, where: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise CaseError(f"{where}: covers 는 TC id 목록")
    out = []
    for x in v:
        x = str(x).strip()
        if not _TC.match(x):
            raise CaseError(f"{where}: covers 의 TC id 형식이 틀렸다: {x!r}")
        if x not in out:
            out.append(x)
    return out


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
    """suite / ids / domains / operations 는 각각 필터. domains·operations 는 OR 로 합친다.
    카탈로그 대조 오류(blocked)인 케이스는 스위트 선택에서 빠진다. id 로 직접 고르면 들어간다(사람이 알고 고른 것)."""
    out = []
    dset = set(domains or [])
    oset = set(operations or [])
    for c in cases.values():
        if suite and c.suite != suite:
            continue
        if c.blocked and ids is None:
            continue
        if ids is not None and c.id not in ids:
            continue
        if (dset or oset) and not (dset & set(c.domains) or oset & set(c.operations)):
            continue
        out.append(c)
    return sorted(out, key=lambda c: c.id)


# ---- 카탈로그 대조 (docs/qa-platform-tc.md §5.2) ------------------------------------------------
def _step_hits(step: dict, hint: dict) -> tuple[bool, list[str]]:
    """단계가 계약 TC 의 method·path·기대와 맞는지. (경로 일치, 문제 목록)."""
    from .spec import match_path
    req = step["request"]
    if req["method"] != str(hint.get("method", "")).upper() or not match_path(str(hint.get("path", "")), req.get("path", "")):
        return False, []
    problems = []
    exp = step.get("expect") or {}
    code = hint.get("error_code")
    if code:
        if exp.get("error_code") != code:
            problems.append(f"expect.error_code 가 {code} 가 아니다 ({exp.get('error_code')!r})")
    else:
        st = exp.get("status")
        if st is not None and not str(st).startswith("2"):
            problems.append(f"성공 계약인데 expect.status 가 {st}")
    return True, problems


def audit(cases: dict[str, Case], catalog) -> None:
    """각 케이스의 covers 를 카탈로그와 대조해 case.audit 를 채운다. catalog 가 None 이면 unchecked."""
    for c in cases.values():
        if catalog is None:
            c.audit = {"status": "unchecked", "errors": [], "warnings": []}
            continue
        errors: list[str] = []
        warnings: list[str] = []
        recs = catalog.records
        # 다른 이름으로 적힌 TC(게이트 검사의 옛 순서 번호 ↔ key)를 지금 카탈로그 id 로 맞춘다 (docs/policy-ssot-split.md §4.5)
        canon = getattr(catalog, "canonical", None)
        if canon:
            legacy = sorted({t for t in c.covers + [x for s in c.steps for x in s["covers"]] if t not in recs and canon(t) in recs and re.search(r"#\d+$", t)})
            c.covers = list(dict.fromkeys(canon(t) for t in c.covers))
            for s in c.steps:
                s["covers"] = list(dict.fromkeys(canon(t) for t in s["covers"]))
            if legacy:
                warnings.append(f"covers 의 옛 TC id {', '.join(legacy)} 를 key id 로 읽었다 — 스크립트를 새 id 로 고친다")
        for step_i, step in enumerate(c.steps, 1):
            for tid in step["covers"]:
                rec = recs.get(tid)
                if not rec:
                    continue   # 아래 케이스 수준에서 보고
                if rec["layer"] == "contract":
                    matched, problems = _step_hits(step, rec["expect_hint"])
                    if not matched:
                        errors.append(f"step {step_i} 가 {tid} 의 {rec['expect_hint'].get('method')} {rec['expect_hint'].get('path')} 를 부르지 않는다")
                    errors.extend(f"step {step_i} · {tid}: {p}" for p in problems)
                elif rec["layer"] == "policy" and rec["kind"] == "reject":
                    code = (rec.get("binding") or {}).get("error_code")
                    if code and (step.get("expect") or {}).get("error_code") != code:
                        warnings.append(f"step {step_i} · {tid}: 바인딩 코드 {code} 와 expect.error_code 가 다르다")
        step_covered = {t for s in c.steps for t in s["covers"]}
        for tid in c.covers:
            rec = recs.get(tid)
            if not rec:
                errors.append(f"covers: 카탈로그에 없는 TC {tid}")
                continue
            if tid in step_covered:
                continue
            if rec["layer"] == "contract":
                hits = [(_step_hits(s, rec["expect_hint"])) for s in c.steps]
                if not any(m for m, _ in hits):
                    errors.append(f"covers {tid}: 그 op 를 부르는 단계가 없다")
                elif not any(m and not p for m, p in hits):
                    errors.append(f"covers {tid}: op 를 부르지만 기대(코드·status)가 맞는 단계가 없다")
            elif rec["layer"] == "policy":
                ops = (rec.get("binding") or {}).get("operations") or []
                code = (rec.get("binding") or {}).get("error_code")
                if ops:
                    op_recs = [r for r in recs.values() if r["layer"] == "contract" and r.get("operation") in ops]
                    calls = any(_step_hits(s, r["expect_hint"])[0] for s in c.steps for r in op_recs)
                    if not calls:
                        warnings.append(f"covers {tid}: 바인딩된 op {', '.join(ops)} 를 부르는 단계가 없다")
                    elif code and not any((s.get("expect") or {}).get("error_code") == code for s in c.steps):
                        warnings.append(f"covers {tid}: 바인딩 코드 {code} 를 기대하는 단계가 없다")
        c.audit = {"status": "error" if errors else ("warn" if warnings else "ok"), "errors": errors, "warnings": warnings}
