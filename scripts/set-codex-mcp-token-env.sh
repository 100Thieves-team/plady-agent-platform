#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
# Legacy default: old EC2/Caddy SSM path. For agent-platform, pass
# --param /plady/agent-platform/<env>/llm-wiki-mcp-bearer-token after provisioning.
TOKEN_PARAM="${TOKEN_PARAM:-/100thieves/wiki/mcp-bearer-token}"
TOKEN_ENV_VAR="${TOKEN_ENV_VAR:-LLM_WIKI_MCP_BEARER_TOKEN}"
AWS_BIN="${AWS_BIN:-aws}"
MODE="launchctl"

usage() {
  cat <<USAGE
Usage: $0 [options]

Load the Codex MCP bearer token from AWS SSM and expose it without printing the token.
The default parameter is the legacy EC2/Caddy SSM path; pass --param for the new agent-platform path once provisioned.
Default mode writes it to macOS launchctl so GUI Codex can read it after app restart.

Options:
  --mode launchctl  Set token for GUI apps in current macOS login session (default)
  --mode shell      Print an export command for the current shell
  --region REGION   AWS region. Default: ${AWS_REGION}
  --param NAME      SSM SecureString parameter name. Default: ${TOKEN_PARAM}
  --env-var NAME    Environment variable name. Default: ${TOKEN_ENV_VAR}
  -h, --help        Show this help

Environment overrides:
  AWS_REGION, TOKEN_PARAM, TOKEN_ENV_VAR, AWS_BIN
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode)
      MODE="$2"
      shift 2
      ;;
    --region)
      AWS_REGION="$2"
      shift 2
      ;;
    --param)
      TOKEN_PARAM="$2"
      shift 2
      ;;
    --env-var)
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

if [[ ! "$TOKEN_ENV_VAR" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "Invalid env var name: ${TOKEN_ENV_VAR}" >&2
  exit 1
fi

command -v "$AWS_BIN" >/dev/null 2>&1 || { echo "Missing aws CLI: ${AWS_BIN}" >&2; exit 1; }

TOKEN="$($AWS_BIN ssm get-parameter \
  --region "$AWS_REGION" \
  --name "$TOKEN_PARAM" \
  --with-decryption \
  --query Parameter.Value \
  --output text)"

case "$MODE" in
  launchctl)
    command -v launchctl >/dev/null 2>&1 || { echo "launchctl is only available on macOS" >&2; exit 1; }
    launchctl setenv "$TOKEN_ENV_VAR" "$TOKEN"
    echo "Set ${TOKEN_ENV_VAR} in launchctl for the current macOS login session. Restart Codex.app."
    ;;
  shell)
    printf 'export %s=%q\n' "$TOKEN_ENV_VAR" "$TOKEN"
    ;;
  *)
    echo "Unknown mode: ${MODE}" >&2
    usage >&2
    exit 1
    ;;
esac

unset TOKEN
