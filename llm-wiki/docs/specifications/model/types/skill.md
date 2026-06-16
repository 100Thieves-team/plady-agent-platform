---
title: "Skill Type"
summary: "Agent skill with workflow instructions — standalone schema with field aliasing."
read_when:
  - Writing skill pages
  - Understanding skill frontmatter and aliasing
status: ready
last_updated: "2025-07-17"
---

# Skill Type

Schema: `schemas/skill.json` (standalone — does not extend `base.json`)

Skill pages use `name`/`description` instead of `title`/`summary`,
following the [agentskills.io](https://agentskills.io) convention. The
engine aliases them at ingest time so they index uniformly.

Compatible with Claude Code skills and agent-foundation skills. Both
runtimes silently ignore fields they don't recognize.

## Aliases

```json
"x-index-aliases": {
  "name": "title",
  "description": "summary",
  "when_to_use": "read_when"
}
```

## Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill identifier (lowercase, hyphenated, max 64 chars) |
| `description` | string | What the skill does and when to use it |
| `type` | string | Must be `skill` |

## Optional Fields

### Discovery and activation

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `when_to_use` | string | none | Additional activation context (appended to description) |
| `argument-hint` | string | none | Hint shown during autocomplete (e.g. `[file-path]`) |
| `paths` | string or list | none | Glob patterns for file-based activation |

### Invocation control

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `disable-model-invocation` | bool | `false` | Prevent auto-invocation |
| `user-invocable` | bool | `true` | Show in slash-command menu |
| `allowed-tools` | string or list | none | Tools pre-approved for this skill |

### Execution

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `context` | string | none | `fork` to run in a subagent |
| `agent` | string | `general-purpose` | Subagent type when context is fork |
| `model` | string | none | Model override for this skill |
| `effort` | string | none | Effort level: `low`, `medium`, `high`, `xhigh`, `max` |
| `shell` | string | `bash` | Shell for inline commands: `bash` or `powershell` |
| `hooks` | object | none | Hooks scoped to this skill's lifecycle |

### Metadata

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | string | none | Lifecycle state |
| `last_updated` | string | none | ISO 8601 date |
| `tags` | list[string] | `[]` | Search terms |
| `owner` | string | none | Who is responsible |
| `superseded_by` | string | none | Slug of replacement |
| `document_refs` | list[string] | `[]` | Slugs of doc pages that describe this skill |
| `compatibility` | string | none | Human-readable environment requirements |
| `license` | string | none | License identifier |
| `metadata` | object | none | Publishing metadata (author, version, homepage) |

## Edge Declarations

| Field | Relation | Target types |
|-------|----------|-------------|
| `document_refs` | `documented-by` | `doc` |
| `superseded_by` | `superseded-by` | Any |

## Template

```yaml
name: ingest
description: >
  Process source files into synthesized wiki pages.
type: skill
status: active
last_updated: "2025-07-17"
allowed-tools: Read Write Edit Bash Grep Glob
disable-model-invocation: true
tags: [ingest, workflow]
owner: geronimo
document_refs: [docs/ingest-guide]
```
