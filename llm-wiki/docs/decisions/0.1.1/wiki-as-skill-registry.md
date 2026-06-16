# Wiki as Skill Registry

## Decision

The wiki is the skill registry. No separate skill discovery protocol.
`type: skill` pages are searchable, listable, and readable like any
other page.

## Context

Agent-foundation uses a dedicated hub system (`index.json`) for skill
discovery. A separate skill protocol was considered for llm-wiki.

## Rationale

The wiki already provides everything a skill registry needs:

| Registry feature  | Wiki equivalent                      |
| ----------------- | ------------------------------------ |
| List all skills   | `wiki_list --type skill`             |
| Search skills     | `wiki_search --type skill`           |
| Read a skill      | `wiki_content_read`                  |
| Register a skill  | `wiki_content_write` + `wiki_ingest` |
| Version a skill   | `wiki_content_commit` (git history)  |
| Deprecate a skill | Set `superseded_by` in frontmatter   |
| Validate a skill  | JSON Schema on ingest (`skill.json`) |

Adding a separate protocol would mean maintaining two systems that do
the same thing.

## Consequences

- Skills stored alongside knowledge pages in the wiki tree
- Skills discoverable via the same search and list tools
- Skills can reference knowledge pages through `concepts` and graph edges
- Cross-wiki skill discovery via `wiki_search --type skill --all`
- No `index.json`, no hub protocol, no separate registry
