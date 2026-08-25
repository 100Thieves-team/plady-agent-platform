//! The rules document must be reachable through the engine, not only on disk.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;

const RULES: &str = "\
# Agent rules

Preamble that is not the contract.

<!-- mcp-instructions:start -->
Raw sources are immutable. One source normally touches several pages.
<!-- mcp-instructions:end -->

## MCP ingest workflow

1. Preserve the original in `raw/`.
2. Compile a source page.

## Link rules

Use CommonMark links.
";

fn setup(dir: &Path, rules: Option<&str>) -> (PathBuf, PathBuf) {
    let config_path = dir.join("state").join("config.toml");
    let wiki_path = dir.join("test");
    llm_wiki::spaces::create(&wiki_path, "test", None, false, true, &config_path, None).unwrap();
    if let Some(text) = rules {
        fs::write(wiki_path.join("AGENTS.md"), text).unwrap();
    }
    (config_path, wiki_path)
}

#[test]
fn full_document_is_returned_without_a_section() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path(), Some(RULES));
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let out = ops::rules(&engine, "test", None).unwrap();
    assert!(out.contains("## Link rules"));
    assert!(out.contains("Preamble"));
}

#[test]
fn a_named_section_is_returned_alone() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path(), Some(RULES));
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let out = ops::rules(&engine, "test", Some("ingest")).unwrap();
    assert!(out.starts_with("## MCP ingest workflow"));
    assert!(out.contains("Preserve the original"));
    assert!(!out.contains("Link rules"), "section ran past its sibling");
}

#[test]
fn unknown_section_lists_the_available_ones() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path(), Some(RULES));
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let err = ops::rules(&engine, "test", Some("nonexistent"))
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("## Link rules"),
        "error should list sections: {err}"
    );
}

#[test]
fn handshake_instructions_carry_only_the_marked_contract() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path(), Some(RULES));
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let text = ops::instructions_for(&engine, "test").unwrap();
    assert!(text.contains("Raw sources are immutable."));
    assert!(
        !text.contains("Preamble"),
        "unmarked preamble leaked into the handshake"
    );
    assert!(
        text.contains("wiki_rules"),
        "instructions must name the tool holding the rest"
    );
}

#[test]
fn a_wiki_without_rules_is_not_an_error() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path(), None);
    // spaces::create may scaffold its own AGENTS.md; remove it to test absence.
    let _ = fs::remove_file(wiki_path.join("AGENTS.md"));
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    assert!(ops::instructions_for(&engine, "test").is_none());
    assert!(ops::rules(&engine, "test", None).is_err());
}

#[test]
fn rules_file_cannot_point_outside_the_repo() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path(), Some(RULES));
    fs::write(dir.path().join("secret.md"), "not yours").unwrap();

    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap_or_default();
    cfg.push_str("\nrules_file = \"../secret.md\"\n");
    fs::write(&wiki_toml, cfg).unwrap();

    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    assert!(
        ops::rules(&engine, "test", None).is_err(),
        "a rules_file escaping the repo root must be refused"
    );
}
