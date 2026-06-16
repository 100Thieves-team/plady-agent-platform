# Frontmatter Mapping

How wiki frontmatter fields map to Hugo template variables.

## Automatic Mapping (hugo.toml)

| Wiki field | Hugo variable | Configured in |
|------------|--------------|---------------|
| `title` | `.Title` | Built-in |
| `last_updated` | `.Lastmod` | `hugo.toml` frontmatter config |
| `last_updated` | `.Date` | `hugo.toml` frontmatter config |
| `tags` | `.Params.tags` | Taxonomy |
| `owner` | `.Params.owner` | Taxonomy |
| `type` | `.Params.type` | Taxonomy |

## Template Access (`.Params.*`)

| Wiki field | Template access | Used in |
|------------|----------------|---------|
| `summary` | `.Params.summary` | Meta description, page lists |
| `type` | `.Params.type` | Type badge, layout selection |
| `status` | `.Params.status` | Status indicator |
| `confidence` | `.Params.confidence` | Confidence badge |
| `owner` | `.Params.owner` | Author taxonomy |
| `tldr` | `.Params.tldr` | Highlighted summary block |
| `sources` | `.Params.sources` | Related pages list |
| `concepts` | `.Params.concepts` | Related pages list |
| `superseded_by` | `.Params.superseded_by` | Superseded banner |
| `claims` | `.Params.claims` | Claims table (Phase 3) |
| `read_when` | — | Not rendered (agent-facing only) |

## Skill Pages (aliased fields)

| Wiki field | Canonical | Template access |
|------------|-----------|----------------|
| `name` | `title` | `.Title` (Hugo reads `name` if `title` absent) |
| `description` | `summary` | `.Params.description` |
| `allowed-tools` | — | `.Params.allowed_tools` |
| `document_refs` | — | `.Params.document_refs` |

## Draft Logic

Hugo's `[frontmatter]` config cannot map conditional values (e.g.
`status: draft` → `.Draft = true`). Currently `status` is available as
`.Params.status` in templates only — it does not control `.Draft`.

Pages are excluded from production by adding `draft: true` directly to
their frontmatter, or via a future render hook / cascade (Phase 2).
