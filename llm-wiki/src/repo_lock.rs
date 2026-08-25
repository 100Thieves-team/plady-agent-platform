//! An advisory lock over a wiki repository's working tree.
//!
//! This repository is not written by one process. The MCP server commits pages,
//! a sync sidecar runs `git add -A` / `git pull --rebase` on a loop, and a
//! renderer rewrites a whole directory of generated pages at once. Each is
//! correct alone; together they interleave — the sync loop can commit a page
//! set an agent is halfway through writing, and a rebase can land on top of a
//! renderer's partial output.
//!
//! The lock is a **directory** created with `mkdir`, because that is the one
//! atomic primitive every writer here can use: [`RepoLock`] in Rust, `mkdir` in
//! the sync shell script, `os.mkdir` in the renderer. A lock file written with
//! `>` would not be atomic in shell, and `flock(1)` is not present in every
//! image these sidecars run on.
//!
//! It is advisory. A writer that ignores it is not blocked — which is exactly
//! why every writer must take it, and why [`LockInfo`] records who holds one:
//! when something does go wrong, the holder is named rather than guessed at.
//!
//! ```no_run
//! # use llm_wiki::repo_lock::RepoLock;
//! # use std::path::Path;
//! # fn main() -> anyhow::Result<()> {
//! let _lock = RepoLock::acquire(Path::new("/srv/wiki"), "mcp:ingest")?;
//! // write pages, validate, commit — released when `_lock` drops
//! # Ok(())
//! # }
//! ```

use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};

/// Directory name of the lock, created inside `.git/`.
///
/// It lives in `.git/` so it is never mistaken for wiki content, never indexed,
/// and never committed.
const LOCK_DIR: &str = "llm-wiki.lock";

/// File inside the lock directory naming its holder.
const OWNER_FILE: &str = "owner";

/// How long to keep trying before giving up.
const DEFAULT_TIMEOUT: Duration = Duration::from_secs(30);

/// After this long a lock is presumed abandoned — a crashed holder must not
/// wedge the wiki permanently.
const DEFAULT_STALE_AFTER: Duration = Duration::from_secs(300);

/// Delay between acquisition attempts.
const RETRY_INTERVAL: Duration = Duration::from_millis(100);

/// Who holds a lock, and since when.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LockInfo {
    /// Free-form holder label, e.g. `mcp:ingest` or `wiki-data-sync`.
    pub holder: String,
    /// Process id of the holder, when it recorded one.
    pub pid: Option<u32>,
    /// Unix seconds at which the lock was taken.
    pub acquired_at: u64,
}

impl LockInfo {
    fn serialize(&self) -> String {
        format!(
            "{}\n{}\n{}\n",
            self.holder,
            self.pid.map(|p| p.to_string()).unwrap_or_default(),
            self.acquired_at
        )
    }

    fn parse(text: &str) -> Option<Self> {
        let mut lines = text.lines();
        let holder = lines.next()?.to_string();
        let pid = lines.next().and_then(|s| s.trim().parse().ok());
        let acquired_at = lines
            .next()
            .and_then(|s| s.trim().parse().ok())
            .unwrap_or(0);
        Some(Self {
            holder,
            pid,
            acquired_at,
        })
    }

    /// Seconds this lock has been held, as of now.
    pub fn age_secs(&self) -> u64 {
        now_secs().saturating_sub(self.acquired_at)
    }
}

impl std::fmt::Display for LockInfo {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.holder)?;
        if let Some(pid) = self.pid {
            write!(f, " (pid {pid})")?;
        }
        write!(f, ", held {}s", self.age_secs())
    }
}

/// A held repository lock. Released on drop.
#[derive(Debug)]
pub struct RepoLock {
    path: PathBuf,
    info: LockInfo,
    released: bool,
}

impl RepoLock {
    /// Take the lock for `repo_root`, waiting up to the default timeout.
    pub fn acquire(repo_root: &Path, holder: &str) -> Result<Self> {
        Self::acquire_with(repo_root, holder, DEFAULT_TIMEOUT, DEFAULT_STALE_AFTER)
    }

    /// Take the lock with explicit waiting and staleness bounds.
    ///
    /// A lock older than `stale_after` is broken and taken over: a holder that
    /// died mid-write would otherwise wedge every later write, which is worse
    /// than the interleaving the lock exists to prevent.
    pub fn acquire_with(
        repo_root: &Path,
        holder: &str,
        timeout: Duration,
        stale_after: Duration,
    ) -> Result<Self> {
        let path = lock_path(repo_root);
        let deadline = SystemTime::now() + timeout;
        let mut broke_stale = false;

        loop {
            match std::fs::create_dir(&path) {
                Ok(()) => {
                    let info = LockInfo {
                        holder: holder.to_string(),
                        pid: Some(std::process::id()),
                        acquired_at: now_secs(),
                    };
                    // Best-effort: the lock is held by the directory's
                    // existence, so a failure to record the holder must not
                    // release it.
                    let _ = std::fs::write(path.join(OWNER_FILE), info.serialize());
                    return Ok(Self {
                        path,
                        info,
                        released: false,
                    });
                }
                Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                    if !broke_stale
                        && let Some(existing) = read_info(&path)
                        && existing.age_secs() > stale_after.as_secs()
                    {
                        tracing::warn!(
                            holder = %existing.holder,
                            age_secs = existing.age_secs(),
                            "breaking a stale repository lock",
                        );
                        let _ = std::fs::remove_dir_all(&path);
                        broke_stale = true;
                        continue;
                    }
                    if SystemTime::now() >= deadline {
                        let held = match read_info(&path) {
                            Some(info) => format!("held by {info}"),
                            None => "holder unknown".to_string(),
                        };
                        bail!(
                            "timed out after {}s waiting for the repository lock ({held}). \
                             Another writer — the sync sidecar, the renderer, or another agent — \
                             is mid-write; retry, or remove {} if you have confirmed nothing holds it.",
                            timeout.as_secs(),
                            path.display()
                        );
                    }
                    std::thread::sleep(RETRY_INTERVAL);
                }
                Err(e) => {
                    return Err(e).with_context(|| {
                        format!("failed to create lock directory {}", path.display())
                    });
                }
            }
        }
    }

    /// Take the lock for a mounted space, honouring its configured waiting and
    /// staleness bounds.
    ///
    /// Reading the config here rather than at each call site keeps every writer
    /// on the same timings; a wiki whose renderer legitimately takes minutes can
    /// raise them in one place.
    pub fn for_space(space: &crate::engine::SpaceContext, holder: &str) -> Result<Self> {
        let cfg = crate::config::load_wiki(&space.repo_root).unwrap_or_default();
        Self::acquire_with(
            &space.repo_root,
            holder,
            Duration::from_secs(cfg.lock_timeout_secs),
            Duration::from_secs(cfg.lock_stale_after_secs),
        )
    }

    /// Who this lock records as its holder.
    pub fn info(&self) -> &LockInfo {
        &self.info
    }

    /// Release early. Idempotent; `drop` will not release twice.
    pub fn release(&mut self) {
        if self.released {
            return;
        }
        self.released = true;
        if let Err(e) = std::fs::remove_dir_all(&self.path) {
            tracing::warn!(path = %self.path.display(), error = %e, "failed to release repository lock");
        }
    }
}

impl Drop for RepoLock {
    fn drop(&mut self) {
        self.release();
    }
}

/// Who currently holds the lock on `repo_root`, if anyone.
pub fn current_holder(repo_root: &Path) -> Option<LockInfo> {
    read_info(&lock_path(repo_root))
}

/// Path of the lock directory for a repository.
///
/// Falls back to the repo root when there is no `.git` — a bare directory used
/// in tests still gets a usable lock.
pub fn lock_path(repo_root: &Path) -> PathBuf {
    let git_dir = repo_root.join(".git");
    if git_dir.is_dir() {
        git_dir.join(LOCK_DIR)
    } else {
        repo_root.join(LOCK_DIR)
    }
}

fn read_info(lock_path: &Path) -> Option<LockInfo> {
    let text = std::fs::read_to_string(lock_path.join(OWNER_FILE)).ok()?;
    LockInfo::parse(&text)
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo(dir: &Path) -> PathBuf {
        std::fs::create_dir_all(dir.join(".git")).unwrap();
        dir.to_path_buf()
    }

    #[test]
    fn lock_lives_under_git_so_it_is_never_content() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        assert_eq!(lock_path(&root), root.join(".git").join(LOCK_DIR));
    }

    #[test]
    fn a_second_acquire_times_out_while_the_first_is_held() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        let _held = RepoLock::acquire(&root, "first").unwrap();

        let err = RepoLock::acquire_with(
            &root,
            "second",
            Duration::from_millis(250),
            DEFAULT_STALE_AFTER,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("timed out"), "unexpected error: {err}");
        assert!(err.contains("first"), "error should name the holder: {err}");
    }

    #[test]
    fn releasing_lets_the_next_writer_in() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        {
            let _held = RepoLock::acquire(&root, "first").unwrap();
        }
        let second = RepoLock::acquire(&root, "second");
        assert!(second.is_ok(), "lock was not released on drop");
    }

    #[test]
    fn a_stale_lock_is_broken_rather_than_wedging_the_wiki() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        let path = lock_path(&root);
        std::fs::create_dir_all(&path).unwrap();
        let ancient = LockInfo {
            holder: "crashed-writer".into(),
            pid: Some(1),
            acquired_at: now_secs() - 10_000,
        };
        std::fs::write(path.join(OWNER_FILE), ancient.serialize()).unwrap();

        let lock = RepoLock::acquire_with(
            &root,
            "recovering",
            Duration::from_millis(500),
            Duration::from_secs(60),
        )
        .expect("a lock older than stale_after must be broken");
        assert_eq!(lock.info().holder, "recovering");
    }

    #[test]
    fn a_fresh_lock_is_not_mistaken_for_stale() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        let _held = RepoLock::acquire(&root, "busy").unwrap();

        assert!(
            RepoLock::acquire_with(
                &root,
                "impatient",
                Duration::from_millis(200),
                Duration::from_secs(60),
            )
            .is_err(),
            "a lock held for milliseconds must not be broken"
        );
    }

    #[test]
    fn holder_is_readable_while_held() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        let _held = RepoLock::acquire(&root, "mcp:ingest").unwrap();

        let info = current_holder(&root).expect("holder should be recorded");
        assert_eq!(info.holder, "mcp:ingest");
        assert_eq!(info.pid, Some(std::process::id()));
        assert!(current_holder(&root).unwrap().age_secs() < 60);
    }

    #[test]
    fn no_holder_when_unlocked() {
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        assert!(current_holder(&root).is_none());
    }

    #[test]
    fn owner_file_round_trips() {
        let info = LockInfo {
            holder: "wiki-data-sync".into(),
            pid: Some(42),
            acquired_at: 1_700_000_000,
        };
        let parsed = LockInfo::parse(&info.serialize()).unwrap();
        assert_eq!(parsed, info);
    }

    #[test]
    fn a_lock_dir_without_an_owner_file_is_still_respected() {
        // A shell writer that created the directory but had not yet written its
        // owner file still holds the lock.
        let dir = tempfile::tempdir().unwrap();
        let root = repo(dir.path());
        std::fs::create_dir_all(lock_path(&root)).unwrap();

        let err = RepoLock::acquire_with(
            &root,
            "rust",
            Duration::from_millis(200),
            DEFAULT_STALE_AFTER,
        )
        .unwrap_err()
        .to_string();
        assert!(err.contains("holder unknown"), "unexpected error: {err}");
    }
}

#[cfg(test)]
mod cross_language_tests {
    use super::*;

    /// The exact bytes the sidecar shell helpers write:
    ///   printf 'wiki-data-sync\n%s\n%s\n' "$$" "$(date -u +%s)"
    /// A format drift here would be silent — Rust would read the lock as
    /// holder-unknown and never break it as stale.
    #[test]
    fn rust_reads_the_owner_file_written_by_the_shell_sidecars() {
        let dir = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(dir.path().join(".git")).unwrap();
        let path = lock_path(dir.path());
        std::fs::create_dir_all(&path).unwrap();
        std::fs::write(path.join(OWNER_FILE), "wiki-data-sync\n1234\n1700000000\n").unwrap();

        let info = current_holder(dir.path()).expect("shell-written owner file must parse");
        assert_eq!(info.holder, "wiki-data-sync");
        assert_eq!(info.pid, Some(1234));
        assert_eq!(info.acquired_at, 1_700_000_000);
    }

    /// And the reverse: what Rust writes must be readable by `sed -n 1p/3p`.
    #[test]
    fn shell_can_read_the_owner_file_written_by_rust() {
        let info = LockInfo {
            holder: "mcp:ingest".into(),
            pid: Some(7),
            acquired_at: 1_700_000_000,
        };
        let text = info.serialize();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines[0], "mcp:ingest", "sed -n 1p must yield the holder");
        assert_eq!(lines[2], "1700000000", "sed -n 3p must yield the timestamp");
    }
}
