"""환경 변수 → 설정. 이름 계약은 docs/qa-platform.md §10.2.

비밀값(QA_ACTORS 의 회원 UUID, 토큰)은 절대 로그에 남기지 않는다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _json_env(env, name: str) -> dict:
    raw = (env.get(name) or "").strip()
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"{name} 은 JSON 객체여야 한다: {e}") from None
    if not isinstance(v, dict):
        raise SystemExit(f"{name} 은 JSON 객체여야 한다")
    return v


class Config:
    """호출 시점의 환경 변수를 읽는다 (테스트가 env 를 바꿔 가며 만들 수 있게)."""

    def __init__(self, env=None):
        env = os.environ if env is None else env
        g = env.get
        self.port = int(g("QA_PORT", "8800"))
        self.data_dir = Path(g("QA_DATA_DIR", "/data"))
        self.cases_dir = Path(g("QA_CASES_DIR", str(Path(__file__).resolve().parent.parent / "cases")))
        self.public_url = g("QA_PUBLIC_URL", "https://qa.agent.plady.io").rstrip("/")

        # 검증 대상
        self.target_env = g("QA_TARGET_ENV", "dev")
        self.target_base_url = g("QA_TARGET_BASE_URL", "https://api.dev.moimyeon.plady.io").rstrip("/")
        self.spec_url = g("QA_SPEC_URL", "https://100thieves-team.github.io/moimyeon-backend/api/branches/dev/openapi/openapi3.yaml")
        self.request_timeout = int(g("QA_REQUEST_TIMEOUT", "30"))
        self.spec_file = g("QA_SPEC_FILE", "") or None          # 로컬·테스트: 파일에서 읽는다
        self.spec_ttl = int(g("QA_SPEC_TTL", "600"))              # API 문서 캐시(초). 사람이 [API 문서 다시 읽기]로 언제든 앞당긴다
        # REST Docs HTML(사람이 읽는 API 문서). 기본은 스펙 URL 의 상위(…/branches/dev/). API 상세가 절 앵커로 링크한다
        self.spec_docs_url = g("QA_SPEC_DOCS_URL", "") or (self.spec_url.rsplit("/openapi/", 1)[0] + "/" if "/openapi/" in self.spec_url else "")

        # 기준 문서 — llm-wiki 체크아웃(읽기 전용 볼륨)과 카탈로그 입력 파일 (docs/qa-platform-tc.md §4.5, §11)
        self.wiki_dir = g("QA_WIKI_DIR", "") or None
        self.wiki_branch = g("QA_WIKI_BRANCH", "main")
        self.wiki_public_url = g("QA_WIKI_PUBLIC_URL", "https://wiki.agent.plady.io").rstrip("/")
        self.catalog_dir = Path(g("QA_CATALOG_DIR", str(Path(__file__).resolve().parent.parent / "catalog")))

        # 테스트 계정·픽스처 (SSM qa-actors / qa-fixtures → env)
        self.actors: dict = _json_env(env, "QA_ACTORS")        # name -> memberId
        self.fixtures: dict = _json_env(env, "QA_FIXTURES")    # key -> value

        # 사람 트리거 — 운영자 목록(자기 신고 드롭다운)
        self.operators = [s.strip() for s in g("QA_OPERATORS", "bebe,dbwp031,중곤").split(",") if s.strip()]

        # GitHub (읽기 전용)
        self.backend_repo = g("QA_BACKEND_REPO", "100Thieves-team/moimyeon-backend")
        self.backend_deploy_workflow = g("QA_BACKEND_DEPLOY_WORKFLOW", "deploy-aws.yml")
        self.backend_branch = g("QA_BACKEND_BRANCH", "dev")
        self.github_token = g("QA_GITHUB_TOKEN", "")
        self.release_checklist_url = g(
            "QA_RELEASE_CHECKLIST_URL",
            "https://raw.githubusercontent.com/100Thieves-team/moimyeon-backend/dev/docs/knowledge/release-checklist.md")

        # 스프린트 = Linear 주간 사이클. API 없이 앵커로 계산한다 (docs/qa-platform.md §4 2.3).
        self.sprint_anchor = g("QA_SPRINT_ANCHOR", "2026-09-13T15:00:00Z")
        self.sprint_anchor_number = int(g("QA_SPRINT_ANCHOR_NUMBER", "9"))
        self.sprint_days = int(g("QA_SPRINT_DAYS", "7"))
        # 스프린트 smoke 리마인더 — Slack 알림만 (qa/reminder.py). 마감 N 일 전부터, 스프린트당 한 번
        self.sprint_reminder = g("QA_SPRINT_REMINDER", "1") not in ("0", "false", "no", "")
        self.sprint_remind_days = int(g("QA_SPRINT_REMIND_DAYS", "1"))

        # Hermes (AI 는 전부 여기로)
        self.hermes_url = g("HERMES_API_URL", "http://hermes-gateway:8642").rstrip("/")
        self.hermes_key = g("HERMES_API_KEY", "")
        self.hermes_model = g("HERMES_MODEL", "gpt-5.5")
        self.hermes_timeout = int(g("HERMES_TIMEOUT", "300"))
        # Hermes 채팅창 (docs/qa-platform-hermes.md §3.2·§8-4·§8-5): 동기 호출 상한, 대화당 턴 한도, 오래된 대화 닫힘 표시
        self.chat_timeout = int(g("QA_CHAT_TIMEOUT", "180"))
        self.chat_max_turns = int(g("QA_CHAT_MAX_TURNS", "40"))
        self.chat_stale_days = int(g("QA_CHAT_STALE_DAYS", "30"))

        # QA MCP 서버 (docs/qa-platform-hermes.md §3.1): Hermes 가 부르는 QA 도구. 비어 있으면 /mcp 가 꺼진다 (503)
        self.qa_mcp_token = g("QA_MCP_TOKEN", "")

        # llm-wiki MCP (보고서 발행에만, 내부 프록시 + 기존 정적 bearer). 비어 있으면 발행 버튼이 꺼진다
        self.wiki_mcp_url = g("LLM_WIKI_MCP_URL", "").rstrip("/")
        self.wiki_mcp_token = g("LLM_WIKI_MCP_BEARER_TOKEN", "")

        # Slack (WIKI_SLACK_WEBHOOK_URL 재사용 — 사용자 결정)
        self.slack_webhook_url = g("WIKI_SLACK_WEBHOOK_URL", "")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "qa.sqlite"

    def sprint_anchor_dt(self) -> datetime:
        dt = datetime.fromisoformat(self.sprint_anchor.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    def current_sprint(self, now: datetime | None = None) -> dict:
        """앵커 사이클 번호 + 경과 주 수. 반환: {number, starts_at, ends_at}."""
        now = now or datetime.now(timezone.utc)
        anchor = self.sprint_anchor_dt()
        span = timedelta(days=self.sprint_days)
        elapsed = (now - anchor) // span
        starts = anchor + span * elapsed
        return {"number": self.sprint_anchor_number + elapsed, "starts_at": starts, "ends_at": starts + span}

    def summary(self) -> dict:
        """로그·/health 용. 비밀값은 존재 여부만."""
        return {
            "target": self.target_base_url, "env": self.target_env, "cases_dir": str(self.cases_dir),
            "actors": sorted(self.actors.keys()), "fixtures": sorted(self.fixtures.keys()), "operators": self.operators,
            "hermes": bool(self.hermes_key), "slack": bool(self.slack_webhook_url), "github_token": bool(self.github_token),
            "wiki_dir": self.wiki_dir, "catalog_dir": str(self.catalog_dir), "wiki_publish": bool(self.wiki_mcp_url and self.wiki_mcp_token),
            "qa_mcp": bool(self.qa_mcp_token),
        }
