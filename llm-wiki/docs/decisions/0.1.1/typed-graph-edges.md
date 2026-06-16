# Typed Graph Edges via x-graph-edges

## Decision

Graph edge types are declared in JSON Schema files using the
`x-graph-edges` extension. The engine reads these declarations to
build a petgraph with labeled, directed edges.

## Context

The concept graph needs to understand not just that pages link to each
other, but *how* they relate. A concept fed by a paper is a different
relationship than a concept that depends on another concept.

## Alternatives Considered

| Approach                       | Strengths                        | Why not                                |
| ------------------------------ | -------------------------------- | -------------------------------------- |
| RDF/OWL ontology               | Formal semantics, inference      | Heavy, requires triple store, overkill |
| JSON-LD + Schema.org           | Linked data, web-standard        | Requires `@context`, no wiki benefit   |
| Property graph (Neo4j-style)   | Labeled nodes + edges, queryable | Needs a graph database                 |
| Hardcoded edge types in engine | Simple                           | Can't add custom edge types            |

## Why x-graph-edges

We already use JSON Schema for validation and `x-index-aliases` for
field mapping. Adding `x-graph-edges` keeps everything in one system:

- Edge declarations live alongside field definitions in the same schema
- The engine reads them at startup, petgraph gets labeled edges
- Custom types can declare their own edge types
- No separate ontology file or graph configuration

## Format

```json
"x-graph-edges": {
  "sources": {
    "relation": "fed-by",
    "direction": "outgoing",
    "target_types": ["paper", "article"]
  }
}
```

The same frontmatter field (`sources`) can have different relations
depending on the page type — concept uses `fed-by`, source uses `cites`,
doc uses `informed-by`.

## Consequences

- Graph edges are type-aware — `wiki_graph` can filter by relation
- Edge declarations are wiki-owner-defined, not hardcoded
- Schema change detection (via `schema_hash`) catches edge declaration
  changes and triggers index rebuild
- Body `[[wiki-links]]` get a generic `links-to` relation (no schema
  declaration needed)
