# No Format Adapters in the Engine

## Decision

Format normalization for external session stores (Claude Code JSONL,
Cursor SQLite, Codex JSON, Obsidian vault, etc.) does not belong in the
engine binary. The engine accepts clean markdown with valid frontmatter;
it does not parse upstream tool formats.

## Context

The Karpathy LLM Wiki pattern captures knowledge from agent session
histories. ref-2 ships 12 format adapters inside its Python pipeline
for converting session store formats into wiki markdown. The question
arose whether `llm-wiki` should provide a `wiki_import` CLI/MCP command
that accepts raw session files and normalizes them.

The `crystallize` skill already covers the knowledge extraction path:
it reads a session, distils decisions and findings, and writes typed
wiki pages via the engine write tools. The skill can consume raw files
directly — Claude reads JSONL, markdown, and most text formats natively.

## Rationale

**Format adapters belong outside the engine for three reasons:**

1. **Format churn.** Session store formats (Claude Code's `.jsonl`
   schema, Cursor's SQLite tables, Codex's JSON envelopes) change as
   those tools evolve. Adapters inside the engine binary create a
   maintenance dependency on every upstream format change.

2. **Wrong abstraction layer.** The engine's boundary is the wiki tree:
   git, tantivy, markdown, frontmatter. Format parsing is pre-engine
   work. Mixing them in one binary violates the engine-vs-skills
   separation established in [engine-vs-skills](engine-vs-skills.md).

3. **LLMs don't need a normalizer.** The purpose of a normalizer would
   be to produce a standard intermediate that the LLM can reason about.
   But Claude can read JSONL and SQLite exports directly — the
   crystallize skill does not need a normalized input to function.

**`wiki_import` as a thin command would be `wiki_content_write` with a
path argument.** No new functionality — only surface area.

## Consequences

- No `wiki_import` MCP tool or CLI subcommand is added to the engine.
- Session transcript ingestion remains a skill-layer concern:
  `crystallize` reads the raw file, extracts typed pages, writes via
  `wiki_content_write` + `wiki_ingest`.
- If automation requires a thin normalizer outside the LLM path, it is
  a standalone script (not part of `llm-wiki-engine`) that pipes clean
  markdown to `wiki_content_write`.
- Format adapters, if ever written, live in `llm-wiki-skills` or a
  dedicated adapter repository — not in the engine.
