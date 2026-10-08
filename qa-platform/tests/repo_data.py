"""레포의 스크립트 중 Hermes 가 쓴 것 (written_by: hermes). 운영 플랫폼이 main 에 계속 더하므로,
레포 데이터를 그대로 읽는 시험은 사람이 쓴 시드 스크립트만 본다 (2026-10-08 한꺼번에 만들기로 98건이 들어왔다)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def hermes_case_ids(root: Path = ROOT) -> set[str]:
    out = set()
    for p in (root / "cases").glob("*.yaml"):
        for c in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("cases") or []:
            if isinstance(c, dict) and c.get("written_by") == "hermes":
                out.add(str(c.get("id")))
    return out


def drop_hermes(app) -> None:
    """App 이 읽은 스크립트에서 Hermes 가 쓴 것을 뺀다."""
    hid = hermes_case_ids()
    app.cases = {k: v for k, v in app.cases.items() if k not in hid}
