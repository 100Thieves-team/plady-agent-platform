# wiki_stats — wiki health dashboard

## Decision

Add `wiki_stats` as the 18th MCP tool. Returns wiki health metrics
in a single call, composed from existing primitives.

## Context

Understanding wiki health required multiple tool calls. No single
view showed page counts, orphans, connectivity, and staleness.

## Key decisions

- **Fixed staleness buckets** — fresh (<7d), stale_7d (7-30d),
  stale_30d (>30d). No config key.
- **No tag distribution** — stats is about health, not content.
- **No verbose flag** — one response, all metrics.
- **Composed** — orchestrates list facets, graph metrics, staleness
  query, and index status. No new index fields.

## Consequences

- 18 tools (was 17)
- Bootstrap can use one call instead of multiple
- Lint can reference stats for orphan/staleness numbers
- Graph metrics (orphans, density, avg connections) computed from
  petgraph via `compute_metrics`
