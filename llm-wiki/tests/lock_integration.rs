//! Write operations must go through the shared repository lock.
//!
//! The point is not that the lock exists but that the ops actually take it: a
//! lock every writer is supposed to hold, that one of them silently skips, is
//! worse than no lock at all, because it looks like protection.

use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;
use llm_wiki::repo_lock::{RepoLock, current_holder};

const PAGE: &str = "---\ntitle: \"P\"\ntype: doc\nstatus: active\n---\n\nBody.\n";

fn setup(dir: &Path) -> (PathBuf, PathBuf) {
    let config_path = dir.join("state").join("config.toml");
    let wiki_path = dir.join("test");
    llm_wiki::spaces::create(&wiki_path, "test", None, false, true, &config_path, None).unwrap();

    // Short waits so a blocked-write test does not sit for the production
    // default; the behaviour under test is the block, not its duration.
    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap_or_default();
    cfg.push_str("\nlock_timeout_secs = 1\n");
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    fs::create_dir_all(wiki_root.join("topics")).unwrap();
    fs::write(wiki_root.join("topics/t-a.md"), PAGE).unwrap();
    llm_wiki::git::commit(&wiki_path, "seed").unwrap();
    (config_path, wiki_path.canonicalize().unwrap())
}

/// Hold the lock the way a sidecar would — from outside this process's engine.
fn hold_as_sidecar(repo: &Path) -> RepoLock {
    RepoLock::acquire(repo, "wiki-data-sync").expect("sidecar should get the lock")
}

#[test]
fn content_write_waits_for_a_sidecar_and_reports_the_holder() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let _held = hold_as_sidecar(&wiki_path);

    let err = ops::content_write(&engine, "topics/t-b", Some("test"), PAGE)
        .unwrap_err()
        .to_string();
    assert!(err.contains("repository lock"), "unexpected error: {err}");
    assert!(
        err.contains("wiki-data-sync"),
        "the error must name the holder so the cause is not guesswork: {err}"
    );
    assert!(
        !wiki_path.join("wiki/topics/t-b.md").exists(),
        "the page was written despite the lock being held"
    );
}

#[test]
fn content_write_succeeds_once_the_lock_is_free() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    {
        let _held = hold_as_sidecar(&wiki_path);
    }
    ops::content_write(&engine, "topics/t-b", Some("test"), PAGE).unwrap();
    assert!(wiki_path.join("wiki/topics/t-b.md").is_file());
}

#[test]
fn a_write_releases_the_lock_it_took() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    ops::content_write(&engine, "topics/t-b", Some("test"), PAGE).unwrap();
    assert!(
        current_holder(&wiki_path).is_none(),
        "the lock outlived the operation that took it"
    );
}

#[test]
fn ingest_waits_for_the_lock() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let _held = hold_as_sidecar(&wiki_path);

    let err = ops::ingest(&engine, &manager, "topics", false, "test")
        .unwrap_err()
        .to_string();
    assert!(err.contains("repository lock"), "unexpected error: {err}");
}

#[test]
fn a_dry_run_ingest_does_not_take_the_lock() {
    // Validation only reads. Blocking it behind the sync loop would make the
    // cheap safety check the slow one, and agents would stop using it.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let _held = hold_as_sidecar(&wiki_path);

    let report = ops::ingest(&engine, &manager, "topics", true, "test")
        .expect("dry run must not be blocked by a writer");
    assert_eq!(report.pages_validated, 1);
}

#[test]
fn a_crashed_holder_does_not_wedge_the_wiki_forever() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());

    // A lock directory left behind by a process that died mid-write, dated far
    // enough back that no clock boundary decides the outcome.
    let lock = wiki_path.join(".git/llm-wiki.lock");
    fs::create_dir_all(&lock).unwrap();
    let long_ago = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_secs()
        - 10_000;
    fs::write(lock.join("owner"), format!("crashed\n1\n{long_ago}\n")).unwrap();

    let manager = WikiEngine::build(&config_path).unwrap();
    let engine = manager.state.read().unwrap();

    let recovered = RepoLock::acquire_with(
        &wiki_path,
        "recovering",
        Duration::from_millis(500),
        Duration::from_secs(60),
    );
    assert!(recovered.is_ok(), "an abandoned lock was never broken");
    drop(recovered);

    ops::content_write(&engine, "topics/t-c", Some("test"), PAGE).unwrap();
}
