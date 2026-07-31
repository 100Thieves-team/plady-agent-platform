#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TF_DIR="${TF_DIR:-${REPO_ROOT}/infra/terraform/ec2}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
TERRAFORM_BIN="${TERRAFORM_BIN:-terraform}"
AWS_BIN="${AWS_BIN:-aws}"
APP_DIR="${APP_DIR:-/opt/plady-agent-platform}"
MCP_BEARER_TOKEN_SSM_PARAMETER_NAME="${MCP_BEARER_TOKEN_SSM_PARAMETER_NAME:-/plady/agent-platform/dev/llm-wiki-mcp-bearer-token}"
DRY_RUN=false

usage() {
  cat <<USAGE
Usage: $0 [options]

Refresh EC2 runtime .env.ec2 from stable SSM secrets without rotating them.
Use this after changing domain_name or after intentionally rotating the MCP token in SSM.
Existing legacy EC2 hosts cloned at /opt/100thieves-wiki-mcp must pass
--app-dir /opt/100thieves-wiki-mcp or set APP_DIR=/opt/100thieves-wiki-mcp.

Options:
  --tf-dir DIR       Terraform directory. Default: ${TF_DIR}
  --region REGION    AWS region. Default: ${AWS_REGION}
  --app-dir DIR      App directory on EC2. Default: ${APP_DIR}
  --token-param NAME SSM SecureString name for MCP bearer token. Default: ${MCP_BEARER_TOKEN_SSM_PARAMETER_NAME}
  --dry-run          Print the remote script without executing it
  -h, --help         Show this help

Environment overrides:
  TF_DIR, AWS_REGION, TERRAFORM_BIN, AWS_BIN, APP_DIR, MCP_BEARER_TOKEN_SSM_PARAMETER_NAME
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tf-dir)
      TF_DIR="$2"
      shift 2
      ;;
    --region)
      AWS_REGION="$2"
      shift 2
      ;;
    --app-dir)
      APP_DIR="$2"
      shift 2
      ;;
    --token-param)
      MCP_BEARER_TOKEN_SSM_PARAMETER_NAME="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
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

terraform_output() {
  local name="$1"
  "$TERRAFORM_BIN" -chdir="$TF_DIR" output -raw "$name"
}

command -v "$TERRAFORM_BIN" >/dev/null 2>&1 || { echo "Missing terraform: ${TERRAFORM_BIN}" >&2; exit 1; }
command -v "$AWS_BIN" >/dev/null 2>&1 || { echo "Missing aws CLI: ${AWS_BIN}" >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "Missing jq" >&2; exit 1; }

INSTANCE_ID="$(terraform_output instance_id)"
WIKI_UI_URL="$(terraform_output wiki_ui_url)"
WIKI_DOMAIN_NAME="${WIKI_UI_URL#https://}"

read -r -d '' REMOTE_SCRIPT <<EOS || true
set -euo pipefail
APP_DIR="${APP_DIR}"
AWS_REGION="${AWS_REGION}"
WIKI_DOMAIN_NAME="${WIKI_DOMAIN_NAME}"
MCP_BEARER_TOKEN_SSM_PARAMETER_NAME="${MCP_BEARER_TOKEN_SSM_PARAMETER_NAME}"

cd "\$APP_DIR"

if [ -f .env.ec2 ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env.ec2
  set +a
fi

: "\${LLM_WIKI_IMAGE:?Missing LLM_WIKI_IMAGE in .env.ec2}"
: "\${WIKI_UI_IMAGE:?Missing WIKI_UI_IMAGE in .env.ec2}"
ACME_EMAIL="\${ACME_EMAIL:-admin@plady.kro.kr}"
MCP_BEARER_TOKEN="\$(aws ssm get-parameter \
  --region "\$AWS_REGION" \
  --name "\$MCP_BEARER_TOKEN_SSM_PARAMETER_NAME" \
  --with-decryption \
  --query Parameter.Value \
  --output text)"

cat >.env.ec2 <<ENV
LLM_WIKI_IMAGE=\${LLM_WIKI_IMAGE}
WIKI_UI_IMAGE=\${WIKI_UI_IMAGE}
ACME_EMAIL=\${ACME_EMAIL}
WIKI_DOMAIN_NAME=\${WIKI_DOMAIN_NAME}
MCP_BEARER_TOKEN=\${MCP_BEARER_TOKEN}
ENV
chmod 600 .env.ec2

docker compose --env-file .env.ec2 -f compose.ec2.yaml up -d caddy wiki-ui mcp-proxy
EOS

if [ "$DRY_RUN" = true ]; then
  echo "Instance: ${INSTANCE_ID}"
  echo "Domain: ${WIKI_DOMAIN_NAME}"
  echo "--- remote script ---"
  printf '%s\n' "$REMOTE_SCRIPT"
  exit 0
fi

PARAMS_FILE="$(mktemp)"
jq -n --arg commands "$REMOTE_SCRIPT" '{commands: [$commands]}' >"$PARAMS_FILE"

COMMAND_ID="$($AWS_BIN ssm send-command \
  --region "$AWS_REGION" \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --comment "Refresh llm-wiki runtime env from SSM" \
  --parameters "file://${PARAMS_FILE}" \
  --query Command.CommandId \
  --output text)"

rm -f "$PARAMS_FILE"

echo "Instance: ${INSTANCE_ID}"
echo "Domain: ${WIKI_DOMAIN_NAME}"
echo "Command: ${COMMAND_ID}"

$AWS_BIN ssm wait command-executed --region "$AWS_REGION" --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID"
$AWS_BIN ssm get-command-invocation \
  --region "$AWS_REGION" \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' \
  --output json
