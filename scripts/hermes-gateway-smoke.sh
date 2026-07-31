#!/usr/bin/env bash
set -euo pipefail

# Smoke test for the Hermes Gateway OpenAI-compatible API server.
#
# Steps:
#   1. GET /health             -> expect {"status":"ok"} (no auth)
#   2. GET /v1/models (no key) -> expect 401 (proves the auth boundary)
#   3. GET /v1/models (Bearer) -> expect 200 + model list
#
# Auth key resolution (first match wins):
#   - HERMES_API_KEY env var (value, never commit it), OR
#   - SSM parameter named by TOKEN_PARAM (default the platform contract name).
#
# Note: step 3 also needs Hermes to have a working provider configured for the
# model list to be non-empty. Without provider credentials it may return 200
# with an empty list or a provider error; that is a provider-config issue, not a
# gateway failure. See docs/hermes-gateway.md.

HERMES_URL="${HERMES_URL:-http://localhost:8642}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
TOKEN_PARAM="${TOKEN_PARAM:-/plady/agent-platform/dev/hermes-api-server-key}"
AWS_BIN="${AWS_BIN:-aws}"

fail() { echo "FAIL: $*" >&2; exit 1; }

if [ -z "${HERMES_API_KEY:-}" ]; then
  echo "HERMES_API_KEY not set; resolving from SSM ${TOKEN_PARAM} (region ${AWS_REGION})" >&2
  HERMES_API_KEY="$($AWS_BIN ssm get-parameter \
    --region "$AWS_REGION" \
    --name "$TOKEN_PARAM" \
    --with-decryption \
    --query Parameter.Value \
    --output text)" \
    || fail "could not read ${TOKEN_PARAM} from SSM (set HERMES_API_KEY directly, or fix AWS creds/TOKEN_PARAM)"
fi

# A blank/missing key would send `Authorization: Bearer ` and mask a real
# misconfig, so refuse to run without a concrete value.
if [ -z "${HERMES_API_KEY:-}" ] || [ "$HERMES_API_KEY" = "None" ]; then
  fail "resolved Hermes API key is empty (set HERMES_API_KEY or a valid TOKEN_PARAM)"
fi

cleanup() { unset HERMES_API_KEY; }
trap cleanup EXIT

echo "== 1. GET ${HERMES_URL}/health (no auth)"
HEALTH="$(curl --noproxy "*" -fsS --max-time 10 "${HERMES_URL}/health")"
echo "  -> ${HEALTH}"
# Parse JSON and require status == ok exactly (a substring glob would pass on
# bodies like {"status":"degraded","detail":"ok"}).
printf '%s' "$HEALTH" | python3 -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get("status")=="ok" else 1)' \
  || fail "/health did not report status ok"
echo "  OK"

echo "== 2. GET ${HERMES_URL}/v1/models (no auth, expect 401)"
CODE="$(curl --noproxy "*" -sS -o /dev/null -w '%{http_code}' --max-time 10 \
  "${HERMES_URL}/v1/models" || true)"
echo "  -> HTTP ${CODE}"
[ "$CODE" = "401" ] || fail "unauthenticated /v1/models returned ${CODE}, expected 401"
echo "  OK"

echo "== 3. GET ${HERMES_URL}/v1/models (Bearer, expect 200)"
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"; cleanup' EXIT
CODE="$(curl --noproxy "*" -sS -o "$BODY_FILE" -w '%{http_code}' --max-time 20 \
  -H "Authorization: Bearer ${HERMES_API_KEY}" \
  "${HERMES_URL}/v1/models")"
echo "  -> HTTP ${CODE}"
[ "$CODE" = "200" ] || fail "authenticated /v1/models returned ${CODE}, expected 200 ($(cat "$BODY_FILE"))"

python3 - "$BODY_FILE" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
models = data.get("data") if isinstance(data, dict) else data
if not isinstance(models, list):  # e.g. {"data": null} on a provider error
    models = []
print(f"  model_count={len(models)}")
for m in models:
    print("  -", m.get("id", m) if isinstance(m, dict) else m)
PY
echo "  OK"

echo "All Hermes Gateway smoke checks passed."
