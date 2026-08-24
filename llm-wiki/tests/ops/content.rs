use super::helpers::setup_wiki;
use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;

// ── Content ───────────────────────────────────────────────────────────────────

#[test]
fn content_read_page() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    match ops::content_read(&engine, "concepts/moe", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => {
            assert!(content.contains("Mixture of Experts"));
        }
        _ => panic!("expected Page"),
    }
}

#[test]
fn content_read_no_frontmatter() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    match ops::content_read(&engine, "concepts/moe", None, true, false).unwrap() {
        ops::ContentReadResult::Page(content) => {
            assert!(!content.contains("title:"));
            assert!(content.contains("Mixture of Experts"));
        }
        _ => panic!("expected Page"),
    }
}

#[test]
fn content_write_and_read_back() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let body = "---\ntitle: \"New\"\ntype: page\n---\n\nHello.\n";
    let result = ops::content_write(&engine, "new-page", None, body).unwrap();
    assert_eq!(result.bytes_written, body.len());

    match ops::content_read(&engine, "new-page", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => assert!(content.contains("Hello.")),
        _ => panic!("expected Page"),
    }
}

#[test]
fn content_read_yaml_asset() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let wiki_root = dir.path().join("test").join("wiki");
    std::fs::create_dir_all(wiki_root.join("policy/_src")).unwrap();
    let body = "status: active\nowner: team\n";
    std::fs::write(wiki_root.join("policy/_src/state-ssot.yaml"), body).unwrap();

    match ops::content_read(&engine, "policy/_src/state-ssot.yaml", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => assert_eq!(content, body),
        _ => panic!("expected asset text"),
    }
}

#[test]
fn content_write_then_read_asset_round_trip() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let body = "policies:\n  - id: p1\n    state: draft\n";
    ops::content_write(&engine, "policy/_src/state-ssot.yaml", None, body).unwrap();

    match ops::content_read(&engine, "policy/_src/state-ssot.yaml", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => assert_eq!(content, body),
        _ => panic!("expected asset text"),
    }

    // Read-modify-write: the edited content must round-trip too
    let edited = "policies:\n  - id: p1\n    state: active\n";
    ops::content_write(&engine, "policy/_src/state-ssot.yaml", None, edited).unwrap();
    match ops::content_read(&engine, "policy/_src/state-ssot.yaml", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => assert_eq!(content, edited),
        _ => panic!("expected asset text"),
    }
}

#[test]
fn content_read_asset_rejects_traversal() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    // Plant a file outside the wiki root that traversal would otherwise reach
    std::fs::write(dir.path().join("test").join("secret.yaml"), "leak: true").unwrap();

    assert!(ops::content_read(&engine, "wiki/../secret.yaml", None, false, false).is_err());
    assert!(ops::content_read(&engine, "policy/../../secret.yaml", None, false, false).is_err());
    assert!(ops::content_read(&engine, "/etc/hosts.txt", None, false, false).is_err());
}

#[test]
fn content_read_missing_asset_reports_not_found() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let err = ops::content_read(&engine, "policy/_src/absent.yaml", None, false, false)
        .map(|_| ())
        .unwrap_err()
        .to_string();
    assert!(err.contains("asset not found"), "unexpected error: {err}");
}

#[test]
fn content_read_list_assets_unchanged() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let wiki_root = dir.path().join("test").join("wiki");
    std::fs::create_dir_all(wiki_root.join("concepts/bundled")).unwrap();
    std::fs::write(
        wiki_root.join("concepts/bundled/index.md"),
        "---\ntitle: \"B\"\ntype: page\n---\n\nBody.\n",
    )
    .unwrap();
    std::fs::write(wiki_root.join("concepts/bundled/data.csv"), "a,b\n").unwrap();

    match ops::content_read(&engine, "concepts/bundled", None, false, true).unwrap() {
        ops::ContentReadResult::Assets(assets) => {
            assert_eq!(assets, vec!["wiki://concepts/bundled/data.csv".to_string()]);
        }
        _ => panic!("expected Assets"),
    }
}

#[test]
fn content_write_yaml_asset_creates_parent_and_matches() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let body = "status: active\nowner: team\n";
    // policy/_src does not exist yet — must be created
    let result = ops::content_write(&engine, "policy/_src/state-ssot.yaml", None, body).unwrap();
    assert!(result.asset);
    assert_eq!(result.bytes_written, body.len());

    assert!(result.path.ends_with("wiki/policy/_src/state-ssot.yaml"));
    assert_eq!(std::fs::read_to_string(&result.path).unwrap(), body);

    // Overwrite is allowed — same semantics as page writes
    let updated = "status: archived\n";
    let result = ops::content_write(&engine, "policy/_src/state-ssot.yaml", None, updated).unwrap();
    assert!(result.asset);
    assert_eq!(std::fs::read_to_string(&result.path).unwrap(), updated);
}

#[test]
fn content_write_asset_rejects_traversal() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    assert!(ops::content_write(&engine, "../escape.yaml", None, "x").is_err());
    assert!(ops::content_write(&engine, "policy/../../escape.yaml", None, "x").is_err());
    assert!(ops::content_write(&engine, "/etc/escape.yaml", None, "x").is_err());
    assert!(ops::content_write(&engine, "policy/..\\escape.yaml", None, "x").is_err());
}

#[test]
fn content_write_asset_rejects_disallowed_extensions() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    assert!(ops::content_write(&engine, "policy/page.html", None, "<html>").is_err());
    assert!(ops::content_write(&engine, "policy/run.sh", None, "#!/bin/sh").is_err());
    assert!(ops::content_write(&engine, "policy/img.png", None, "binary").is_err());
}

#[test]
fn content_write_page_unchanged_by_asset_support() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    // Overwrite an existing page by slug
    let body = "---\ntitle: \"MoE\"\ntype: concept\n---\n\nUpdated.\n";
    let result = ops::content_write(&engine, "concepts/moe", None, body).unwrap();
    assert!(!result.asset);
    assert!(result.path.ends_with("concepts/moe.md"));

    match ops::content_read(&engine, "concepts/moe", None, false, false).unwrap() {
        ops::ContentReadResult::Page(content) => assert!(content.contains("Updated.")),
        _ => panic!("expected Page"),
    }

    // Explicit .md paths are still rejected — pages use extensionless slugs
    assert!(ops::content_write(&engine, "concepts/moe.md", None, body).is_err());
}

#[test]
fn content_new_page() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let result = ops::content_new(
        &engine,
        "concepts/new-concept",
        None,
        false,
        false,
        None,
        None,
    )
    .unwrap();
    assert!(result.uri.starts_with("wiki://test/concepts/new-concept"));
    assert_eq!(result.slug, "concepts/new-concept");
    assert!(!result.bundle);
    assert!(result.path.exists());
    assert!(result.path.to_string_lossy().ends_with(".md"));
}

#[test]
fn content_new_section() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let result = ops::content_new(&engine, "topics", None, true, false, None, None).unwrap();
    assert!(result.uri.contains("topics"));
}

#[test]
fn content_new_bundle_result_has_path_and_wiki_root() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let result =
        ops::content_new(&engine, "concepts/bundled", None, false, true, None, None).unwrap();
    assert!(result.bundle);
    assert!(result.path.ends_with("index.md"));
    assert!(result.path.exists());
    assert!(result.wiki_root.is_dir());
}

#[test]
fn content_commit_all() {
    let dir = tempfile::tempdir().unwrap();
    let config_path = setup_wiki(dir.path(), "test");
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    // Write a new file so there's something to commit
    ops::content_write(
        &engine,
        "scratch",
        None,
        "---\ntitle: \"Scratch\"\ntype: page\n---\n\ntemp\n",
    )
    .unwrap();

    let hash = ops::content_commit(&engine, "test", &[], true, Some("test commit")).unwrap();
    assert!(!hash.is_empty());
}
