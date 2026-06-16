# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and this project adheres to [Semantic Versioning](https://semver.org).

## [0.1.0] — Unreleased

### Added

- **`site/` scaffold** — Hugo site designed to be placed inside a wiki repository; `contentDir = "../wiki"` via `[module.mounts]` with `excludeFiles` (inbox, raw, schemas, exports)
- **Layouts** — `baseof.html`, `single.html`, `list.html`, `index.html`; partials: `head`, `header`, `footer`, `metadata`, `superseded`, `backlinks`, `page-list-item`
- **Frontmatter rendering** — type badge, status, confidence, owner, last updated, tags; superseded banner; backlinks from frontmatter `sources`/`concepts` fields; related pages list
- **Mermaid** — fenced code block render hook + `mermaid` shortcode; loaded via CDN
- **`render-link.html`** — resolves `[text](wiki://name/slug)` to local Hugo URLs; cross-wiki and broken links rendered with `.broken-link` styling
- **CSS** — minimal styles with type-color system (concept, paper, note, skill, doc, section, query-result); status and confidence badges
- **`site/Makefile`** — `serve`, `build`, `clean` targets
- **`templates/.github/workflows/hugo-deploy.yml`** — CI template for GitHub Pages deployment; copy to target wiki repo
- **`skills/setup/SKILL.md`** — manual install skill with prerequisites, steps, and configuration guidance
- **Docs** — specifications (content-mapping, frontmatter-mapping, layouts, wikilinks), guides (getting-started), roadmap
