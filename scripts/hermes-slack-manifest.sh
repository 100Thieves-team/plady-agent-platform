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
HERMES_IMAGE="${HERMES_IMAGE:-nousresearch/hermes-agent:v2026.6.19}"
HERMES_PLATFORM="${HERMES_PLATFORM:-linux/amd64}"
APP_NAME="${APP_NAME:-Plady Hermes}"

# Entrypoint is `hermes`; override the default `gateway run` command with the
# `slack manifest` subcommand (available v0.8.0+). Ephemeral container, no volume.
# On boot the image prints a "Syncing bundled skills..." banner before the JSON,
# so capture everything and emit only from the first `{` — leaving clean JSON on
# stdout (safe to redirect to a file). On failure (no JSON), dump the raw output.
out="$(docker run --rm -i --platform "$HERMES_PLATFORM" \
  "$HERMES_IMAGE" slack manifest --name "$APP_NAME" 2>&1)"
json="$(printf '%s\n' "$out" | awk '/^[[:space:]]*\{/{p=1} p')"
if [ -n "$json" ]; then
  printf '%s\n' "$json"
else
  printf '%s\n' "$out" >&2
  echo "ERROR: no manifest JSON in hermes output (see above)." >&2
  exit 1
fi
