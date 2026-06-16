# `llms` Format on Existing Tools

## Decision

Add `format: "llms"` as a supported output format on `wiki_list`,
`wiki_search`, and `wiki_graph`. Do not add a new orientation tool.
Implement `wiki_export` as a file-writing tool (not a content-returning
tool) with a default output path of `llms.txt` at the wiki repository root.

## Context

The emerging `llms.txt` ecosystem (Cursor, Perplexity, and other LLM-native
tools) expects a machine-readable summary of a knowledge base at a
well-known path. Separately, skills that need to orient themselves before
acting — crystallize, ingest, research, lint — currently burn 2–4 tool
calls to build a map of wiki content.

Two design options were considered:

1. **New `wiki_export` MCP tool returning content in the tool response** —
   produces a full wiki map in one call, but floods the tool response context
   window for large wikis. Also adds a new tool to the surface.

2. **`format: "llms"` on existing tools + file-writing `wiki_export`** —
   orientation via `wiki_list(format: "llms")` (paginated, response-safe);
   file production via `wiki_export(wiki: "name", path: "llms.txt")`.

## Rationale

**`format` as a first-class parameter is already precedent.** `wiki_graph`
already accepts `format: "mermaid" | "dot"`. Extending to `llms` is
consistent with the existing tool surface — no new tool, just a new
rendering mode.

**Separation of concerns between session use and file production.** A
tool response and a file have different constraints: a response must fit in
a context window, a file can be arbitrarily large. `format: "llms"` on
`wiki_list` handles session orientation (paginated, bounded). `wiki_export`
handles file production (unbounded, writes to disk). Conflating them in one
tool would require either a size limit on the tool response or accepting
large responses as normal behavior — neither is correct.

**`wiki_export` meets the engine tool criterion.** It writes to the wiki
filesystem, which is stateful access that a skill cannot replicate via
other tools. Its response is a confirmation report (`path`, `pages_written`,
`bytes`), not the content itself — the content went to the file.

**Default path at wiki root enables ecosystem publishing with zero config.**
`wiki_export(wiki: "name")` writes `<wiki-root>/llms.txt`. That file can be
committed to git, served by Hugo, or referenced by external tools — without
requiring the caller to know the wiki's filesystem path.

## Consequences

- `wiki_list`, `wiki_search`, `wiki_graph` each gain a `format: "llms"`
  option; their existing formats (`text`, `json`, `mermaid`, `dot`) are
  unchanged.
- `wiki_export` is a new MCP tool and CLI command; parameters are `wiki`
  (required), `path` (optional, defaults to `llms.txt` at wiki root),
  `format` (`llms-txt` | `llms-full` | `json`), `status`.
- No existing tool is removed or renamed.
- Skills updated to use `wiki_list(format: "llms")` for orientation and
  `wiki_graph(format: "llms")` for graph interpretation.
