#!/usr/bin/env sh
set -eu

: "${LLM_WIKI_NAME:=100thieves}"
: "${LLM_WIKI_DESCRIPTION:=100 Thieves team LLM Wiki}"
: "${LLM_WIKI_CONFIG:=/config/config.toml}"
: "${LLM_WIKI_WORKSPACE:=/workspace}"

mkdir -p "$(dirname "$LLM_WIKI_CONFIG")" "$LLM_WIKI_WORKSPACE"

# The Hugo scaffold is mounted at /workspace/site for preview only.
# Keep it out of the git-backed wiki repository managed by llm-wiki.
if [ ! -f "$LLM_WIKI_WORKSPACE/.gitignore" ]; then
  cat > "$LLM_WIKI_WORKSPACE/.gitignore" <<'GITIGNORE'
site/
public/
resources/
.hugo_build.lock
GITIGNORE
fi

if [ ! -f "$LLM_WIKI_WORKSPACE/wiki.toml" ]; then
  llm-wiki --config "$LLM_WIKI_CONFIG" spaces create "$LLM_WIKI_WORKSPACE" \
    --name "$LLM_WIKI_NAME" \
    --description "$LLM_WIKI_DESCRIPTION" \
    --set-default
else
  llm-wiki --config "$LLM_WIKI_CONFIG" spaces register "$LLM_WIKI_WORKSPACE" \
    --name "$LLM_WIKI_NAME" \
    --description "$LLM_WIKI_DESCRIPTION" || true
  llm-wiki --config "$LLM_WIKI_CONFIG" spaces set-default "$LLM_WIKI_NAME" || true
fi

# If the global config volume says the space already exists but the workspace was
# recreated, llm-wiki only re-registers it. Make the bind-mounted workspace
# explicitly git-backed in that case too.
if [ ! -d "$LLM_WIKI_WORKSPACE/.git" ]; then
  git -C "$LLM_WIKI_WORKSPACE" init
fi

# The bind-mounted wiki repository may be owned by the host user (for example
# ec2-user) while the container runs as root.
git config --global --add safe.directory "$LLM_WIKI_WORKSPACE" || true

git -C "$LLM_WIKI_WORKSPACE" config user.name "llm-wiki"
git -C "$LLM_WIKI_WORKSPACE" config user.email "llm-wiki@localhost"

if ! git -C "$LLM_WIKI_WORKSPACE" rev-parse --verify HEAD >/dev/null 2>&1 || \
  [ -n "$(git -C "$LLM_WIKI_WORKSPACE" status --porcelain)" ]; then
  git -C "$LLM_WIKI_WORKSPACE" add -A
  git -C "$LLM_WIKI_WORKSPACE" diff --cached --quiet || \
    git -C "$LLM_WIKI_WORKSPACE" commit -m "create: $LLM_WIKI_NAME"
fi

exec "$@"
