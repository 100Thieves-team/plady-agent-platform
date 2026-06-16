# Content Mapping

How wiki repository structure maps to Hugo site structure.

## Directory Mapping

```
Wiki repo                    Hugo sees
─────────                    ─────────
wiki/                        contentDir (all pages)
wiki/concepts/foo.md         /concepts/foo/        (flat page)
wiki/concepts/bar/index.md   /concepts/bar/        (bundle page)
wiki/concepts/bar/img.png    /concepts/bar/img.png (bundle asset)
wiki/concepts/index.md       /concepts/            (section index)
```

## Excluded Directories

Exclusions are configured via `[module.mounts]` `excludeFiles` in `hugo.toml`
(not `ignoreFiles` — that doesn't work reliably when `contentDir` is outside
the site directory):

| Pattern | Reason |
|---------|--------|
| `inbox/**` | Unprocessed drop zone |
| `raw/**` | Immutable archive |
| `schemas/**` | Engine configuration, not content |
| `**/*.json` | Wiki export files |
| `**/*.txt` | Wiki export files |
| `**/LINT.md` | Engine output |

## Page Types

Hugo selects layouts based on the `type` frontmatter field, not the
directory. A concept page in `wiki/research/moe.md` with `type: concept`
uses the concept layout regardless of its directory.

## Slug Resolution

Wiki slugs are paths relative to `wiki/` without extension. Hugo URLs
match: `concepts/mixture-of-experts` → `/concepts/mixture-of-experts/`.

## Bundle Model

Wiki bundles (`slug/index.md` + assets) map directly to Hugo page
bundles. Assets are served at the same relative path — no rewriting
needed.
