"""Hermes 로 케이스 채우기 (docs/qa-platform-scenarios.md §7). 근거 조립 → Hermes → 결정론 검증(§6.1) → 합쳐 저장.

원칙은 스크립트 생성(qa/drafts.py)과 같다. Hermes 는 플랫폼이 넣어 준 근거만으로 쓰고, 위키 도구를 쓰지 않는다.
- 근거: PRD 2장 원문과 요구 id, 그 기능의 규칙표(게이트·검사·명령), 거절 검사의 ErrorCode·자동화 제외, 명령에 묶인 API 요약,
  지금 시나리오 파일, 아직 테스트가 없는 거절 조건.
- 출력: 그 기능의 시나리오 파일. 플랫폼은 그것을 **합친다**. 이미 있는 케이스는 건드리지 않고, 새 key 의 케이스와 비어 있던 gates 만 더한다.
  사람이 쓴 것을 Hermes 가 덮어쓰지 않게 하려는 것이다. 더한 케이스에는 `written_by: hermes` 가 붙는다.
"""
from __future__ import annotations

import hashlib
import json
import re

import yaml

from . import scenarios as S
from .wiki import doc_slug

FILL_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 한 기능의 PRD 2장 사용자 시나리오마다, QA 가 확인할 갈래(케이스)와 단계별 게이트를 채운다. "
    "아래에 주어진 근거만 쓴다. 근거에 없는 조건·거절·코드는 지어내지 않는다. 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나. 최상위는 `feature:` 와 `scenarios:` 다. 설명 문장은 쓰지 않는다.\n"
    "2. 시나리오 id 는 PRD 2장에 있는 Sn 만 쓴다. 새 시나리오를 만들지 않는다.\n"
    "3. `gates:` 는 단계 요구 id → 그 행동을 허락하는 게이트 id 목록이다. 주어진 게이트 목록에 있는 id 만 쓴다. 조회만 하는 단계에는 적지 않는다.\n"
    "4. 케이스 kind 는 happy · branch · reject · extra 다.\n"
    "   - happy: 시나리오마다 하나, key 는 happy. checks 에는 그 흐름이 끝났을 때 확인할 명령 성공 테스트 조건(C.x)을 쓴다.\n"
    "   - branch: PRD 의 `분기:` 줄마다 하나. at 은 그 분기 줄의 요구 id.\n"
    "   - reject: 아직 테스트가 없는 거절 조건 하나에 케이스 하나. key 는 검사 key 그대로(시나리오 안에서 겹치면 `게이트끝이름.key`). "
    "at 은 그 게이트를 gates 에 적은 단계의 요구 id, checks 는 [그 검사 테스트 조건 id] 하나. ErrorCode 가 없는 검사는 `mode: manual`.\n"
    "5. title 은 한국어 한 문장. given(전제)·then(기대 결과)은 검사의 ref·message·error·note 와 PRD 문장에서만 가져오고, 모르면 비운다.\n"
    "6. checks 에는 주어진 테스트 조건 id 만 쓴다.\n"
    "7. 이미 있는 케이스 key 는 다시 쓰지 않아도 된다. 써도 플랫폼이 무시한다. 새로 더할 것에 집중한다.\n"
    "8. 케이스 key 는 소문자·숫자·점·하이픈. new·edit·delete 는 쓰지 않는다."
)


def feature_rules(ssot: dict, doc: str, extra_gates: set[str]) -> tuple[list[dict], list[dict]]:
    """이 기능에 걸린 게이트와 명령 — 출처가 이 PRD 인 것, 그 명령의 게이트, 시나리오 파일에 이미 적힌 게이트."""
    pre = f"PRD/{doc} "
    cmds = [c for c in ssot.get("commands") or [] if any(str(s).startswith(pre) for s in c.get("source") or [])]
    gids = {c.get("gate") for c in cmds if c.get("gate")} | set(extra_gates)
    gates = [g for g in ssot.get("gates") or [] if g["id"] in gids or any(str(s).startswith(pre) for s in g.get("source") or [])]
    gids |= {g["id"] for g in gates}
    cmds += [c for c in ssot.get("commands") or [] if c.get("gate") in gids and c not in cmds]
    return gates, cmds


def assemble_fill(*, doc: str, wiki, ssot: dict, catalog, spec, feature, ov_feature: dict) -> tuple[str, str]:
    """(프롬프트, 해시)."""
    extra = {g for s in (feature.scenarios if feature else []) for gl in s.gates.values() for g in gl}
    gates, cmds = feature_rules(ssot, doc, extra)
    parts = [f"# 기능: {doc}", "# PRD 2장 (시나리오 원문)\n" + (wiki.prd_section(doc, "2", max_lines=200) or "(본문 없음)")]
    steps = []
    for s in ov_feature["scenarios"]:
        if not s["in_prd"]:
            continue
        steps.append(f"## {s['id']} {s['title']}")
        steps += [f"- {st['req']} {'분기' if st['branch'] else '단계 ' + str(st['no'])}: {st['text']}" for st in s["steps"] if st.get("req")]
    parts.append("# 단계와 요구 id (gates·at 은 이 id 만)\n" + "\n".join(steps))
    recs = catalog.records if catalog is not None else {}
    g_out = []
    for g in gates:
        checks = []
        for c in g.get("checks") or []:
            tid = f"{g['id']}#{c.get('key')}"
            r = recs.get(tid) or {}
            checks.append({k: v for k, v in {"tc": tid, "ref": c.get("ref"), "error": (r.get("binding") or {}).get("error_code") or c.get("error"),
                                              "message": c.get("message"), "note": (c.get("note") or "")[:300] or None,
                                              "excluded": r.get("excluded")}.items() if v})
        g_out.append({"id": g["id"], "name": g.get("name"), "checks": checks})
    parts.append("# 게이트와 검사 (거절 테스트 조건 id 는 `게이트#key`, excluded 는 자동화 제외)\n```json\n" + json.dumps(g_out, ensure_ascii=False, indent=1) + "\n```")
    c_out = []
    for c in cmds:
        r = recs.get(c["id"]) or {}
        ops = (r.get("binding") or {}).get("operations") or []
        api = []
        for o in ops:
            op = spec.ops.get(o) if spec else None
            api.append(f"{op.method} {op.path} ({o})" if op else o)
        c_out.append({k: v for k, v in {"tc": c["id"], "name": c.get("name"), "actor": c.get("actor"), "gate": c.get("gate"), "api": api or None,
                                        "excluded": r.get("excluded")}.items() if v})
    parts.append("# 명령 (성공 테스트 조건 id 는 명령 id)\n```json\n" + json.dumps(c_out, ensure_ascii=False, indent=1) + "\n```")
    cur = S.dump_feature(feature.raw) if feature else "(아직 시나리오 파일이 없다)"
    parts.append("# 지금 시나리오 파일 (이미 있는 케이스는 그대로 둔다)\n```yaml\n" + cur.strip() + "\n```")
    rej = [f"- {s['id']} at {r['at']}: {r['id']} {r['error_code'] or 'ErrorCode 없음'} — {r['title']}" for s in ov_feature["scenarios"] for r in s["untested_rejects"]]
    parts.append("# 아직 테스트가 없는 거절 조건 (gates 를 새로 적으면 거기 걸린 거절 검사도 더한다)\n" + ("\n".join(rej) or "(없음)"))
    parts.append(f"# 출력\n`feature: {doc}` 와 scenarios 를 ```yaml 블록 하나로.")
    text = "\n\n".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def parse_fill(text: str) -> dict:
    blocks = re.findall(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S) or [text]
    for b in blocks:
        try:
            d = yaml.safe_load(b)
        except yaml.YAMLError:
            continue
        if isinstance(d, dict) and isinstance(d.get("scenarios"), list):
            return d
    raise S.ScenarioError("Hermes 출력에서 scenarios 를 찾지 못했다")


def merge_op(doc: str, out: dict, feature) -> dict:
    """Hermes 출력 → 합치기 변경(op action merge). 이미 있는 케이스 key 와 PRD 에 없는 형식의 것은 여기서 거르지 않고 apply_op·검증이 본다."""
    scns = []
    for s in out.get("scenarios") or []:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        cur = feature.scenario(str(s["id"])) if feature else None
        have = {v.key for v in cur.variants} if cur else set()
        vs = [dict(S.variant_raw(v), written_by="hermes") for v in s.get("variants") or [] if isinstance(v, dict) and str(v.get("key") or "") not in have]
        scns.append({"id": str(s["id"]), "actor": s.get("actor"), "gates": s.get("gates") or {}, "variants": vs})
    return {"feature": doc, "scenario": "*", "action": "merge", "scenarios": scns}


# ---------------------------------------------------------------------------------------------
# [Hermes 로 다시 맞추기] (§10) — PRD·규칙표 문장이 바뀐 시나리오의 케이스를 바뀐 만큼만 고친다
# ---------------------------------------------------------------------------------------------
REALIGN_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 한 시나리오의 PRD 문장이나 규칙표 검사가 바뀌었다. 바뀐 문장에 걸린 케이스만 바뀐 만큼 고친다. "
    "주어진 근거만 쓰고 지어내지 않는다. 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```yaml 코드 블록 하나. 시나리오 하나를 `id`, `gates`, `variants` 로 쓴다.\n"
    "2. 고쳐도 되는 케이스 key 목록이 주어진다. 그 밖의 케이스는 쓰지 않는다. 써도 플랫폼이 무시한다.\n"
    "3. 없어진 테스트 조건은 checks 에서 뺀다. 바뀐 문장에 맞게 title·given·then·at·checks 를 고친다. 바뀌지 않은 칸은 그대로 둔다.\n"
    "4. gates 는 바뀐 요구 id 의 것만 적는다.\n"
    "5. 새로 필요한 케이스가 있으면 새 key 로 더해도 된다. 케이스 kind·key 규칙은 지금 파일과 같다."
)


def affected(s, drift: dict) -> tuple[list[str], list[str]]:
    """바뀐·없어진 항목에 걸린 케이스 key 와 요구 id. 케이스는 at 이 바뀐 요구이거나 checks 가 바뀐 테스트 조건을 가리키면 걸린다."""
    ids = {x["id"] for x in drift["changed"] + drift["removed"]}
    reqs = sorted({i for i in ids | {x["id"] for x in drift["added"]} if re.match(r"^R\d+$", i)})
    keys = [v.key for v in s.variants if (v.at in ids) or (set(v.checks) & ids)]
    return keys, reqs


def assemble_realign(*, doc: str, wiki, ssot: dict, feature, sid: str, drift: dict, keys: list[str], reqs: list[str]) -> tuple[str, str]:
    s = feature.scenario(sid)
    gates, _ = feature_rules(ssot, doc, {g for gl in s.gates.values() for g in gl})
    parts = [f"# 기능: {doc} · 시나리오 {sid}", "# PRD 2장 (지금 문장)\n" + (wiki.prd_section(doc, "2", max_lines=200) or "(본문 없음)")]
    lines = [f"- 바뀜 {x['id']}: {x['text']}" for x in drift["changed"]] + [f"- 없어짐 {x['id']}" for x in drift["removed"]] + \
            [f"- 새로 생김 {x['id']}: {x['text']}" for x in drift["added"]]
    parts.append("# 지난 저장 뒤 바뀐 것 (지금 내용)\n" + "\n".join(lines))
    g_out = [{"id": g["id"], "name": g.get("name"), "checks": [{"tc": f"{g['id']}#{c.get('key')}", "ref": c.get("ref"), "error": c.get("error"),
                                                                "message": c.get("message")} for c in g.get("checks") or []]} for g in gates]
    parts.append("# 게이트와 검사 (지금)\n```json\n" + json.dumps(g_out, ensure_ascii=False, indent=1) + "\n```")
    raw = {k: v for k, v in s.raw.items() if k != "basis"}
    parts.append("# 지금 시나리오 (파일)\n```yaml\n" + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False).strip() + "\n```")
    parts.append(f"# 고쳐도 되는 케이스 key\n{', '.join(keys) or '(없음 — 새 케이스만 더할 수 있다)'}\n\n# gates 를 고쳐도 되는 요구 id\n{', '.join(reqs) or '(없음)'}")
    parts.append("# 출력\n시나리오 하나(id, gates, variants)를 ```yaml 블록 하나로.")
    text = "\n\n".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def parse_realign(text: str, sid: str) -> dict:
    blocks = re.findall(r"```(?:ya?ml)?\s*\n(.*?)```", text, re.S) or [text]
    for b in blocks:
        try:
            d = yaml.safe_load(b)
        except yaml.YAMLError:
            continue
        if isinstance(d, dict) and isinstance(d.get("scenarios"), list):
            d = next((x for x in d["scenarios"] if isinstance(x, dict) and str(x.get("id")) == sid), None)
        if isinstance(d, dict) and isinstance(d.get("variants"), list):
            return d
    raise S.ScenarioError("Hermes 출력에서 시나리오(variants)를 찾지 못했다")


def revise_op(doc: str, sid: str, out: dict, feature, keys: list[str], reqs: list[str]) -> dict:
    have = {v.key for v in feature.scenario(sid).variants}
    vs = [dict(S.variant_raw(v), written_by="hermes") for v in out.get("variants") or []
          if isinstance(v, dict) and (str(v.get("key") or "") in keys or str(v.get("key") or "") not in have)]
    gates = {str(k): v for k, v in (out.get("gates") or {}).items() if str(k) in reqs}
    return {"feature": doc, "scenario": sid, "action": "revise", "variants": vs, "allowed": keys, "allowed_reqs": reqs, "gates": gates}
