---
title: "REST / OpenAPI layer"
summary: "Full HTTP REST API over llm-wiki-engine — tiered /wiki + /admin route groups, utoipa-generated OpenAPI spec, cursor pagination, separate opt-in port."
status: draft
date: "2026-05-03"
---

# REST / OpenAPI Layer Design

## Context

llm-wiki exposes 22 MCP tools and 18 CLI subcommands but no REST API. External consumers (UIs, CI pipelines, other services) cannot interact with a running instance over plain HTTP. This design adds a complete REST API with full CLI parity, generated OpenAPI spec, and Swagger UI.

## Decisions

- **No auth in v1.** Trust the network layer. Future: `tower-http` `ValidateRequestHeader` for bearer token — zero new deps.
- **Tiered routes.** `/api/v1/wiki/{wiki}/*` for usage operations; `/api/v1/admin/*` for management. Enables per-group auth later.
- **`utoipa` for OpenAPI.** Macro-annotated, axum 0.8 native, active ecosystem. Generates spec at compile time.
- **Separate opt-in port.** `serve.api_port` (default 8081) independent from MCP HTTP port (8080). Operators can firewall independently.
- **New `src/api/` module.** Mirrors `src/mcp/` pattern. Merged into axum router in `server.rs` via `.merge()`.
- **Cursor pagination.** Opaque base64-encoded integer offset. Stateless, no server session.

## Module Structure

```
src/api/
  mod.rs              — router() fn, OpenAPI assembly, Swagger UI mount
  handlers/
    mod.rs
    wiki.rs           — /api/v1/wiki/* handlers
    admin.rs          — /api/v1/admin/* handlers
  dto.rs              — request/response structs (#[derive(ToSchema)])
  error.rs            — ApiError → IntoResponse + ToSchema
```

`server.rs` change (one line in `serve_http`):

```rust
let router = Router::new()
    .merge(mcp_router)
    .merge(api::router(engine.clone()));
```

## Route Map

```
GET  /api/v1/openapi.json
GET  /api/v1/docs                              (Swagger UI)

# Wiki operations
GET  /api/v1/wiki/{wiki}/search                ?q=&top_k=&sections=&cursor=&limit=
GET  /api/v1/wiki/{wiki}/list                  ?cursor=&limit=&type=&tag=
GET  /api/v1/wiki/{wiki}/pages/{slug}
PUT  /api/v1/wiki/{wiki}/pages/{slug}          (full replace)
POST /api/v1/wiki/{wiki}/pages                 (create new, slug derived from title)
DELETE /api/v1/wiki/{wiki}/pages/{slug}
POST /api/v1/wiki/{wiki}/pages/{slug}/commit
POST /api/v1/wiki/{wiki}/ingest
GET  /api/v1/wiki/{wiki}/lint                  ?slug= (optional, all pages if absent)
GET  /api/v1/wiki/{wiki}/suggest/{slug}        ?limit=
GET  /api/v1/wiki/{wiki}/graph                 ?format=&depth=&type=
GET  /api/v1/wiki/{wiki}/export                ?format=
GET  /api/v1/wiki/{wiki}/stats
GET  /api/v1/wiki/{wiki}/history/{slug}        ?cursor=&limit=

# Admin operations
GET  /api/v1/admin/spaces
POST /api/v1/admin/spaces
GET  /api/v1/admin/spaces/{name}
DELETE /api/v1/admin/spaces/{name}
PUT  /api/v1/admin/spaces/default              body: { "name": "..." }
GET  /api/v1/admin/config                      ?wiki= (absent = global config; present = resolved config for that wiki)
PATCH /api/v1/admin/config                     body: { "key": "serve.http_port", "value": "9090", "global": true }
GET  /api/v1/admin/index/{wiki}
POST /api/v1/admin/index/{wiki}/rebuild
GET  /api/v1/admin/schema/{wiki}
POST /api/v1/admin/schema/{wiki}
DELETE /api/v1/admin/schema/{wiki}/{type}
GET  /api/v1/admin/logs                        ?cursor=&limit=
DELETE /api/v1/admin/logs
```

`{wiki}` path segment maps to `--wiki` CLI flag. Unknown wiki → `404 wiki_not_found`.

## DTOs

All in `dto.rs`, `#[derive(Serialize, Deserialize, ToSchema)]`.

### Pagination

```rust
pub struct PageParams {
    pub cursor: Option<String>,   // opaque base64-encoded offset
    pub limit:  Option<u32>,      // default: config defaults.list_page_size
}

pub struct Page<T> {
    pub items:       Vec<T>,
    pub total:       u32,
    pub next_cursor: Option<String>,  // None = last page
}
```

Cursor encoding: `base64::encode(offset.to_le_bytes())`. Stateless — decodes to integer offset, passed to existing `ops/` functions unchanged.

### Key request/response pairs (representative)

```rust
// Search
pub struct SearchQuery  { pub q: String, pub top_k: Option<u32>, pub sections: Option<bool> }
pub struct SearchHit    { pub slug: String, pub title: String, pub excerpt: Option<String>, pub score: f32 }

// Page content
pub struct PageReadResponse  { pub slug: String, pub title: String, pub content: String, pub frontmatter: serde_json::Value }
pub struct PageWriteRequest  { pub content: String, pub frontmatter: Option<serde_json::Value> }
pub struct PageNewRequest    { pub title: String, pub content: String, pub page_type: Option<String> }

// Lint
pub struct LintViolation { pub slug: String, pub rule: String, pub severity: String, pub message: String }

// Spaces
pub struct SpaceEntry   { pub name: String, pub path: String, pub description: Option<String> }
pub struct SpaceCreate  { pub name: String, pub path: String, pub description: Option<String>, pub wiki_root: Option<String> }

// Config
pub struct ConfigPatch  { pub key: String, pub value: String, pub global: bool }
```

## Error Handling

```rust
pub enum ApiError {
    NotFound(String),
    BadRequest(String),
    Conflict(String),
    Internal(anyhow::Error),
}
```

JSON body: `{ "error": "<message>", "code": "<snake_case>" }`

| Variant | HTTP status | code |
|---------|-------------|------|
| NotFound | 404 | `not_found` / `wiki_not_found` / `page_not_found` |
| BadRequest | 400 | `bad_request` |
| Conflict | 409 | `conflict` |
| Internal | 500 | `internal` |

`anyhow::Error` from `ops/` layer converts via `From<anyhow::Error> for ApiError` → `Internal`.

## HTTP Status Conventions

| Situation | Status |
|-----------|--------|
| Successful read | 200 |
| Resource created | 201 |
| Mutation with no response body | 204 |
| Invalid input | 400 |
| Unknown wiki / page / space | 404 |
| Slug already exists | 409 |
| Engine error | 500 |

## Config Changes

New fields in `ServeConfig`:

```toml
[serve]
api      = false    # enable REST API (default: false)
api_port = 8081     # REST API port (separate from http_port = 8080)
```

New arms in `set_global_config_value` / `get_config_value`: `serve.api`, `serve.api_port`.

New CLI flag: `llm-wiki serve --api` (mirrors `--http`, `--acp`).

`serve_http` in `server.rs` spawns a second `TcpListener` when `config.serve.api` is true, with the same restart/shutdown logic as the existing HTTP listener.

## New Dependencies

```toml
utoipa             = { version = "5", features = ["axum_extras"] }
utoipa-swagger-ui  = { version = "8", features = ["axum"] }
base64             = "0.22"
```

`utoipa` 5.x targets axum 0.8. `utoipa-swagger-ui` 8.x pairs with utoipa 5. `base64` for cursor encoding only.

## Testing

Integration tests in `tests/api/`. Each test binds `TcpListener::bind("127.0.0.1:0")` (random port) + `tempfile::TempDir` wiki root — same pattern as existing integration tests. No mocking.

### `/wiki` coverage

| Endpoint | Cases |
|----------|-------|
| search | results returned; empty `q` → 400 |
| list | pagination: first page has `next_cursor`; last page has `next_cursor: null` |
| pages GET | known slug → 200; unknown → 404 |
| pages PUT | content updated, re-read matches |
| pages POST | created → 201, duplicate slug → 409 |
| pages DELETE | deleted → 204, re-GET → 404 |
| ingest | file ingested, appears in list |
| lint | clean wiki → empty items; dirty page → violations |
| suggest | returns `Page<Suggestion>` |
| graph | returns mermaid string |
| export | returns export body |
| stats | returns `WikiStats` with correct page count |
| history | returns `Page<HistoryEntry>` |

### `/admin` coverage

| Endpoint | Cases |
|----------|-------|
| spaces GET | lists registered spaces |
| spaces POST | creates space → 201 |
| spaces DELETE | removes → 204, re-GET → 404 |
| spaces default PUT | default updated |
| config GET | reflects defaults |
| config PATCH | key updated, re-GET reflects change |
| index GET | returns status |
| index rebuild POST | returns 204 |
| schema CRUD | list → add → show → remove round-trip |
| logs GET | returns `Page<String>` |
| logs DELETE | clears → 204 |

### OpenAPI

- `GET /api/v1/openapi.json` → 200, valid JSON
- Spot-check: spec contains `paths./api/v1/wiki/{wiki}/search`

## Future Considerations (out of scope for v1)

- **Auth**: `tower-http` `ValidateRequestHeader` bearer token, gated per route group (`/admin` first)
- **Streaming export**: chunked transfer for large wikis
- **Webhook events**: POST to registered URLs on page write/ingest
- **Rate limiting**: `tower_governor` middleware
