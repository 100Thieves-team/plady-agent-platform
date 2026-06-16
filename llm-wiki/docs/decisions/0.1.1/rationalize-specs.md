# Rationalize llm-wiki Specifications

## Context

The llm-wiki project went through a design rethink. The new design is
captured in:

- `docs/overview.md` — project introduction, architecture, core concepts
- `docs/focused-llm-wiki-design.md` — focused engine, skills in separate repo
- `docs/type-specific-frontmatter.md` — JSON Schema type profiles, wiki.toml
- `docs/roadmap.md` — phased roadmap

The old specifications were moved to `docs/specifications/archive/`.

## What Was Done

Fresh specifications written in `docs/specifications/` from the design
documents. Each spec reviewed iteratively until marked `ready`.

## Final Layout

```
docs/specifications/
├── README.md                        ← status table + section index
│
├── model/                           ← data model
│   ├── wiki-repository-layout.md    ← repo structure, content layers, roots
│   ├── page-content.md              ← flat vs bundle, slug resolution, body conventions
│   ├── epistemic-model.md           ← why types carry epistemic distinctions
│   ├── wiki-toml.md                 ← wiki.toml reference
│   ├── global-config.md             ← config.toml reference
│   ├── type-system.md               ← type mechanism, aliasing, graph edges, built-in index
│   └── types/                       ← one doc per type (or per schema)
│       ├── base.md                  ← base schema, default fallback
│       ├── concept.md               ← concept + query-result
│       ├── source.md                ← all 9 source types (share paper.json)
│       ├── skill.md                 ← skill with field aliasing
│       ├── doc.md                   ← reference document
│       └── section.md               ← section index
│
├── tools/                           ← one doc per tool or tool group
│   ├── overview.md                  ← 15 tools, design principle, global flags
│   ├── space-management.md          ← spaces create/list/remove/set-default
│   ├── config-management.md         ← config get/set/list
│   ├── content-operations.md        ← content read/write/new/commit
│   ├── search.md                    ← wiki_search
│   ├── list.md                      ← wiki_list
│   ├── ingest.md                    ← wiki_ingest
│   ├── graph.md                     ← wiki_graph
│   └── index.md                     ← index rebuild/status
│
├── engine/                          ← engine behavior
│   ├── engine-state.md              ← ~/.llm-wiki/ layout
│   ├── index-management.md          ← tantivy index, staleness, schema change, rebuild
│   ├── graph.md                     ← petgraph, typed edges, rendering
│   ├── ingest-pipeline.md           ← validate → alias → index → commit
│   └── server.md                    ← transports, multi-wiki, resilience, logging
│
├── integrations/                    ← external connections
│   ├── mcp-clients.md               ← Cursor, VS Code, Windsurf config
│   └── acp-transport.md             ← ACP for Zed / VS Code
│
└── archive/                         ← old specs (read-only reference)
```

## Key Design Decisions Made During Rationalization

### Base schema minimized

Required fields: `title`, `type` only. Everything else is optional or
type-specific. `read_when` moved from base to concept/source schemas.
This makes the base compatible with Hugo, agent-foundation, and Claude
Code skill frontmatter via aliasing.

### CLI consistency

All commands grouped under parent subcommands:
- `llm-wiki spaces create/list/remove/set-default`
- `llm-wiki config get/set/list`
- `llm-wiki content read/write/new/commit`
- `llm-wiki search`, `llm-wiki list`, `llm-wiki ingest`, `llm-wiki graph`
- `llm-wiki index rebuild/status`

`llm-wiki init` renamed to `llm-wiki spaces create`.
`content new` uses `--section` flag instead of separate `new page`/`new section`.

### MCP tool naming

Content tools renamed to `wiki_content_*` (read, write, new, commit).
Space tools are `wiki_spaces_*`. Config is `wiki_config`.

### No file modification on ingest

The engine never modifies files on disk. Index defaults (`status`,
`type`, `last_updated`) are applied at index time only.

### Schema change detection via hashing

`schema_version` (manual integer) replaced by `schema_hash` (SHA-256
computed from type registry). Per-type hashes stored in `state.toml`
enable partial rebuilds when only some types change.

### Output format

All list/search/status commands support `--format text|json` with a
global `defaults.output_format` config key.

### Frontmatter authoring moved to skills

`frontmatter.md` removed from specs. Field-by-field guide, templates,
accumulation contract, and common mistakes belong in the `frontmatter`
skill in `llm-wiki-skills`, not in engine specs.

### features.md moved out of specs

Feature inventory is a reference doc, not a specification. Moved to
`docs/features.md`.

## Rules Applied

### Single source of truth

Each concept defined in one place. Other files reference, not redefine.

| Concept              | Defined in                   |
| -------------------- | ---------------------------- |
| Base fields          | `model/types/base.md`        |
| Type-specific fields | `model/types/<type>.md`      |
| Type mechanism       | `model/type-system.md`       |
| Tool surface         | `tools/overview.md`          |
| Ingest pipeline      | `engine/ingest-pipeline.md`  |
| Index schema         | `engine/index-management.md` |
| Config keys          | `model/global-config.md`     |
| wiki.toml format     | `model/wiki-toml.md`         |

### Design over code

No Rust structs, function signatures, or MCP parameter tables. CLI
examples and output samples instead.

### No dead references

Eliminated: `schema.md`, `llm-wiki instruct`, `wiki_lint` tool,
`wiki_context`/`wiki_ask`, `wiki_index_check`, `source-summary`,
`integrate_file`/`integrate_folder`, `src/instructions.md`.
