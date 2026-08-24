#!/usr/bin/env bash
# 정책서(상태-SSOT.yaml) → wiki/policy 게시 파이프라인 (5단계, C안 하이브리드).
#
#   render_wiki.py 로 마크다운 페이지들을 렌더 → team-wiki-v2 의 wiki/policy/ 에
#   반영 → 커밋/푸시 → (EC2 wiki-data-sync 가 <=120s 내 pull, wiki-ui 워처가
#   <=30s 내 클린 재빌드) → 검색 인덱스 재빌드.
#
# 사용:
#   scripts/sync-policy.sh              # 렌더 + 커밋/푸시 + 인덱스 재빌드
#   scripts/sync-policy.sh --dry-run    # 렌더만 하고 diff 를 보여준다
#   scripts/sync-policy.sh --skip-index # 인덱스 재빌드 생략
#
# 전제:
#   - interview-ddd 는 로컬 폴더(비 git). 렌더 입력의 버전은 yaml 내용 해시로 스탬프된다.
#   - 인덱스 재빌드는 AWS_PROFILE=plady-service 자격과 SSM 파라미터
#     /plady/agent-platform/dev/llm-wiki-mcp-bearer-token 을 쓴다 (mcp-call.py 규약).
#   - 렌더된 페이지 frontmatter 의 managed_by: harness 가 "직접 수정 금지" 표식이다.
#     사람이든 에이전트든 페이지가 아니라 yaml(또는 PRD)을 고친다.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DESIGN_DIR="${DESIGN_DIR:-$HOME/Desktop_nonsync/teams/100-thieves/interview-ddd/docs/design}"
WIKI_DIR="${WIKI_DIR:-$REPO_DIR/wiki-workspace}"
POLICY_DIR="$WIKI_DIR/wiki/policy"
MCP_URL="${MCP_URL:-https://mcp.agent.plady.io/mcp}"
TOKEN_PARAM="${TOKEN_PARAM:-/plady/agent-platform/dev/llm-wiki-mcp-bearer-token}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"

DRY_RUN=0
SKIP_INDEX=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-index) SKIP_INDEX=1 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

[ -f "$DESIGN_DIR/상태-SSOT.yaml" ] || { echo "상태-SSOT.yaml 이 없다: $DESIGN_DIR" >&2; exit 1; }
[ -d "$WIKI_DIR/.git" ] || { echo "wiki-workspace 가 git checkout 이 아니다: $WIKI_DIR" >&2; exit 1; }

# ── 1. 렌더 (PRD § 참조 드리프트 검증 포함; [drift] 경고는 stderr 로 나온다) ──
mkdir -p "$POLICY_DIR"
python3 "$DESIGN_DIR/render_wiki.py" \
  -i "$DESIGN_DIR/상태-SSOT.yaml" \
  -o "$POLICY_DIR" \
  --prd-dir "$WIKI_DIR/raw/product"

# ── 2. 게시 (커밋/푸시) ──
cd "$WIKI_DIR"
git add wiki/policy
if git diff --cached --quiet; then
  echo "변경 없음 — 게시 생략"
  exit 0
fi

if [ "$DRY_RUN" = 1 ]; then
  echo "── dry-run: 커밋하지 않는다. 변경 요약 ──"
  git diff --cached --stat
  git reset -q wiki/policy
  exit 0
fi

HASH=$(python3 -c "import json,sys;print(json.load(open('$POLICY_DIR/sync-manifest.json'))['source_hash'])")
git commit -q -m "harness: 정책서 sync — 상태-SSOT.yaml@${HASH}"
git push origin main
echo "푸시 완료 ($(git rev-parse --short HEAD)) — 사이드카 pull(<=120s) + wiki-ui 재빌드(<=30s) 후 라이브 반영"

# ── 3. 검색 인덱스 재빌드 (프로덕션 볼륨에 커밋이 도착한 뒤여야 의미가 있다) ──
if [ "$SKIP_INDEX" = 1 ]; then
  echo "--skip-index: 인덱스 재빌드 생략"
  exit 0
fi
echo "사이드카 pull 대기 (150s)..."
sleep 150
MCP_BEARER_TOKEN="$(aws ssm get-parameter --profile "${AWS_PROFILE:-plady-service}" --region "$AWS_REGION" \
  --name "$TOKEN_PARAM" --with-decryption --query Parameter.Value --output text)" \
  python3 "$REPO_DIR/scripts/mcp-call.py" --url "$MCP_URL" call wiki_index_rebuild --args '{}'
