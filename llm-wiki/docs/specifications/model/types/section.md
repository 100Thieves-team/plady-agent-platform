---
title: "Section Type"
summary: "Section index page — groups related pages under a directory."
read_when:
  - Creating sections
  - Understanding section pages
status: ready
last_updated: "2025-07-17"
---

# Section Type

Schema: `schemas/section.json` (extends `base.json`)

A section is a directory with an `index.md` that groups related pages.
No additional fields beyond base.

Section pages are excluded from search results by default
(`--include-sections` to include them). They serve as navigation, not
knowledge.

## Template

```yaml
title: "Scaling Research"
summary: "Papers and concepts related to model scaling."
type: section
status: active
last_updated: "2025-07-17"
```
