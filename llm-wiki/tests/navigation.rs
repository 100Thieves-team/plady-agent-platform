//! The catalogue and the timeline, over a wiki with real shape.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;

fn page(title: &str, summary: &str) -> String {
    format!(
        "---\ntitle: \"{title}\"\nstatus: active\nsummary: \"{summary}\"\nlast_updated: \"2026-08-25\"\ntags:\n  - x\n---\n\nbody\n"
    )
}

fn setup(dir: &Path) -> (PathBuf, PathBuf) {
    let config_path = dir.join("state").join("config.toml");
    let wiki_path = dir.join("test");
    llm_wiki::spaces::create(&wiki_path, "test", None, false, true, &config_path, None).unwrap();

    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap_or_default();
    cfg.push_str(
        "\nexternal_roots = [\"raw\"]\n\n\
         [type_by_prefix]\n\
         sources = \"source\"\n\
         topics = \"topic\"\n\
         people = \"person\"\n\
         raw = \"raw\"\n",
    );
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    for dir_name in ["topics", "sources", "people"] {
        fs::create_dir_all(wiki_root.join(dir_name)).unwrap();
    }
    fs::write(wiki_root.join("topics/t-a.md"), page("Topic A", "첫 토픽")).unwrap();
    fs::write(
        wiki_root.join("topics/t-b.md"),
        page("Topic B", "둘째 토픽"),
    )
    .unwrap();
    fs::write(wiki_root.join("people/p-a.md"), page("Person A", "사람")).unwrap();
    fs::create_dir_all(wiki_path.join("raw/meetings")).unwrap();
    fs::write(wiki_path.join("raw/meetings/m1.md"), page("M1", "원문")).unwrap();
    // A non-ASCII filename: git escapes these in `--name-only` output unless
    // told not to, and this wiki's pages are almost all Korean.
    fs::write(
        wiki_path.join("raw/meetings/데일리스크럼-8-25.md"),
        page("스크럼", "한글 파일명"),
    )
    .unwrap();
    llm_wiki::git::commit(&wiki_path, "seed pages").unwrap();

    // A second commit so the timeline has more than one entry.
    fs::write(wiki_root.join("sources/s-a.md"), page("Source A", "요약")).unwrap();
    llm_wiki::git::commit(&wiki_path, "add source A").unwrap();

    (config_path, wiki_path.canonicalize().unwrap())
}

fn engine_for(config_path: &Path) -> WikiEngine {
    let m = WikiEngine::build(config_path).unwrap();
    m.rebuild_index("test").unwrap();
    m
}

// ── Catalog ───────────────────────────────────────────────────────────────────

#[test]
fn the_catalog_groups_every_kind_with_counts_and_summaries() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let cat = ops::catalog(&engine, "test", None).unwrap();
    let kinds: Vec<&str> = cat.sections.iter().map(|s| s.kind.as_str()).collect();
    assert!(kinds.contains(&"topic"), "{kinds:?}");
    assert!(kinds.contains(&"source"), "{kinds:?}");
    assert!(kinds.contains(&"raw"), "{kinds:?}");

    let topics = cat.sections.iter().find(|s| s.kind == "topic").unwrap();
    assert_eq!(topics.total, 2);
    assert!(
        topics
            .entries
            .iter()
            .any(|e| e.summary.as_deref() == Some("첫 토픽")),
        "a catalogue without summaries is just a file listing"
    );
}

#[test]
fn compiled_layers_come_before_preserved_sources() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let cat = ops::catalog(&engine, "test", None).unwrap();
    let pos = |k: &str| cat.sections.iter().position(|s| s.kind == k);
    assert!(
        pos("topic") < pos("raw"),
        "raw should not be the first thing an agent reads: {:?}",
        cat.sections.iter().map(|s| &s.kind).collect::<Vec<_>>()
    );
}

#[test]
fn section_index_pages_are_not_catalogued_as_knowledge() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    fs::write(
        wiki_path.join("raw/_index.md"),
        "---\ntitle: Raw\ntype: section\n---\n\nindex\n",
    )
    .unwrap();
    llm_wiki::git::commit(&wiki_path, "add section index").unwrap();

    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();
    let cat = ops::catalog(&engine, "test", None).unwrap();
    assert!(
        !cat.sections.iter().any(|s| s.kind == "section"),
        "structural index pages are navigation, not content"
    );
}

#[test]
fn naming_a_section_lists_only_that_kind() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let cat = ops::catalog(&engine, "test", Some("topic")).unwrap();
    assert_eq!(cat.sections.len(), 1);
    assert_eq!(cat.sections[0].kind, "topic");
}

#[test]
fn an_unknown_section_says_so_rather_than_returning_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let cat = ops::catalog(&engine, "test", Some("nonexistent")).unwrap();
    assert!(cat.sections.is_empty());
    assert!(
        cat.notes.iter().any(|n| n.contains("which kinds exist")),
        "an empty answer should say how to get a useful one: {:?}",
        cat.notes
    );
}

// ── Recent ────────────────────────────────────────────────────────────────────

#[test]
fn recent_reports_commits_newest_first_with_their_pages() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let report = ops::recent(&engine, "test", None, None).unwrap();
    assert!(report.changes.len() >= 2, "{:?}", report.changes);
    assert_eq!(report.changes[0].message, "add source A");
    assert_eq!(report.changes[0].pages, ["sources/s-a"]);
}

#[test]
fn recent_reports_slugs_across_content_roots() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let report = ops::recent(&engine, "test", None, None).unwrap();
    let all: Vec<&str> = report
        .changes
        .iter()
        .flat_map(|c| c.pages.iter().map(String::as_str))
        .collect();
    assert!(all.contains(&"topics/t-a"), "{all:?}");
    assert!(
        all.contains(&"raw/meetings/m1"),
        "preserved sources belong in the timeline too: {all:?}"
    );
    assert!(
        all.contains(&"raw/meetings/데일리스크럼-8-25"),
        "a non-ASCII page name must survive git's path quoting: {all:?}"
    );
}

#[test]
fn the_limit_is_honoured() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let report = ops::recent(&engine, "test", Some(1), None).unwrap();
    assert_eq!(report.changes.len(), 1);
}

#[test]
fn a_future_window_returns_nothing_rather_than_everything() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let report = ops::recent(&engine, "test", None, Some("30 years ago")).unwrap();
    assert!(
        !report.changes.is_empty(),
        "a wide window should include everything"
    );

    let none = ops::recent(&engine, "test", None, Some("2099-01-01")).unwrap();
    assert!(
        none.changes.is_empty(),
        "a window after every commit should be empty, not ignored: {:?}",
        none.changes
    );
}

#[test]
fn the_report_says_where_it_came_from() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let report = ops::recent(&engine, "test", None, None).unwrap();
    assert!(
        report.notes.iter().any(|n| n.contains("git history")),
        "a derived answer should say what it derives from: {:?}",
        report.notes
    );
}
