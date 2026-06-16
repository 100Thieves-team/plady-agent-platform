# Cross-Wiki Links

## Decision

`wiki://` URIs are resolved at **graph build time**, not at index time.
The index stores raw strings as-is. Cross-wiki graph traversal requires
an explicit `cross_wiki: true` flag — single-wiki is the default.
Broken cross-wiki links are a **lint concern**, not an ingest concern.

## Context

Pages need to reference each other across wiki spaces. `wiki://` URIs
already exist and work for `wiki_content_read`. The question was whether
to normalize them at index time (schema change + re-index) or resolve
them at graph build time (no schema change).

## Rationale

**Graph-time resolution avoids an index schema change.** Storing and
normalizing cross-wiki URIs at index time would require a new field type,
a migration path for existing indexes, and re-indexing all existing pages.
Graph-time resolution is zero-cost at ingest — the raw URI string is
already stored under `body_links` and frontmatter edge fields.

**Single-wiki default preserves performance and simplicity.** Building a
unified graph requires opening searchers on all mounted wikis
simultaneously. This is fine for 2–3 wikis but grows with deployment size.
The single-wiki graph remains the default; `cross_wiki: true` is an
explicit opt-in.

**Same relation labels across wikis.** `fed-by` is `fed-by` whether the
target is local or cross-wiki. The rendering distinguishes locality (via
CSS class or node attribute), not the relation semantics.

**Lint, not ingest, for validation.** Ingest validates frontmatter
structure and field types — it should not fail because a target wiki is
not mounted at ingest time. Unmounted ≠ wrong: the target wiki may be
mounted in a different session. Lint reports unmounted cross-wiki targets
as `Warning`, not `Error`.

**Silently drop unresolvable cross-wiki edges.** Consistent with current
behavior for missing local slugs. Lint is the signal, not a graph build
error.

## Consequences

- No index schema change; no re-index of existing wikis.
- `src/links.rs` gains a `ParsedLink` enum (`Local` vs `CrossWiki`)
  consumed by `graph.rs` only — not the index.
- `wiki_graph` gains a `cross_wiki` parameter; `build_graph_cross_wiki`
  added alongside the existing `build_graph`.
- Lint gains a `broken-cross-wiki-link` rule flagging URIs whose wiki
  name is not in the global config.
- `wiki_content_read` is unchanged — already handles `wiki://` URIs.
