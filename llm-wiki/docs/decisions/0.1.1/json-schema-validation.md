# JSON Schema for Type Validation

## Decision

Per-type frontmatter validation uses JSON Schema Draft 2020-12. Custom
engine behavior is declared via `x-` prefixed extensions
(`x-index-aliases`, `x-graph-edges`) that standard validators ignore.

## Context

One frontmatter schema doesn't fit all page types. A concept page
carries `sources`, `concepts`, `confidence`. A skill page carries
`name`, `description`, `allowed-tools`. Forcing all pages into the
same schema means either ignoring type-specific fields or requiring
every field on every page.

## Alternatives Considered

| Approach                     | Why not                                    |
| ---------------------------- | ------------------------------------------ |
| Hardcoded validation in Rust | Can't add custom types without recompiling |
| TOML schema in wiki.toml     | No standard, no tooling, no composition    |
| Custom YAML schema format    | Reinventing the wheel                      |

## Why JSON Schema

- **Standard** — Draft 2020-12, same as agent-foundation
- **Toolable** — validators in every language (Rust: `jsonschema`)
- **Composable** — `$ref` and `allOf` for shared field definitions
- **Self-documenting** — `description` on every property
- **Extensible** — `x-` keywords for engine-specific behavior without
  breaking standard validators

## How `x-` Extensions Work

Standard JSON Schema validators silently ignore `x-` prefixed keywords.
The engine reads them for its own purposes:

- `x-index-aliases` — maps type-specific field names to canonical
  index roles at ingest time
- `x-graph-edges` — declares typed directed edges for the concept graph

This means the same schema file works for both standard validation
(any JSON Schema validator) and engine-specific indexing/graph behavior.

## Consequences

- Schemas live in `schemas/` in the wiki repo, committed and versioned
- Wiki owners can add custom types by adding a schema file + registering
  in `wiki.toml`
- The engine binary doesn't need to know about specific types
- Agent-foundation schemas can be referenced via `$ref` for compatibility
