use std::fs;

use llm_wiki::content_roots::ContentRoots;
use llm_wiki::git;

/// Init a repo with a `wiki/` directory and one committed file.
fn setup_repo(dir: &std::path::Path) -> std::path::PathBuf {
    let wiki = dir.join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    git::init_repo(dir).unwrap();
    fs::write(dir.join("README.md"), "# test\n").unwrap();
    git::commit(dir, "init").unwrap();
    wiki
}

#[test]
fn init_repo_creates_git_repository() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    assert!(dir.path().join(".git").exists());
}

#[test]
fn commit_creates_commit_and_returns_hash() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    fs::write(dir.path().join("test.txt"), "hello").unwrap();

    let hash = git::commit(dir.path(), "test commit").unwrap();
    assert!(!hash.is_empty());
    assert_eq!(hash.len(), 40);
}

#[test]
fn commit_empty_returns_empty_string() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    fs::write(dir.path().join("test.txt"), "hello").unwrap();
    git::commit(dir.path(), "first").unwrap();

    // Nothing changed — should be a no-op
    let hash = git::commit(dir.path(), "empty").unwrap();
    assert!(hash.is_empty());
}

#[test]
fn current_head_returns_commit_hash() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    fs::write(dir.path().join("test.txt"), "hello").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    let head = git::current_head(dir.path());
    assert!(head.is_some());
    assert_eq!(head.unwrap().len(), 40);
}

#[test]
fn current_head_none_on_empty_repo() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    assert!(git::current_head(dir.path()).is_none());
}

#[test]
fn current_head_matches_commit_hash() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    fs::write(dir.path().join("test.txt"), "hello").unwrap();

    let commit_hash = git::commit(dir.path(), "initial").unwrap();
    let head_hash = git::current_head(dir.path()).unwrap();
    assert_eq!(commit_hash, head_hash);
}

#[test]
fn commit_paths_commits_only_specified_files() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    fs::write(dir.path().join("init.txt"), "init").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::write(dir.path().join("a.txt"), "aaa").unwrap();
    fs::write(dir.path().join("b.txt"), "bbb").unwrap();

    let hash =
        git::commit_paths(dir.path(), &[&dir.path().join("a.txt")], "commit a only").unwrap();
    assert_eq!(hash.len(), 40);
}

#[test]
fn commit_paths_empty_returns_empty_string() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let a = dir.path().join("a.txt");
    fs::write(&a, "aaa").unwrap();
    git::commit_paths(dir.path(), &[a.as_path()], "first").unwrap();

    // Same file, same content — no-op
    let hash = git::commit_paths(dir.path(), &[a.as_path()], "empty").unwrap();
    assert!(hash.is_empty());
}

// ── changed_wiki_files ────────────────────────────────────────────────────────

#[test]
fn changed_wiki_files_detects_new_file() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("init.md"), "---\ntitle: Init\n---\n").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::write(wiki.join("new-page.md"), "---\ntitle: New\n---\n").unwrap();

    let changes = git::changed_wiki_files(dir.path(), &ContentRoots::single(&wiki)).unwrap();
    assert!(changes.iter().any(|c| c.path.ends_with("new-page.md")));
}

#[test]
fn changed_wiki_files_detects_modified_file() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("page.md"), "---\ntitle: Old\n---\n").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::write(wiki.join("page.md"), "---\ntitle: New\n---\n").unwrap();

    let changes = git::changed_wiki_files(dir.path(), &ContentRoots::single(&wiki)).unwrap();
    assert!(
        changes
            .iter()
            .any(|c| c.path.ends_with("page.md") && c.status == git2::Delta::Modified)
    );
}

#[test]
fn changed_wiki_files_detects_deleted_file() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("page.md"), "---\ntitle: Gone\n---\n").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::remove_file(wiki.join("page.md")).unwrap();

    let changes = git::changed_wiki_files(dir.path(), &ContentRoots::single(&wiki)).unwrap();
    assert!(
        changes
            .iter()
            .any(|c| c.path.ends_with("page.md") && c.status == git2::Delta::Deleted)
    );
}

#[test]
fn changed_wiki_files_ignores_non_md() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("init.md"), "---\ntitle: Init\n---\n").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::write(wiki.join("image.png"), "fake-png").unwrap();

    let changes = git::changed_wiki_files(dir.path(), &ContentRoots::single(&wiki)).unwrap();
    assert!(!changes.iter().any(|c| c.path.ends_with("image.png")));
}

#[test]
fn changed_wiki_files_ignores_files_outside_wiki() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("init.md"), "---\ntitle: Init\n---\n").unwrap();
    git::commit(dir.path(), "initial").unwrap();

    fs::write(dir.path().join("README.md"), "# Hello").unwrap();

    let changes = git::changed_wiki_files(dir.path(), &ContentRoots::single(&wiki)).unwrap();
    assert!(!changes.iter().any(|c| c.path.ends_with("README.md")));
}

// ── changed_since_commit ──────────────────────────────────────────────────────

#[test]
fn changed_since_commit_detects_gap() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();

    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("page-a.md"), "---\ntitle: A\n---\n").unwrap();
    let first = git::commit(dir.path(), "first").unwrap();

    fs::write(wiki.join("page-b.md"), "---\ntitle: B\n---\n").unwrap();
    git::commit(dir.path(), "second").unwrap();

    let changes =
        git::changed_since_commit(dir.path(), &ContentRoots::single(&wiki), &first).unwrap();
    assert!(changes.iter().any(|c| c.path.ends_with("page-b.md")));
    assert!(!changes.iter().any(|c| c.path.ends_with("page-a.md")));
}

// ── collect_changed_files ─────────────────────────────────────────────────────

#[test]
fn collect_changed_files_detects_new_file() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(dir.path().join("README.md"), "# test\n").unwrap();
    git::commit(dir.path(), "init").unwrap();

    fs::write(wiki.join("new.md"), "---\ntitle: New\n---\n").unwrap();

    let changes =
        git::collect_changed_files(dir.path(), &ContentRoots::single(&wiki), None).unwrap();
    assert!(!changes.is_empty());
}

#[test]
fn collect_changed_files_empty_when_clean() {
    let dir = tempfile::tempdir().unwrap();
    git::init_repo(dir.path()).unwrap();
    let wiki = dir.path().join("wiki");
    fs::create_dir_all(&wiki).unwrap();
    fs::write(wiki.join("foo.md"), "---\ntitle: Foo\n---\n").unwrap();
    git::commit(dir.path(), "add foo").unwrap();
    let head = git::current_head(dir.path()).unwrap();

    let changes =
        git::collect_changed_files(dir.path(), &ContentRoots::single(&wiki), Some(&head)).unwrap();
    assert!(changes.is_empty());
}

// ── commit_paths isolation ────────────────────────────────────────────────────

#[test]
fn commit_paths_excludes_work_staged_by_another_writer() {
    // The working tree is shared with sidecars that run `git add -A`. A
    // path-limited commit must not sweep their staged work along with it.
    let dir = tempfile::tempdir().unwrap();
    let wiki = setup_repo(dir.path());
    fs::write(wiki.join("mine.md"), "---\ntitle: Mine\n---\n").unwrap();
    fs::write(wiki.join("theirs.md"), "---\ntitle: Theirs\n---\n").unwrap();

    // Another writer stages its file in the shared index.
    let repo = git2::Repository::open(dir.path()).unwrap();
    let mut idx = repo.index().unwrap();
    idx.add_path(std::path::Path::new("wiki/theirs.md"))
        .unwrap();
    idx.write().unwrap();

    let mine = wiki.join("mine.md");
    let hash = git::commit_paths(dir.path(), &[mine.as_path()], "commit mine only").unwrap();
    assert!(!hash.is_empty());

    let repo = git2::Repository::open(dir.path()).unwrap();
    let tree = repo.head().unwrap().peel_to_tree().unwrap();
    assert!(
        tree.get_path(std::path::Path::new("wiki/mine.md")).is_ok(),
        "the named path is missing from the commit"
    );
    assert!(
        tree.get_path(std::path::Path::new("wiki/theirs.md"))
            .is_err(),
        "another writer's staged file leaked into a path-limited commit"
    );
}

#[test]
fn commit_paths_records_a_deletion() {
    let dir = tempfile::tempdir().unwrap();
    let wiki = setup_repo(dir.path());
    fs::write(wiki.join("gone.md"), "---\ntitle: Gone\n---\n").unwrap();
    let gone = wiki.join("gone.md");
    git::commit_paths(dir.path(), &[gone.as_path()], "add").unwrap();

    fs::remove_file(&gone).unwrap();
    let hash = git::commit_paths(dir.path(), &[gone.as_path()], "remove").unwrap();
    assert!(!hash.is_empty(), "deletion produced no commit");

    let repo = git2::Repository::open(dir.path()).unwrap();
    let tree = repo.head().unwrap().peel_to_tree().unwrap();
    assert!(tree.get_path(std::path::Path::new("wiki/gone.md")).is_err());
}

#[test]
fn commit_paths_leaves_the_shared_index_file_alone() {
    let dir = tempfile::tempdir().unwrap();
    let wiki = setup_repo(dir.path());
    fs::write(wiki.join("a.md"), "---\ntitle: A\n---\n").unwrap();
    fs::write(wiki.join("b.md"), "---\ntitle: B\n---\n").unwrap();

    let repo = git2::Repository::open(dir.path()).unwrap();
    let mut idx = repo.index().unwrap();
    idx.add_path(std::path::Path::new("wiki/b.md")).unwrap();
    idx.write().unwrap();
    drop(idx);
    drop(repo);
    let before = fs::read(dir.path().join(".git/index")).unwrap();

    let a = wiki.join("a.md");
    git::commit_paths(dir.path(), &[a.as_path()], "a only").unwrap();

    let after = fs::read(dir.path().join(".git/index")).unwrap();
    assert_eq!(before, after, "the shared .git/index was overwritten");
}
