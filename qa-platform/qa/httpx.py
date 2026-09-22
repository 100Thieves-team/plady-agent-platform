"""표준 라이브러리 HTTP 호출 한 곳. 러너·GitHub·Hermes·Slack 이 모두 이걸 쓴다.

테스트는 `qa.httpx.request` 를 바꿔 끼운다.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class HttpResult:
    __slots__ = ("status", "headers", "text", "json", "elapsed_ms", "error")

    def __init__(self, status: int, headers: dict, text: str, elapsed_ms: int, error: str | None = None):
        self.status = status
        self.headers = headers
        self.text = text
        self.elapsed_ms = elapsed_ms
        self.error = error
        try:
            self.json = json.loads(text) if text else None
        except ValueError:
            self.json = None


def request(method: str, url: str, headers: dict | None = None, body=None, timeout: int = 30) -> HttpResult:
    """네트워크 오류는 status 0 + error 로 돌려준다 (예외를 던지지 않는다)."""
    data = None
    hdrs = dict(headers or {})
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
    hdrs.setdefault("User-Agent", "plady-qa-platform/0.1")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=hdrs)
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            return HttpResult(resp.status, dict(resp.headers), text, int((time.monotonic() - t0) * 1000))
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace") if e.fp else ""
        return HttpResult(e.code, dict(e.headers or {}), text, int((time.monotonic() - t0) * 1000))
    except Exception as e:  # URLError, timeout, ssl
        return HttpResult(0, {}, "", int((time.monotonic() - t0) * 1000), error=f"{type(e).__name__}: {e}")


class HttpError(RuntimeError):
    def __init__(self, status: int, text: str):
        super().__init__(f"HTTP {status}: {text[:300]}")
        self.status = status
        self.text = text


def stream(method: str, url: str, headers: dict | None = None, body=None, timeout: int = 30):
    """응답을 줄 단위로 낸다 (SSE 용). HTTP 오류는 HttpError, 네트워크 오류는 그대로 예외. timeout 은 읽기 한 번의 한도다."""
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if not isinstance(body, (bytes, bytearray, str)) else (body.encode() if isinstance(body, str) else bytes(body))
        hdrs.setdefault("Content-Type", "application/json")
    hdrs.setdefault("User-Agent", "plady-qa-platform/0.1")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=hdrs)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace") if e.fp else "") from None
    with resp:
        for raw in resp:
            yield raw.decode("utf-8", "replace").rstrip("\r\n")
