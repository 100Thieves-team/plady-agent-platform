use std::collections::HashSet;
use std::path::Path;
use std::path::PathBuf;

use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use walkdir::WalkDir;

use crate::config::{RedactConfig, ValidationConfig};
use crate::content_roots::ContentRoots;
use crate::frontmatter;
use crate::git;
use crate::ops::redact::{RedactionMatch, RedactionReport, redact_body};
use crate::type_registry::SpaceTypeRegistry;

/// Normalize line endings: CRLF → LF, lone CR → LF.
pub fn normalize_line_endings(input: &str) -> String {
    input.replace("\r\n", "\n").replace('\r', "\n")
}

/// Options controlling an ingest run.
#[derive(Debug, Clone, Default)]
pub struct IngestOptions {
    /// Validate only — do not write to disk or commit.
    pub dry_run: bool,
    /// Automatically commit validated files to git.
    pub auto_commit: bool,
    /// When `Some`, only files in this set are validated; others increment `unchanged_count`.
    /// When `None`, all files are validated.
    pub changed_paths: Option<HashSet<PathBuf>>,
    /// When `Some`, run redaction pass on each file body before validation.
    pub redact: Option<RedactConfig>,
}

/// Result of an ingest operation.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct IngestReport {
    /// Number of Markdown pages that passed validation.
    pub pages_validated: usize,
    /// Number of non-Markdown asset files discovered.
    pub assets_found: usize,
    /// Validation warning messages (non-fatal).
    pub warnings: Vec<String>,
    /// Git commit hash produced after ingest, or empty string if no commit was made.
    pub commit: String,
    /// Number of files skipped because they were not in `changed_paths`.
    #[serde(default)]
    pub unchanged_count: usize,
    /// Redaction reports for any files that had secrets removed.
    #[serde(default)]
    pub redacted: Vec<RedactionReport>,
}

/// Walk `path` (file or directory), validate, optionally redact, commit, and return a report.
///
/// `path` may be absolute, or relative to whichever content root owns it: a
/// leading external-root segment (`raw/meetings`) resolves against the repo
/// root, anything else against the wiki root. That keeps `raw/` — the layer the
/// wiki compiles from — reachable by the same call that ingests compiled pages.
pub fn ingest(
    path: &Path,
    options: &IngestOptions,
    roots: &ContentRoots,
    registry: &SpaceTypeRegistry,
    validation: &ValidationConfig,
) -> Result<IngestReport> {
    let repo_root = roots.repo_root();

    let full_path = if path.is_absolute() {
        path.to_path_buf()
    } else {
        roots.base_for(&path.to_string_lossy()).join(path)
    };

    if !full_path.exists() {
        bail!("path does not exist: {}", full_path.display());
    }

    // Reject anything outside the space's content roots
    let canonical = full_path.canonicalize()?;
    let in_a_root = roots.walk_roots().iter().any(|(dir, _)| {
        dir.canonicalize()
            .map(|c| canonical.starts_with(&c))
            .unwrap_or(false)
    });
    if !in_a_root {
        let names: Vec<String> = std::iter::once("wiki".to_string())
            .chain(roots.external_names().iter().cloned())
            .collect();
        bail!(
            "path is outside this wiki's content roots ({}): {}",
            names.join(", "),
            full_path.display()
        );
    }

    let mut report = IngestReport::default();

    if full_path.is_file() {
        let skip = should_skip(&full_path, repo_root, &options.changed_paths);
        if skip {
            report.unchanged_count += 1;
        } else {
            validate_file(
                &full_path,
                roots,
                registry,
                validation,
                options.redact.as_ref(),
                &mut report,
            )?;
        }
    } else {
        for entry in WalkDir::new(&full_path).into_iter().filter_map(|e| e.ok()) {
            let p = entry.path();
            if p.is_file() {
                if p.extension().and_then(|e| e.to_str()) == Some("md") {
                    if should_skip(p, repo_root, &options.changed_paths) {
                        report.unchanged_count += 1;
                    } else {
                        validate_file(
                            p,
                            roots,
                            registry,
                            validation,
                            options.redact.as_ref(),
                            &mut report,
                        )?;
                    }
                } else {
                    report.assets_found += 1;
                }
            }
        }
    }

    if !options.dry_run && options.auto_commit {
        let msg = format!(
            "ingest: {} — +{} pages, +{} assets",
            path.display(),
            report.pages_validated,
            report.assets_found
        );
        let hash = git::commit(repo_root, &msg)?;
        report.commit = hash;
    }

    Ok(report)
}

fn should_skip(abs_path: &Path, repo_root: &Path, changed: &Option<HashSet<PathBuf>>) -> bool {
    let Some(set) = changed else { return false };
    if set.is_empty() {
        return false;
    }
    // `changed` holds repo-relative paths so files in external roots are
    // representable; compare against the repo root, not the wiki root.
    let rel = abs_path.strip_prefix(repo_root).unwrap_or(abs_path);
    !set.contains(rel)
}

fn slug_from_path(abs_path: &Path, roots: &ContentRoots) -> String {
    roots
        .slug_from_path(abs_path)
        .map(|s| s.as_str().to_string())
        .unwrap_or_else(|_| abs_path.to_string_lossy().into_owned())
}

fn validate_file(
    path: &Path,
    roots: &ContentRoots,
    registry: &SpaceTypeRegistry,
    validation: &ValidationConfig,
    redact_cfg: Option<&RedactConfig>,
    report: &mut IngestReport,
) -> Result<()> {
    let raw = std::fs::read_to_string(path)?;
    let mut content = normalize_line_endings(&raw);

    // Redaction pass — body only, before validation
    if let Some(cfg) = redact_cfg {
        let parsed = frontmatter::parse(&content);
        let separator = "---";
        // Find where body starts (after the closing frontmatter delimiter)
        let body_start = if content.starts_with(separator) {
            // skip first "---", find closing "---"
            let after_open = &content[3..];
            after_open
                .find("\n---")
                .map(|pos| 3 + pos + 4 + 1)
                .unwrap_or(0)
        } else {
            0
        };

        if body_start > 0 && body_start <= content.len() {
            let front = &content[..body_start];
            let body = &content[body_start..];
            let (redacted_body, matches) = redact_body(body, cfg);
            if !matches.is_empty() {
                let slug = slug_from_path(path, roots);
                // Adjust line numbers by frontmatter line count
                let fm_lines = front.lines().count();
                let adjusted: Vec<RedactionMatch> = matches
                    .into_iter()
                    .map(|m| RedactionMatch {
                        pattern_name: m.pattern_name,
                        line_number: m.line_number + fm_lines,
                    })
                    .collect();
                report.redacted.push(RedactionReport {
                    slug,
                    matches: adjusted,
                });
                std::fs::write(path, format!("{front}{redacted_body}"))?;
                content = normalize_line_endings(&std::fs::read_to_string(path)?);
            }
        } else {
            // No frontmatter — redact the whole file
            let (redacted, matches) = redact_body(&content, cfg);
            if !matches.is_empty() {
                let slug = slug_from_path(path, roots);
                report.redacted.push(RedactionReport { slug, matches });
                std::fs::write(path, &redacted)?;
                content = normalize_line_endings(&redacted);
            }
        }
        let _ = parsed; // parsed only used to determine frontmatter presence above
    }

    let page = frontmatter::parse(&content);

    // No frontmatter — warn but count as validated
    if page.frontmatter.is_empty() {
        report
            .warnings
            .push(format!("{}: no frontmatter found", path.display()));
        report.pages_validated += 1;
        return Ok(());
    }

    // Validate base fields via type registry
    let warnings = registry.validate(&page.frontmatter, &validation.type_strictness)?;
    for w in warnings {
        report.warnings.push(format!("{}: {}", path.display(), w));
    }

    report.pages_validated += 1;
    Ok(())
}
