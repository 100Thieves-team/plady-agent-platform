#!/usr/bin/env bash
set -euo pipefail

CODEX_BIN="${CODEX_BIN:-codex}"
MCP_NAME="${MCP_NAME:-team-wiki}"
# Legacy default: the old EC2/Caddy wiki endpoint. For agent-platform, pass
# --url https://mcp.agent.plady.io/mcp after PLA-247 provisions it.
MCP_URL="${MCP_URL:-https://plady.kro.kr/mcp}"
TOKEN_ENV_VAR="${TOKEN_ENV_VAR:-LLM_WIKI_MCP_BEARER_TOKEN}"

usage() {
  cat <<USAGE
Usage: $0 [options]

Add the 100Thieves LLM Wiki MCP endpoint to local Codex config.
The default URL is the legacy EC2/Caddy endpoint; pass --url for the new agent-platform endpoint once PLA-247 provisions it.
The bearer token itself is not stored in Codex config; Codex reads it from an environment variable.

Options:
  --name NAME           MCP server name. Default: ${MCP_NAME}
  --url URL             MCP endpoint URL. Default: ${MCP_URL}
  --token-env-var NAME  Bearer token environment variable. Default: ${TOKEN_ENV_VAR}
  -h, --help            Show this help

Environment overrides:
  CODEX_BIN, MCP_NAME, MCP_URL, TOKEN_ENV_VAR
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --name)
      MCP_NAME="$2"
      shift 2
      ;;
    --url)
      MCP_URL="$2"
      shift 2
      ;;
    --token-env-var)
      TOKEN_ENV_VAR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

command -v "$CODEX_BIN" >/dev/null 2>&1 || {
  echo "Missing Codex CLI: ${CODEX_BIN}" >&2
  exit 1
}

if [[ ! "$TOKEN_ENV_VAR" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  cat >&2 <<ERROR
Invalid --token-env-var: ${TOKEN_ENV_VAR}

Pass the environment variable name, not the token value.
Example:
  --token-env-var LLM_WIKI_MCP_BEARER_TOKEN
ERROR
  exit 1
fi

if "$CODEX_BIN" mcp get "$MCP_NAME" >/dev/null 2>&1; then
  "$CODEX_BIN" mcp remove "$MCP_NAME"
fi

"$CODEX_BIN" mcp add "$MCP_NAME" \
  --url "$MCP_URL" \
  --bearer-token-env-var "$TOKEN_ENV_VAR"

cat <<NEXT

Added Codex MCP server '${MCP_NAME}' -> ${MCP_URL}

Before starting Codex, export the token environment variable:

export ${TOKEN_ENV_VAR}="\$(aws ssm get-parameter \\
  --region ap-northeast-2 \\
  --name /100thieves/wiki/mcp-bearer-token \\
  --with-decryption \\
  --query Parameter.Value \\
  --output text)"

Verify:
  ${CODEX_BIN} mcp list | grep ${MCP_NAME}
NEXT
