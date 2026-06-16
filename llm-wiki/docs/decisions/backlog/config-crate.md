---
title: "Reject config crate (deferred)"
summary: "Do not adopt the config crate — current TOML loading is sufficient. Revisit if env-var override support becomes a real requirement."
status: deferred
date: "2026-05-03"
---

# Reject `config` crate adoption

## Context

`src/config.rs` loads two TOML files (`~/.llm-wiki/config.toml` and `<wiki-root>/wiki.toml`) via plain `toml::from_str` into typed structs. Merge logic lives in `resolve()`. The `config` crate (crates.io) was evaluated as a potential replacement to reduce match-arm boilerplate in the CLI `config get/set` commands and to gain layered source support (env vars, multiple files).

## Decision

Do not adopt the `config` crate.

**Reasons:**

- `resolve()` implements selective `Option<T>` merging (per-wiki section absent = global wins). The `config` crate cannot replace this logic — it would stay regardless.
- Typed field access (`config.serve.http_port`, etc.) is unchanged by the crate. No simplification there.
- The only code the crate would replace: three match-arm functions (~190 arms) in `ops/config.rs` used solely by the CLI `config get/set` subcommands. That is not a scaling problem.
- Match arms are exhaustive and compiler-checked. Replacing them with string-keyed `config.get("key")` calls loses that guarantee; typos become silent runtime failures.
- The only genuinely missing feature is env-var overrides. This can be addressed with a targeted `apply_env_overrides` function (~20 lines, zero new dependencies) if the need arises.

## Consequences

No change to `Cargo.toml` or `src/config.rs`. When a new config key is added, three match blocks in `ops/config.rs` must be updated (~3 lines per key). Acceptable cost.

## Revisit conditions

Reopen this decision if any of the following occur:

- Env-var override support is requested for Docker or CI deployments and the scope exceeds ~5 keys.
- The number of config keys grows large enough that maintaining three match blocks becomes a recurring source of bugs.
- A structured config-diff or config-migration feature is needed that would benefit from the crate's introspection APIs.
