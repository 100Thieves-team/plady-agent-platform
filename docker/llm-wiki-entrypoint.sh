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

exec "$@"
