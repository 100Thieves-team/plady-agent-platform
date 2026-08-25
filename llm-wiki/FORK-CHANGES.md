# Fork changes

This tree vendors [geronimo-iia/llm-wiki](https://github.com/geronimo-iia/llm-wiki) v0.4.1 and
carries local changes on top. Everything below is ours; keep this list current so a future rebase
onto upstream knows what to replay.

Changes are additive where possible — new modules, new config fields, new tool arguments — so that
upstream files stay close to their original shape.

## Asset read/write over MCP

`wiki_content_read` / `wiki_content_write` accept paths whose last segment carries a file
extension, resolving them to co-located assets rather than pages. Writes are limited to text
formats (`yaml`, `yml`, `json`, `txt`, `csv`); reads accept any non-`.md` extension. Both share
`slug::split_asset_path` so path-traversal defenses cannot drift apart.

Motivation: the team's policy spec lives in a YAML file inside the wiki repo and is edited by
agents through MCP.

- `src/slug.rs` — `WRITABLE_ASSET_EXTENSIONS`, `WriteTarget`, `resolve_write_target`,
  `resolve_entry_and_rel`, `split_asset_path`
- `src/ops/content.rs` — asset branches in `content_read` / `content_write`
- `tests/ops/content.rs`, `tests/slug.rs`

## External content roots (the `raw/` layer)

Upstream treats one directory — `wiki_root`, default `<repo>/wiki` — as the whole wiki. In the
three-layer model this project follows (Karpathy's LLM Wiki: immutable raw sources, LLM-owned
compiled pages, schema/rules), the raw source layer sits *outside* that directory, which made it
unreadable, unwritable, and unindexable through the server. An agent asked to preserve a meeting
transcript had nowhere correct to put it.

A space may now declare sibling directories of the wiki root as **external content roots**:

```toml
# wiki.toml
external_roots = ["raw"]
```

A slug names its own root through its first segment — `sources/x` is a compiled page, `raw/meetings/x`
is preserved source material. Because an external slug already carries its root's directory name,
resolving it only needs the *parent* of the wiki root as the join base, so no existing slug, link,
or URI changes meaning. A space with no `external_roots` behaves exactly as before.

External roots are **create-only**: a new file may be written there, an existing one may not be
overwritten. That is what makes "raw sources are immutable" enforceable rather than advisory; the
error points at the two legitimate alternatives (add an addendum, or compile the correction into a
`wiki/` page).

- `src/content_roots.rs` — new module; `ContentRoots` owns root resolution, slug↔path mapping,
  walk order, and repo-relative prefixes
- `src/config.rs` — `WikiConfig::external_roots`
- `src/engine.rs` — `SpaceContext::roots`, built at mount
- `src/index_manager.rs` — `rebuild`, `rebuild_types`, `update`, and `open`'s recovery tuple take
  `&ContentRoots`; the walks cover every root
- `src/git.rs` — change detection filters on all roots' repo-relative prefixes
- `src/markdown.rs` — page/asset I/O resolves through `ContentRoots`
- `src/ingest.rs`, `src/ops/ingest.rs` — `path` resolves against the root its first segment names;
  the traversal guard checks every root instead of only the wiki root. `IngestOptions::changed_paths`
  now holds **repo-relative** paths (a file under an external root has no wiki-root-relative form)
- `src/ops/content.rs` — `guard_external_overwrite`
- `src/slug.rs` — `resolve_read_target` takes `&ContentRoots`
- `src/mcp/tools.rs` — tool descriptions state that `raw/...` is readable, create-only, and
  ingestable
- `tests/external_roots.rs` — end-to-end coverage

### Rebase notes

- `ContentRoots::single(path)` is the drop-in for any upstream call site that still passes a bare
  `wiki_root`, so new upstream code compiles with a one-word change.
- The only behavioural change for a wiki that declares no external roots is the repo-relative
  `changed_paths` representation.

## Docker image

`docker/llm-wiki.Dockerfile` (in the wrapper repo) builds this vendored source in a multi-stage
cargo build. It previously downloaded an upstream release tarball, which silently discarded every
local change.
