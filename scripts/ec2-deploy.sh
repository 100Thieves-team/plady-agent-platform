#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PLA-273 EC2 origin deploy (runs ON the instance, invoked via SSM Run Command).
#
# Unmanned deploy for the agent.plady.io platform: no inbound SSH. The GitHub
# Actions workflow (.github/workflows/deploy-agent-platform.yml) writes
# compose.ec2.yaml + this script to the box, then runs this with the image
# coordinates in the environment. It:
#   1. installs Docker + the compose plugin if missing (Amazon Linux 2023),
#   2. reads runtime secrets from SSM (instance role + aws/ssm KMS),
#   3. renders .env.ec2 (never committed; chmod 600),
#   4. logs in to ECR, pulls the pinned images, and brings the stack up,
#   5. waits for container health and runs internal smoke checks.
#
# Idempotent: safe to re-run for every push (named volumes persist state).
#
# Required env (set by the workflow):
#   AWS_REGION, ECR_REGISTRY, LLM_WIKI_REPO, WIKI_UI_REPO, IMAGE_TAG
# Optional env (defaults shown):
#   APP_DIR=/opt/plady-agent-platform
#   PLATFORM_ENV=dev
#   HERMES_KEY_PARAM=/plady/agent-platform/<env>/hermes-api-server-key
#   MCP_TOKEN_PARAM=/plady/agent-platform/<env>/llm-wiki-mcp-bearer-token
#   ANTHROPIC_KEY_PARAM=/plady/agent-platform/<env>/anthropic-api-key  (optional)
#   WIKI_PUBLIC_HOST=wiki.agent.plady.io
#   MCP_PUBLIC_HOST=mcp.agent.plady.io
#   HERMES_PUBLIC_HOST=hermes.agent.plady.io
# ---------------------------------------------------------------------------
set -euo pipefail

log() { printf '\n=== %s ===\n' "$*"; }

AWS_REGION="${AWS_REGION:?AWS_REGION required}"
ECR_REGISTRY="${ECR_REGISTRY:?ECR_REGISTRY required}"
LLM_WIKI_REPO="${LLM_WIKI_REPO:?LLM_WIKI_REPO required}"
WIKI_UI_REPO="${WIKI_UI_REPO:?WIKI_UI_REPO required}"
IMAGE_TAG="${IMAGE_TAG:?IMAGE_TAG required}"

APP_DIR="${APP_DIR:-/opt/plady-agent-platform}"
PLATFORM_ENV="${PLATFORM_ENV:-dev}"
HERMES_KEY_PARAM="${HERMES_KEY_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/hermes-api-server-key}"
MCP_TOKEN_PARAM="${MCP_TOKEN_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/llm-wiki-mcp-bearer-token}"
ANTHROPIC_KEY_PARAM="${ANTHROPIC_KEY_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/anthropic-api-key}"
WIKI_PUBLIC_HOST="${WIKI_PUBLIC_HOST:-wiki.agent.plady.io}"
MCP_PUBLIC_HOST="${MCP_PUBLIC_HOST:-mcp.agent.plady.io}"
HERMES_PUBLIC_HOST="${HERMES_PUBLIC_HOST:-hermes.agent.plady.io}"

COMPOSE_FILE="${APP_DIR}/compose.ec2.yaml"
ENV_FILE="${APP_DIR}/.env.ec2"
DC=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" --profile hermes)

# --- 1. Docker + compose plugin -------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker (Amazon Linux 2023)"
  dnf install -y docker
fi
systemctl enable --now docker

if ! docker compose version >/dev/null 2>&1; then
  log "Installing docker compose plugin"
  arch="$(uname -m)"; case "$arch" in x86_64) ca=x86_64 ;; aarch64) ca=aarch64 ;; *) ca="$arch" ;; esac
  install -d /usr/libexec/docker/cli-plugins
  curl -fsSL -o /usr/libexec/docker/cli-plugins/docker-compose \
    "https://github.com/docker/compose/releases/download/v2.39.4/docker-compose-linux-${ca}"
  chmod +x /usr/libexec/docker/cli-plugins/docker-compose
fi
docker --version
docker compose version

# --- 2. Secrets from SSM ---------------------------------------------------
ssm_get() {
  aws ssm get-parameter --region "$AWS_REGION" --name "$1" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || true
}

log "Reading runtime secrets from SSM"
HERMES_API_SERVER_KEY="$(ssm_get "$HERMES_KEY_PARAM")"
MCP_BEARER_TOKEN="$(ssm_get "$MCP_TOKEN_PARAM")"
ANTHROPIC_API_KEY="$(ssm_get "$ANTHROPIC_KEY_PARAM")"

[ -n "$HERMES_API_SERVER_KEY" ] && [ "$HERMES_API_SERVER_KEY" != "None" ] \
  || { echo "FATAL: ${HERMES_KEY_PARAM} missing/undecryptable" >&2; exit 1; }
[ -n "$MCP_BEARER_TOKEN" ] && [ "$MCP_BEARER_TOKEN" != "None" ] \
  || { echo "FATAL: ${MCP_TOKEN_PARAM} missing/undecryptable" >&2; exit 1; }
[ "$ANTHROPIC_API_KEY" = "None" ] && ANTHROPIC_API_KEY=""
echo "  hermes key: present | mcp token: present | anthropic key: $([ -n "$ANTHROPIC_API_KEY" ] && echo present || echo 'absent (provider unconfigured)')"

# --- 3. Render .env.ec2 (secret-grade; never committed) --------------------
log "Rendering ${ENV_FILE}"
mkdir -p "$APP_DIR"
umask 077
cat >"$ENV_FILE" <<ENV
LLM_WIKI_IMAGE=${ECR_REGISTRY}/${LLM_WIKI_REPO}:${IMAGE_TAG}
WIKI_UI_IMAGE=${ECR_REGISTRY}/${WIKI_UI_REPO}:${IMAGE_TAG}
WIKI_DOMAIN_NAME=${WIKI_PUBLIC_HOST}
MCP_PUBLIC_HOST=${MCP_PUBLIC_HOST}
HERMES_PUBLIC_HOST=${HERMES_PUBLIC_HOST}
MCP_BEARER_TOKEN=${MCP_BEARER_TOKEN}
HERMES_API_SERVER_KEY=${HERMES_API_SERVER_KEY}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
ENV
chmod 600 "$ENV_FILE"

# --- 4. ECR login + pull + up ---------------------------------------------
log "ECR login ${ECR_REGISTRY}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

log "Pulling images"
"${DC[@]}" pull

log "Bringing the stack up"
"${DC[@]}" up -d --remove-orphans

# --- 5. Health gate --------------------------------------------------------
log "Container status"
"${DC[@]}" ps

log "Internal smoke (inside the compose network)"
fail=0

# wiki UI (Hugo can take a few seconds to render on first boot)
ok=0
for i in $(seq 1 30); do
  if "${DC[@]}" exec -T caddy wget -q -O /dev/null http://wiki-ui:1313/ 2>/dev/null; then ok=1; break; fi
  sleep 2
done
[ "$ok" = 1 ] && echo "  wiki-ui: OK" || { echo "  wiki-ui: FAIL"; fail=1; }

# mcp-proxy: no bearer -> 401
code="$("${DC[@]}" exec -T caddy wget -q -S -O /dev/null http://mcp-proxy:18765/mcp 2>&1 | awk '/HTTP\//{print $2; exit}')"
[ "$code" = "401" ] && echo "  mcp-proxy no-auth: 401 OK" || { echo "  mcp-proxy no-auth: got '${code}', want 401"; fail=1; }

# hermes: /health -> ok
if "${DC[@]}" exec -T hermes-gateway curl -fsS --max-time 10 http://localhost:8642/health 2>/dev/null | grep -q '"status":"ok"'; then
  echo "  hermes /health: OK"
else
  echo "  hermes /health: FAIL"; fail=1
fi

[ "$fail" = 0 ] && log "DEPLOY OK" || { log "DEPLOY DEGRADED — see above"; exit 1; }
