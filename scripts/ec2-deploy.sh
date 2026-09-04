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
WIKI_DATA_KEY_PARAM="${WIKI_DATA_KEY_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/team-wiki-v2-deploy-key}"
TEAM_WIKI_V2_REPO_SSH="${TEAM_WIKI_V2_REPO_SSH:-git@github.com:100Thieves-team/team-wiki-v2.git}"
WIKI_SYNC_INTERVAL="${WIKI_SYNC_INTERVAL:-120}"
# Slack messaging platform (PLA-244-B). All optional: absent → Slack stays off.
SLACK_BOT_TOKEN_PARAM="${SLACK_BOT_TOKEN_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/slack-bot-token}"
SLACK_APP_TOKEN_PARAM="${SLACK_APP_TOKEN_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/slack-app-token}"
SLACK_ALLOWED_USERS_PARAM="${SLACK_ALLOWED_USERS_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/slack-allowed-users}"
# wiki-auth token issuer (docs/wiki-token-issuer.md). Both optional: either
# absent -> issuer stays off (503) and static-token auth is unchanged.
WIKI_TOKEN_PASSWORD_HASH_PARAM="${WIKI_TOKEN_PASSWORD_HASH_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/wiki-token-password-hash}"
WIKI_TOKEN_JWT_SECRET_PARAM="${WIKI_TOKEN_JWT_SECRET_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/wiki-token-jwt-secret}"
WIKI_SLACK_WEBHOOK_URL_PARAM="${WIKI_SLACK_WEBHOOK_URL_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/wiki-slack-webhook-url}"
N8N_ENCRYPTION_KEY_PARAM="${N8N_ENCRYPTION_KEY_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/n8n-encryption-key}"
WEBEX_WEBHOOK_SECRET_PARAM="${WEBEX_WEBHOOK_SECRET_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/webex-webhook-secret}"
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
SLACK_BOT_TOKEN="$(ssm_get "$SLACK_BOT_TOKEN_PARAM")"
SLACK_APP_TOKEN="$(ssm_get "$SLACK_APP_TOKEN_PARAM")"
SLACK_ALLOWED_USERS="$(ssm_get "$SLACK_ALLOWED_USERS_PARAM")"
WIKI_TOKEN_PASSWORD_HASH="$(ssm_get "$WIKI_TOKEN_PASSWORD_HASH_PARAM")"
WIKI_TOKEN_JWT_SECRET="$(ssm_get "$WIKI_TOKEN_JWT_SECRET_PARAM")"
# wiki 반영 시점 Slack 알림용 incoming webhook (optional, fail-open). The URL
# itself is the secret — NEVER echo it; report presence only.
WIKI_SLACK_WEBHOOK_URL="$(ssm_get "$WIKI_SLACK_WEBHOOK_URL_PARAM")"
[ "$WIKI_SLACK_WEBHOOK_URL" = "None" ] && WIKI_SLACK_WEBHOOK_URL=""
# n8n (Webex transcript ingest, docs/webex-ingest.md). Both optional: without the
# encryption key the n8n profile is simply not started. Presence only is logged.
N8N_ENCRYPTION_KEY="$(ssm_get "$N8N_ENCRYPTION_KEY_PARAM")"
[ "$N8N_ENCRYPTION_KEY" = "None" ] && N8N_ENCRYPTION_KEY=""
WEBEX_WEBHOOK_SECRET="$(ssm_get "$WEBEX_WEBHOOK_SECRET_PARAM")"
[ "$WEBEX_WEBHOOK_SECRET" = "None" ] && WEBEX_WEBHOOK_SECRET=""
if [ -n "$N8N_ENCRYPTION_KEY" ]; then
  DC+=(--profile n8n)
  echo "  n8n: on (encryption key present; webex secret $([ -n "$WEBEX_WEBHOOK_SECRET" ] && echo present || echo ABSENT))"
else
  echo "  n8n: off (${N8N_ENCRYPTION_KEY_PARAM} absent)"
fi
if [ -n "$WIKI_SLACK_WEBHOOK_URL" ]; then
  echo "  wiki slack notify: on (webhook present)"
else
  echo "  wiki slack notify: off (${WIKI_SLACK_WEBHOOK_URL_PARAM} absent)"
fi

[ -n "$HERMES_API_SERVER_KEY" ] && [ "$HERMES_API_SERVER_KEY" != "None" ] \
  || { echo "FATAL: ${HERMES_KEY_PARAM} missing/undecryptable" >&2; exit 1; }
[ -n "$MCP_BEARER_TOKEN" ] && [ "$MCP_BEARER_TOKEN" != "None" ] \
  || { echo "FATAL: ${MCP_TOKEN_PARAM} missing/undecryptable" >&2; exit 1; }
# Slack params are optional; normalize "None" (missing) to empty so absent
# tokens leave the platform off and an empty allowlist stays fail-closed.
[ "$SLACK_BOT_TOKEN" = "None" ] && SLACK_BOT_TOKEN=""
[ "$SLACK_APP_TOKEN" = "None" ] && SLACK_APP_TOKEN=""
[ "$SLACK_ALLOWED_USERS" = "None" ] && SLACK_ALLOWED_USERS=""
# Allowlist holds Slack Member IDs (no internal whitespace); strip any stray
# spaces/newlines so a "U1, U2" SSM value still matches.
SLACK_ALLOWED_USERS="$(printf '%s' "$SLACK_ALLOWED_USERS" | tr -d '[:space:]')"
# Both-or-neither: Socket Mode needs the bot (xoxb) AND app (xapp) token. A
# half-configured pair can't connect, so blank both to keep Slack cleanly off
# rather than booting a broken adapter.
if [ -z "$SLACK_BOT_TOKEN" ] || [ -z "$SLACK_APP_TOKEN" ]; then
  SLACK_BOT_TOKEN=""
  SLACK_APP_TOKEN=""
fi
# wiki-auth issuer: both-or-neither (hash 없이 secret만 있으면 발급 불가 상태가
# 모호해지므로 깨끗하게 off). NEVER echo the values.
[ "$WIKI_TOKEN_PASSWORD_HASH" = "None" ] && WIKI_TOKEN_PASSWORD_HASH=""
[ "$WIKI_TOKEN_JWT_SECRET" = "None" ] && WIKI_TOKEN_JWT_SECRET=""
if [ -z "$WIKI_TOKEN_PASSWORD_HASH" ] || [ -z "$WIKI_TOKEN_JWT_SECRET" ]; then
  WIKI_TOKEN_PASSWORD_HASH=""
  WIKI_TOKEN_JWT_SECRET=""
  echo "  wiki token issuer: off (${WIKI_TOKEN_PASSWORD_HASH_PARAM} / ${WIKI_TOKEN_JWT_SECRET_PARAM} absent; static token only)"
else
  echo "  wiki token issuer: on (password-hash + jwt-secret present)"
fi
# Codex (openai-codex) provider auth is a device-code OAuth session persisted to
# the hermes-home volume (/opt/data/auth.json), written once by a human via
# `hermes auth add openai-codex` — NOT an SSM secret. Nothing to inject here; the
# config-init merge sets model.provider declaratively. See docs/hermes-gateway.md.
echo "  hermes key: present | mcp token: present | codex auth: device-code OAuth in hermes-home volume (not env)"
if [ -n "$SLACK_BOT_TOKEN" ] && [ -n "$SLACK_APP_TOKEN" ]; then
  if [ -n "$SLACK_ALLOWED_USERS" ]; then slack_state="enabled (allowlist set)"; else slack_state="enabled (allowlist EMPTY -> all users denied)"; fi
else
  slack_state="off (bot/app token absent)"
fi
echo "  slack: ${slack_state}"

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
TEAM_WIKI_V2_REPO_SSH=${TEAM_WIKI_V2_REPO_SSH}
TEAM_WIKI_V2_DEPLOY_KEY_B64=${TEAM_WIKI_V2_DEPLOY_KEY_B64}
WIKI_SYNC_INTERVAL=${WIKI_SYNC_INTERVAL}
SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
SLACK_APP_TOKEN=${SLACK_APP_TOKEN}
SLACK_ALLOWED_USERS=${SLACK_ALLOWED_USERS}
WIKI_TOKEN_PASSWORD_HASH=${WIKI_TOKEN_PASSWORD_HASH}
WIKI_TOKEN_JWT_SECRET=${WIKI_TOKEN_JWT_SECRET}
WIKI_SLACK_WEBHOOK_URL=${WIKI_SLACK_WEBHOOK_URL}
N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
WEBEX_WEBHOOK_SECRET=${WEBEX_WEBHOOK_SECRET}
ENV
chmod 600 "$ENV_FILE"

# --- 4. ECR login + pull + up ---------------------------------------------
log "ECR login ${ECR_REGISTRY}"
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "$ECR_REGISTRY"

log "Pulling images"
"${DC[@]}" pull

# --- 4b. Hermes config merge (model.provider + mcp_servers, PLA-244/PLA-277) ---
# Merge the runtime backend selection (model.provider: openai-codex) and the
# llm-wiki MCP server into the hermes config inside the hermes-home volume
# (~/.hermes/config.yaml == /opt/data/config.yaml) before the gateway starts, so
# its first boot already sees both. Idempotent and surgical: the one-shot
# hermes-config-init service leaf-`set`s only model.provider/default,
# mcp_servers.llm-wiki and the slack keys, preserving any human-placed keys. No
# secret is written — the MCP token is injected to the gateway as
# LLM_WIKI_MCP_BEARER_TOKEN env and resolved from the config placeholder at
# connect-time, and the Codex provider credential is the device-code OAuth
# session in /opt/data/auth.json (human-written, not touched here).
# See docs/hermes-gateway.md.
log "Merging hermes config (model.provider=openai-codex + mcp_servers.llm-wiki) into the hermes-home config"
# -T: this runs under SSM Run Command (no TTY); `compose run` allocates a
# pseudo-TTY by default and would abort with "the input device is not a TTY".
# Matches the `exec -T` smoke checks below.
"${DC[@]}" run -T --rm hermes-config-init

# --- 4c. n8n workflows: repo n8n/workflows/ is the SSOT ---------------------
# Import overwrites workflows by id (credentials live only in the DB and are
# untouched) and marks the ingest workflow active; the `up` below then starts
# n8n, which registers the webhook. This runs BEFORE the stack comes up and with
# n8n stopped: the import CLI and the server share one SQLite file, and running
# both at once (first deploy did) fails on the database lock. Skipped when the
# n8n profile is off.
if printf '%s\n' "${DC[@]}" | grep -qx 'n8n'; then
  log "Importing n8n workflows from n8n/workflows/ (n8n stopped meanwhile)"
  "${DC[@]}" stop n8n >/dev/null 2>&1 || true
  "${DC[@]}" run -T --rm n8n import:workflow --separate --input=/workflows
  "${DC[@]}" run -T --rm n8n update:workflow --id=webex-transcript-ingest --active=true
fi

log "Bringing the stack up"
"${DC[@]}" up -d --remove-orphans

# wiki-auth bind-mounts docker/wiki-auth/app.py (shipped by the workflow next to
# compose.ec2.yaml). A content-only change to that file does NOT change the
# container config, so `up -d` would leave the old process running the old code —
# force-recreate the (tiny) sidecar every deploy so it always runs the shipped file.
log "Recreating wiki-auth to load the shipped app.py"
"${DC[@]}" up -d --force-recreate wiki-auth

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

# --- 6. Image hygiene ------------------------------------------------------
# Every deploy pulls two ~200 MB images tagged by commit; nothing removed the
# old ones and the 30 GB root disk hit 92% after two weeks (62 stale tags).
# Keep the last three days for a quick rollback, drop the rest. Only images no
# container references are touched, so the running stack is unaffected.
log "Pruning images older than 72h"
docker image prune -af --filter "until=72h" --format '{{.Size}}' 2>/dev/null | tail -1 || true
df -h / | tail -1
