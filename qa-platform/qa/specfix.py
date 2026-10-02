"""스펙 확인에서 위키 수정까지 (docs/qa-platform-v2.md §14, 사용자 결정 2026-09-28).

[추천대로]·[다르게]로 정한 항목마다 Hermes 가 PRD·규칙표 수정안을 찾아 바꾸기 목록으로 낸다. 플랫폼이 검증하고 바뀐 줄을
보여 준다. 사람이 [위키에 반영]을 누를 때만 위키에 커밋한다. 다시 점검은 사람이 [위키 고친 뒤 다시 점검]으로 한 번 누른다.

- 고칠 수 있는 파일: scope 기능의 PRD(`raw/product/<기능>.md`)와 그 기능의 규칙표 조각(`wiki/policy/_src/기능/<기능>.yaml`),
  공통·결정 조각. 조립본 `상태-SSOT.yaml` 과 렌더 결과는 고칠 수 없다.
- 반영: PRD 는 `wiki_apply` mode archive, 조각은 `wiki_content_write`(uri `policy/_src/...`) 뒤 `wiki_content_commit`.
- 수정안은 만들 때의 원래 파일(base)과 고친 파일(after)을 같이 저장한다. 반영할 때는 지금 파일에 줄 단위 3-way merge 로
  얹는다. 다른 수정안이 앞뒤 문맥을 바꿔도 같은 줄을 고치지 않았으면 그대로 반영된다. 같은 줄이면 충돌이다.
- PRD 를 고치면 index.yaml meta.기준_문서 의 그 문서 값을 반영 시각으로 올린다. 위키 렌더러는 이 값이 바뀔 때만 요구 문장
  기준을 지금 PRD 로 옮긴다. 안 올리면 위키 CI(policy-drift-check)가 드리프트로 경고한다.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

FIXABLE = {"mismatch", "ambiguous"}
_REQ = re.compile(r"`(R\d+)`")
INDEX = "wiki/policy/_src/index.yaml"
KST = timezone(timedelta(hours=9))

SYSTEM = (
    "너는 기획 문서(PRD)와 상태 규칙표(SSOT)를 관리하는 편집자다. 사람이 정한 결정대로 PRD 와 규칙표를 최소한으로 고친다. "
    "아래 근거만 쓰고 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```json 코드 블록 하나: {\"summary\": 한 줄 요약, \"edits\": [{\"path\": 파일 경로, \"find\": 지금 파일에 있는 원문, \"replace\": 바꿀 글}]}\n"
    "2. path 는 아래에 원문을 준 파일만 쓴다. 파일 전체를 새로 쓰지 않는다. find 는 그 파일에 정확히 한 번 나오는 원문을 공백·줄바꿈까지 그대로 복사한다. "
    "짧게 잡되 한 번만 나오게 앞뒤를 조금 넣는다.\n"
    "3. PRD 의 요구 id(줄 끝 `R63` 같은 것)는 지우지 않는다. 문장을 고쳐도 id 는 그대로 둔다. 새 요구 문장이 필요하면 그 PRD 에서 가장 큰 요구 id 다음 번호를 쓴다.\n"
    "4. PRD 를 고치면 같은 요구를 인용하는 규칙표 조각(source 에 `PRD/<기능> R63` 이 있는 기록)도 결정에 맞게 고친다. 아래 '이 요구를 인용한 규칙표 기록' 목록을 본다. "
    "규칙표만 바꿀 결정이면 규칙표만. index.yaml 의 기준 날짜는 플랫폼이 올리니 고치지 않는다.\n"
    "5. 결정 근거를 남긴다. 고친 PRD 문장 끝(요구 id 앞)에 괄호로 짧게, 규칙표는 note 에 PR 번호·백엔드 결정 id 를 적는다.\n"
    "6. 결정과 상관없는 곳은 고치지 않는다. 확신이 없으면 edits 를 빈 목록으로 두고 summary 에 이유를 쓴다."
)


class SpecFixError(ValueError):
    pass


class Conflict(SpecFixError):
    """두 수정이 같은 줄을 고친다."""


class Blobs:
    """수정안의 원래 파일·고친 파일 본문. sha 로 찾는다 (data_dir/specfix/<sha>.txt)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def put(self, text: str) -> str:
        h = sha(text)
        p = self.root / f"{h}.txt"
        if not p.is_file():
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(p)
        return h

    def get(self, h: str | None) -> str | None:
        p = self.root / f"{h}.txt" if h else None
        return p.read_text(encoding="utf-8") if p and p.is_file() else None


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def uri_of(path: str) -> str:
    """위키 레포 경로 → MCP asset uri. wiki/policy/_src/X.yaml → policy/_src/X.yaml"""
    return path[len("wiki/"):] if path.startswith("wiki/") else path


def part_files(root: Path) -> list[str]:
    """규칙표 조각 파일 전부 (조립본·index 빼고)."""
    src = root / "wiki" / "policy" / "_src"
    fs = sorted(src.glob("기능/*.yaml")) + sorted(src.glob("상태/*.yaml")) + [src / "공통.yaml", src / "결정.yaml"]
    return [str(p.relative_to(root)) for p in fs if p.is_file()]


def records(text: str) -> list[tuple[str, int, int]]:
    """조각 본문의 기록 → [(id, 첫 줄, 끝 줄 다음)]. `- id: X` 줄에서 다음 `- id:` 줄 앞까지."""
    lines = text.splitlines()
    starts = [(i, m.group(1)) for i, ln in enumerate(lines) for m in [re.match(r"\s*- id: (\S+)\s*$", ln)] if m]
    return [(rid, i, starts[k + 1][0] if k + 1 < len(starts) else len(lines)) for k, (i, rid) in enumerate(starts)]


def citing(root: Path, docs: list[str], rids: list[str] | None = None) -> list[dict]:
    """source 에 `PRD/<문서> R<n>` 을 적은 규칙표 기록 → [{doc, req, id, path, lines}]. rids 가 없으면 그 문서의 요구 전부."""
    want = set(rids or [])
    pat = re.compile(r"PRD/(" + "|".join(re.escape(d) for d in docs) + r") (R\d+)(?!\d)") if docs else None
    out, seen = [], set()
    for path in part_files(root) if pat else []:
        text = (root / path).read_text(encoding="utf-8")
        lines = text.splitlines()
        for rec, a, b in records(text):
            for d, r in pat.findall("\n".join(lines[a:b])):
                if (not want or r in want) and (d, r, rec, path) not in seen:
                    seen.add((d, r, rec, path))
                    out.append({"doc": d, "req": r, "id": rec, "path": path, "lines": [a, b]})
    return out


def changed_reqs(before: str, after: str) -> list[str]:
    """PRD 에서 문장이 바뀐 요구 id."""
    def lines(t):
        return {r: ln.strip() for ln in t.splitlines() for r in _REQ.findall(ln)}
    a, b = lines(before), lines(after)
    return sorted((r for r in b if a.get(r) != b[r]), key=lambda r: int(r[1:]))


def doc_of_prd(path: str, index_text: str) -> str | None:
    """raw/product/<slug>.md → index.yaml 기준_문서 의 문서 이름."""
    m = re.match(r"raw/product/(.+)\.md$", path)
    if not m:
        return None
    for d in _baseline_lines(index_text):
        if d.replace(" ", "-") == m.group(1):
            return d
    return None


def _baseline_lines(index_text: str) -> dict[str, int]:
    """index.yaml 의 meta.기준_문서 블록 → {문서: 줄 번호}."""
    lines, out, ind = index_text.splitlines(), {}, None
    for i, ln in enumerate(lines):
        if ind is None:
            m = re.match(r"(\s*)기준_문서:\s*$", ln)
            if m:
                ind = len(m.group(1))
            continue
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if len(ln) - len(ln.lstrip()) <= ind:
            break
        m = re.match(r'\s*"?([^":]+?)"?\s*:', ln)
        if m:
            out[m.group(1)] = i
    return out


def bump_baseline(index_text: str, docs: list[str], now: datetime | None = None) -> str:
    """기준_문서[문서] 를 지금 시각(KST, 분까지)으로. 이미 같은 값이면 초까지 적어 반드시 바뀌게 한다."""
    now = (now or datetime.now(KST)).astimezone(KST)
    lines, at = index_text.splitlines(True), _baseline_lines(index_text)
    for d in docs:
        if d not in at:
            continue
        i = at[d]
        m = re.match(r'(\s*"?[^":]+?"?\s*:\s*)(.*?)(\r?\n?)$', lines[i])
        old = m.group(2).strip().strip('"')
        new = now.strftime("%Y-%m-%d %H:%M")
        if new == old:
            new = now.strftime("%Y-%m-%d %H:%M:%S")
        lines[i] = f'{m.group(1)}"{new}"{m.group(3)}'
    return "".join(lines)


def allowed_paths(root: Path, docs: list[str], extra: list[str] | None = None) -> list[str]:
    """이 항목에서 고칠 수 있는 파일 (있는 것만). extra 는 바뀌는 요구를 인용한 기록이 있는 조각."""
    out = []
    for d in docs:
        slug = d.replace(" ", "-")
        for p in (f"raw/product/{slug}.md", f"wiki/policy/_src/기능/{slug}.yaml"):
            if (root / p).is_file() and p not in out:
                out.append(p)
    for p in ["wiki/policy/_src/공통.yaml", "wiki/policy/_src/결정.yaml", *(extra or [])]:
        if (root / p).is_file() and p not in out:
            out.append(p)
    return out


def docs_of(finding: dict, scope_features: list[str]) -> list[str]:
    """항목의 스펙 문장에 나온 「기능」, 없으면 이번 범위 기능 전부."""
    named = [m for m in re.findall(r"「([^」]+)」", finding.get("spec") or "") if m in scope_features]
    return list(dict.fromkeys(named)) or scope_features


def finding_reqs(finding: dict) -> list[str]:
    rs = [str(r) for r in finding.get("reqs") or []] + re.findall(r"\bR\d+\b", " ".join(str(finding.get(k) or "") for k in ("spec", "title", "question")))
    return list(dict.fromkeys(rs))


def assemble(*, finding: dict, pr: dict, root: Path, paths: list[str], cited: list[dict] | None = None) -> str:
    how = finding.get("resolution")
    decision = (f"추천대로: {finding.get('suggestion')}" if how == "recommended"
                else f"다르게 정함: {finding.get('note')} (추천은 '{finding.get('suggestion')}' 였다)")
    parts = [f"# PR #{pr.get('number')} {pr.get('title') or ''}",
             "# 스펙 확인 항목", json.dumps({k: finding.get(k) for k in ("kind", "title", "spec", "code", "question", "reqs")}, ensure_ascii=False, indent=1),
             "# 사람이 정한 것", decision, f"(정한 사람 {finding.get('resolved_by')})"]
    if cited:
        parts.append("# 이 요구를 인용한 규칙표 기록 (PRD 문장을 고치면 이 기록도 새 문장에 맞는지 보고 고친다)\n"
                     + "\n".join(f"- {c['doc']} {c['req']} ← {c['id']} ({c['path']})" for c in cited))
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


def propose(*, finding: dict, pr: dict, root: Path, scope_features: list[str], ask, blobs: Blobs | None = None) -> dict:
    """수정안 하나 → {summary, edits, files: [{path, diff}], base: {path: sha}, after: {path: sha}, cited}. 검증에 막히면 오류를 붙여 한 번 다시 묻는다.
    blobs 가 있으면 바뀐 파일의 원래 본문과 고친 본문을 저장해 반영 때 3-way merge 에 쓴다."""
    docs = docs_of(finding, scope_features)
    cited = citing(root, docs, finding_reqs(finding))
    paths = allowed_paths(root, docs, [c["path"] for c in cited])
    if not paths:
        raise SpecFixError("고칠 PRD·규칙표 파일을 찾지 못했다")
    before = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    prompt = assemble(finding=finding, pr=pr, root=root, paths=paths, cited=cited)
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
    changed = [p for p in paths if after[p] != before[p]]
    files = [{"path": p, "diff": diff(p, before[p], after[p])} for p in changed]
    res = {"summary": out["summary"], "edits": out["edits"], "files": files, "base": {p: sha(before[p]) for p in changed},
           "cited": prd_cited(root, before, after)}
    if blobs:
        res["base"] = {p: blobs.put(before[p]) for p in changed}
        res["after"] = {p: blobs.put(after[p]) for p in changed}
    return res


def prd_cited(root: Path, before: dict[str, str], after: dict[str, str]) -> list[dict]:
    """고친 PRD 에서 문장이 바뀐 요구와 그 요구를 인용한 규칙표 기록. 기록이 있는 파일을 이번 수정안이 고쳤는지도 적는다."""
    index = (root / INDEX).read_text(encoding="utf-8") if (root / INDEX).is_file() else ""
    out = []
    for p in after:
        if p.endswith(".md") and after[p] != before.get(p):
            d = doc_of_prd(p, index) or p
            reqs = changed_reqs(before.get(p, ""), after[p])
            rows = citing(root, [d], reqs) if reqs else []
            for r in reqs:
                out.append({"doc": d, "req": r, "records": [{"id": c["id"], "path": c["path"], "edited": _touched(before, after, c)}
                                                          for c in rows if c["req"] == r]})
    return out


def _touched(before: dict[str, str], after: dict[str, str], rec: dict) -> bool:
    """수정안이 그 기록의 줄을 고쳤는가."""
    p = rec["path"]
    if p not in after or after[p] == before.get(p):
        return False
    a, b = rec["lines"]
    return any(i1 < b and max(i2, i1 + 1) > a for i1, i2, _ in _hunks(before[p].splitlines(True), after[p].splitlines(True)))


# ---- 반영: 줄 단위 3-way merge ----------------------------------------------------------

def _hunks(base: list[str], other: list[str]) -> list[tuple[int, int, list[str]]]:
    sm = difflib.SequenceMatcher(None, base, other, autojunk=False)
    return [(i1, i2, other[j1:j2]) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal"]


def merge3(base: str, ours: str, theirs: str, path: str = "") -> str:
    """base 에서 ours(지금 파일)와 theirs(수정안)로 갈라진 두 변경을 합친다. 같은 줄을 서로 다르게 고쳤으면 Conflict.
    붙어 있는 줄을 따로 고친 것은 충돌이 아니다."""
    if ours == base or theirs == ours:
        return theirs
    if theirs == base:
        return ours
    B = base.splitlines(True)
    hs = sorted([(*h, 0) for h in _hunks(B, ours.splitlines(True))] + [(*h, 1) for h in _hunks(B, theirs.splitlines(True))],
                key=lambda h: (h[0], h[1], h[3]))
    take: list[tuple[int, int, list[str], int]] = []
    for h in hs:
        i1, i2, lines, side = h
        clash = None
        for t in take:
            if t[3] == side:
                continue
            j1, j2 = t[0], t[1]
            same_point = i1 == i2 == j1 == j2
            if same_point or max(i1, j1) < min(i2, j2) or (i1 == i2 and j1 < i1 < j2) or (j1 == j2 and i1 < j1 < i2):
                clash = t
                break
        if clash:
            if (clash[0], clash[1], clash[2]) == (i1, i2, lines):
                continue                                                              # 둘이 똑같이 고쳤다
            raise Conflict(f"{path} {i1 + 1}번째 줄 근처를 지금 위키와 이 수정안이 서로 다르게 고친다")
        take.append(h)
    out, pos = [], 0
    for i1, i2, lines, _ in sorted(take, key=lambda h: (h[0], h[1])):
        out += B[pos:i1] + lines
        pos = max(pos, i2)
    return "".join(out + B[pos:])


def _rebased(pr: dict, cur: dict[str, str], blobs: Blobs | None) -> dict[str, str]:
    """수정안 하나를 지금 파일(cur)에 얹은 결과 {path: text}. base·after 가 없는 옛 수정안은 찾아 바꾸기로."""
    after_sha = pr.get("after") or {}
    if blobs and after_sha:
        out = {}
        for p, h in after_sha.items():
            base, theirs = blobs.get((pr.get("base") or {}).get(p)), blobs.get(h)
            if base is None or theirs is None:
                raise Conflict(f"{p}: 수정안의 원래 파일을 찾지 못했다")
            out[p] = merge3(base, cur[p], theirs, p)
        return out
    paths = list(dict.fromkeys(e["path"] for e in pr.get("edits") or []))
    try:
        new = apply_edits({p: cur[p] for p in paths}, pr.get("edits") or [], paths)
    except SpecFixError as ex:
        raise Conflict(str(ex))
    return new


def _paths(pr: dict) -> list[str]:
    return list(dict.fromkeys([*(pr.get("after") or {}), *(e["path"] for e in pr.get("edits") or [])]))


def combine(root: Path, proposals: list[dict], blobs: Blobs | None = None, *, now: datetime | None = None
            ) -> tuple[dict[str, str], dict[str, str], dict[int, str]]:
    """반영할 수정안들을 지금 위키 파일에 차례로 3-way merge → (before, after, 충돌 {순번: 이유}).
    충돌한 수정안은 빼고 나머지만 합친다. PRD 가 바뀌면 index.yaml 기준 날짜를 올린다. 합친 결과가 검증을 못 넘기면 SpecFixError."""
    paths = list(dict.fromkeys(p for pr in proposals for p in _paths(pr)))
    before = {p: (root / p).read_text(encoding="utf-8") for p in paths}
    after, conflicts = dict(before), {}
    for i, pr in enumerate(proposals):
        try:
            after.update(_rebased(pr, after, blobs))
        except Conflict as ex:
            conflicts[i] = str(ex)
    docs = []
    if (root / INDEX).is_file():
        index = (root / INDEX).read_text(encoding="utf-8")
        docs = [d for p in after if p.endswith(".md") and after[p] != before[p] for d in [doc_of_prd(p, index)] if d]
        if docs:
            before.setdefault(INDEX, index)
            after[INDEX] = bump_baseline(after.get(INDEX, index), docs, now)
    validate(root, before, after)
    return before, after, conflicts


def rebase(pr: dict, cur: dict[str, str], blobs: Blobs) -> dict:
    """다른 수정안을 반영한 뒤 대기 중 수정안을 지금 파일 기준으로 다시 계산 — base 를 지금 파일로, 바뀐 줄 비교도 새로. 같은 줄이면 Conflict."""
    new = _rebased(pr, cur, blobs)
    changed = [p for p in new if new[p] != cur[p]]
    return {**pr, "files": [{"path": p, "diff": diff(p, cur[p], new[p])} for p in changed],
            "base": {p: blobs.put(cur[p]) for p in changed}, "after": {p: blobs.put(new[p]) for p in changed}}
