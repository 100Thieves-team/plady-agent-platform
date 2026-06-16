# Layouts

Template structure and type-specific rendering.

## Template Hierarchy

```
layouts/
├── _default/
│   ├── baseof.html          base template (head, header, content, footer)
│   ├── single.html          single page (all types, delegates to type partial)
│   └── list.html            section list (groups by type)
├── partials/
│   ├── head.html            <head> with meta from frontmatter
│   ├── header.html          site header + nav
│   ├── footer.html          site footer
│   ├── metadata.html        type badge, status, confidence, owner, tags
│   ├── superseded.html      superseded banner (if superseded_by is set)
│   ├── backlinks.html       pages linking here (from sources/concepts fields)
│   └── types/
│       ├── concept.html     sources list, claims table, confidence
│       ├── source.html      concepts informed, claims
│       ├── skill.html       skill-specific fields
│       └── doc.html         doc-specific fields
└── _markup/
    └── render-link.html     [[wikilink]] and wiki:// URI resolution
```

## Layout Selection

The `single.html` template delegates to a type-specific partial:

```html
{{ $type := .Params.type | default "page" }}
{{ $partial := printf "types/%s.html" $type }}
{{ if templates.Exists (printf "partials/%s" $partial) }}
  {{ partial $partial . }}
{{ else }}
  {{ .Content }}
{{ end }}
```

## Section Lists

`list.html` renders:
1. The section's own `index.md` content (if any)
2. Child pages grouped by type, sorted by title
3. Each entry shows: title, summary, type badge, status

## Metadata Partial

Renders for every page:

| Element | Source | Display |
|---------|--------|---------|
| Type badge | `.Params.type` | Colored pill (concept=blue, paper=green, skill=yellow) |
| Status | `.Params.status` | Text indicator |
| Confidence | `.Params.confidence` | Badge (if present) |
| Owner | `.Params.owner` | Link to author taxonomy |
| Last updated | `.Lastmod` | Date |
| Tags | `.Params.tags` | Links to tag taxonomy |

## Type Colors

| Category | Types | Color |
|----------|-------|-------|
| Knowledge | concept, query-result | `#cce5ff` (blue) |
| Source | paper, article, documentation, ... | `#d4edda` (green) |
| Extension | skill, doc | `#ffeeba` (yellow) |
| Navigation | section | `#f8f9fa` (gray) |
