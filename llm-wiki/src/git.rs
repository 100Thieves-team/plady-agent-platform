use std::collections::HashMap;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use git2::{Delta, Repository, Signature};
use serde::{Deserialize, Serialize};

use crate::content_roots::ContentRoots;

/// Initialise a new git repository at `path`.
pub fn init_repo(path: &Path) -> Result<()> {
    Repository::init(path)
        .with_context(|| format!("failed to init git repo at {}", path.display()))?;
    Ok(())
}

fn make_signature(repo: &Repository) -> Result<Signature<'_>> {
    repo.signature()
        .or_else(|_| Signature::now("llm-wiki", "llm-wiki@localhost"))
        .context("failed to create git signature")
}

/// Stage all files and commit. Returns empty string if nothing to commit.
pub fn commit(repo_root: &Path, message: &str) -> Result<String> {
    let repo = Repository::open(repo_root)
        .with_context(|| format!("failed to open repo at {}", repo_root.display()))?;

    let sig = make_signature(&repo)?;
    let mut index = repo.index()?;
    index.add_all(["*"].iter(), git2::IndexAddOption::DEFAULT, None)?;
    index.write()?;
    let tree_oid = index.write_tree()?;
    let tree = repo.find_tree(tree_oid)?;

    let parent = repo.head().ok().and_then(|h| h.peel_to_commit().ok());

    // Skip if tree matches parent (nothing changed)
    if let Some(ref p) = parent
        && p.tree_id() == tree_oid
    {
        return Ok(String::new());
    }

    let parents: Vec<&git2::Commit> = parent.iter().collect();
    let oid = repo.commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)?;
    Ok(oid.to_string())
}

/// Commit exactly `paths` and nothing else. Returns empty string if the result
/// would be identical to HEAD.
///
/// The commit tree is built from **HEAD plus these paths**, not from whatever
/// happens to be staged. This repository's working tree is shared with sidecar
/// processes that run `git add -A`, so reusing the on-disk index would sweep
/// their half-finished work into a commit that claims to be path-limited. For
/// the same reason the on-disk index is never written back — only the tree
/// objects are.
///
/// A path that no longer exists is staged as a deletion, so removing a page is
/// expressible through the same call.
pub fn commit_paths(repo_root: &Path, paths: &[&Path], message: &str) -> Result<String> {
    let repo = Repository::open(repo_root)
        .with_context(|| format!("failed to open repo at {}", repo_root.display()))?;

    let sig = make_signature(&repo)?;
    let parent = repo.head().ok().and_then(|h| h.peel_to_commit().ok());

    // Reset the in-memory index to HEAD so nothing another writer staged can
    // ride along. `write_tree` persists tree objects only; `write` — which would
    // overwrite the shared .git/index — is deliberately not called.
    let mut index = repo.index()?;
    match parent.as_ref() {
        Some(commit) => index.read_tree(&commit.tree()?)?,
        None => index.clear()?,
    }

    for path in paths {
        let rel = path.strip_prefix(repo_root).unwrap_or(path);
        if path.exists() {
            index.add_path(rel)?;
        } else {
            // Missing on disk means the caller deleted it; record the removal
            // rather than failing the whole commit.
            let _ = index.remove_path(rel);
        }
    }

    let tree_oid = index.write_tree()?;
    let tree = repo.find_tree(tree_oid)?;

    if let Some(ref p) = parent
        && p.tree_id() == tree_oid
    {
        return Ok(String::new());
    }

    let parents: Vec<&git2::Commit> = parent.iter().collect();
    let oid = repo.commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)?;
    Ok(oid.to_string())
}

/// Get current HEAD commit hash. Returns None if repo has no commits.
pub fn current_head(repo_root: &Path) -> Option<String> {
    let repo = Repository::open(repo_root).ok()?;
    let head = repo.head().ok()?.peel_to_commit().ok()?;
    Some(head.id().to_string())
}

// ── Change detection ──────────────────────────────────────────────────────────

/// A file that changed between git tree states.
#[derive(Debug, Clone)]
pub struct ChangedFile {
    /// Repository-relative path of the changed file.
    pub path: PathBuf,
    /// Git delta status (Added, Modified, Deleted, etc.).
    pub status: Delta,
}

/// Detect changed `.md` files under any of a space's content roots in the
/// working tree vs HEAD.
pub fn changed_wiki_files(repo_root: &Path, roots: &ContentRoots) -> Result<Vec<ChangedFile>> {
    let repo = Repository::open(repo_root)
        .with_context(|| format!("failed to open repo at {}", repo_root.display()))?;
    let head_tree = repo
        .head()
        .and_then(|h| h.peel_to_tree())
        .context("no HEAD commit")?;
    let mut opts = git2::DiffOptions::new();
    opts.include_untracked(true).recurse_untracked_dirs(true);
    let diff = repo.diff_tree_to_workdir_with_index(Some(&head_tree), Some(&mut opts))?;
    Ok(collect_md_changes(&diff, &roots.repo_relative_prefixes()))
}

/// Detect changed `.md` files under any of a space's content roots between a
/// past commit and HEAD.
pub fn changed_since_commit(
    repo_root: &Path,
    roots: &ContentRoots,
    from_commit: &str,
) -> Result<Vec<ChangedFile>> {
    let repo = Repository::open(repo_root)
        .with_context(|| format!("failed to open repo at {}", repo_root.display()))?;
    let from_oid = git2::Oid::from_str(from_commit)
        .with_context(|| format!("invalid commit hash: {from_commit}"))?;
    let from_tree = repo.find_commit(from_oid)?.tree()?;
    let head_tree = repo
        .head()
        .and_then(|h| h.peel_to_tree())
        .context("no HEAD commit")?;
    let diff = repo.diff_tree_to_tree(Some(&from_tree), Some(&head_tree), None)?;
    Ok(collect_md_changes(&diff, &roots.repo_relative_prefixes()))
}

fn collect_md_changes(diff: &git2::Diff, prefixes: &[PathBuf]) -> Vec<ChangedFile> {
    let mut changes = Vec::new();
    diff.foreach(
        &mut |delta, _| {
            let path = delta.new_file().path().or_else(|| delta.old_file().path());
            if let Some(p) = path
                && prefixes.iter().any(|prefix| p.starts_with(prefix))
                && p.extension().and_then(|e| e.to_str()) == Some("md")
            {
                changes.push(ChangedFile {
                    path: p.to_path_buf(),
                    status: delta.status(),
                });
            }
            true
        },
        None,
        None,
        None,
    )
    .ok();
    changes
}

/// Collect all changed `.md` files by merging two git diffs:
/// - Working tree vs HEAD (uncommitted changes)
/// - `last_indexed_commit` vs HEAD (commits since last index update)
///
/// Working tree changes overwrite commit-based changes on duplicates.
pub fn collect_changed_files(
    repo_root: &Path,
    roots: &ContentRoots,
    last_indexed_commit: Option<&str>,
) -> Result<HashMap<PathBuf, Delta>> {
    let mut changes = HashMap::new();

    // B: last indexed commit vs HEAD (insert first so A wins on duplicates)
    if let Some(from_hash) = last_indexed_commit
        && let Ok(files) = changed_since_commit(repo_root, roots, from_hash)
    {
        for f in files {
            changes.insert(f.path, f.status);
        }
    }

    // A: working tree vs HEAD (overwrites B on duplicates)
    if let Ok(files) = changed_wiki_files(repo_root, roots) {
        for f in files {
            changes.insert(f.path, f.status);
        }
    }

    Ok(changes)
}

// ── Page history ──────────────────────────────────────────────────────────────

/// A single entry from `git log` for a wiki page.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    /// Full commit SHA-1 hash.
    pub hash: String,
    /// ISO-8601 author date string.
    pub date: String,
    /// Commit subject line.
    pub message: String,
    /// Author name.
    pub author: String,
}

/// One commit plus the repo-relative paths it touched.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RecentEntry {
    /// Full commit SHA-1.
    pub hash: String,
    /// ISO-8601 author date.
    pub date: String,
    /// Commit subject.
    pub message: String,
    /// Author name.
    pub author: String,
    /// Repo-relative paths under the requested prefixes.
    pub paths: Vec<String>,
}

/// Recent commits touching any of `prefixes`, newest first.
///
/// `since` is passed to `git log --since` verbatim, so callers can ask in the
/// terms people actually use ("2 weeks ago") rather than counting commits.
/// Commits that touched only files outside the prefixes are dropped, since a
/// wiki's history should not be diluted by tooling changes in the same repo.
pub fn recent_changes(
    repo_root: &Path,
    limit: usize,
    since: Option<&str>,
    prefixes: &[PathBuf],
) -> Result<Vec<RecentEntry>> {
    let mut cmd = std::process::Command::new("git");
    cmd.current_dir(repo_root).args([
        "-c",
        "core.quotepath=false",
        // Without this git quotes and octal-escapes any path outside ASCII —
        // `"raw/meetings/\353\215\260…"` — and every page in a non-English
        // wiki comes back unparseable.
        "log",
        "--name-only",
        "--no-renames",
        "--format=%x01%H%x00%aI%x00%s%x00%an",
    ]);
    if limit > 0 {
        cmd.args(["-n", &limit.to_string()]);
    }
    if let Some(since) = since.map(str::trim).filter(|s| !s.is_empty()) {
        cmd.arg(format!("--since={since}"));
    }
    if !prefixes.is_empty() {
        cmd.arg("--");
        for prefix in prefixes {
            cmd.arg(prefix);
        }
    }

    let output = cmd
        .output()
        .context("failed to run git log — is git installed?")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        if stderr.is_empty() {
            return Ok(Vec::new());
        }
        anyhow::bail!("git log failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut entries = Vec::new();
    // \x01 opens each record so the trailing path block is unambiguous.
    for record in stdout.split('\u{1}').skip(1) {
        let mut lines = record.lines();
        let Some(header) = lines.next() else { continue };
        let parts: Vec<&str> = header.split('\0').collect();
        if parts.len() < 4 {
            continue;
        }
        let paths: Vec<String> = lines
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .map(str::to_string)
            .collect();
        entries.push(RecentEntry {
            hash: parts[0].to_string(),
            date: parts[1].to_string(),
            message: parts[2].to_string(),
            author: parts[3].to_string(),
            paths,
        });
    }
    Ok(entries)
}

/// Return git commit history for a file path relative to repo root.
/// Uses `git log` (shell) for simplicity and built-in `--follow` support.
pub fn page_history(
    repo_root: &Path,
    rel_path: &Path,
    limit: usize,
    follow: bool,
) -> Result<Vec<HistoryEntry>> {
    let mut cmd = std::process::Command::new("git");
    cmd.current_dir(repo_root)
        .args(["log", "--format=%H%x00%aI%x00%s%x00%an"]);
    if follow {
        cmd.arg("--follow");
    }
    if limit > 0 {
        cmd.args(["-n", &limit.to_string()]);
    }
    cmd.arg("--").arg(rel_path);

    let output = cmd
        .output()
        .context("failed to run git log — is git installed?")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        // Empty history is not an error (new file, no commits yet)
        if stderr.is_empty() {
            return Ok(Vec::new());
        }
        anyhow::bail!("git log failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut entries = Vec::new();
    for line in stdout.lines() {
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.splitn(4, '\0').collect();
        if parts.len() == 4 {
            entries.push(HistoryEntry {
                hash: parts[0].to_string(),
                date: parts[1].to_string(),
                message: parts[2].to_string(),
                author: parts[3].to_string(),
            });
        }
    }
    Ok(entries)
}
