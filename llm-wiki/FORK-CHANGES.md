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

## Reachable agent rules

The rules file (`AGENTS.md`) sits at the repo root, outside the wiki root, so no tool could read
it: an agent had to already know the conventions in order to follow them. Two paths now expose it.

The MCP handshake carries a short contract, delimited in the rules file itself:

```markdown
<!-- mcp-instructions:start -->
…the contract every agent must have in context…
<!-- mcp-instructions:end -->
```

Keeping it inside the rules file means one source of truth and no Rust rebuild when a convention
changes. `wiki_rules({section?})` returns the full document, or one heading's section.

- `src/ops/rules.rs` — new module
- `src/config.rs` — `WikiConfig::rules_file` (default `AGENTS.md`; paths escaping the repo root are
  refused)
- `src/mcp/mod.rs` — `ServerInfo::with_instructions`
- `src/mcp/{tools,handlers}.rs` — the `wiki_rules` tool
- `tests/rules.rs`

## Page types derived from location

Every compiled page in this wiki declared `type: doc`, so `wiki_search(type=…)`, `wiki_list(type=…)`,
the graph's `target_types`, and the `unknown-type` lint were all inert. The directory already
encodes what a page is, so a wiki can declare the mapping instead of rewriting ~200 files:

```toml
# wiki.toml
[type_by_prefix]
sources = "source"
topics  = "topic"
raw     = "raw"
```

Applied at index time; `section` index pages keep their structural type. A wiki that declares no
mapping is untouched.

- `src/content_roots.rs` — `with_type_by_prefix`, `page_kind` (longest whole-segment prefix wins)
- `src/config.rs` — `WikiConfig::type_by_prefix`
- `src/index_manager.rs` — `apply_derived_type` at every parse site (full rebuild, partial rebuild,
  incremental update) so all three agree
- `tests/derived_types.rs`

## Upstream bugs found on the way

These are fixes to pre-existing behaviour, not consequences of the changes above.

* **`type` was a stemmed text field.** `base.json` declares it as a plain string, so it was
  classified as text and tokenized: a `TermQuery` for `source` missed documents indexed under the
  stem `sourc`. Type filters failed silently for any type whose stem differs from itself — `doc`
  worked only by luck. `type` is now registered as a keyword alongside `slug`, `uri`, and
  `body_links` (`src/index_schema.rs`).
* **`rebuild` could not recover from a schema change.** `Index::open_or_create` reuses an existing
  index only when the schema matches, so adding a type schema made every rebuild fail — precisely
  when a rebuild is needed. An incompatible directory is now discarded and recreated, which a
  rebuild's `delete_all_documents` implied anyway (`src/index_manager.rs`).
* **`[[1]](url)` was read as a wikilink to a page named `1`.** Slack exports write footnote markers
  that way. A `]]` immediately followed by `(` is CommonMark link text, and an all-digit payload is
  a citation marker — neither is a slug (`src/links.rs`).
* **Site URLs were treated as slugs.** Rendered pages navigate with `/raw/product/rooms/` and
  `meetings/`. A slug is relative and never ends in a separator, so leading- and trailing-slash
  destinations are no longer extracted as links (`src/links.rs`). On this wiki these three link
  fixes took lint from 121 errors to 1.

## A lock shared by every writer

Three processes write this repository's working tree: the MCP server commits pages, a sync sidecar
runs `git add -A` and `git pull --rebase` on a loop, and a renderer rewrites a directory of
generated pages at once. Each is correct alone; together they interleave. The sync loop can commit
a page set an agent is halfway through writing — which is how a multi-page ingest ends up as
several commits with the sidecar's message on them.

`src/repo_lock.rs` adds an advisory lock at `<repo>/.git/llm-wiki.lock`. It is a **directory**,
created with `mkdir`, because that is the one atomic primitive all three languages share: a lock
file written with `>` is not atomic in shell, and `flock(1)` is absent from some of these images.
The owner file records holder, pid, and acquisition time, so a blocked writer names who is holding
it instead of timing out anonymously. A lock older than `lock_stale_after_secs` is broken — a
crashed holder must not wedge the wiki permanently.

Taken by `content_write`, `content_new`, `content_commit`, and non-dry-run `ingest`. A dry run does
not take it: validation only reads, and making the cheap safety check the slow one would train
agents out of using it.

The sidecars in `compose.ec2.yaml` take the same lock with inline `sh` helpers using the identical
directory name and owner-file format. `tests/lock_integration.rs` covers the Rust side and
`repo_lock::cross_language_tests` pins the file format both directions.

- `src/repo_lock.rs`, `src/lib.rs`
- `src/config.rs` — `lock_timeout_secs` (30), `lock_stale_after_secs` (300)
- `src/ops/{content,ingest}.rs` — acquisition points
- `compose.ec2.yaml` — `wiki-data-sync` and `policy-renderer` helpers

### `commit_paths` built a tree from whatever was staged

An upstream bug the lock does not cover. `commit_paths` called `repo.index()` and added its paths to
the **shared on-disk index**, so anything another writer had staged rode along in a commit that
claims to be path-limited — and `index.write()` then overwrote their staging area. The tree is now
built from HEAD plus the named paths, and the on-disk index is never written. A path that no longer
exists is staged as a deletion instead of failing the call (`src/git.rs`).
