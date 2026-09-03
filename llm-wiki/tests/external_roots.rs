//! End-to-end coverage for external content roots — the `raw/` layer.
//!
//! A wiki that declares `external_roots = ["raw"]` must be able to index, read,
//! write, and ingest files in `<repo>/raw`, all under slugs that keep the `raw/`
//! prefix. Preserved source material is create-only: an existing file there is
//! never rewritten.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::git;
use llm_wiki::ops;

const PAGE: &str = "---\ntitle: \"Scrum 8-24\"\ntype: doc\nstatus: active\n---\n\nHuddle notes.\n";

/// Create a wiki that declares `raw/` as an external root, with one compiled
/// page and one preserved raw page already committed.
fn setup(dir: &Path) -> (PathBuf, PathBuf) {
    let config_path = dir.join("state").join("config.toml");
    let wiki_path = dir.join("test");

    llm_wiki::spaces::create(&wiki_path, "test", None, false, true, &config_path, None).unwrap();

    // Opt this wiki into the raw layer.
    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap_or_default();
    cfg.push_str("\nexternal_roots = [\"raw\"]\n");
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    fs::create_dir_all(wiki_root.join("sources")).unwrap();
    fs::write(
        wiki_root.join("sources/scrum-8-24-summary.md"),
        "---\ntitle: \"Scrum summary\"\ntype: doc\nstatus: active\n---\n\nSummary.\n",
    )
    .unwrap();

    let raw_root = wiki_path.join("raw");
    fs::create_dir_all(raw_root.join("meetings")).unwrap();
    fs::write(raw_root.join("meetings/scrum-8-24.md"), PAGE).unwrap();

    git::commit(&wiki_path, "seed").unwrap();
    // The engine stores the canonical repo path; on macOS the tempdir is a
    // symlink (/var → /private/var), so compare against the canonical form.
    let wiki_path = wiki_path.canonicalize().unwrap();
    (config_path, wiki_path)
}

#[test]
fn raw_pages_are_indexed_and_searchable() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();

    manager.rebuild_index("test").unwrap();

    let engine = manager.state.read().unwrap();
    let result = ops::search(
        &engine,
        "test",
        &ops::SearchParams {
            query: "Huddle",
            type_filter: None,
            no_excerpt: true,
            top_k: Some(20),
            include_sections: false,
            cross_wiki: false,
        },
    )
    .unwrap();
    let slugs: Vec<&str> = result.results.iter().map(|r| r.slug.as_str()).collect();
    assert!(
        slugs.contains(&"raw/meetings/scrum-8-24"),
        "raw page missing from search results: {slugs:?}"
    );
}

#[test]
fn raw_slug_keeps_its_root_prefix() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();
    let space = engine.space("test").unwrap();

    let slug = space
        .roots
        .slug_from_path(&wiki_path.join("raw/meetings/scrum-8-24.md"))
        .unwrap();
    assert_eq!(slug.as_str(), "raw/meetings/scrum-8-24");
    assert_eq!(
        space.roots.resolve(&slug).unwrap(),
        wiki_path.join("raw/meetings/scrum-8-24.md")
    );
}

#[test]
fn raw_page_is_readable_through_content_read() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let read = ops::content_read(
        &engine,
        "raw/meetings/scrum-8-24",
        Some("test"),
        false,
        false,
    )
    .unwrap();
    match read {
        ops::ContentReadResult::Page(text) => assert!(text.contains("Huddle notes.")),
        _ => panic!("expected a page"),
    }
}

#[test]
fn new_raw_page_can_be_written() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let result =
        ops::content_write(&engine, "raw/meetings/scrum-8-25", Some("test"), PAGE).unwrap();

    assert_eq!(result.path, wiki_path.join("raw/meetings/scrum-8-25.md"));
    assert!(result.path.is_file());
}

#[test]
fn existing_raw_page_is_not_overwritten() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let err = ops::content_write(
        &engine,
        "raw/meetings/scrum-8-24",
        Some("test"),
        "---\ntitle: \"Rewritten\"\n---\n\nDestroyed.\n",
    )
    .unwrap_err()
    .to_string();

    assert!(
        err.contains("preserved source material"),
        "unexpected error: {err}"
    );
    let on_disk = fs::read_to_string(wiki_path.join("raw/meetings/scrum-8-24.md")).unwrap();
    assert_eq!(on_disk, PAGE, "raw file was modified despite the guard");
}

#[test]
fn compiled_pages_are_still_overwritable() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    ops::content_write(
        &engine,
        "sources/scrum-8-24-summary",
        Some("test"),
        "---\ntitle: \"Scrum summary\"\ntype: doc\n---\n\nRevised.\n",
    )
    .unwrap();

    let on_disk = fs::read_to_string(wiki_path.join("wiki/sources/scrum-8-24-summary.md")).unwrap();
    assert!(on_disk.contains("Revised."));
}

#[test]
fn ingest_accepts_a_raw_path() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let report = ops::ingest(&engine, &manager, "raw/meetings", true, "test").unwrap();
    assert_eq!(report.pages_validated, 1, "raw page was not validated");
}

#[test]
fn ingest_still_rejects_paths_outside_every_root() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    fs::create_dir_all(wiki_path.join("schemas")).unwrap();
    fs::write(wiki_path.join("schemas/stray.md"), PAGE).unwrap();

    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let err = ops::ingest(&engine, &manager, "../schemas/stray.md", true, "test")
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("content roots") || err.contains("does not exist"),
        "unexpected error: {err}"
    );
}

#[test]
fn wikis_without_external_roots_are_unaffected() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = dir.path().join("state").join("config.toml");
    let wiki_path = dir.path().join("plain");
    llm_wiki::spaces::create(&wiki_path, "plain", None, false, true, &config_path, None).unwrap();

    let raw_root = wiki_path.join("raw");
    fs::create_dir_all(&raw_root).unwrap();
    fs::write(raw_root.join("note.md"), PAGE).unwrap();
    git::commit(&wiki_path, "seed").unwrap();

    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("plain").unwrap();
    let engine = manager.state.read().unwrap();
    let space = engine.space("plain").unwrap();

    assert!(space.roots.external_names().is_empty());
    // `raw/note` resolves under the wiki root, where nothing exists
    assert!(
        ops::content_read(&engine, "raw/note", Some("plain"), false, false).is_err(),
        "raw/ should be invisible to a wiki that has not opted in"
    );
}

// ── Living documents inside a preserved root ──────────────────────────────────

/// A wiki that keeps specifications beside transcripts and says which is which.
fn setup_with_revisable(dir: &Path) -> (PathBuf, PathBuf) {
    let (config_path, wiki_path) = setup(dir);
    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap();
    cfg.push_str("\nrevisable = [\"raw/product\"]\n");
    fs::write(&wiki_toml, cfg).unwrap();

    fs::create_dir_all(wiki_path.join("raw/product")).unwrap();
    fs::write(wiki_path.join("raw/product/spec.md"), PAGE).unwrap();
    llm_wiki::git::commit(&wiki_path, "add a spec").unwrap();
    (config_path, wiki_path)
}

#[test]
fn a_declared_living_document_can_be_revised_in_place() {
    // A specification is revised as the product changes, and the revision is
    // the record. Freezing it would freeze the thing the wiki compiles from.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup_with_revisable(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let revised = "---\ntitle: \"Spec\"\ntype: doc\nstatus: active\n---\n\n개정된 내용.\n";
    ops::content_write(&engine, "raw/product/spec", Some("test"), revised)
        .expect("a declared living document must be writable");

    let on_disk = fs::read_to_string(wiki_path.join("raw/product/spec.md")).unwrap();
    assert!(on_disk.contains("개정된 내용."));
}

#[test]
fn a_transcript_beside_it_is_still_write_once() {
    // The declaration is per path, not per root: declaring specs revisable must
    // not unfreeze the meeting notes they sit next to.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup_with_revisable(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let err = ops::content_write(
        &engine,
        "raw/meetings/scrum-8-24",
        Some("test"),
        "---\ntitle: X\n---\n\n덮어쓰기.\n",
    )
    .unwrap_err()
    .to_string();
    assert!(err.contains("preserved source material"), "{err}");
    assert_eq!(
        fs::read_to_string(wiki_path.join("raw/meetings/scrum-8-24.md")).unwrap(),
        PAGE
    );
}

#[test]
fn apply_honours_the_same_distinction() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup_with_revisable(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let req = |path: &str| llm_wiki::ops::ApplyRequest {
        mode: llm_wiki::ops::ApplyMode::Archive,
        changes: vec![llm_wiki::ops::Change {
            path: path.to_string(),
            content: "---\ntitle: X\ntype: doc\n---\n\n개정.\n".to_string(),
        }],
        message: None,
        reason: None,
        expected_head: None,
        dry_run: true,
    };

    assert!(
        ops::apply(&engine, &manager, "test", &req("raw/product/spec")).is_ok(),
        "a living document should pass"
    );
    assert!(
        ops::apply(&engine, &manager, "test", &req("raw/meetings/scrum-8-24")).is_err(),
        "a transcript should not"
    );
}
