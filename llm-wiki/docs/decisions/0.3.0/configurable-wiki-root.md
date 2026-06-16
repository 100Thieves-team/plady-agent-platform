---
title: "Configurable wiki_root"
summary: "wiki_root field in wiki.toml + spaces register command — adopting repos where content already lives in a non-standard directory."
status: accepted
date: "2026-05-01"
---

# Configurable wiki_root

## Context

All hardcoded paths in the engine assumed the wiki content directory was
`<repo>/wiki/`. Adopting an existing repository where pages already live
under `docs/`, `content/`, `skills/`, or any other name required manually
restructuring that repo. There was also no way to register an existing repo
without creating files and making a git commit.

## Decision

1. **`wiki_root` field in `wiki.toml`** — optional string, default `"wiki"`.
   Parsed by `WikiConfig`; absent key behaves identically to v0.2.x.

2. **`mount_space` reads `wiki.toml`** — `WikiEngine::build` calls
   `config::load_wiki(&repo_root)` and joins `wiki_cfg.wiki_root` instead of
   the hard-coded literal `"wiki"`. `SpaceContext.wiki_root: PathBuf` is the
   single source of truth; all callers (`ops/content.rs`, `mcp/handlers.rs`,
   `mcp/mod.rs`) derive the path from it.

3. **`validate_wiki_root`** — called at create/register time. Rejects: empty
   string, absolute path, `..` components, reserved dirs (`inbox`, `raw`,
   `schemas`), non-existent directory, and paths that resolve outside the repo
   root after `canonicalize`.

4. **`spaces register` / `wiki_spaces_register`** — new CLI subcommand and MCP
   tool that registers an existing repo without creating files or commits.
   Conflict rule: `--wiki-root` flag errors if `wiki.toml` already declares a
   different value (user edits `wiki.toml` manually).

## Alternatives Considered

**Symlink `wiki/` → custom dir** — works but invisible to the engine and
fragile on Windows. Rejected.

**`wiki_root` in global config per entry** — would mean the global registry
carries content-layout details. Rejected in favour of keeping layout in
`wiki.toml` (repo-local, committed, shared across machines).

**Auto-detect content dir** — heuristic; ambiguous when multiple non-reserved
directories exist. Rejected.

## Consequences

- Zero behaviour change for existing wikis (`wiki_root` absent → `"wiki"`).
- `spaces create --wiki-root <dir>` and `spaces register` enable adoption of
  non-standard repos.
- `wiki.toml` only writes `wiki_root` when it differs from the default,
  keeping existing files unchanged.
- `SpaceContext.wiki_root` is now the canonical path reference; hardcoded
  `.join("wiki")` is eliminated from the codebase.
