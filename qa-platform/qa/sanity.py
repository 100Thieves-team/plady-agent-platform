"""Sanity 테스트 — 머지된 PR 하나를 스펙대로 확인한다 (docs/qa-platform-v2.md §4).

사람이 [Sanity 시작]을 누르면 다섯 단계를 차례로 한다. 스펙 확인이 필요하면 2단계에서 멈추고 사람을 기다린다.
  1 관련 스펙 찾기  2 스펙 점검  3 케이스 준비  4 스크립트 만들기  5 실행·검사
이 파일은 PR 요약·결정론 부분(변경 파일 → API → 규칙표 → PRD)과 상태 이름을 갖는다. 단계 실행은 app.py 의 App.sanity_* 가 한다.
"""
from __future__ import annotations

import re

from .github import domains_from_files

STEPS = ("관련 스펙 찾기", "스펙 점검", "케이스 준비", "스크립트 만들기", "실행·검사")
STATUS_KO = {"queued": "기다리는 중", "running": "진행 중", "needs_spec": "확인 필요", "passed": "통과", "failed": "실패",
             "error": "멈춤", "canceled": "그만둠", "interrupted": "멈춤", "empty": "확인할 것 없음"}
STATUS_BADGE = {"queued": "running", "running": "running", "needs_spec": "need", "passed": "pass", "failed": "fail",
                "error": "fail", "canceled": "none", "interrupted": "none", "empty": "none"}
KIND_KO = {"mismatch": "스펙과 코드가 달라요", "ambiguous": "스펙이 모호해요", "missing_api": "없어진 API 를 써요",
           "undocumented_api": "API 문서에 없어요", "no_rules": "규칙표가 없어요", "impact": "영향"}
BLOCKING = {"mismatch", "ambiguous", "missing_api", "undocumented_api"}      # 사람이 정해야 넘어가는 종류

_CONTROLLER = re.compile(r"/controller/(v1/)?[A-Za-z]+Controller\.kt$")
_MAPPING = re.compile(r'^([+-])\s*@(Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?"([^"]+)"')
_WORKLOG = re.compile(r"(^|/)\.worklog/.+/decisions\.md$")
# API 모양: 컨트롤러와 그 아래 요청·응답 DTO, API 문서(asciidoc). 동작 코드: 그 밖의 src/main (도메인·파사드·저장소·마이그레이션)
_CONTRACT = re.compile(r"/controller/.+\.kt$|/src/docs/asciidoc/")
_MAIN = re.compile(r"(^|/)src/main/")
SCOPE_KO = {"api": "API 변경", "code": "동작 변경", "none": "API·코드 변경 없음"}


def summarize(files: list[dict]) -> dict:
    """PR 변경 파일 → {changed_files, additions, deletions, scope, api, contract, domains} (§4.4).
    scope: api(컨트롤러·요청/응답 DTO·API 문서가 바뀜) · code(API 모양은 그대로, 동작 코드가 바뀜) · none(시험·문서·인프라만).
    api 는 Sanity 대상인가(scope 가 none 이 아님). contract 는 API 모양을 바꾼 파일 이름(컨트롤러 빼고 DTO 등)."""
    names = [f["filename"] for f in files]
    contract = [n for n in names if _CONTRACT.search(n) and "/src/test/" not in n]
    code = [n for n in names if _MAIN.search(n) and "/src/test/" not in n]
    scope = "api" if contract else ("code" if code else "none")
    return {"changed_files": len(files), "additions": sum(f.get("additions") or 0 for f in files),
            "deletions": sum(f.get("deletions") or 0 for f in files), "scope": scope, "api": scope != "none",
            "contract": [n.rsplit("/", 1)[-1] for n in contract if not _CONTROLLER.search(n)], "domains": sorted(domains_from_files(names))}


def endpoint_changes(files: list[dict]) -> list[dict]:
    """컨트롤러 diff 의 @XxxMapping 줄 → [{change: added|removed, method, path, file}]. 같은 끝점이 +·- 둘 다면 옮긴 것으로 보고 뺀다."""
    seen: dict[tuple, set] = {}
    for f in files:
        if not _CONTROLLER.search(f["filename"]):
            continue
        for line in (f.get("patch") or "").splitlines():
            m = _MAPPING.match(line)
            if m:
                seen.setdefault((m.group(2).upper(), m.group(3)), set()).add((m.group(1), f["filename"]))
    out = []
    for (method, path), marks in sorted(seen.items(), key=lambda x: x[0][1]):
        signs = {s for s, _ in marks}
        if len(signs) == 1:
            out.append({"change": "added" if "+" in signs else "removed", "method": method, "path": path,
                        "file": sorted(fn for _, fn in marks)[0].rsplit("/", 1)[-1]})
    return out


def decision_files(files: list[dict]) -> list[str]:
    """백엔드 결정 기록(.worklog/*/decisions.md) — Hermes 가 스펙 점검 때 함께 읽는다."""
    return [f["filename"] for f in files if _WORKLOG.search(f["filename"])]


def path_to_op(spec, method: str, path: str) -> str | None:
    """컨트롤러 경로(/v1/rooms/{roomId}/cancellation) → OpenAPI operationId. 경로 변수 이름은 달라도 된다."""
    if spec is None:
        return None
    norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p.rstrip("/"))  # noqa: E731
    for oid, op in spec.ops.items():
        if op.method == method and norm(op.path) == norm(path):
            return oid
    return None


# ---- Hermes: 관련 스펙 찾기 · 스펙 점검 (§4.2 1·2단계) ------------------------------------------
FIND_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. dev 로 머지된 PR 하나가 어느 기능·시나리오·요구(PRD 단계)에 닿는지 고른다. "
    "아래 근거만 쓰고, 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```json 코드 블록 하나: {\"scope\": [{\"feature\": 기능 이름, \"scenario\": \"S1\", \"reqs\": [\"R147\", …], \"why\": 한 문장}]}\n"
    "2. feature · scenario · reqs 는 주어진 목록에 있는 것만 쓴다. 목록 밖의 기능은 쓰지 않는다.\n"
    "3. reqs 는 PR 이 동작을 바꾸거나 새로 만든 단계만. 조회·화면 문구만 바뀐 단계는 넣지 않는다.\n"
    "4. PR 이 사용자 기능을 바꾸지 않았으면(로그·인프라·문서) scope 는 빈 목록이다."
)

CHECK_SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 머지된 PR 의 변경과 스펙(PRD 단계·규칙표)을 나란히 읽고, 테스트를 만들기 전에 사람이 정해야 할 것을 찾는다. "
    "아래 근거만 쓰고, 한국어로 쓴다. 확실한 근거가 있는 것만 적는다. 없으면 빈 목록이다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```json 코드 블록 하나: {\"findings\": [{\"kind\": \"mismatch\"|\"ambiguous\", \"title\", \"spec\", \"code\", \"question\", \"suggestion\"}]}\n"
    "2. mismatch 는 스펙과 코드가 다른 것, ambiguous 는 코드가 정한 규칙이 스펙에 없거나 스펙이 두 가지로 읽히는 것이다.\n"
    "3. title 은 해요체 한 문장(예: \"진행 완료와 출석 기록이 나뉘었어요\"). spec 은 「기능」 Sn Rn · 그 문장, code 는 파일 이름이나 결정 기록 id · 요약.\n"
    "4. question 은 사람에게 묻는 한 문장. suggestion 은 추천 답과 이유 한 문장. 팀 원칙: PRD 가 백엔드 코드와 아예 안 맞으면 백엔드 dev 기준으로 PRD·규칙표를 맞춘다. "
    "단 PRD 규칙을 코드가 빠뜨린 것이면 백엔드 결함으로 본다.\n"
    "5. 아래 '플랫폼이 이미 찾은 것' 과 같은 내용은 다시 쓰지 않는다. 최대 8개."
)


def _json_block(text: str) -> dict:
    import json
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S) or [text]
    for b in blocks:
        try:
            d = json.loads(b)
        except ValueError:
            continue
        if isinstance(d, dict):
            return d
    raise ValueError("Hermes 출력에서 JSON 을 찾지 못했다")


def parse_scope(text: str, catalog: dict[str, dict[str, set]]) -> list[dict]:
    """catalog: {기능: {Sn: {R…}}}. 목록 밖 것은 버리고, 같은 시나리오는 합친다."""
    out: dict[tuple, dict] = {}
    for x in _json_block(text).get("scope") or []:
        if not isinstance(x, dict):
            continue
        f, s = str(x.get("feature") or "").strip(), str(x.get("scenario") or "").strip()
        if f not in catalog or s not in catalog[f]:
            continue
        reqs = [r for r in (str(r).strip() for r in x.get("reqs") or []) if r in catalog[f][s]]
        cell = out.setdefault((f, s), {"feature": f, "scenario": s, "reqs": [], "why": str(x.get("why") or "")[:300]})
        cell["reqs"] += [r for r in reqs if r not in cell["reqs"]]
    return list(out.values())


def parse_findings(text: str) -> list[dict]:
    out = []
    for x in (_json_block(text).get("findings") or [])[:8]:
        if not isinstance(x, dict) or x.get("kind") not in ("mismatch", "ambiguous") or not x.get("title"):
            continue
        out.append({k: str(x.get(k) or "")[:600] for k in ("kind", "title", "spec", "code", "question", "suggestion")}
                   | {"source": "hermes", "reqs": [str(r) for r in (x.get("reqs") or []) if re.match(r"^R\d+$", str(r))]})
    return out


def diff_excerpt(files: list[dict], limit: int = 40000, per_file: int = 4000) -> str:
    """Hermes 에게 줄 diff — 컨트롤러·도메인·파사드·요청/응답 먼저, 시험 코드는 뺀다."""
    def rank(f):
        n = f["filename"]
        return (0 if _CONTROLLER.search(n) else 1 if "/domain/" in n or "/facade/" in n else 2 if "/request/" in n or "/response/" in n else 3)
    parts, used = [], 0
    for f in sorted((f for f in files if "/src/test/" not in f["filename"] and f.get("patch")), key=rank):
        chunk = f"--- {f['filename']} ({f.get('status')}, +{f.get('additions')} -{f.get('deletions')})\n{f['patch'][:per_file]}"
        if used + len(chunk) > limit:
            parts.append(f"(이하 {len(files)} 개 중 나머지 생략)")
            break
        parts.append(chunk)
        used += len(chunk)
    return "\n".join(parts)
