"""OpenAPI(백엔드 REST Docs → GitHub Pages openapi3.yaml) 읽기 — 계약 TC 의 원천. docs/qa-platform-tc.md §4.1.

- `QA_SPEC_URL` 을 1시간 캐시로 읽고, 성공본은 `<data>/catalog/openapi.yaml` 에 남겨 네트워크가 죽어도 마지막 판으로 돈다.
- `QA_SPEC_FILE` 이 있으면 파일을 읽는다(로컬·테스트).
- 에러 코드는 응답 예시(`examples.*.value` 의 `error.code`)에서 뽑는다. 예시 이름이 `createRoom-e1402-…` 라도 본문을 본다.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import httpx

METHODS = ("get", "post", "put", "patch", "delete")
_CODE = re.compile(r'"code"\s*:\s*"(E\d{3,4})"')
_MSG = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass
class Op:
    id: str
    method: str
    path: str
    summary: str = ""
    tags: list = field(default_factory=list)
    success: dict = field(default_factory=dict)     # status(str) -> example json|None
    errors: dict = field(default_factory=dict)      # code -> {status, message, example}
    request_example: object = None
    params: list = field(default_factory=list)      # [{name, in: path|query|header, required, description}]

    @property
    def is_write(self) -> bool:
        return self.method in ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class SpecData:
    hash: str
    ops: dict            # operationId -> Op
    fetched_at: float
    source: str          # url | file | cache

    def op_for(self, method: str, path: str) -> Op | None:
        method = method.upper()
        best = None
        for op in self.ops.values():
            if op.method == method and match_path(op.path, path):
                # 템플릿 세그먼트가 적은(더 구체적인) 쪽을 우선: /v1/rooms/creation-limit 가 /v1/rooms/{roomId} 보다 먼저
                if best is None or op.path.count("{") < best.path.count("{"):
                    best = op
        return best


def match_path(template: str, path: str) -> bool:
    """`/v1/rooms/{roomId}` 와 `/v1/rooms/{{roomId}}` · `/v1/rooms/abc` 를 세그먼트 단위로 맞춘다. 쿼리는 무시."""
    t = [s for s in template.split("?")[0].split("/") if s != ""]
    p = [s for s in path.split("?")[0].split("/") if s != ""]
    if len(t) != len(p):
        return False
    for a, b in zip(t, p):
        if a.startswith("{") and a.endswith("}"):
            if not b:
                return False
            continue
        if b.startswith("{{") and b.endswith("}}"):
            return False   # 고정 세그먼트 자리에 치환 표현이 오면 다른 경로일 수 있다 — 보수적으로 불일치
        if a != b:
            return False
    return True


def _json_content(content: dict) -> dict:
    """`application/json` 과 `application/json;charset=UTF-8` 둘 다 온다 (REST Docs 산출물)."""
    for k, v in (content or {}).items():
        if str(k).split(";")[0].strip() == "application/json" and isinstance(v, dict):
            return v
    return {}


def _example_value(ex) -> object:
    if isinstance(ex, dict) and "value" in ex:
        v = ex["value"]
    else:
        v = ex
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def parse(doc: dict) -> dict[str, Op]:
    ops: dict[str, Op] = {}
    for path, item in (doc.get("paths") or {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method not in METHODS or not isinstance(op, dict):
                continue
            oid = op.get("operationId") or f"{method}:{path}"
            o = Op(id=oid, method=method.upper(), path=path, summary=str(op.get("summary") or ""), tags=list(op.get("tags") or []))
            for prm in (op.get("parameters") or []):
                if isinstance(prm, dict) and prm.get("name"):
                    o.params.append({"name": str(prm["name"]), "in": str(prm.get("in") or "query"), "required": bool(prm.get("required")),
                                     "description": str(prm.get("description") or "")})
            rb = _json_content((op.get("requestBody") or {}).get("content") or {})
            for ex in (rb.get("examples") or {}).values():
                o.request_example = _example_value(ex)
                break
            for status, resp in (op.get("responses") or {}).items():
                status = str(status)
                content = _json_content((resp or {}).get("content") or {}) if isinstance(resp, dict) else {}
                examples = content.get("examples") or {}
                if status.startswith("2"):
                    first = None
                    for ex in examples.values():
                        first = _example_value(ex)
                        break
                    o.success[status] = first
                    continue
                for ex in examples.values():
                    v = _example_value(ex)
                    text = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                    m = _CODE.search(text)
                    if not m:
                        continue
                    code = m.group(1)
                    mm = _MSG.search(text)
                    if code not in o.errors:
                        o.errors[code] = {"status": int(status) if status.isdigit() else status,
                                          "message": (mm.group(1) if mm else ""), "example": v}
            ops[oid] = o
    return ops


class Spec:
    def __init__(self, url: str, cache_dir: Path, file: str | None = None, ttl: int = 3600):
        self.url = url
        self.file = file
        self.ttl = ttl
        self.cache_dir = Path(cache_dir)
        self._lock = threading.Lock()
        self._data: SpecData | None = None
        self.last_error: str | None = None

    def age_seconds(self) -> int | None:
        """마지막으로 문서를 읽은 뒤 지난 초. 화면의 "n분 전 읽음" 표시용."""
        return int(time.monotonic() - self._data.fetched_at) if self._data else None

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / "openapi.yaml"

    def _load_text(self, text: str, source: str) -> SpecData:
        doc = yaml.safe_load(text)
        if not isinstance(doc, dict) or "paths" not in doc:
            raise ValueError("OpenAPI 문서가 아니다 (paths 없음)")
        return SpecData(hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], ops=parse(doc),
                        fetched_at=time.monotonic(), source=source)

    def get(self, force: bool = False) -> SpecData | None:
        with self._lock:
            if self._data and not force and (self.file or time.monotonic() - self._data.fetched_at < self.ttl):
                return self._data
            try:
                if self.file:
                    self._data = self._load_text(Path(self.file).read_text(encoding="utf-8"), "file")
                    self.last_error = None
                    return self._data
                r = httpx.request("GET", self.url, timeout=20)
                if r.status == 200 and r.text:
                    self._data = self._load_text(r.text, "url")
                    self.last_error = None
                    try:
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        self.cache_path.write_text(r.text, encoding="utf-8")
                    except OSError:
                        pass
                    return self._data
                self.last_error = f"OpenAPI 조회 실패: status={r.status} {r.error or ''}".strip()
            except Exception as e:   # yaml, IO
                self.last_error = f"OpenAPI 파싱 실패: {e}"
            if self._data:
                self._data.fetched_at = time.monotonic()   # 실패 시 재시도 간격을 둔다
                return self._data
            if self.cache_path.is_file():
                try:
                    self._data = self._load_text(self.cache_path.read_text(encoding="utf-8"), "cache")
                    return self._data
                except Exception as e:
                    self.last_error = f"{self.last_error}; 캐시도 실패: {e}"
            return None
