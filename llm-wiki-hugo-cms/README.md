# llm-wiki-hugo-cms

**Publish your [llm-wiki](https://github.com/geronimo-iia/llm-wiki) as a
static website — no database, no CMS, no copy step.**

Hugo reads your wiki's Markdown files directly. The wiki is the CMS.
Hugo is the renderer.

---

## How it works

Wiki pages are plain Markdown with YAML frontmatter. Hugo's `contentDir`
points directly at the `wiki/` directory — no import, no transform, no sync
step. Edit a page, refresh the browser.

```
my-wiki/
├── site/          ← this project (Hugo scaffold)
│   └── hugo.toml  ← contentDir = "../wiki"
├── wiki/          ← your knowledge base
│   ├── concepts/
│   └── sources/
└── wiki.toml
```

Bundle pages (`slug/index.md` + co-located assets) map directly to Hugo's
page bundle model. Type, status, confidence, tags, and graph edges in
frontmatter all render automatically.

---

## What you get

- **Type badges** — color-coded by type category (concept, paper, note, skill, doc)
- **Metadata block** — status, confidence score, owner, last updated, tags
- **Superseded banners** — automatic notice when `superseded_by` is set
- **Backlinks** — pages that link here, derived from frontmatter edge fields
- **Related pages** — `sources` and `concepts` lists resolved to live links
- **Mermaid diagrams** — fenced code blocks and shortcode, rendered in-browser
- **`wiki://` link resolution** — `[text](wiki://name/slug)` links resolve to local Hugo URLs
- **Taxonomy pages** — tag, author, and type index pages generated automatically
- **GitHub Pages CI** — workflow template included, one config line to deploy

---

## Quick start

```bash
cd ~/wikis/research
git clone https://github.com/geronimo-iia/llm-wiki-hugo-cms _hugo_cms
cp -r _hugo_cms/site .
cp -r _hugo_cms/templates/.github .
rm -rf _hugo_cms

# Configure: set baseURL and title in site/hugo.toml
# then preview:
cd site && hugo server --buildDrafts
```

→ [Full setup guide](docs/guides/getting-started.md)

---

## Documentation

| | |
|---|---|
| [Getting started](docs/guides/getting-started.md) | Setup walkthrough |
| [Specifications](docs/specifications/README.md) | Content mapping, frontmatter, layouts |
| [Roadmap](docs/roadmap.md) | What's built, what's next |

---

## Part of the llm-wiki ecosystem

| Repository | Description |
|-----------|-------------|
| [llm-wiki](https://github.com/geronimo-iia/llm-wiki) | Wiki engine — 22 MCP tools, full-text search, typed graph, git-backed |
| [llm-wiki-skills](https://github.com/geronimo-iia/llm-wiki-skills) | Claude Code plugin — ingest, crystallize, research, lint, graph workflows |
| [llm-wiki-hugo-cms](https://github.com/geronimo-iia/llm-wiki-hugo-cms) | This project — Hugo rendering scaffold |

---

## License

[MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE)
