"""스크립트 안의 `{{…}}` 치환. docs/qa-platform.md §8.

지원:
  {{name}}                  save 로 저장된 변수
  {{actor.X.memberId}}      테스트 계정 X 의 회원 UUID
  {{fixture.key}}           환경 픽스처 (키에 점이 있어도 정확히 일치하는 키를 먼저 본다)
  {{date:+N}} / {{date:-N}} 오늘(KST) 기준 N 일 뒤/전 ISO 날짜
  {{uuid}} / {{rand}}       임의값
  {{time:rand}}             09:00~20:50 사이 10분 단위 임의 시각(HH:MM). 룸 생성은 (방장, 공고, 직무, 시작 시각)이 같으면
                            새로 만들지 않고 있던 룸을 돌려주므로, 남은 룸과 겹치지 않게 시각을 흩는다 (2026-09-25)
문자열 전체가 하나의 치환이면 값의 타입(int 등)을 유지한다.
"""
from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_FULL = re.compile(r"^\{\{\s*([^{}]+?)\s*\}\}$")
_PART = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


class TemplateError(KeyError):
    """치환할 값이 없다. `kind` 가 actor/fixture 면 설정 부재(스크립트 skip 사유)다."""

    def __init__(self, expr: str, kind: str = "var"):
        super().__init__(expr)
        self.expr = expr
        self.kind = kind

    def __str__(self) -> str:
        return f"치환할 값이 없다: {{{{{self.expr}}}}}"


class Context:
    def __init__(self, actors: dict | None = None, fixtures: dict | None = None, variables: dict | None = None,
                 today: datetime | None = None):
        self.actors = actors or {}
        self.fixtures = fixtures or {}
        self.vars = dict(variables or {})
        self.today = today

    def resolve(self, expr: str):
        expr = expr.strip()
        if expr == "uuid":
            return str(uuid.uuid4())
        if expr == "rand":
            return secrets.token_hex(3)
        if expr == "time:rand":
            n = secrets.randbelow(72)                       # 09:00 부터 10분씩 72칸
            return f"{9 + n // 6:02d}:{(n % 6) * 10:02d}"
        if expr.startswith("date:"):
            offset = expr[5:].strip() or "0"
            try:
                days = int(offset)
            except ValueError:
                raise TemplateError(expr) from None
            base = self.today or datetime.now(KST)
            return (base + timedelta(days=days)).date().isoformat()
        if expr.startswith("actor."):
            parts = expr.split(".")
            if len(parts) != 3 or parts[2] != "memberId" or parts[1] not in self.actors:
                raise TemplateError(expr, "actor")
            return self.actors[parts[1]]
        if expr.startswith("fixture."):
            key = expr[len("fixture."):]
            if key in self.fixtures:
                return self.fixtures[key]
            cur = self.fixtures
            for p in key.split("."):
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    raise TemplateError(expr, "fixture")
            return cur
        if expr in self.vars:
            return self.vars[expr]
        raise TemplateError(expr)

    def render(self, value):
        if isinstance(value, str):
            m = _FULL.match(value)
            if m:
                return self.resolve(m.group(1))
            return _PART.sub(lambda mm: str(self.resolve(mm.group(1))), value)
        if isinstance(value, dict):
            return {k: self.render(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.render(v) for v in value]
        return value


_IDX = re.compile(r"^([^\[\]]*)((?:\[\d+\])*)$")


def get_path(obj, path: str):
    """`data.rooms[0].roomId` 같은 경로로 값을 꺼낸다. 없으면 None."""
    cur = obj
    for seg in path.split("."):
        if seg == "":
            continue
        m = _IDX.match(seg)
        if not m:
            return None
        key, idx = m.group(1), m.group(2)
        if key:
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                return None
        for n in re.findall(r"\[(\d+)\]", idx):
            i = int(n)
            if isinstance(cur, list) and i < len(cur):
                cur = cur[i]
            else:
                return None
    return cur
