# Three Repositories

## Decision

Three independent repositories, three independent release cycles:

| Repository          | What                                            | Language    |
| ------------------- | ----------------------------------------------- | ----------- |
| `llm-wiki`          | Wiki engine — MCP tools, tantivy, git, petgraph | Rust        |
| `llm-wiki-skills`   | Claude Code plugin — skills for the engine      | Markdown    |
| `llm-wiki-hugo-cms` | Hugo site scaffold — render wiki as website     | Hugo + HTML |

## Rationale

| Concern       | Single repo                               | Separate repos                                                |
| ------------- | ----------------------------------------- | ------------------------------------------------------------- |
| Release cycle | Coupled — skills wait for engine releases | Independent — skills ship when ready                          |
| Contributions | Requires Rust build for any change        | Skills are Markdown PRs                                       |
| Distribution  | Binary-only                               | Engine via cargo, skills via Claude marketplace, Hugo via git |
| Testing       | Engine rebuild for skill edits            | Edit SKILL.md, reload                                         |

The engine is a Rust binary that changes slowly. Skills are Markdown
files that change fast. The Hugo renderer reads the wiki tree
read-only. None of them need to be in the same repo.

## Separation of Concerns

| Concern                            | Where                                   |
| ---------------------------------- | --------------------------------------- |
| File management, git, search index | Engine (`llm-wiki`)                     |
| Frontmatter validation             | Engine + JSON Schema files in wiki repo |
| Concept graph                      | Engine (petgraph from tantivy index)    |
| How to ingest a source             | Skill (`llm-wiki-skills`)               |
| How to crystallize a session       | Skill (`llm-wiki-skills`)               |
| How to audit wiki structure        | Skill (`llm-wiki-skills`)               |
| How to render as a website         | Hugo (`llm-wiki-hugo-cms`)              |
| What types exist and their fields  | Wiki repo (`wiki.toml` + `schemas/`)    |
