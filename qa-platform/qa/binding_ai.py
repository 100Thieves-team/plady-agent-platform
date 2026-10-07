"""API 연결·에러 코드를 AI 가 채운다 (docs/qa-platform-v2.md §16.2-1).

규칙표 명령에 어느 API(operationId)가 해당하는지, 거절 검사가 어떤 에러 코드로 나오는지를 Hermes 가 API 문서에서 찾아 제안하고,
플랫폼이 검증해 `catalog/bindings.yaml` 에 더한다. 정본은 여전히 규칙표(SSOT)와 API 문서이고 이 파일은 둘을 잇는 표다.
API 문서에 그 동작의 끝점이 없으면 `no_api` 에 이유와 함께 적는다 — 그 명령의 케이스는 "백엔드 미구현" 으로 보인다.
"""
from __future__ import annotations

import json
import re
from datetime import date

import yaml

COMMON_CODES = {"E400", "E1102"}       # 어느 API 나 낼 수 있는 코드 — 잘못된 요청·로그인 필요
_OP = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_CODE = re.compile(r"^E\d{3,4}$")

SYSTEM = (
    "너는 Spring 백엔드 팀의 QA 엔지니어다. 규칙표(SSOT)의 명령·거절 검사를 dev API 문서(OpenAPI)의 끝점·에러 코드와 잇는다. "
    "아래 근거만 쓴다. 모르면 비운다. 한국어로 쓴다.\n\n"
    "출력 규칙(어기면 버려진다):\n"
    "1. 출력은 ```json 코드 블록 하나: {\"commands\": {\"C.x\": [\"operationId\", …]}, \"checks\": {\"G.x#key\": \"E1234\"}, \"no_api\": {\"C.x\": \"이유 한 문장\"}}\n"
    "2. commands: 그 명령을 사용자가 일으키는 API 의 operationId. API 목록에 있는 것만. 조회만 하는 명령이면 그 조회 API.\n"
    "3. checks: 그 거절이 나올 때의 에러 코드. 그 명령의 API 가 에러 예시로 가진 코드에서 고른다. 로그인 필요는 E1102, 값 검증 실패는 그 API 의 검증 코드(예: E400, E1402). "
    "예시에서 근거를 못 찾으면 적지 않는다.\n"
    "4. no_api: API 목록을 다 봐도 그 명령을 일으키는 끝점이 없으면 이유와 함께 적는다(예: \"참여자를 내보내는 끝점이 없다\"). 시스템이 스스로 하는 명령(배치·자동 처리)은 적지 않는다.\n"
    "5. 확신이 없으면 어느 칸에도 적지 않는다."
)


def op_codes(op) -> set[str]:
    return {str(c) for c in (getattr(op, "errors", None) or {})}


def assemble(*, commands: list[dict], checks: list[dict], spec) -> tuple[str, str]:
    """commands: [{id, name, actor, source_text}], checks: [{id, command, cond, message}]."""
    import hashlib
    parts = ["# 이을 명령 (지금 API 가 묶여 있지 않다)"]
    parts += [f"- {c['id']} {c.get('name') or ''} · 하는 사람 {c.get('actor') or '-'} · 근거 {c.get('source_text') or '-'}" for c in commands] or ["(없음)"]
    parts.append("# 코드를 찾을 거절 검사 (지금 에러 코드가 없다)")
    parts += [f"- {k['id']} · 명령 {k.get('command') or '-'} · 조건 {k.get('cond') or '-'} · 메시지 {k.get('message') or '-'}" for k in checks] or ["(없음)"]
    parts.append("# dev API 목록 (operationId · 메서드 경로 · 요약 · 에러 예시 코드)")
    for oid, op in sorted((spec.ops if spec else {}).items(), key=lambda x: x[1].path):
        if "/v1/dev/" in op.path:
            continue                       # dev 전용 QA 데이터 API 는 제품 동작이 아니다
        parts.append(f"- {oid} · {op.method} {op.path} · {(op.summary or '')[:80]} · {', '.join(sorted(op_codes(op))) or '-'}")
    parts.append("# 출력\n```json 블록 하나로 commands · checks · no_api.")
    text = "\n".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def parse(text: str) -> dict:
    for b in re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S) or [text]:
        try:
            d = json.loads(b)
        except ValueError:
            continue
        if isinstance(d, dict):
            return d
    raise ValueError("Hermes 출력에서 JSON 을 찾지 못했다")


def validate(out: dict, *, spec, commands: list[dict], checks: list[dict], current: dict) -> tuple[dict, list[str]]:
    """제안 → (받아들인 것 {commands, checks, no_api}, 버린 이유). current 는 지금 bindings(commands: {cmd: [op]})."""
    ops = spec.ops if spec else {}
    want_cmds = {c["id"] for c in commands}
    want_checks = {k["id"]: k for k in checks}
    acc = {"commands": {}, "checks": {}, "no_api": {}}
    why: list[str] = []
    for cmd, v in (out.get("commands") or {}).items():
        vs = [str(x) for x in (v if isinstance(v, list) else [v]) if x]
        if cmd not in want_cmds:
            why.append(f"{cmd}: 이을 명령 목록에 없다")
            continue
        bad = [o for o in vs if not _OP.match(o) or o not in ops or "/v1/dev/" in ops[o].path]
        if bad or not vs:
            why.append(f"{cmd}: API 목록에 없는 operationId {bad or vs}")
            continue
        acc["commands"][cmd] = vs
    bound = {**{k: list(v) for k, v in (current.get("commands") or {}).items()}, **acc["commands"]}
    for rid, code in (out.get("checks") or {}).items():
        code = str(code or "").strip().upper()
        if rid not in want_checks or not code:
            continue
        if not _CODE.match(code):
            why.append(f"{rid}: 코드 형식이 틀렸다 {code}")
            continue
        cmd_ops = bound.get(want_checks[rid].get("command") or "", [])
        allowed = set(COMMON_CODES) | {c for o in cmd_ops if o in ops for c in op_codes(ops[o])}
        if code not in allowed:
            why.append(f"{rid}: {code} 는 그 명령의 API({', '.join(cmd_ops) or '없음'}) 에러 예시에 없다")
            continue
        acc["checks"][rid] = code
    for cmd, reason in (out.get("no_api") or {}).items():
        if cmd in want_cmds and cmd not in acc["commands"] and str(reason or "").strip():
            acc["no_api"][cmd] = str(reason).strip()[:200]
    return acc, why


def apply(text: str | None, acc: dict, *, operator: str = "hermes") -> str:
    """bindings.yaml 본문에 받아들인 것을 더한다. 주석과 기존 줄은 그대로 두고 각 묶음 끝에 붙인다."""
    text = text or "commands:\n\nchecks:\n"
    stamp = f"# Hermes {date.today().isoformat()}"
    lines = text.rstrip("\n").split("\n")
    doc = yaml.safe_load(text) or {}

    def block_end(key: str) -> int | None:
        """최상위 key: 블록의 마지막 내용 줄 다음 위치."""
        start = next((i for i, ln in enumerate(lines) if ln.startswith(f"{key}:")), None)
        if start is None:
            return None
        end = start + 1
        for i in range(start + 1, len(lines)):
            if lines[i] and not lines[i].startswith((" ", "#")):
                break
            if lines[i].startswith("  "):
                end = i + 1
        return end

    def add(key: str, new_lines: list[str]):
        if not new_lines:
            return
        at = block_end(key)
        if at is None:
            lines.extend(["", f"{key}:"] + new_lines)
        else:
            lines[at:at] = new_lines
    have_cmds = doc.get("commands") or {}
    have_checks = doc.get("checks") or {}
    add("commands", [f"  {k}: {v[0] if len(v) == 1 else '[' + ', '.join(v) + ']'}   {stamp}" for k, v in acc.get("commands", {}).items() if k not in have_cmds])
    add("checks", [f'  "{k}": {v}   {stamp}' for k, v in acc.get("checks", {}).items() if k not in have_checks])
    have_no = doc.get("no_api") or {}
    if acc.get("no_api") and not any(ln.startswith("no_api:") for ln in lines):
        lines.extend(["", "# 규칙표 명령인데 dev API 문서에 끝점이 없는 것. 이 명령의 케이스는 '백엔드 미구현' 으로 보인다(docs/qa-platform-v2.md §16).",
                      "# API 가 생기면 commands 로 옮기고 여기서 지운다."])
    add("no_api", [f"  {k}: {json.dumps(v, ensure_ascii=False)}   {stamp}" for k, v in acc.get("no_api", {}).items() if k not in have_no])
    out = "\n".join(lines) + "\n"
    yaml.safe_load(out)
    return out
