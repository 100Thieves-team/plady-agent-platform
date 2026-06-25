#!/usr/bin/env bash
set -euo pipefail

# Legacy defaults: old EC2/Caddy wiki endpoint and SSM path. For the new
# agent-platform endpoint, override MCP_URL and TOKEN_PARAM explicitly.
MCP_URL="${MCP_URL:-https://plady.kro.kr/mcp}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
TOKEN_PARAM="${TOKEN_PARAM:-/100thieves/wiki/mcp-bearer-token}"
AWS_BIN="${AWS_BIN:-aws}"

TOKEN="$($AWS_BIN ssm get-parameter \
  --region "$AWS_REGION" \
  --name "$TOKEN_PARAM" \
  --with-decryption \
  --query Parameter.Value \
  --output text)"

HEADERS_FILE="$(mktemp)"
BODY_FILE="$(mktemp)"
TOOLS_FILE="$(mktemp)"
cleanup() {
  rm -f "$HEADERS_FILE" "$BODY_FILE" "$TOOLS_FILE"
  unset TOKEN
}
trap cleanup EXIT

curl --noproxy "*" -sS -D "$HEADERS_FILE" -o "$BODY_FILE" --max-time 20 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"check-mcp-tools","version":"0"}}}' \
  "$MCP_URL" >/dev/null

SESSION_ID="$(awk -F': ' 'tolower($1)=="mcp-session-id" {gsub(/\r/,"",$2); print $2}' "$HEADERS_FILE")"
if [ -z "$SESSION_ID" ]; then
  echo "MCP initialize did not return mcp-session-id" >&2
  cat "$BODY_FILE" >&2
  exit 1
fi

curl --noproxy "*" -sS --max-time 20 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}' \
  "$MCP_URL" >/dev/null

curl --noproxy "*" -sS --max-time 20 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  "$MCP_URL" >"$TOOLS_FILE"

python3 - "$TOOLS_FILE" <<'PY'
import json, sys
text = open(sys.argv[1]).read()
for line in text.splitlines():
    if not line.startswith('data: '):
        continue
    payload = line[6:].strip()
    if not payload or not payload.startswith('{'):
        continue
    data = json.loads(payload)
    tools = data.get('result', {}).get('tools')
    if tools is not None:
        print(f'tool_count={len(tools)}')
        for tool in tools:
            print(tool['name'])
        break
else:
    print(text)
    raise SystemExit('tools/list response did not include tools')
PY
