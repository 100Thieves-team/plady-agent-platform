# Engine vs Skills Separation

## Decision

The engine is a stateless tool provider. All workflow intelligence
(ingest, crystallize, research, lint, bootstrap) lives in skills —
external, replaceable, platform-specific.

## Context

Early designs embedded LLM prompts and workflow instructions in the
engine binary (`llm-wiki instruct`). This coupled the engine to a
specific LLM interaction style and made the binary the single source
of truth for both tool behavior and workflow orchestration.

## Rationale

A tool belongs in the engine if and only if it requires stateful access
that a skill cannot replicate:

- Filesystem writes into the wiki tree
- Git operations (commit, history)
- Tantivy index queries (search, list, graph traversal)
- Space registry mutations

Everything else — workflow orchestration, LLM prompting, multi-step
procedures — belongs in skills.

This separation enables:

- Independent release cycles (skills ship faster than the engine)
- Platform-specific skills (Claude Code plugin, Cursor prompts, custom agents)
- Community contributions to skills without requiring Rust builds
- Engine binary with zero embedded LLM opinions

## Consequences

- `llm-wiki instruct` removed from the binary
- `llm-wiki lint` CLI command removed (moves to skill)
- `llm-wiki-skills` repository created as a Claude Code plugin
- The engine ships no LLM prompts
