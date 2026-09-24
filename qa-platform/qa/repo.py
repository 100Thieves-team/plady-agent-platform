"""이 레포(plady-agent-platform)의 스크립트·수동 테스트 조건 파일을 main 에서 읽고 main 에 바로 커밋한다. docs/qa-platform-editor.md §6.

- 스크립트(`qa-platform/cases/*.yaml`)와 테스트 조건 입력(`qa-platform/catalog/*.yaml`)의 원본은 레포다. 플랫폼은 승인 버튼이 눌렸을 때만 쓴다.
- 커밋 메시지에 `[skip ci]` 를 붙여 YAML 한 줄 때문에 플랫폼 전체가 다시 배포되지 않게 한다. 대신 플랫폼은 시작할 때와
  [스크립트 다시 읽기] 때 main 의 파일을 `<data>/repo/` 로 받아 그걸 읽는다(sync). 커밋한 파일은 그 자리에 바로 쓴다.
- 파일 전체를 다시 쓰지 않는다. `cases:` 목록에서 그 항목의 텍스트 구간만 바꾸거나 지운다 — 다른 항목·주석·순서가 남는다.
- 토큰(QA_REPO_TOKEN)이 없으면 enabled 가 False 다. 그때는 이미지에 구운 파일을 읽고, 승인은 파일 받기로 끝난다.
"""
from __future__ import annotations

import base64
import re
import shutil
import threading
import time
from pathlib import Path

import yaml

from . import httpx
from .config import Config
from .store import now_iso

_ITEM_START = re.compile(r"^  - ")


class RepoError(RuntimeError):
    pass


# ---------------------------------------------------------------------------------------------
# YAML 목록 항목 구간 다루기 (순수 함수 — 테스트가 직접 부른다)
# ---------------------------------------------------------------------------------------------
def item_spans(text: str) -> list[tuple[int, int, str]]:
    """`cases:` 목록의 항목마다 (시작 줄, 끝 줄(제외), id). 항목 뒤의 빈 줄·주석은 다음 항목 몫으로 둔다."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if _ITEM_START.match(ln)]
    spans = []
    for n, i in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        for j in range(i + 1, end):
            ln = lines[j]
            if ln.strip() and not ln.startswith((" ", "\t", "#")):
                end = j
                break
        while end - 1 > i and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        block = "".join(ln[2:] if ln.startswith("  ") else ln for ln in lines[i:end])
        try:
            doc = yaml.safe_load(block)
        except yaml.YAMLError:
            doc = None
        iid = str(doc[0].get("id")) if isinstance(doc, list) and doc and isinstance(doc[0], dict) and doc[0].get("id") is not None else ""
        spans.append((i, end, iid))
    return spans


def dump_item(raw: dict) -> str:
    """항목 하나를 `  - id: …` 꼴(두 칸 들여쓰기) 텍스트로."""
    t = yaml.safe_dump([raw], allow_unicode=True, sort_keys=False, width=1000, default_flow_style=False)
    return "".join(("  " + ln) if ln.strip() else ln for ln in t.splitlines(keepends=True))


def ids_in(text: str) -> list[str]:
    return [iid for _, _, iid in item_spans(text)]


def replace_item(text: str, item_id: str, raw: dict | None) -> str:
    """id 항목을 raw 로 바꾼다. raw 가 None 이면 지운다. 없으면 RepoError."""
    lines = text.splitlines(keepends=True)
    for i, end, iid in item_spans(text):
        if iid == item_id:
            new = [] if raw is None else [dump_item(raw)]
            out = "".join(lines[:i] + new + lines[end:])
            if raw is None and not item_spans(out):
                out = re.sub(r"(?m)^cases:\s*$", "cases: []", out, count=1)
            return out
    raise RepoError(f"파일에 {item_id} 항목이 없다")


def append_item(text: str | None, raw: dict, header: str = "") -> str:
    """목록 끝에 붙인다. 파일이 없거나 `cases: []` 면 목록을 연다."""
    if not text or not text.strip():
        return (header + "cases:\n" if header else "cases:\n") + dump_item(raw)
    text = re.sub(r"(?m)^cases:\s*\[\]\s*$", "cases:", text, count=1)
    if not text.endswith("\n"):
        text += "\n"
    return text + ("\n" if item_spans(text) else "") + dump_item(raw)


# ---------------------------------------------------------------------------------------------
# GitHub Contents API
# ---------------------------------------------------------------------------------------------
class Repo:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.repo = cfg.repo
        self.branch = cfg.repo_branch
        self.root = cfg.repo_root.strip("/")
        self.local = cfg.data_dir / "repo"          # main 에서 받은 cases/ · catalog/
        self.state: dict = {"synced_at": None, "error": None, "files": 0}
        self._lock = threading.Lock()                # 커밋은 한 번에 하나 (같은 파일 sha 경합 방지)

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.repo_token)

    def _api(self, method: str, path: str, body=None) -> httpx.HttpResult:
        return httpx.request(method, f"https://api.github.com/repos/{self.repo}/{path}", body=body, timeout=20,
                             headers={"Authorization": "Bearer " + self.cfg.repo_token, "Accept": "application/vnd.github+json",
                                      "X-GitHub-Api-Version": "2022-11-28"})

    def _err(self, what: str, r: httpx.HttpResult) -> RepoError:
        msg = (r.json or {}).get("message") if isinstance(r.json, dict) else None
        return RepoError(f"GitHub {what}: status={r.status} {msg or r.error or (r.text or '')[:200]}")

    def read(self, rel: str) -> tuple[str | None, str | None]:
        """(텍스트, blob sha). 파일이 없으면 (None, None)."""
        r = self._api("GET", f"contents/{self.root}/{rel}?ref={self.branch}")
        if r.status == 404:
            return None, None
        if r.status != 200 or not isinstance(r.json, dict):
            raise self._err(f"{rel} 읽기", r)
        return base64.b64decode(r.json.get("content") or "").decode("utf-8"), r.json.get("sha")

    def list_dir(self, rel: str, missing_ok: bool = False) -> list[str]:
        r = self._api("GET", f"contents/{self.root}/{rel}?ref={self.branch}")
        if r.status == 404 and missing_ok:
            return []
        if r.status != 200 or not isinstance(r.json, list):
            raise self._err(f"{rel}/ 목록", r)
        return [x["name"] for x in r.json if isinstance(x, dict) and x.get("type") == "file" and str(x.get("name", "")).endswith((".yaml", ".yml"))]

    def write(self, rel: str, text: str, sha: str | None, message: str) -> dict:
        body = {"message": message, "content": base64.b64encode(text.encode("utf-8")).decode("ascii"), "branch": self.branch}
        if sha:
            body["sha"] = sha
        r = self._api("PUT", f"contents/{self.root}/{rel}", body)
        if r.status not in (200, 201) or not isinstance(r.json, dict):
            if r.status in (409, 422):
                raise RepoError(f"main 의 {rel} 이 그사이 바뀌었다 — 잠시 뒤 다시 승인해 달라 (status {r.status})")
            raise self._err(f"{rel} 커밋", r)
        c = r.json.get("commit") or {}
        return {"sha": c.get("sha"), "url": c.get("html_url")}

    # ---- 동기화 ----
    def sync(self) -> bool:
        """main 의 cases/·catalog/·scenarios/ YAML 을 <data>/repo 로 받는다. 실패하면 이전 것을 그대로 둔다. scenarios/ 는 없어도 된다."""
        if not self.enabled:
            return False
        tmp = self.cfg.data_dir / f"repo.tmp-{int(time.time() * 1000)}"
        try:
            n = 0
            for sub in ("cases", "catalog", "scenarios"):
                (tmp / sub).mkdir(parents=True, exist_ok=True)
                for name in self.list_dir(sub, missing_ok=(sub == "scenarios")):
                    text, _ = self.read(f"{sub}/{name}")
                    if text is not None:
                        (tmp / sub / name).write_text(text, encoding="utf-8")
                        n += 1
            with self._lock:
                old = self.cfg.data_dir / "repo.old"
                shutil.rmtree(old, ignore_errors=True)
                if self.local.exists():
                    self.local.rename(old)
                tmp.rename(self.local)
                shutil.rmtree(old, ignore_errors=True)
            self.state = {"synced_at": now_iso(), "error": None, "files": n}
            return True
        except (RepoError, OSError) as ex:
            shutil.rmtree(tmp, ignore_errors=True)
            self.state = {**self.state, "error": str(ex)[:300]}
            return False

    @property
    def synced(self) -> bool:
        return self.enabled and (self.local / "cases").is_dir() and (self.local / "catalog").is_dir()

    def commit(self, rel: str, change, message: str) -> dict:
        """rel 파일의 main 판에 change(text|None → 새 text)를 적용해 커밋하고, 로컬 사본에도 쓴다. 반환 {sha, url, text}."""
        with self._lock:
            text, sha = self.read(rel)
            new = change(text)
            if new == text:
                raise RepoError("바뀐 내용이 없다")
            out = self.write(rel, new, sha, message)
            p = self.local / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(new, encoding="utf-8")
            return {**out, "text": new}
