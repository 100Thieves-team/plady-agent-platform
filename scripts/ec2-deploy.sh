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
#   CLAUDE_OAUTH_PARAM=/plady/agent-platform/<env>/claude-code-oauth-token (optional)
#   WIKI_DATA_KEY_PARAM=/plady/agent-platform/<env>/team-wiki-v2-deploy-key (optional;
#     write-enabled deploy key for team-wiki-v2. Absent -> wiki backing disabled, sidecar idles)
#   TEAM_WIKI_V2_REPO_SSH=git@github.com:100Thieves-team/team-wiki-v2.git
#   WIKI_SYNC_INTERVAL=120
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
CLAUDE_OAUTH_PARAM="${CLAUDE_OAUTH_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/claude-code-oauth-token}"
WIKI_DATA_KEY_PARAM="${WIKI_DATA_KEY_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/team-wiki-v2-deploy-key}"
TEAM_WIKI_V2_REPO_SSH="${TEAM_WIKI_V2_REPO_SSH:-git@github.com:100Thieves-team/team-wiki-v2.git}"
WIKI_SYNC_INTERVAL="${WIKI_SYNC_INTERVAL:-120}"
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
CLAUDE_CODE_OAUTH_TOKEN="$(ssm_get "$CLAUDE_OAUTH_PARAM")"

[ -n "$HERMES_API_SERVER_KEY" ] && [ "$HERMES_API_SERVER_KEY" != "None" ] \
  || { echo "FATAL: ${HERMES_KEY_PARAM} missing/undecryptable" >&2; exit 1; }
[ -n "$MCP_BEARER_TOKEN" ] && [ "$MCP_BEARER_TOKEN" != "None" ] \
  || { echo "FATAL: ${MCP_TOKEN_PARAM} missing/undecryptable" >&2; exit 1; }
[ "$CLAUDE_CODE_OAUTH_TOKEN" = "None" ] && CLAUDE_CODE_OAUTH_TOKEN=""
echo "  hermes key: present | mcp token: present | claude code oauth: $([ -n "$CLAUDE_CODE_OAUTH_TOKEN" ] && echo present || echo 'absent (provider unconfigured)')"

# team-wiki-v2 deploy key (PLA-275). Optional, like the Claude OAuth token: absent
# -> wiki backing disabled, the wiki-data-sync sidecar idles, the stack still
# comes up. Base64-encode (single line) so it survives the .env.ec2 heredoc and
# the compose interpolation; the sidecar decodes it. NEVER echo the value.
WIKI_DATA_DEPLOY_KEY="$(ssm_get "$WIKI_DATA_KEY_PARAM")"
[ "$WIKI_DATA_DEPLOY_KEY" = "None" ] && WIKI_DATA_DEPLOY_KEY=""
if [ -n "$WIKI_DATA_DEPLOY_KEY" ]; then
  TEAM_WIKI_V2_DEPLOY_KEY_B64="$(printf '%s' "$WIKI_DATA_DEPLOY_KEY" | base64 -w0)"
  echo "  wiki backing: enabled (team-wiki-v2 deploy key present)"
else
  TEAM_WIKI_V2_DEPLOY_KEY_B64=""
  echo "  wiki backing: disabled (${WIKI_DATA_KEY_PARAM} absent; sidecar idles, fill SSM + redeploy to enable)"
fi

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
CLAUDE_CODE_OAUTH_TOKEN=${CLAUDE_CODE_OAUTH_TOKEN}
TEAM_WIKI_V2_REPO_SSH=${TEAM_WIKI_V2_REPO_SSH}
TEAM_WIKI_V2_DEPLOY_KEY_B64=${TEAM_WIKI_V2_DEPLOY_KEY_B64}
WIKI_SYNC_INTERVAL=${WIKI_SYNC_INTERVAL}
ENV
chmod 600 "$ENV_FILE"

# --- 4. ECR login + pull + up ---------------------------------------------
log "ECR login ${ECR_REGISTRY}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

log "Pulling images"
"${DC[@]}" pull

# --- 4b. Hermes mcp_servers mapping (PLA-244) ------------------------------
# Merge the llm-wiki MCP server into the hermes config inside the hermes-home
# volume (~/.hermes/config.yaml == /opt/data/config.yaml) before the gateway
# starts, so its first boot already sees the tool. Idempotent and surgical: the
# one-shot hermes-config-init service rewrites only mcp_servers.llm-wiki and
# leaves the human-managed model/provider section intact. No secret is written —
# the token is injected to the gateway as LLM_WIKI_MCP_BEARER_TOKEN env and
# resolved from the config placeholder at connect-time. See docs/hermes-gateway.md.
log "Merging hermes mcp_servers mapping (llm-wiki) into the hermes-home config"
# -T: this runs under SSM Run Command (no TTY); `compose run` allocates a
# pseudo-TTY by default and would abort with "the input device is not a TTY".
# Matches the `exec -T` smoke checks below.
"${DC[@]}" run -T --rm hermes-config-init

log "Bringing the stack up"
"${DC[@]}" up -d --remove-orphans

# hermes reads config.yaml only at startup. On a redeploy where the image tag is
# unchanged, `up -d` leaves the running gateway as-is, so restart it to pick up
# any mcp_servers change merged above (cheap; the /health gate below retries
# through the ~70-tool boot).
log "Restarting hermes-gateway to load the MCP config"
"${DC[@]}" restart hermes-gateway

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

# mcp-proxy: no bearer -> 401. wget exits non-zero on a 401, and with
# `pipefail` that would abort the script under `set -e`, so swallow it with
# `|| true` — the assertion below is what actually judges the result.
code="$("${DC[@]}" exec -T caddy wget -q -S -O /dev/null http://mcp-proxy:18765/mcp 2>&1 | awk '/HTTP\//{print $2; exit}' || true)"
[ "$code" = "401" ] && echo "  mcp-proxy no-auth: 401 OK" || { echo "  mcp-proxy no-auth: got '${code}', want 401"; fail=1; }

# hermes: /health -> ok. Probe from caddy (busybox wget) over the compose
# network rather than `curl` inside hermes-gateway — keeps the smoke checks
# consistent and avoids assuming curl exists in the upstream image. This also
# exercises the caddy->hermes routing the public origin depends on. Retry:
# hermes bundles ~70 tools at boot and is not ready the instant `up -d` returns.
ok=0
for i in $(seq 1 30); do
  if "${DC[@]}" exec -T caddy wget -q -O - http://hermes-gateway:8642/health 2>/dev/null | grep -qE '"status":[[:space:]]*"ok"'; then ok=1; break; fi
  sleep 2
done
[ "$ok" = 1 ] && echo "  hermes /health: OK" || { echo "  hermes /health: FAIL"; fail=1; }

[ "$fail" = 0 ] && log "DEPLOY OK" || { log "DEPLOY DEGRADED — see above"; exit 1; }
