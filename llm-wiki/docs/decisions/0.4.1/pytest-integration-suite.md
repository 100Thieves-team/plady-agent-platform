---
title: "Migrate integration tests to pytest"
summary: "Replace bash test scripts with a pytest suite under tests-integration/."
status: accepted
date: "2026-05-04"
---

# Migrate integration tests to pytest

## Decision

Replace bash integration scripts with a pytest suite under `tests-integration/` managed by `uv`. Three suites: `engine/` (CLI subprocess), `mcp/` (MCP stdio via `mcp` Python SDK), `acp/` (ACP NDJSON stdio via `asyncio`).

## Context

The bash harness in `docs/testing/scripts/` accumulated structural limits: `grep -v` negative assertions could false-positive, no guaranteed teardown, JSON inspection required `jq`, ACP tests required tmpfiles + `sleep` polling. A false-positive bug shipped in the initial scripts and was only caught during v0.4.1 gap analysis.

## Rationale

- `assert "x" not in result.stdout` cannot false-positive; `grep -v` can
- pytest `tmp_path` gives isolated directories with automatic teardown
- Python `asyncio.create_subprocess_exec` replaces 120 lines of ACP shell helpers
- `@pytest.mark.parametrize`, JUnit XML, per-file runs available without extra infrastructure

## Architecture

```
tests-integration/
  pyproject.toml      # uv project: pytest + pytest-asyncio + mcp
  Makefile            # test-engine / test-acp / test-mcp via uv
  conftest.py         # WikiEnv fixture — boots two wikis per test
  engine/             # CLI subprocess tests
  mcp/                # MCP stdio tests
  acp/                # ACP stdio tests
```

Root `Makefile` delegates with `$(MAKE) -C tests-integration`. `tests-integration/` excluded from `cargo publish` via `Cargo.toml`.
