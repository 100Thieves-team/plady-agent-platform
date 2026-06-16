# llm-wiki development Makefile

DEBUG_BIN := ./target/debug/llm-wiki
REL_BIN   := ./target/release/llm-wiki

.PHONY: build build-release validate-py validate-py-engine validate-py-acp validate-py-mcp pre-release

# ── Build ──────────────────────────────────────────────────────────────────────

build:
	cargo build

build-release:
	cargo build --release --locked

# ── integration suite ──────────────────────────────────────────────────

validate-py: build
	$(MAKE) -C tests-integration test BINARY=$(CURDIR)/$(DEBUG_BIN)

validate-py-engine: build
	$(MAKE) -C tests-integration test-engine BINARY=$(CURDIR)/$(DEBUG_BIN)

validate-py-acp: build
	$(MAKE) -C tests-integration test-acp BINARY=$(CURDIR)/$(DEBUG_BIN)

validate-py-mcp: build
	$(MAKE) -C tests-integration test-mcp BINARY=$(CURDIR)/$(DEBUG_BIN)

# ── Pre-release checklist ─────────────────────────────────────────────────────
# Mirrors docs/guides/release.md pre-release checklist.
# Run before opening a release PR — all commands must pass.

pre-release:
	cargo test
	cargo test --doc
	cargo fmt --check
	cargo clippy --all-targets -- -D warnings
	cargo build --release --locked
