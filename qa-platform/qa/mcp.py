"""최소 MCP 클라이언트 (streamable HTTP, JSON-RPC) — llm-wiki `wiki_apply` 호출용. docs/qa-platform-tc.md §9.

표준 라이브러리만. 흐름: initialize → notifications/initialized → tools/call. 세션은 `Mcp-Session-Id` 헤더로 잇는다.
응답은 `application/json` 또는 `text/event-stream`(data: 줄에 JSON-RPC) 둘 다 받는다.
내부 경로 `http://mcp-proxy:18765/mcp` + 기존 정적 bearer(MCP_BEARER_TOKEN). 발행 버튼에서만 쓴다.
"""
from __future__ import annotations

import json
import re
import uuid

from . import httpx

_HDR_SESSION = "Mcp-Session-Id"
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)


class McpError(RuntimeError):
    pass


def _parse_rpc(r: httpx.HttpResult, want_id) -> dict | None:
    """본문에서 id 가 맞는 JSON-RPC 응답을 찾는다. SSE 면 data: 줄을 모은다."""
    ctype = ""
    for k, v in (r.headers or {}).items():
        if k.lower() == "content-type":
            ctype = str(v)
    candidates: list[str] = []
    if "text/event-stream" in ctype:
        for line in (r.text or "").splitlines():
            if line.startswith("data:"):
                candidates.append(line[5:].strip())
    elif r.text:
        candidates.append(r.text)
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            continue
        objs = obj if isinstance(obj, list) else [obj]
        for o in objs:
            if isinstance(o, dict) and o.get("jsonrpc") == "2.0" and (want_id is None or o.get("id") == want_id):
                return o
    return None


class McpClient:
    def __init__(self, url: str, bearer: str, timeout: int = 60, client_name: str = "plady-qa-platform"):
        self.url = url
        self.bearer = bearer
        self.timeout = timeout
        self.client_name = client_name
        self.session_id: str | None = None
        self._n = 0

    def _headers(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        if self.bearer:
            h["Authorization"] = "Bearer " + self.bearer
        if self.session_id:
            h[_HDR_SESSION] = self.session_id
        return h

    def _post(self, payload: dict, want_id) -> dict | None:
        r = httpx.request("POST", self.url, headers=self._headers(), body=payload, timeout=self.timeout)
        if r.status in (401, 403):
            raise McpError(f"MCP 인증 실패 status={r.status} (LLM_WIKI_MCP_BEARER_TOKEN 확인)")
        if r.status >= 400 or r.error:
            raise McpError(f"MCP HTTP 오류 status={r.status} {r.error or (r.text or '')[:200]}")
        for k, v in (r.headers or {}).items():
            if k.lower() == _HDR_SESSION.lower() and v:
                self.session_id = str(v)
        return _parse_rpc(r, want_id)

    def _call(self, method: str, params: dict | None = None) -> dict:
        self._n += 1
        rid = self._n
        resp = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, rid)
        if resp is None:
            raise McpError(f"MCP {method}: 응답에서 JSON-RPC 결과를 찾지 못했다")
        if resp.get("error"):
            err = resp["error"]
            raise McpError(f"MCP {method}: {err.get('message') if isinstance(err, dict) else err}")
        return resp.get("result") or {}

    def initialize(self) -> dict:
        res = self._call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                         "clientInfo": {"name": self.client_name, "version": "0.2"}})
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, None)
        except McpError:
            pass   # 일부 서버는 알림에 202 만 준다 — 본문 없음은 정상
        return res

    def call_tool(self, name: str, arguments: dict) -> dict:
        if self.session_id is None:
            self.initialize()
        res = self._call("tools/call", {"name": name, "arguments": arguments})
        if res.get("isError"):
            text = " ".join(str(c.get("text") or "") for c in (res.get("content") or []) if isinstance(c, dict))
            raise McpError(f"{name} 실패: {text[:600]}")
        return res

    @staticmethod
    def tool_text(res: dict) -> str:
        return "\n".join(str(c.get("text") or "") for c in (res.get("content") or []) if isinstance(c, dict) and c.get("type") == "text")


def wiki_apply(client: McpClient, *, path: str, content: str, message: str, dry_run: bool = False, expected_head: str | None = None) -> dict:
    """generated 모드로 페이지 하나를 쓴다. 반환: 도구 결과 텍스트를 JSON 으로 풀어 본 것 (안 풀리면 {"text": …})."""
    args = {"mode": "generated", "changes": [{"path": path, "content": content}], "message": message, "dry_run": dry_run}
    if expected_head:
        args["expected_head"] = expected_head
    res = client.call_tool("wiki_apply", args)
    text = McpClient.tool_text(res)
    try:
        return json.loads(text) if text.strip().startswith("{") else {"text": text}
    except ValueError:
        return {"text": text}


def mask_ids(text: str) -> str:
    """보고서에 회원 UUID 같은 식별값이 실리지 않게 — UUID 는 앞 8자리만 남긴다."""
    return _UUID.sub(lambda m: m.group(0)[:8] + "-…", text)
