---
title: "Decision: ops.rs — Shared Business Logic"
summary: "Extract duplicated CLI/MCP business logic into src/ops.rs."
status: accepted
date: "2025-07-18"
---

# Decision: ops.rs — Shared Business Logic

## Context

After Step 14 (MCP server), CLI (`main.rs`) and MCP (`mcp/handlers.rs`)
implemented the same business logic independently. Both resolved wikis,
called the same module functions, and used the same EngineManager
mutation pattern. The only differences were argument parsing and output
formatting.

A side-by-side comparison revealed:
- 13 of 15 operations had identical logic
- 2 divergences: CLI search and list were missing auto-recovery
  (MCP had it, CLI passed `None`)
- No single source of truth for business logic

## Decision

Extract all shared business logic into `src/ops.rs`. CLI and MCP
become thin adapters:

```
CLI:  clap args  → ops::*  → println / format
MCP:  JSON args  → ops::*  → Content::text / ToolResult
```

## What lives in ops.rs

Every function between "args parsed" and "result ready to format":

| Group | Functions |
|-------|-----------|
| Spaces | `spaces_create`, `spaces_list`, `spaces_remove`, `spaces_set_default` |
| Config | `config_get`, `config_set`, `config_list_global`, `config_list_resolved` |
| Content | `content_read`, `content_write`, `content_new`, `content_commit` |
| Search | `search` (via `SearchParams`) |
| List | `list` |
| Ingest | `ingest` (handles EngineManager mutation internally) |
| Index | `index_rebuild`, `index_status` |
| Graph | `graph_build` (via `GraphParams`) |

Functions with many parameters use param structs (`SearchParams`,
`GraphParams`) to stay under clippy's 7-argument limit.

## What stays in CLI

- Argument parsing (clap)
- `--format` text/json output switching
- `println!` / `print!` output
- `init_logging`
- `EngineManager::build` (CLI builds per invocation)

## What stays in MCP

- Argument parsing (JSON map → arg helpers)
- `Content::text` wrapping
- `collect_page_uris` + resource notifications
- `ToolResult` / panic isolation

## Consequences

- Single source of truth for all business logic
- CLI search and list now have auto-recovery (was missing)
- New operations only need to be implemented once

