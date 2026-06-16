# Tool Surface

## Decision

The engine exposes 15 MCP/ACP/CLI tools. Tools that don't require
stateful access were removed or folded.

## What Was Removed

| Former tool        | Disposition                     | Why                                                                     |
| ------------------ | ------------------------------- | ----------------------------------------------------------------------- |
| `wiki_lint`        | Skill                           | Read-analyze-fix workflow the LLM orchestrates using search, list, read |
| `wiki_instruct`    | Removed                         | Replaced by `llm-wiki-skills` plugin                                    |
| `wiki_context`     | Removed                         | `wiki_search` covers both                                               |
| `wiki_ask`         | Removed                         | `wiki_search` covers both                                               |
| `wiki_index_check` | Folded into `wiki_index_status` | One status tool is enough                                               |

## What Was Renamed

| Before                               | After                 | Why                                         |
| ------------------------------------ | --------------------- | ------------------------------------------- |
| `wiki_init`                          | `wiki_spaces_create`  | Grouped under `spaces` for CLI consistency  |
| `wiki_read`                          | `wiki_content_read`   | Grouped under `content` for CLI consistency |
| `wiki_write`                         | `wiki_content_write`  | Grouped under `content` for CLI consistency |
| `wiki_new_page` / `wiki_new_section` | `wiki_content_new`    | Merged with `--section` flag                |
| `wiki_commit`                        | `wiki_content_commit` | Grouped under `content` for CLI consistency |

## Rationale

The stateful access criterion: if a skill can do it by calling existing
tools, it doesn't need its own tool. Lint is a read-analyze-fix loop
using search + list + read. Instruct is static text that belongs in a
skill file. Context and ask are just search with different output
formatting.

CLI consistency: all operations grouped under parent subcommands
(`spaces`, `config`, `content`, `index`).
