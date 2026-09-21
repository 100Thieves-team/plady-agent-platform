"""GitHub 읽기 전용 조회 — 배포 감지·PR·변경 파일. 공개 레포라 토큰 없이 동작한다(60 req/h).

캐시로 rate limit 을 아낀다: Actions 목록 60초, PR 조회는 SHA/번호별 영구.
"""
from __future__ import annotations

import re
import threading
import time

from . import httpx
from .config import Config

API = "https://api.github.com"

# 변경 파일 → 도메인. docs/qa-platform.md §4 2.2. 매칭 안 되면 빈 집합 → 호출자가 전체 sanity 로 폴백.
_RULES = [
    (re.compile(r"core/core-api/src/main/kotlin/io/plady/moimyeon/core/domain/([a-z]+)/"), lambda m: m.group(1)),
    (re.compile(r"core/core-api/src/main/kotlin/io/plady/moimyeon/core/api/controller/v1/([A-Za-z]+?)(?:Controller)?\.kt$"), lambda m: m.group(1).lower()),
    (re.compile(r"core/core-api/src/main/kotlin/io/plady/moimyeon/core/api/facade/([A-Za-z]+?)(?:Facade)?\.kt$"), lambda m: m.group(1).lower()),
    (re.compile(r"storage/db-core/src/main/kotlin/io/plady/moimyeon/storage/db/core/([a-z]+)/"), lambda m: m.group(1)),
    (re.compile(r"^security/"), lambda m: "auth"),
    (re.compile(r"storage/db-core/src/main/resources/db/migration/"), lambda m: "schema"),
]
_ALIASES = {"devauth": "auth", "roomapplication": "application", "roomcomment": "guestbook"}


def domains_from_files(files: list[str]) -> set[str]:
    out = set()
    for f in files:
        for rx, fn in _RULES:
            m = rx.search(f)
            if m:
                d = fn(m)
                out.add(_ALIASES.get(d, d))
                break
    return out


class GitHub:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()
        self.last_error: str | None = None

    def _get(self, path: str, ttl: float | None, params: str = ""):
        key = path + params
        with self._lock:
            hit = self._cache.get(key)
            if hit and (ttl is None or time.monotonic() - hit[0] < ttl):
                return hit[1]
        headers = {"Accept": "application/vnd.github+json"}
        if self.cfg.github_token:
            headers["Authorization"] = "Bearer " + self.cfg.github_token
        r = httpx.request("GET", f"{API}{path}{params}", headers=headers, timeout=20)
        if r.status != 200 or r.json is None:
            self.last_error = f"GitHub {path}: status={r.status} {r.error or (r.text or '')[:160]}"
            with self._lock:
                if hit:            # 실패 시 만료된 캐시라도 돌려준다
                    return hit[1]
            return None
        self.last_error = None
        with self._lock:
            self._cache[key] = (time.monotonic(), r.json)
        return r.json

    def list_deploys(self, limit: int = 10) -> list[dict]:
        """dev 브랜치의 성공한 deploy 워크플로 실행. [{run_id, sha, at, url, title}]"""
        data = self._get(f"/repos/{self.cfg.backend_repo}/actions/workflows/{self.cfg.backend_deploy_workflow}/runs",
                         ttl=60, params=f"?branch={self.cfg.backend_branch}&status=success&per_page={limit}")
        if not data:
            return []
        out = []
        for wr in data.get("workflow_runs", []):
            out.append({"run_id": wr.get("id"), "sha": wr.get("head_sha"), "at": wr.get("updated_at"),
                        "url": wr.get("html_url"), "title": wr.get("display_title") or wr.get("name"),
                        "branch": wr.get("head_branch")})
        return out

    def pr_for_sha(self, sha: str) -> dict | None:
        data = self._get(f"/repos/{self.cfg.backend_repo}/commits/{sha}/pulls", ttl=None)
        if not data:
            return None
        for pr in data:
            return {"number": pr.get("number"), "title": pr.get("title"), "url": pr.get("html_url"),
                    "author": (pr.get("user") or {}).get("login"), "merged_at": pr.get("merged_at")}
        return None

    def pr_files(self, number: int) -> list[str]:
        files: list[str] = []
        for page in (1, 2, 3):
            data = self._get(f"/repos/{self.cfg.backend_repo}/pulls/{number}/files", ttl=None,
                             params=f"?per_page=100&page={page}")
            if not data:
                break
            files.extend(f.get("filename") for f in data if f.get("filename"))
            if len(data) < 100:
                break
        return files

    def release_checklist(self) -> list[str]:
        """백엔드 docs/knowledge/release-checklist.md 의 `- [ ]` 항목. 실패 시 빈 목록."""
        key = "checklist"
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.monotonic() - hit[0] < 3600:
                return hit[1]  # type: ignore[return-value]
        r = httpx.request("GET", self.cfg.release_checklist_url, timeout=15)
        if r.status != 200:
            return hit[1] if hit else []  # type: ignore[return-value]
        items = [re.sub(r"\s+", " ", m.group(1)).strip() for m in re.finditer(r"^- \[ \] (.+?)(?=\n(?:- \[ \]|\n|#)|\Z)", r.text, re.M | re.S)]
        with self._lock:
            self._cache[key] = (time.monotonic(), items)
        return items
