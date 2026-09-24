"""시나리오 파일 — 기능(PRD) > 시나리오(PRD 2장 Sn) > 변형 > 스크립트. docs/qa-platform-scenarios.md §2, §5, §6.1.

파일은 `qa-platform/scenarios/<기능>.yaml` 하나에 기능 하나. 시나리오 제목과 단계는 파일에 없고 PRD 2장에서 읽는다.
변형 상태(자동화됨·사람이 확인·제외·테스트 없음)와 테스트 없는 거절 규칙은 저장하지 않고 매번 계산한다.

- `load_dir` 는 형식만 본다 (위키·TC 목록 없이도 읽힌다). 틀린 파일은 빼고 오류를 남긴다.
- `check` 는 §6.1 결정론 검증 — PRD 2장·TC 목록·스크립트와 대조한다. 오류와 경고를 돌려준다.
- `overview` 는 화면이 쓰는 계산 결과 — PRD 의 모든 기능·시나리오를 싣고, 파일이 없는 시나리오는 "변형 없음" 으로 둔다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .cases import _TC, _VARIANT
from .wiki import doc_slug

KINDS = ("happy", "branch", "reject", "extra")
KIND_KO = {"happy": "정상 흐름", "branch": "분기", "reject": "거절", "extra": "추가"}
MODES = ("auto", "manual")
STATES = ("auto", "manual", "excluded", "untested")
STATE_KO = {"auto": "자동화됨", "manual": "사람이 확인", "excluded": "제외", "untested": "테스트 없음"}
_SCN_ID = re.compile(r"^S\d+$")
_REQ = re.compile(r"^R\d+$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9.\-]*$")
_GATE = re.compile(r"^G\.[a-z_]+\.[a-z_]+$")
VARIANT_ID = _VARIANT      # 룸-생성/S1/headcount-range


class ScenarioError(ValueError):
    pass


@dataclass
class Variant:
    key: str
    kind: str
    title: str
    at: str | None = None
    given: str = ""
    then: str = ""
    checks: list = field(default_factory=list)
    mode: str = "auto"
    raw: dict = field(default_factory=dict)


@dataclass
class Scenario:
    id: str
    actor: str | None = None
    gates: dict = field(default_factory=dict)          # 요구 id → [게이트 id]
    variants: list = field(default_factory=list)
    basis_hash: str | None = None
    raw: dict = field(default_factory=dict)

    def variant(self, key: str) -> Variant | None:
        return next((v for v in self.variants if v.key == key), None)


@dataclass
class Feature:
    feature: str                                       # PRD 문서 이름 (룸 생성)
    slug: str                                          # 파일 이름 (룸-생성)
    scenarios: list = field(default_factory=list)
    file: str = ""
    raw: dict = field(default_factory=dict)

    def scenario(self, sid: str) -> Scenario | None:
        return next((s for s in self.scenarios if s.id == sid), None)


def variant_id(slug: str, sid: str, key: str) -> str:
    return f"{slug}/{sid}/{key}"


# ---------------------------------------------------------------------------------------------
# 읽기 — 형식 검증
# ---------------------------------------------------------------------------------------------
def _str_list(v, where: str) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ScenarioError(f"{where}: 목록이어야 한다")
    return [str(x).strip() for x in v if str(x).strip()]


def parse_feature(d, file: str) -> Feature:
    if not isinstance(d, dict):
        raise ScenarioError(f"{file}: 파일은 맵이어야 한다 (feature, scenarios)")
    name = d.get("feature")
    if not isinstance(name, str) or not name.strip():
        raise ScenarioError(f"{file}: feature(PRD 문서 이름)가 필요하다")
    slug = doc_slug(name)
    stem = unicodedata.normalize("NFC", Path(file).stem)       # macOS 파일 이름은 NFD 일 수 있다
    if file != "<inline>" and stem != slug:
        raise ScenarioError(f"{file}: 파일 이름은 기능 이름과 같아야 한다 ({slug}.yaml)")
    raw_scns = d.get("scenarios") or []
    if not isinstance(raw_scns, list):
        raise ScenarioError(f"{file}: scenarios 는 목록")
    scns, seen = [], set()
    for i, s in enumerate(raw_scns, 1):
        where = f"{file}: 시나리오 {i}"
        if not isinstance(s, dict):
            raise ScenarioError(f"{where} 는 맵")
        sid = str(s.get("id") or "")
        if not _SCN_ID.match(sid):
            raise ScenarioError(f"{where}: id 는 PRD 2장 번호(S1, S2 …): {sid!r}")
        if sid in seen:
            raise ScenarioError(f"{file}: 시나리오 {sid} 가 두 번 나온다")
        seen.add(sid)
        where = f"{file}: {sid}"
        gates_raw = s.get("gates") or {}
        if not isinstance(gates_raw, dict):
            raise ScenarioError(f"{where}: gates 는 요구 id → 게이트 목록 맵")
        gates = {}
        for req, gl in gates_raw.items():
            req = str(req)
            if not _REQ.match(req):
                raise ScenarioError(f"{where}: gates 의 키는 요구 id(R6): {req!r}")
            gl = [gl] if isinstance(gl, str) else gl
            gl = _str_list(gl, f"{where}: gates.{req}")
            bad = [g for g in gl if not _GATE.match(g)]
            if bad:
                raise ScenarioError(f"{where}: gates.{req} 는 게이트 id(G.room.create): {bad}")
            gates[req] = gl
        variants, keys = [], set()
        for j, v in enumerate(s.get("variants") or [], 1):
            vw = f"{where}: 변형 {j}"
            if not isinstance(v, dict):
                raise ScenarioError(f"{vw} 는 맵")
            key = str(v.get("key") or "")
            if not _KEY.match(key):
                raise ScenarioError(f"{vw}: key 는 소문자·숫자·점·하이픈: {key!r}")
            if key in keys:
                raise ScenarioError(f"{where}: 변형 key {key} 가 겹친다")
            keys.add(key)
            vw = f"{where}/{key}"
            kind = v.get("kind")
            if kind not in KINDS:
                raise ScenarioError(f"{vw}: kind 는 {KINDS} 중 하나: {kind!r}")
            title = v.get("title")
            if not isinstance(title, str) or not title.strip():
                raise ScenarioError(f"{vw}: title 필요")
            at = v.get("at")
            if at is not None:
                at = str(at)
                if not _REQ.match(at):
                    raise ScenarioError(f"{vw}: at 은 요구 id(R6): {at!r}")
            if kind in ("branch", "reject") and not at:
                raise ScenarioError(f"{vw}: {KIND_KO[kind]} 변형은 at(갈라지는 단계의 요구 id)이 필요하다")
            mode = v.get("mode") or "auto"
            if mode not in MODES:
                raise ScenarioError(f"{vw}: mode 는 auto 또는 manual: {mode!r}")
            checks = _str_list(v.get("checks"), f"{vw}: checks")
            bad = [t for t in checks if not _TC.match(t)]
            if bad:
                raise ScenarioError(f"{vw}: checks 의 TC id 형식이 틀렸다: {bad}")
            variants.append(Variant(key=key, kind=kind, title=title.strip(), at=at, given=str(v.get("given") or "").strip(),
                                    then=str(v.get("then") or "").strip(), checks=checks, mode=mode, raw=v))
        actor = s.get("actor")
        scns.append(Scenario(id=sid, actor=str(actor) if actor else None, gates=gates, variants=variants,
                             basis_hash=(str(s["basis_hash"]) if s.get("basis_hash") else None), raw=s))
    return Feature(feature=name.strip(), slug=slug, scenarios=scns, file=file, raw=d)


def load_dir(path: Path | None) -> tuple[dict[str, Feature], list[str]]:
    """반환: (slug → Feature, 오류). 폴더가 없으면 빈 것 — 시나리오 파일은 아직 없을 수 있다."""
    feats: dict[str, Feature] = {}
    errors: list[str] = []
    if not path or not Path(path).is_dir():
        return feats, errors
    for f in sorted(Path(path).glob("*.y*ml")):
        try:
            doc = yaml.safe_load(f.read_text(encoding="utf-8"))
            ft = parse_feature(doc, unicodedata.normalize("NFC", f.name))
        except yaml.YAMLError as ex:
            errors.append(f"{f.name}: YAML 파싱 실패: {ex}")
            continue
        except ScenarioError as ex:
            errors.append(str(ex))
            continue
        if ft.slug in feats:
            errors.append(f"{f.name}: 기능 {ft.feature} 가 두 파일에 있다")
            continue
        feats[ft.slug] = ft
    return feats, errors


# ---------------------------------------------------------------------------------------------
# §6.1 결정론 검증
# ---------------------------------------------------------------------------------------------
def _canon(catalog, tid: str) -> str:
    fn = getattr(catalog, "canonical", None)
    return fn(tid) if fn else tid


def _gate_of(tid: str) -> str | None:
    m = re.match(r"^(G\.[a-z_]+\.[a-z_]+)#", tid)
    return m.group(1) if m else None


def check(feats: dict[str, Feature], *, wiki, catalog, cases: dict) -> dict:
    """반환 {"errors": [..], "warnings": [..], "by_feature": {slug: {errors, warnings}}, "scripts": {case_id: [오류]}}.
    wiki 가 없으면 PRD 대조를, catalog 가 없으면 TC 대조를 건너뛴다."""
    out = {"errors": [], "warnings": [], "by_feature": {}, "scripts": {}}

    def add(slug, level, msg):
        out[level].append(f"{slug}: {msg}")
        out["by_feature"].setdefault(slug, {"errors": [], "warnings": []})[level].append(msg)

    recs = catalog.records if catalog is not None else None
    gate_ids = {r.get("gate") for r in recs.values() if r.get("gate")} if recs is not None else set()
    impl: dict[str, list[str]] = {}
    for c in cases.values():
        if getattr(c, "variant", None):
            impl.setdefault(c.variant, []).append(c.id)
    for slug, ft in feats.items():
        prd = {s["id"]: s for s in (wiki.prd_scenarios(ft.feature) if wiki is not None and wiki.available else [])}
        have_prd = wiki is not None and wiki.available and wiki.prd_path(ft.feature) is not None
        if wiki is not None and wiki.available and not have_prd:
            add(slug, "errors", f"PRD 문서 「{ft.feature}」 가 위키에 없다")
        for s in ft.scenarios:
            reqs = {st["req"] for st in (prd.get(s.id) or {}).get("steps", []) if st.get("req")}
            if have_prd and s.id not in prd:
                add(slug, "errors", f"{s.id} 가 PRD 2장에 없다")
            for req, gl in s.gates.items():
                if have_prd and s.id in prd and req not in reqs:
                    add(slug, "errors", f"{s.id} gates 의 {req} 가 그 시나리오의 단계에 없다")
                if recs is not None:
                    for gid in gl:
                        if gid not in gate_ids:
                            add(slug, "errors", f"{s.id} gates.{req} 의 {gid} 가 TC 목록에 없다")
            for v in s.variants:
                vid = f"{s.id}/{v.key}"
                if v.at and have_prd and s.id in prd and v.at not in reqs:
                    add(slug, "errors", f"{vid} 의 at {v.at} 가 {s.id} 의 단계에 없다")
                if recs is not None:
                    for t in v.checks:
                        if _canon(catalog, t) not in recs:
                            add(slug, "errors", f"{vid} checks 의 {t} 가 TC 목록에 없다")
                gchecks = [t for t in v.checks if _gate_of(t)]
                if v.kind == "reject" and v.at:
                    allowed = set(s.gates.get(v.at) or [])
                    outside = [t for t in gchecks if _gate_of(t) not in allowed]
                    if outside:
                        add(slug, "warnings", f"{vid}: checks {', '.join(outside)} 가 {v.at} 단계의 gates 밖이다")
                if len(gchecks) > 1:
                    add(slug, "warnings", f"{vid}: 검사 {len(gchecks)}개를 한 변형이 확인한다 — 검사 하나에 변형 하나가 기본이다")
                full = variant_id(slug, s.id, v.key)
                ids = impl.get(full) or []
                if len(ids) > 1:
                    add(slug, "warnings", f"{vid}: 스크립트 {len(ids)}개가 구현한다 ({', '.join(sorted(ids))})")
                for cid in ids:
                    c = cases[cid]
                    covered = {_canon(catalog, t) for t in c.covers} if catalog is not None else set(c.covers)
                    miss = [t for t in v.checks if _canon(catalog, t) not in covered]
                    if miss:
                        add(slug, "warnings", f"{vid}: 스크립트 {cid} 의 covers 에 변형이 확인할 {', '.join(miss)} 가 없다")
    known = {variant_id(slug, s.id, v.key) for slug, ft in feats.items() for s in ft.scenarios for v in s.variants}
    for vid, ids in impl.items():
        if vid not in known:
            for cid in ids:
                msg = f"variant {vid} 가 시나리오 파일에 없다"
                out["scripts"].setdefault(cid, []).append(msg)
                out["errors"].append(f"스크립트 {cid}: {msg}")
    return out


# ---------------------------------------------------------------------------------------------
# 화면용 계산 — 변형 상태, 테스트 없는 거절 규칙, 기능별 합계
# ---------------------------------------------------------------------------------------------
def variant_state(v: Variant, scripts: list, catalog) -> str:
    """자동화됨(스크립트가 있다) · 제외(확인할 TC 가 모두 자동화 제외) · 사람이 확인(mode manual) · 테스트 없음."""
    if scripts:
        return "auto"
    recs = catalog.records if catalog is not None else {}
    if v.checks and all((recs.get(_canon(catalog, t)) or {}).get("excluded") for t in v.checks):
        return "excluded"
    if v.mode == "manual":
        return "manual"
    return "untested"


def untested_rejects(s: Scenario, catalog) -> list[dict]:
    """§2.2 — 시나리오 단계에 걸린 게이트의 거절 검사 중 어느 변형도 확인하지 않고 자동화 제외도 아닌 것.
    ErrorCode 가 없는 검사는 manual 로 시작한다(§16 3차)."""
    if catalog is None:
        return []
    done = {_canon(catalog, t) for v in s.variants for t in v.checks}
    out, seen = [], set()
    for req, gl in s.gates.items():             # 파일에 적힌 단계 순서, 게이트 순서
        for gid in gl:
            rows = []
            for rec in catalog.records.values():
                if rec.get("gate") != gid or rec.get("kind") != "reject" or rec["id"] in done or rec["id"] in seen or rec.get("excluded"):
                    continue
                seen.add(rec["id"])
                code = (rec.get("binding") or {}).get("error_code")
                rows.append({"id": rec["id"], "at": req, "gate": gid, "title": rec.get("title") or "", "error_code": code,
                             "mode": "auto" if code else "manual", "key": rec["id"].split("#", 1)[-1]})
            out += sorted(rows, key=lambda x: ((x["error_code"] is None), (x.get("position") or 0), x["id"]))
    return out


def overview(feats: dict[str, Feature], *, wiki, catalog, cases: dict, last: dict[str, dict] | None = None) -> list[dict]:
    """PRD 의 모든 기능 → [{feature, slug, file, scenarios: [{id, title, steps, variants: [...], untested_rejects}], counts, last}].
    시나리오 파일에 있지만 PRD 에 없는 것도 싣는다(검증 오류로도 보인다)."""
    last = last or {}
    impl: dict[str, list] = {}
    for c in cases.values():
        if getattr(c, "variant", None):
            impl.setdefault(c.variant, []).append(c)
    docs = wiki.prd_docs() if wiki is not None and wiki.available else []
    names = list(dict.fromkeys(docs + [ft.feature for ft in feats.values()]))
    out = []
    for name in names:
        slug = doc_slug(name)
        ft = feats.get(slug)
        prd = wiki.prd_scenarios(name) if wiki is not None and wiki.available else []
        sids = list(dict.fromkeys([p["id"] for p in prd] + ([s.id for s in ft.scenarios] if ft else [])))
        rows = []
        counts = {k: 0 for k in STATES} | {"variants": 0, "rejects": 0, "pass": 0, "fail": 0}
        for sid in sids:
            p = next((x for x in prd if x["id"] == sid), None)
            s = ft.scenario(sid) if ft else None
            vs = []
            for v in (s.variants if s else []):
                vid = variant_id(slug, sid, v.key)
                scripts = sorted(impl.get(vid) or [], key=lambda c: c.id)
                st = variant_state(v, scripts, catalog)
                lv = sorted((last[c.id] for c in scripts if c.id in last), key=lambda r: r.get("created_at") or "", reverse=True)
                vs.append({"id": vid, "variant": v, "state": st, "scripts": scripts, "last": lv[0] if lv else None})
                counts[st] += 1
                counts["variants"] += 1
                if lv:
                    counts["pass" if lv[0]["verdict"] == "pass" else "fail"] += 1
            ur = untested_rejects(s, catalog) if s else []
            counts["rejects"] += len(ur)
            rows.append({"id": sid, "title": (p or {}).get("title") or "(PRD 2장에 없다)", "steps": (p or {}).get("steps") or [],
                         "in_prd": p is not None, "scenario": s, "variants": vs, "untested_rejects": ur})
        out.append({"feature": name, "slug": slug, "file": ft.file if ft else None, "scenarios": rows, "counts": counts})
    return out


def variant_index(feats: dict[str, Feature]) -> dict[str, tuple[Feature, Scenario, Variant]]:
    return {variant_id(slug, s.id, v.key): (ft, s, v) for slug, ft in feats.items() for s in ft.scenarios for v in s.variants}
