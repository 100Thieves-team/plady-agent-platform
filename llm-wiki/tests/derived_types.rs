//! Page types derived from slug prefixes.
//!
//! The wiki's directories already encode what each page is; `type_by_prefix`
//! makes the index agree, so `type` filters and graph edges work without
//! rewriting frontmatter across the corpus.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;

/// Every page here claims `type: doc` — the uninformative value the mapping
/// exists to correct.
const DOC: &str = "---\ntitle: \"P\"\ntype: doc\nstatus: active\n---\n\nBody text.\n";
const SECTION: &str = "---\ntitle: \"S\"\ntype: section\nstatus: active\n---\n\nIndex.\n";

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
         raw = \"raw\"\n",
    );
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    for (rel, body) in [
        ("sources/a.md", DOC),
        ("topics/t-x.md", DOC),
        ("people/p-y.md", DOC),
    ] {
        let path = wiki_root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, body).unwrap();
    }
    let raw_root = wiki_path.join("raw");
    fs::create_dir_all(raw_root.join("meetings")).unwrap();
    fs::write(raw_root.join("meetings/m.md"), DOC).unwrap();
    fs::write(raw_root.join("_index.md"), SECTION).unwrap();

    llm_wiki::git::commit(&wiki_path, "seed").unwrap();
    (config_path, wiki_path.canonicalize().unwrap())
}

fn slugs_of_type(manager: &WikiEngine, type_name: &str) -> Vec<String> {
    let engine = manager.state.read().unwrap();
    let list = ops::list(&engine, "test", Some(type_name), None, 1, Some(100)).unwrap();
    let mut slugs: Vec<String> = list.pages.iter().map(|p| p.slug.clone()).collect();
    slugs.sort();
    slugs
}

#[test]
fn slug_prefix_overrides_uninformative_frontmatter() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("test").unwrap();

    assert_eq!(slugs_of_type(&manager, "source"), ["sources/a"]);
    assert_eq!(slugs_of_type(&manager, "topic"), ["topics/t-x"]);
    assert_eq!(slugs_of_type(&manager, "raw"), ["raw/meetings/m"]);
}

#[test]
fn unmapped_prefixes_keep_their_declared_type() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("test").unwrap();

    // `people` has no mapping, so its page stays `doc`
    assert_eq!(slugs_of_type(&manager, "doc"), ["people/p-y"]);
}

#[test]
fn section_pages_are_never_retyped() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("test").unwrap();

    // `raw/_index` sits under a mapped prefix but must stay structural
    assert!(
        !slugs_of_type(&manager, "raw").contains(&"raw".to_string()),
        "a section index page was retyped"
    );
}

#[test]
fn incremental_update_derives_the_same_type_as_a_rebuild() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("test").unwrap();

    fs::write(wiki_path.join("wiki/sources/b.md"), DOC).unwrap();
    llm_wiki::git::commit(&wiki_path, "add source b").unwrap();
    manager.refresh_index("test").unwrap();

    assert_eq!(
        slugs_of_type(&manager, "source"),
        ["sources/a", "sources/b"]
    );
}

#[test]
fn a_wiki_without_the_mapping_is_unaffected() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = dir.path().join("state").join("config.toml");
    let wiki_path = dir.path().join("plain");
    llm_wiki::spaces::create(&wiki_path, "plain", None, false, true, &config_path, None).unwrap();

    let wiki_root = wiki_path.join("wiki");
    fs::create_dir_all(wiki_root.join("sources")).unwrap();
    fs::write(wiki_root.join("sources/a.md"), DOC).unwrap();
    llm_wiki::git::commit(&wiki_path, "seed").unwrap();

    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("plain").unwrap();
    let engine = manager.state.read().unwrap();

    let list = ops::list(&engine, "plain", Some("doc"), None, 1, Some(100)).unwrap();
    assert_eq!(list.pages.len(), 1, "frontmatter type should be untouched");
}

#[test]
fn type_filter_matches_exactly_rather_than_by_stem() {
    // `type` must be indexed as a keyword. As a stemmed text field, "source"
    // is stored under the stem "sourc" and a TermQuery for "source" finds
    // nothing — a filter that fails silently rather than erroring.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    manager.rebuild_index("test").unwrap();

    assert_eq!(slugs_of_type(&manager, "source"), ["sources/a"]);
    assert!(
        slugs_of_type(&manager, "sourc").is_empty(),
        "the stem must not match — that would mean the field is still tokenized"
    );
}
