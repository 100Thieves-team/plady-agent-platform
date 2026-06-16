# wiki_diff — not a tool

## Decision

`wiki_diff` is not added as an MCP tool. Page diffs are handled via
`wiki_history` + `git diff` in bash.

## Context

A `wiki_diff` tool was proposed to show content changes between two
commits for a page. It would wrap `git diff <from> <to> -- <path>`.

## Why not

The engine's design principle: "a tool belongs in the engine if and
only if it requires stateful access that a skill cannot replicate."

`git diff` does not require stateful access. The wiki is a git repo.
The LLM can:

1. Call `wiki_history` to get commit hashes
2. Run `git diff` via bash

This is a two-step workflow, not a stateful operation. Adding a tool
for it would be a thin wrapper that violates the design principle and
inflates the tool surface.

## Alternative

The content skill documents the workflow:

```
wiki_history(slug: "<slug>", limit: 2)
```

Then in bash:

```bash
git -C <repo_root> diff <from_hash> <to_hash> -- wiki/<slug>.md
```

## Consequences

- Tool count stays at 18
- No new code to maintain
- The LLM learns the git-native workflow
- If this becomes a recurring pain point, it can be promoted to a
  tool later
