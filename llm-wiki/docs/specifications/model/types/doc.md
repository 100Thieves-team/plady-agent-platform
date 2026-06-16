---
title: "Doc Type"
summary: "Reference document — document authority base for any knowledge."
read_when:
  - Writing doc pages
  - Storing reference documents in the wiki
status: ready
last_updated: "2025-07-17"
---

# Doc Type

Schema: `schemas/doc.json` (extends `base.json`)

A doc is a reference document — specifications, guides, standards,
policies. It carries document authority: the content is the source of
truth, not a synthesis from other sources.

## Additional Fields

| Field       | Type         | Required | Description                                  |
| ----------- | ------------ | -------- | -------------------------------------------- |
| `read_when` | list[string] | no       | Retrieval conditions                         |
| `sources`   | list[string] | no       | Slugs of source pages that informed this doc |

## Edge Declarations

| Field           | Relation        | Target types     |
| --------------- | --------------- | ---------------- |
| `sources`       | `informed-by`   | All source types |
| `superseded_by` | `superseded-by` | Any              |

## Template

```yaml
title: "Payment API Reference"
summary: "Endpoints, auth, error codes for the Payment API."
type: doc
status: active
last_updated: "2025-07-17"
tags: [api, payment]
sources: [sources/payment-rfc-2024]
```
