#!/usr/bin/env bash
# 팀원용: 비밀번호를 입력해 llm-wiki MCP 단기 토큰을 발급받는다.
# 계약: docs/wiki-token-issuer.md. 비밀번호는 stdin 프롬프트로만 받고(에코 없음)
# 인자/환경변수로 받지 않는다. 발급 토큰은 stdout 으로 export 라인만 출력한다.
#
# 사용:
#   eval "$(scripts/wiki-token.sh)"                     # 운영 (기본 12h)
#   eval "$(WIKI_MCP_ORIGIN=http://localhost:18765 scripts/wiki-token.sh)"  # 로컬
#   TTL_SECONDS=3600 scripts/wiki-token.sh              # 1시간짜리
set -euo pipefail

ORIGIN="${WIKI_MCP_ORIGIN:-https://mcp.agent.plady.io}"
TTL="${TTL_SECONDS:-43200}"

read -r -s -p "wiki token password: " PASSWORD </dev/tty
echo >&2

RESPONSE="$(printf '{"password": %s, "ttl_seconds": %s}' \
    "$(printf '%s' "$PASSWORD" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    "$TTL" \
  | curl -fsS -X POST "${ORIGIN}/auth/token" -H "Content-Type: application/json" -d @-)" \
  || { echo "발급 실패: ${ORIGIN}/auth/token 응답 오류 (비밀번호/발급기 구성 확인)" >&2; exit 1; }

TOKEN="$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
EXPIRES="$(printf '%s' "$RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin)["expires_at"])')"

echo "# expires_at: ${EXPIRES}" >&2
printf 'export MCP_BEARER_TOKEN=%q\n' "$TOKEN"
