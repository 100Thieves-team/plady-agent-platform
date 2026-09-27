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
             "error": "멈춤", "canceled": "그만둠", "interrupted": "멈춤"}
STATUS_BADGE = {"queued": "running", "running": "running", "needs_spec": "need", "passed": "pass", "failed": "fail",
                "error": "fail", "canceled": "none", "interrupted": "none"}
KIND_KO = {"mismatch": "스펙과 코드가 달라요", "ambiguous": "스펙이 모호해요", "missing_api": "없어진 API 를 써요",
           "undocumented_api": "API 문서에 없어요", "no_rules": "규칙표가 없어요", "impact": "영향"}
BLOCKING = {"mismatch", "ambiguous", "missing_api", "undocumented_api"}      # 사람이 정해야 넘어가는 종류

_CONTROLLER = re.compile(r"/controller/(v1/)?[A-Za-z]+Controller\.kt$")
_MAPPING = re.compile(r'^([+-])\s*@(Get|Post|Put|Patch|Delete)Mapping\(\s*(?:value\s*=\s*)?"([^"]+)"')
_WORKLOG = re.compile(r"(^|/)\.worklog/.+/decisions\.md$")


def summarize(files: list[dict]) -> dict:
    """PR 변경 파일 → {changed_files, additions, deletions, api, domains}. api 는 컨트롤러가 바뀌었는가(§4.4)."""
    names = [f["filename"] for f in files]
    return {"changed_files": len(files), "additions": sum(f.get("additions") or 0 for f in files),
            "deletions": sum(f.get("deletions") or 0 for f in files),
            "api": any(_CONTROLLER.search(n) for n in names), "domains": sorted(domains_from_files(names))}


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
