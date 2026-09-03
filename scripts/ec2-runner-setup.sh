#!/usr/bin/env bash
# ec2-runner-setup.sh — org-level self-hosted GitHub Actions runner on the
# platform EC2 (review-swarm 실행용). Runs as root on the box, shipped the same
# way as ec2-deploy.sh (base64 through `aws ssm send-command`; no repo checkout).
#
#   bash ec2-runner-setup.sh prepare    # idempotent host prep: disk, swap, git,
#                                       #   node, runner user, runner tarball, claude CLI
#   bash ec2-runner-setup.sh register   # config.sh + systemd service. Needs the
#                                       #   registration token in SSM (see below)
#   bash ec2-runner-setup.sh env        # (re)write the runner's .env from SSM
#   bash ec2-runner-setup.sh doctor     # versions, service state, one tiny
#                                       #   `claude -p` round trip as the runner user
#   bash ec2-runner-setup.sh remove     # stop + uninstall the service (GitHub-side
#                                       #   removal is done from the org UI / API)
#
# Secrets: never printed. Both come from SSM Parameter Store through the
# instance role (AmazonSSMManagedInstanceCore grants ssm:GetParameter):
#   /plady/agent-platform/<env>/gha-runner-registration-token  short-lived (1h),
#       minted with `gh api -X POST orgs/<org>/actions/runners/registration-token`
#       (needs admin:org) and deleted after `register`.
#   /plady/agent-platform/<env>/claude-code-oauth-token        the subscription
#       token the platform already uses; lands in the runner's `.env` as
#       CLAUDE_CODE_OAUTH_TOKEN so `claude -p` works headless without a login.
#
# Sizing: t3.small (2 GB, no swap by default). `prepare` adds a 2 GB swapfile;
# review-swarm engine.concurrency must stay small on this box (2 in our configs).
set -euo pipefail

PHASE="${1:-prepare}"

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
PLATFORM_ENV="${PLATFORM_ENV:-dev}"
GITHUB_ORG="${GITHUB_ORG:-100Thieves-team}"

RUNNER_USER="${RUNNER_USER:-actions-runner}"
RUNNER_HOME="/home/${RUNNER_USER}"
RUNNER_DIR="${RUNNER_HOME}/actions-runner"
RUNNER_VERSION="${RUNNER_VERSION:-2.337.0}"
# sha256 of actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz, from the release notes.
RUNNER_SHA256="${RUNNER_SHA256:-70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613}"
RUNNER_NAME="${RUNNER_NAME:-agent-platform-ec2}"
RUNNER_LABELS="${RUNNER_LABELS:-self-hosted,review-swarm,linux,ec2}"

CLAUDE_CODE_VERSION="${CLAUDE_CODE_VERSION:-2.1.259}"
SWAP_MB="${SWAP_MB:-2048}"

REG_TOKEN_PARAM="${REG_TOKEN_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/gha-runner-registration-token}"
CLAUDE_TOKEN_PARAM="${CLAUDE_TOKEN_PARAM:-/plady/agent-platform/${PLATFORM_ENV}/claude-code-oauth-token}"

log() { printf '\n==> %s\n' "$*"; }
as_runner() { sudo -u "$RUNNER_USER" -H env PATH="${RUNNER_HOME}/.npm-global/bin:/usr/local/bin:/usr/bin:/bin" "$@"; }
ssm_get() {
  aws ssm get-parameter --region "$AWS_REGION" --name "$1" --with-decryption \
    --query Parameter.Value --output text 2>/dev/null || true
}

# ── prepare ───────────────────────────────────────────────────────────────────
prepare() {
  log "Disk: reclaim unused docker images (running containers keep theirs)"
  df -h / | tail -1
  docker image prune -af --filter "until=72h" >/dev/null 2>&1 || true
  df -h / | tail -1

  if ! swapon --show | grep -q '^/swapfile'; then
    log "Swap: ${SWAP_MB} MB swapfile"
    if [ ! -f /swapfile ]; then
      fallocate -l "${SWAP_MB}M" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count="$SWAP_MB" status=none
      chmod 600 /swapfile
      mkswap /swapfile >/dev/null
    fi
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    sysctl -q -w vm.swappiness=10
    echo 'vm.swappiness=10' > /etc/sysctl.d/90-swappiness.conf
  fi
  free -m | sed -n '1,3p'

  log "Packages: git, node ${RUNNER_NODE_MAJOR:-22}, libicu (runner dependency)"
  dnf install -y -q git nodejs22 nodejs22-npm libicu >/dev/null
  # AL2023 ships versioned binaries; make the bare names resolve for jobs.
  for b in node npm npx; do
    if ! command -v "$b" >/dev/null 2>&1 && [ -x "/usr/bin/${b}-22" ]; then
      ln -sf "/usr/bin/${b}-22" "/usr/bin/${b}"
    fi
  done
  git --version; node -v; npm -v

  if ! id "$RUNNER_USER" >/dev/null 2>&1; then
    log "User: ${RUNNER_USER}"
    useradd -m -s /bin/bash "$RUNNER_USER"
  fi

  if [ ! -x "${RUNNER_DIR}/config.sh" ] || ! grep -q "^${RUNNER_VERSION}$" "${RUNNER_DIR}/.runner-version" 2>/dev/null; then
    log "Runner: actions/runner v${RUNNER_VERSION}"
    tarball="/tmp/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
    curl -fsSL -o "$tarball" \
      "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-x64-${RUNNER_VERSION}.tar.gz"
    echo "${RUNNER_SHA256}  ${tarball}" | sha256sum -c - >/dev/null
    install -d -o "$RUNNER_USER" -g "$RUNNER_USER" "$RUNNER_DIR"
    tar -xzf "$tarball" -C "$RUNNER_DIR"
    chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_DIR"
    echo "$RUNNER_VERSION" > "${RUNNER_DIR}/.runner-version"
    rm -f "$tarball"
    "${RUNNER_DIR}/bin/installdependencies.sh" >/dev/null 2>&1 || true
  fi
  ls "${RUNNER_DIR}/config.sh" >/dev/null && echo "  runner ${RUNNER_VERSION} at ${RUNNER_DIR}"

  log "Claude Code CLI ${CLAUDE_CODE_VERSION} for ${RUNNER_USER} (npm prefix ~/.npm-global)"
  as_runner mkdir -p "${RUNNER_HOME}/.npm-global"
  as_runner npm config set prefix "${RUNNER_HOME}/.npm-global" >/dev/null
  if [ "$(as_runner claude --version 2>/dev/null | awk '{print $1}')" != "$CLAUDE_CODE_VERSION" ]; then
    as_runner npm install -g --no-audit --no-fund "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" >/dev/null
  fi
  as_runner claude --version
  grep -q 'npm-global/bin' "${RUNNER_HOME}/.bashrc" 2>/dev/null || \
    echo 'export PATH="$HOME/.npm-global/bin:$PATH"' >> "${RUNNER_HOME}/.bashrc"

  log "PREPARE OK"
}

# ── env ───────────────────────────────────────────────────────────────────────
# The runner loads `.env` (KEY=VALUE) and `.path` from its root into every job.
# config.sh writes both; we rewrite .env afterwards with what jobs need.
write_env() {
  local claude_token
  claude_token="$(ssm_get "$CLAUDE_TOKEN_PARAM")"
  [ -n "$claude_token" ] || { echo "no value at ${CLAUDE_TOKEN_PARAM}" >&2; return 1; }
  umask 077
  cat > "${RUNNER_DIR}/.env" <<ENV
HOME=${RUNNER_HOME}
LANG=C.UTF-8
CLAUDE_CODE_OAUTH_TOKEN=${claude_token}
DISABLE_AUTOUPDATER=1
DISABLE_TELEMETRY=1
DISABLE_ERROR_REPORTING=1
ENV
  chown "$RUNNER_USER:$RUNNER_USER" "${RUNNER_DIR}/.env"
  # Make the runner user's npm global bin visible to jobs (claude lives there).
  if [ -f "${RUNNER_DIR}/.path" ] && ! grep -q 'npm-global/bin' "${RUNNER_DIR}/.path"; then
    sed -i "s#^#${RUNNER_HOME}/.npm-global/bin:#" "${RUNNER_DIR}/.path"
  elif [ ! -f "${RUNNER_DIR}/.path" ]; then
    echo "${RUNNER_HOME}/.npm-global/bin:/usr/local/bin:/usr/bin:/bin" > "${RUNNER_DIR}/.path"
    chown "$RUNNER_USER:$RUNNER_USER" "${RUNNER_DIR}/.path"
  fi
  echo "  .env written (CLAUDE_CODE_OAUTH_TOKEN present: yes)"
}

# ── register ──────────────────────────────────────────────────────────────────
register() {
  [ -x "${RUNNER_DIR}/config.sh" ] || { echo "run 'prepare' first" >&2; exit 1; }
  local token
  token="$(ssm_get "$REG_TOKEN_PARAM")"
  [ -n "$token" ] || { echo "no registration token at ${REG_TOKEN_PARAM} — mint one and put it there first" >&2; exit 1; }

  if [ -f "${RUNNER_DIR}/.runner" ]; then
    log "Runner already configured; re-registering with --replace"
    systemctl stop "actions.runner.${GITHUB_ORG}.${RUNNER_NAME}.service" 2>/dev/null || true
  fi
  log "Registering ${RUNNER_NAME} [${RUNNER_LABELS}] to https://github.com/${GITHUB_ORG}"
  (cd "$RUNNER_DIR" && as_runner ./config.sh --unattended --replace \
      --url "https://github.com/${GITHUB_ORG}" --token "$token" \
      --name "$RUNNER_NAME" --labels "$RUNNER_LABELS" --work _work)
  unset token

  write_env

  log "systemd service"
  (cd "$RUNNER_DIR" && ./svc.sh install "$RUNNER_USER" >/dev/null && ./svc.sh start >/dev/null)
  sleep 3
  (cd "$RUNNER_DIR" && ./svc.sh status | sed -n '1,12p')

  # Best effort: the token is single-purpose and expires in an hour anyway.
  aws ssm delete-parameter --region "$AWS_REGION" --name "$REG_TOKEN_PARAM" >/dev/null 2>&1 \
    && echo "  registration token deleted from SSM" \
    || echo "  (registration token not deleted here — delete ${REG_TOKEN_PARAM} from the workstation)"
  log "REGISTER OK"
}

# ── doctor ────────────────────────────────────────────────────────────────────
doctor() {
  log "Host"; free -m | sed -n '2,3p'; df -h / | tail -1
  log "Tooling"; git --version; node -v; as_runner claude --version
  log "Service"
  (cd "$RUNNER_DIR" && ./svc.sh status 2>/dev/null | sed -n '1,8p') || echo "  not installed"
  log "Runner env file"
  [ -f "${RUNNER_DIR}/.env" ] && sed -E 's/^(CLAUDE_CODE_OAUTH_TOKEN)=.*/\1=<set>/' "${RUNNER_DIR}/.env" || echo "  missing"
  log "claude -p round trip as ${RUNNER_USER} (one tiny call)"
  set -a; . "${RUNNER_DIR}/.env"; set +a
  as_runner env CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN" DISABLE_AUTOUPDATER=1 \
    timeout 90 claude -p 'Reply with exactly: RUNNER-OK' --output-format text 2>&1 | tail -3
}

# ── remove ────────────────────────────────────────────────────────────────────
remove() {
  (cd "$RUNNER_DIR" && ./svc.sh stop >/dev/null 2>&1; ./svc.sh uninstall >/dev/null 2>&1) || true
  echo "service removed; delete the runner from the org (Settings → Actions → Runners) to finish"
}

case "$PHASE" in
  prepare)  prepare ;;
  register) register ;;
  env)      write_env ;;
  doctor)   doctor ;;
  remove)   remove ;;
  *) echo "usage: $0 {prepare|register|env|doctor|remove}" >&2; exit 2 ;;
esac
