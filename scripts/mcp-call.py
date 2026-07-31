#!/usr/bin/env python3
"""Minimal MCP Streamable-HTTP client (stdlib only).

llm-wiki MCP 엔드포인트(mcp-proxy)에 대해 initialize 핸드셰이크 후
tools/list 또는 tools/call 을 실행한다. 회의록 ingest v0 경로
(docs/meeting-ingest.md)와 레지스트리 smoke(docs/mcp-registry.md)에서 사용.

사용 예:
  export MCP_BEARER_TOKEN="..."
  scripts/mcp-call.py list-tools
  scripts/mcp-call.py call wiki_search --args '{"query": "ADR"}'
  scripts/mcp-call.py call wiki_ingest --args @meeting.json \
      --url https://mcp.agent.plady.io/mcp

도구별 인자 스키마는 list-tools 출력(inputSchema)이 SSOT다. 이 스크립트는
스키마를 추측하지 않는다.
"""
import argparse
import json
import os
import sys
import urllib.request

PROTOCOL_VERSION = "2025-03-26"


def _parse_body(resp):
    """JSON 또는 SSE(text/event-stream) 응답에서 첫 JSON-RPC 메시지를 꺼낸다."""
    ctype = resp.headers.get("Content-Type", "")
    raw = resp.read().decode("utf-8", errors="replace")
    if "text/event-stream" in ctype:
        for line in raw.splitlines():
            if line.startswith("data:"):
                data = line[len("data:"):].strip()
                if data:
                    return json.loads(data)
        raise RuntimeError(f"SSE 응답에 data 라인이 없습니다:\n{raw[:500]}")
    if not raw.strip():
        return None  # 202 Accepted (notification)
    return json.loads(raw)


class McpClient:
    def __init__(self, url, bearer):
        self.url = url
        self.bearer = bearer
        self.session_id = None
        self._next_id = 0

    def _request(self, payload):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(
            self.url, data=json.dumps(payload).encode(), headers=headers
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            return _parse_body(resp)

    def rpc(self, method, params=None):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        msg = self._request(payload)
        if msg is None:
            raise RuntimeError(f"{method}: 빈 응답")
        if "error" in msg:
            raise RuntimeError(f"{method} 오류: {json.dumps(msg['error'], ensure_ascii=False)}")
        return msg.get("result")

    def notify(self, method):
        self._request({"jsonrpc": "2.0", "method": method})

    def initialize(self):
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "plady-mcp-call", "version": "0.1.0"},
            },
        )
        self.notify("notifications/initialized")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("MCP_URL", "http://localhost:18765/mcp"))
    parser.add_argument("--bearer-env", default="MCP_BEARER_TOKEN",
                        help="bearer token 을 읽을 환경변수 이름 (값을 인자로 받지 않는다)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list-tools")
    call = sub.add_parser("call")
    call.add_argument("tool")
    call.add_argument("--args", default="{}",
                      help="도구 인자 JSON. @path 로 파일 지정 가능")
    opts = parser.parse_args()

    bearer = os.environ.get(opts.bearer_env, "")
    if not bearer:
        print(f"경고: ${opts.bearer_env} 가 비어 있습니다. 무인증 호출은 401이 정상입니다.",
              file=sys.stderr)

    client = McpClient(opts.url, bearer)
    client.initialize()

    if opts.command == "list-tools":
        result = client.rpc("tools/list")
    else:
        raw = opts.args
        if raw.startswith("@"):
            with open(raw[1:], encoding="utf-8") as f:
                raw = f.read()
        result = client.rpc("tools/call", {"name": opts.tool, "arguments": json.loads(raw)})

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()


if __name__ == "__main__":
    main()
