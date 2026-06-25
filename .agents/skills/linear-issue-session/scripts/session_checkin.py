#!/usr/bin/env python3
"""Create a local Codex Workpad update draft for a Linear issue session.

This script is safe for Stop/SessionEnd hooks: it performs no network calls and
never writes to Linear. It only writes a markdown draft under _workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ISSUE_RE = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")

SAFE_ENV_KEYS = {
    "LINEAR_ISSUE_KEY",
    "PLADY_ROOT",
    "PLADY_LINEAR_ISSUE",
    "CURRENT_LINEAR_ISSUE",
    "JEAN_MCP_SESSION",
    "JEAN_SESSION_ID",
    "JEAN_WORKTREE_ID",
    "JEAN_WORKTREE_PATH",
    "JEAN_WORKTREE_NAME",
    "JEAN_PROJECT_ID",
    "JEAN_PROJECT_PATH",
    "JEAN_PROJECT_NAME",
    "JEAN_BACKEND",
    "JEAN_EXECUTION_MODE",
    "WORKTREE_ID",
    "WORKTREE_PATH",
    "WORKTREE_NAME",
    "BRANCH_NAME",
    "GIT_BRANCH",
}
SAFE_ENV_PREFIXES = ("JEAN_",)
UNSAFE_ENV_PARTS = ("TOKEN", "SECRET", "PASSWORD", "COOKIE", "PRIVATE", "API_KEY", "AUTH")
SAFE_PAYLOAD_KEYS = {
    "sessionid",
    "session",
    "worktreeid",
    "worktree",
    "worktreepath",
    "projectid",
    "projectpath",
    "projectname",
    "cwd",
    "workspace",
    "projectroot",
    "root",
    "backend",
    "executionmode",
}


def run_git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def find_git_root(path: Path) -> Path | None:
    top_level = run_git(path, "rev-parse", "--show-toplevel")
    return Path(top_level).expanduser().resolve() if top_level else None


def find_issue_key(value: str | None) -> str | None:
    if not value:
        return None
    match = ISSUE_RE.search(value)
    return match.group(1) if match else None


def walk_values(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for value in obj.values():
            yield from walk_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_values(value)


def read_hook_payload() -> tuple[str, dict[str, Any] | None]:
    if sys.stdin.isatty():
        return "", None
    raw = sys.stdin.read()
    if not raw.strip():
        return raw, None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw, None
    return raw, parsed if isinstance(parsed, dict) else {"payload": parsed}


def safe_env_value(key: str, value: str | None) -> str | None:
    if not value:
        return None
    if key not in SAFE_ENV_KEYS and not key.startswith(SAFE_ENV_PREFIXES):
        return None
    if key not in SAFE_ENV_KEYS and any(part in key for part in UNSAFE_ENV_PARTS):
        return None
    clean = value.strip()
    if not clean:
        return None
    return clean if len(clean) <= 300 else clean[:297] + "..."


def collect_env_metadata() -> dict[str, str]:
    metadata: dict[str, str] = {}
    for key, value in os.environ.items():
        safe = safe_env_value(key, value)
        if safe is not None:
            metadata[key] = safe
    return dict(sorted(metadata.items()))


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def collect_payload_metadata(payload: dict[str, Any] | None) -> dict[str, str]:
    metadata: dict[str, str] = {}

    def visit(obj: Any, path: str = "payload") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                next_path = f"{path}.{key}"
                if normalize_key(key) in SAFE_PAYLOAD_KEYS and isinstance(value, (str, int, float, bool)):
                    text = str(value).strip()
                    if text:
                        metadata[next_path] = text if len(text) <= 300 else text[:297] + "..."
                visit(value, next_path)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                visit(value, f"{path}[{index}]")

    visit(payload)
    return dict(sorted(metadata.items()))


def infer_root(cli_root: str | None, payload: dict[str, Any] | None) -> Path:
    if cli_root:
        path = Path(cli_root).expanduser().resolve()
        return find_git_root(path) or path

    candidates: list[str] = []
    if payload:
        for key in ("cwd", "workspace", "projectRoot", "root", "worktreePath", "projectPath"):
            value = payload.get(key)
            if isinstance(value, str):
                candidates.append(value)

    for key in ("PLADY_ROOT", "JEAN_WORKTREE_PATH", "JEAN_PROJECT_PATH", "WORKTREE_PATH", "PROJECT_ROOT", "PWD"):
        value = os.environ.get(key)
        if value:
            candidates.append(value)

    candidates.append(os.getcwd())

    for candidate in candidates:
        path = Path(candidate).expanduser().resolve()
        git_root = find_git_root(path)
        if git_root:
            return git_root
        if (path / ".git").exists() or (path / ".agents").exists():
            return path

    cwd = Path.cwd().resolve()
    return find_git_root(cwd) or cwd


def infer_issue(args: argparse.Namespace, root: Path, payload: dict[str, Any] | None) -> str | None:
    env_candidates = (
        "LINEAR_ISSUE_KEY",
        "PLADY_LINEAR_ISSUE",
        "CURRENT_LINEAR_ISSUE",
        "JEAN_ISSUE",
        "JEAN_LINEAR_ISSUE",
        "JEAN_WORKTREE_NAME",
        "JEAN_BRANCH_NAME",
        "WORKTREE_NAME",
        "BRANCH_NAME",
        "GIT_BRANCH",
    )
    for candidate in (args.issue, *(os.environ.get(key) for key in env_candidates)):
        issue = find_issue_key(candidate)
        if issue:
            return issue

    branch = run_git(root, "branch", "--show-current")
    issue = find_issue_key(branch)
    if issue:
        return issue

    for text in (str(root), os.getcwd()):
        issue = find_issue_key(text)
        if issue:
            return issue

    for value in collect_env_metadata().values():
        issue = find_issue_key(value)
        if issue:
            return issue

    if payload:
        for value in walk_values(payload):
            issue = find_issue_key(value)
            if issue:
                return issue

    return None


def status_snapshot(root: Path) -> tuple[str, str, str]:
    branch = run_git(root, "branch", "--show-current") or "(unknown)"
    status = run_git(root, "status", "--short") or "(clean or unavailable)"
    changed = run_git(root, "diff", "--name-only") or "(none or unavailable)"
    return branch, status, changed


def format_metadata(metadata: dict[str, str]) -> str:
    if not metadata:
        return "- (none detected)"
    return "\n".join(f"- {key}: `{value}`" for key, value in metadata.items())


def write_draft(root: Path, issue: str, payload_raw: str, payload: dict[str, Any] | None) -> Path:
    branch, status, changed = status_snapshot(root)
    env_metadata = collect_env_metadata()
    payload_metadata = collect_payload_metadata(payload)
    output_dir = root / "_workspace" / "linear-checkins"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"{issue}-{stamp}.md"

    jean_lines = []
    for label, keys in (
        ("Jean session", ("JEAN_MCP_SESSION", "JEAN_SESSION_ID")),
        ("Jean worktree", ("JEAN_WORKTREE_ID", "JEAN_WORKTREE_NAME", "JEAN_WORKTREE_PATH")),
        ("Jean project", ("JEAN_PROJECT_ID", "JEAN_PROJECT_NAME", "JEAN_PROJECT_PATH")),
        ("Execution mode", ("JEAN_EXECUTION_MODE",)),
    ):
        values = [env_metadata[key] for key in keys if key in env_metadata]
        if values:
            jean_lines.append(f"{label}: {' | '.join(values)}")
    jean_stamp = "\n".join(jean_lines) if jean_lines else "Jean: n/a"

    content = f"""# Codex Workpad Update Draft

Issue: {issue}
Generated at: {stamp}
Branch: `{branch}`
Repo root: `{root}`

## How to apply
- Open the Linear issue and find the active `## Codex Workpad` comment.
- Merge the proposed sections below into that single comment; do not post a separate progress comment unless editing the Workpad is unavailable.
- Replace TODO items with factual session results before writing to Linear.

## Proposed Workpad Content

````markdown
## Codex Workpad
```text
{jean_stamp}
Workspace: {root}
Branch: {branch}
Updated: {stamp}
```

### Plan
- [ ] TODO: reconcile existing plan items against this session.
- [ ] TODO: mark completed items only when backed by code, tests, docs, PR, or Linear evidence.

### Acceptance Criteria
- [ ] TODO: mirror issue acceptance criteria and mark only verified criteria.

### Validation
- [ ] TODO: record each command/manual check and result.

### Notes
- Generated local Workpad draft from Stop/SessionEnd hook.
- Changed files snapshot:

```text
{changed}
```

- Git status snapshot:

```text
{status}
```

### Confusions
- None recorded by hook. Replace this if the session was blocked or ambiguous.
````

## Safe Jean / Session Metadata
Environment:
{format_metadata(env_metadata)}

Hook payload:
{format_metadata(payload_metadata)}
"""

    if payload_raw.strip():
        content += "\n## Hook Payload Note\nHook payload was present. Only safe metadata fields were copied above. Inspect session logs if more context is needed before applying the Workpad update.\n"

    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root. Defaults to hook payload cwd, Jean worktree path, or current directory.")
    parser.add_argument("--issue", help="Linear issue key, e.g. PLA-123.")
    parser.add_argument("--from-hook", action="store_true", help="Mark invocation as hook-driven.")
    args = parser.parse_args()

    payload_raw, payload = read_hook_payload()
    root = infer_root(args.root, payload)
    issue = infer_issue(args, root, payload)

    if not issue:
        print("linear Workpad draft: no Linear issue key found; no-op")
        return 0

    draft = write_draft(root, issue, payload_raw, payload)
    print(f"linear Workpad update draft: {draft}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
