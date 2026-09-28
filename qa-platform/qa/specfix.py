"""스펙 확인에서 위키 수정까지 (docs/qa-platform-v2.md §14, 사용자 결정 2026-09-28).

[추천대로]·[다르게]로 정한 항목마다 Hermes 가 PRD·규칙표 수정안을 찾아 바꾸기 목록으로 낸다. 플랫폼이 검증하고 바뀐 줄을
보여 준다. 사람이 [위키에 반영]을 누를 때만 위키에 커밋한다. 다시 점검은 사람이 [위키 고친 뒤 다시 점검]으로 한 번 누른다.

- 고칠 수 있는 파일: scope 기능의 PRD(`raw/product/<기능>.md`)와 그 기능의 규칙표 조각(`wiki/policy/_src/기능/<기능>.yaml`),
  공통·결정 조각. 조립본 `상태-SSOT.yaml` 과 렌더 결과는 고칠 수 없다.
- 반영: PRD 는 `wiki_apply` mode archive, 조각은 `wiki_content_write`(uri `policy/_src/...`) 뒤 `wiki_content_commit`.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

FIXABLE = {"mismatch", "ambiguous"}
_REQ = re.compile(r"`(R\d+)`")

SYSTEM = (
    "너는 기획 문서(PRD)와 상태 규칙표(SSOT)를 관리하는 편집자다. 사람이 정한 결정대로 PRD 와 규칙표를 최소한으로 고친다. "
    "아래 근거만 쓰고 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```json 코드 블록 하나: {\"summary\": 한 줄 요약, \"edits\": [{\"path\": 파일 경로, \"find\": 지금 파일에 있는 원문, \"replace\": 바꿀 글}]}\n"
    "2. path 는 아래에 원문을 준 파일만 쓴다. 파일 전체를 새로 쓰지 않는다. find 는 그 파일에 정확히 한 번 나오는 원문을 공백·줄바꿈까지 그대로 복사한다. "
    "짧게 잡되 한 번만 나오게 앞뒤를 조금 넣는다.\n"
    "3. PRD 의 요구 id(줄 끝 `R63` 같은 것)는 지우지 않는다. 문장을 고쳐도 id 는 그대로 둔다. 새 요구 문장이 필요하면 그 PRD 에서 가장 큰 요구 id 다음 번호를 쓴다.\n"
    "4. PRD 를 고치면 같은 요구를 인용하는 규칙표 조각(source 에 `PRD/<기능> R63` 이 있는 기록)도 결정에 맞게 고친다. 규칙표만 바꿀 결정이면 규칙표만.\n"
    "5. 결정 근거를 남긴다. 고친 PRD 문장 끝(요구 id 앞)에 괄호로 짧게, 규칙표는 note 에 PR 번호·백엔드 결정 id 를 적는다.\n"
    "6. 결정과 상관없는 곳은 고치지 않는다. 확신이 없으면 edits 를 빈 목록으로 두고 summary 에 이유를 쓴다."
)


class SpecFixError(ValueError):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def uri_of(path: str) -> str:
    """위키 레포 경로 → MCP asset uri. wiki/policy/_src/X.yaml → policy/_src/X.yaml"""
    return path[len("wiki/"):] if path.startswith("wiki/") else path


def allowed_paths(root: Path, docs: list[str]) -> list[str]:
    """이 항목에서 고칠 수 있는 파일 (있는 것만)."""
    out = []
    for d in docs:
        slug = d.replace(" ", "-")
        for p in (f"raw/product/{slug}.md", f"wiki/policy/_src/기능/{slug}.yaml"):
            if (root / p).is_file() and p not in out:
                out.append(p)
    for p in ("wiki/policy/_src/공통.yaml", "wiki/policy/_src/결정.yaml"):
        if (root / p).is_file():
            out.append(p)
    return out


def docs_of(finding: dict, scope_features: list[str]) -> list[str]:
    """항목의 스펙 문장에 나온 「기능」, 없으면 이번 범위 기능 전부."""
    named = [m for m in re.findall(r"「([^」]+)」", finding.get("spec") or "") if m in scope_features]
    return list(dict.fromkeys(named)) or scope_features


def assemble(*, finding: dict, pr: dict, root: Path, paths: list[str]) -> str:
    how = finding.get("resolution")
    decision = (f"추천대로: {finding.get('suggestion')}" if how == "recommended"
                else f"다르게 정함: {finding.get('note')} (추천은 '{finding.get('suggestion')}' 였다)")
    parts = [f"# PR #{pr.get('number')} {pr.get('title') or ''}",
             "# 스펙 확인 항목", json.dumps({k: finding.get(k) for k in ("kind", "title", "spec", "code", "question", "reqs")}, ensure_ascii=False, indent=1),
             "# 사람이 정한 것", decision, f"(정한 사람 {finding.get('resolved_by')})"]
    for p in paths:
        parts.append(f"# 파일 {p}\n```\n{(root / p).read_text(encoding='utf-8')}\n```")
    parts.append("# 출력\n```json 블록 하나로 summary 와 edits.")
    return "\n\n".join(parts)


def parse(text: str) -> dict:
    for b in re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S) or [text]:
        try:
            d = json.loads(b)
        except ValueError:
            continue
        if isinstance(d, dict) and isinstance(d.get("edits"), list):
            return {"summary": str(d.get("summary") or "")[:300],
                    "edits": [{"path": str(e.get("path") or ""), "find": str(e.get("find") or ""), "replace": str(e.get("replace") or "")}
                              for e in d["edits"] if isinstance(e, dict)]}
    raise SpecFixError("Hermes 출력에서 수정안 JSON 을 찾지 못했다")


def apply_edits(texts: dict[str, str], edits: list[dict], allowed: list[str]) -> dict[str, str]:
    """edits 를 차례로 적용한 새 텍스트. find 가 정확히 한 번 있어야 한다."""
    out = dict(texts)
    for i, e in enumerate(edits, 1):
        p = e["path"]
        if p not in allowed:
            raise SpecFixError(f"{i}번째 수정: 고칠 수 없는 파일이다 ({p})")
        if not e["find"]:
            raise SpecFixError(f"{i}번째 수정: find 가 비었다")
        n = out[p].count(e["find"])
        if n != 1:
            raise SpecFixError(f"{i}번째 수정: {p} 에서 find 가 {n}번 나온다 — 정확히 한 번이어야 한다")
        out[p] = out[p].replace(e["find"], e["replace"], 1)
    return out


def validate(root: Path, before: dict[str, str], after: dict[str, str]) -> None:
    """요구 id 를 지우지 않았는가, 조각이 yaml 이고 조립 검사를 통과하는가."""
    for p, new in after.items():
        if new == before[p]:
            continue
        if p.endswith(".md"):
            gone = sorted(set(_REQ.findall(before[p])) - set(_REQ.findall(new)), key=lambda r: int(r[1:]))
            if gone:
                raise SpecFixError(f"{p}: 요구 id {', '.join(gone)} 가 사라진다 — 요구 id 는 지우지 않는다")
        else:
            try:
                yaml.safe_load(new)
            except yaml.YAMLError as ex:
                raise SpecFixError(f"{p}: yaml 이 깨진다 — {str(ex).splitlines()[0]}")
    if not any(p.endswith(".yaml") and after[p] != before[p] for p in after):
        return
    tool = root / "tools" / "policy-renderer" / "ssot_load.py"
    if not tool.is_file():
        return
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "_src"
        shutil.copytree(root / "wiki" / "policy" / "_src", src)
        for p, new in after.items():
            if p.startswith("wiki/policy/_src/"):
                (src / p[len("wiki/policy/_src/"):]).write_text(new, encoding="utf-8")
        for cmd in ("assemble", "check"):
            r = subprocess.run([sys.executable, str(tool), cmd, str(src)], capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise SpecFixError(f"규칙표 조립 검사({cmd})를 못 넘긴다 — {(r.stdout + r.stderr).strip()[-400:]}")


def diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), fromfile=path, tofile=path, n=2))


def propose(*, finding: dict, pr: dict, root: Path, scope_features: list[str], ask) -> dict:
    """수정안 하나 → {summary, edits, files: [{path, diff}], base: {path: sha}}. 검증에 막히면 오류를 붙여 한 번 다시 묻는다."""
    paths = allowed_paths(root, docs_of(finding, scope_features))
    if not paths:
        raise SpecFixError("고칠 PRD·규칙표 파일을 찾지 못했다")
    before = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    prompt = assemble(finding=finding, pr=pr, root=root, paths=paths)
    text, err = ask(SYSTEM, prompt, "qa-specfix"), None
    for attempt in (0, 1):
        try:
            out = parse(text)
            after = apply_edits(before, out["edits"], paths)
            validate(root, before, after)
            err = None
            break
        except SpecFixError as ex:
            err = str(ex)
            if attempt == 0:
                text = ask(SYSTEM, prompt + f"\n\n# 앞 출력이 검증에서 막혔다. 고쳐서 다시 낸다\n- {err}\n\n# 앞 출력\n{text[:12000]}", "qa-specfix")
    if err:
        raise SpecFixError(err)
    files = [{"path": p, "diff": diff(p, before[p], after[p])} for p in paths if after[p] != before[p]]
    return {"summary": out["summary"], "edits": out["edits"], "files": files, "base": {p: sha(before[p]) for p in paths}}


def combine(root: Path, proposals: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """반영할 수정안들을 지금 위키 파일에 차례로 적용 → (before, after). 그사이 바뀌어 find 가 안 맞으면 SpecFixError."""
    paths = list(dict.fromkeys(e["path"] for pr in proposals for e in pr["edits"]))
    before = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    after = dict(before)
    for pr in proposals:
        try:
            after = apply_edits(after, pr["edits"], paths)
        except SpecFixError as ex:
            raise SpecFixError(f"「{pr.get('summary') or '수정안'}」 을 지금 위키에 적용할 수 없다 — 그사이 파일이 바뀌었다. [다시 만들기]를 눌러 주세요 ({ex})")
    validate(root, before, after)
    return before, after
