#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Print the canonical Slack app manifest that the pinned hermes-agent image
# expects (scopes, event subscriptions, Socket Mode), straight from the source
# of truth — `hermes slack manifest` — instead of a hand-maintained copy that
# could drift from the image. Paste the output into
# https://api.slack.com/apps → "Create New App" → "From a manifest". PLA-244.
#
# Usage:
#   scripts/hermes-slack-manifest.sh                 # print manifest (JSON) to stdout
#   APP_NAME="Plady Hermes" scripts/hermes-slack-manifest.sh
#   scripts/hermes-slack-manifest.sh > slack-manifest.json   # save/commit if desired
#
# Requires Docker. Runs the hermes image one-shot; needs no secrets and writes
# nothing to the hermes-home volume.
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HERMES_IMAGE="${HERMES_IMAGE:-nousresearch/hermes-agent:v2026.4.3}"
HERMES_PLATFORM="${HERMES_PLATFORM:-linux/amd64}"
APP_NAME="${APP_NAME:-Plady Hermes}"

# Entrypoint is `hermes`; override the default `gateway run` command with the
# manifest subcommand. --no-supervise/-T keep it non-interactive. Uses an
# ephemeral container (no volume) so nothing persists.
exec docker run --rm -i --platform "$HERMES_PLATFORM" \
  "$HERMES_IMAGE" slack manifest --name "$APP_NAME"
