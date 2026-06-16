# Getting Started

Set up Hugo rendering for an existing llm-wiki repository.

## Prerequisites

- [Hugo extended](https://gohugo.io/installation/) ≥ 0.147.0
- An llm-wiki repository with pages in `wiki/`

## 1. Add the Hugo scaffold to your wiki

```bash
cd ~/wikis/research
git clone https://github.com/geronimo-iia/llm-wiki-hugo-cms _hugo_cms
cp -r _hugo_cms/site .
cp -r _hugo_cms/templates/.github .
rm -rf _hugo_cms
```

Your wiki now looks like:

```
research/
├── site/              ← Hugo site (contentDir = "../wiki")
│   ├── hugo.toml
│   ├── layouts/
│   └── ...
├── .github/
│   └── workflows/
│       └── hugo-deploy.yml   ← CI for GitHub Pages
├── wiki/              ← your content (Hugo reads this)
├── wiki.toml
└── schemas/
```

## 2. Configure

Edit `site/hugo.toml`:

```toml
baseURL = "https://<your-username>.github.io/<repo-name>/"
title   = "<your wiki name from wiki.toml>"
```

Everything else — `contentDir`, excludes, frontmatter mapping, taxonomies —
is pre-configured and works out of the box.

## 3. Preview

```bash
cd site
hugo server --buildDrafts
```

Open the URL printed by Hugo (e.g. `http://localhost:1313/my-wiki/`).
Pages with `status: draft` or `status: stub` are visible in preview but
excluded from production builds.

## 4. Build

```bash
hugo --gc --minify
```

Output goes to `site/public/`.

## 5. Deploy to GitHub Pages

Enable GitHub Pages in your repo settings (Settings → Pages → Source:
GitHub Actions), then push to `main`. The CI workflow builds and deploys
automatically.

## Customization

### Change styles

Edit `site/assets/css/custom.css` for colors, fonts, and spacing.

### Add a type-specific layout

Create `site/layouts/partials/types/<type>.html` — it will be picked up
automatically for pages with that `type` frontmatter value.

### Adjust frontmatter mapping

Edit `site/hugo.toml` — see [frontmatter-mapping.md](../specifications/frontmatter-mapping.md).
