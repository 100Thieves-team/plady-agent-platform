//! Ingest as one operation: plan, then apply a complete change set.
//!
//! Karpathy's model says a single source touches ten to fifteen wiki pages. The
//! per-file `wiki_ingest` call made that the agent's bookkeeping problem, and
//! the failure mode it produced was not a crash — it was an ingest that stopped
//! after the source summary and looked finished. Nothing in the server
//! disagreed.
//!
//! Two calls replace that:
//!
//! * [`ingest_plan`] is read-only and takes no lock. It answers "what would a
//!   complete ingest of this raw file touch?" — which pages are mandatory, which
//!   existing topics and people the text points at, and whether some source page
//!   already covers it.
//! * [`apply`] takes the whole change set at once, validates the **resulting
//!   diff** rather than the caller's description of it, and commits exactly the
//!   paths that actually changed.
//!
//! Two properties matter more than the shape of the API:
//!
//! **Validation reads the diff, not the request.** A path listed in `changes`
//! whose content equals what is already on disk did not change, and a rule
//! satisfied by listing a topic without editing it is not satisfied. Everything
//! is decided from proposed-content-versus-current-content.
//!
//! **Nothing is written until everything validates.** The whole change set is
//! checked in memory first, so a rejected apply leaves no half-written pages to
//! clean up and no window for the sync sidecar to commit a fragment.

use anyhow::{Result, bail};
use serde::Serialize;

use crate::engine::{EngineState, WikiEngine};
use crate::frontmatter;
use crate::git;
use crate::links;
use crate::repo_lock::RepoLock;
use crate::slug::Slug;

// ── Modes ─────────────────────────────────────────────────────────────────────

/// What kind of ingest a change set is, which decides the rules it must satisfy.
///
/// A single strictness switch would be worn down to `off` by the first
/// legitimate exception. These are separate contracts instead: each is easy to
/// satisfy honestly and hard to misuse, because `Archive` cannot smuggle in a
/// compiled page and `Deferred` leaves a visible mark.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ApplyMode {
    /// Compiling knowledge from a source: raw preserved, a source page written,
    /// and at least one topic or person page actually updated.
    Knowledge,
    /// Preserving source material only. No compiled page may be included —
    /// otherwise this would be the escape hatch out of `Knowledge`.
    Archive,
    /// Output of a renderer or other harness, confined to generated paths.
    Generated,
    /// Knowledge whose topic is genuinely not yet known. Requires a reason and
    /// marks the source so the gap is visible rather than silently accepted.
    Deferred,
}

impl ApplyMode {
    /// Parse a mode name, listing the alternatives when it is not one.
    pub fn parse(name: &str) -> Result<Self> {
        match name.trim().to_ascii_lowercase().as_str() {
            "knowledge" => Ok(Self::Knowledge),
            "archive" => Ok(Self::Archive),
            "generated" => Ok(Self::Generated),
            "deferred" => Ok(Self::Deferred),
            other => bail!(
                "unknown ingest mode \"{other}\" — expected knowledge (raw + source + topic), \
                 archive (raw only), generated (harness output), or deferred (source with no \
                 topic yet, reason required)"
            ),
        }
    }

    fn as_str(self) -> &'static str {
        match self {
            Self::Knowledge => "knowledge",
            Self::Archive => "archive",
            Self::Generated => "generated",
            Self::Deferred => "deferred",
        }
    }
}

// ── Request and report ────────────────────────────────────────────────────────

/// One page or asset to write, as slug-or-path plus its full new content.
#[derive(Debug, Clone)]
pub struct Change {
    /// Slug (`topics/t-foo`) or content-root-relative path.
    pub path: String,
    /// Complete new file content.
    pub content: String,
}

/// Everything an apply needs.
#[derive(Debug, Clone)]
pub struct ApplyRequest {
    /// Contract this change set must satisfy.
    pub mode: ApplyMode,
    /// The complete change set — pages omitted here are not written.
    pub changes: Vec<Change>,
    /// Commit message. Derived from the diff when absent.
    pub message: Option<String>,
    /// Why the topic is unknown. Required by [`ApplyMode::Deferred`].
    pub reason: Option<String>,
    /// HEAD the caller planned against. Refused if the repository has moved.
    pub expected_head: Option<String>,
    /// Validate and report without writing.
    pub dry_run: bool,
}

/// What an apply did, grouped by the layer each page belongs to.
#[derive(Debug, Clone, Serialize, Default)]
pub struct ApplyReport {
    /// Mode this change set was validated against.
    pub mode: String,
    /// Preserved source pages created.
    pub raw: Vec<String>,
    /// Compiled source pages written.
    pub sources: Vec<String>,
    /// Topic pages updated.
    pub topics: Vec<String>,
    /// Person pages updated.
    pub people: Vec<String>,
    /// Written pages belonging to no mapped layer.
    pub other: Vec<String>,
    /// Requested paths whose content already matched — not committed.
    pub unchanged: Vec<String>,
    /// Commit hash, or empty when nothing changed or this was a dry run.
    pub commit: String,
    /// Commit message used.
    pub message: String,
    /// Non-fatal observations.
    pub warnings: Vec<String>,
    /// True when nothing was written.
    pub dry_run: bool,
}

impl ApplyReport {
    /// Total pages actually written.
    pub fn written_count(&self) -> usize {
        self.raw.len()
            + self.sources.len()
            + self.topics.len()
            + self.people.len()
            + self.other.len()
    }
}

// ── Plan ──────────────────────────────────────────────────────────────────────

/// A page an ingest of some raw source is likely to touch.
#[derive(Debug, Clone, Serialize)]
pub struct Candidate {
    /// Slug of the existing page.
    pub slug: String,
    /// Its title, for the agent to judge relevance without another read.
    pub title: String,
    /// Layer it belongs to (`topic`, `person`, …).
    pub kind: String,
    /// BM25 relevance against the raw text, for ranking within one plan.
    pub score: f32,
    /// Why it surfaced — the search that matched it.
    pub why: String,
}

/// What a complete ingest of one raw source would involve.
#[derive(Debug, Clone, Serialize)]
pub struct IngestPlan {
    /// The raw page this plans an ingest of.
    pub raw_path: String,
    /// Whether that raw page already exists.
    pub raw_exists: bool,
    /// HEAD at planning time — pass back as `expected_head` to detect drift.
    pub head: String,
    /// Steps a `knowledge` apply must include.
    pub required: Vec<String>,
    /// Existing topic and person pages the raw text points at.
    pub candidates: Vec<Candidate>,
    /// Source pages already citing this raw path.
    pub existing_sources: Vec<String>,
    /// What the candidate search could not answer, so a gap is not read as an
    /// absence of relevant pages.
    pub notes: Vec<String>,
    /// The ingest section of the wiki's rules.
    pub rules_excerpt: Option<String>,
}

/// Plan an ingest of `raw_path` without writing or locking anything.
///
/// The candidate list is the point: an agent that has to think of the affected
/// topics unaided is the agent that writes one page and stops. Terms are drawn
/// from the raw text and matched against existing pages, so the answer reflects
/// this wiki rather than a guess.
pub fn ingest_plan(engine: &EngineState, wiki_name: &str, raw_path: &str) -> Result<IngestPlan> {
    let space = engine.space(wiki_name)?;
    let raw_slug = Slug::try_from(raw_path.trim_end_matches(".md"))?;
    let resolved = space.roots.resolve(&raw_slug).ok();
    let raw_exists = resolved.is_some();

    let body = resolved
        .as_ref()
        .and_then(|p| std::fs::read_to_string(p).ok())
        .map(|text| frontmatter::parse(&text).body)
        .unwrap_or_default();

    let (candidates, notes) = find_candidates(engine, wiki_name, &body)?;
    let existing_sources = sources_citing(engine, wiki_name, raw_slug.as_str())?;

    let mut required = Vec::new();
    if !raw_exists {
        required.push(format!(
            "preserve the original at `{raw_slug}` — nothing below is evidence without it"
        ));
    }
    required.push(
        "write a `sources/…` page carrying `raw_source_path: \"{raw}\"`"
            .replace("{raw}", raw_slug.as_str()),
    );
    required.push(
        "update at least one topic or person page it bears on — a source page alone is an \
         incomplete ingest"
            .to_string(),
    );

    Ok(IngestPlan {
        raw_path: raw_slug.as_str().to_string(),
        raw_exists,
        head: git::current_head(&space.repo_root).unwrap_or_default(),
        required,
        candidates,
        existing_sources,
        notes,
        rules_excerpt: super::rules(engine, wiki_name, Some("ingest")).ok(),
    })
}

/// Rank existing topic and person pages against the raw text.
///
/// The raw body becomes one BM25 query rather than a series of per-term
/// searches. Searching term by term gives every term its own top results, so a
/// URL fragment like `https` returns three people as confidently as a real
/// subject word does. One query lets BM25 weigh the terms against each other,
/// and only pages that match the text as a whole rise.
///
/// Returns candidates plus a note for any layer that produced nothing usable —
/// silence and "I found nothing relevant" mean different things to the agent
/// reading this.
fn find_candidates(
    engine: &EngineState,
    wiki_name: &str,
    body: &str,
) -> Result<(Vec<Candidate>, Vec<String>)> {
    let query = build_query(body);
    if query.is_empty() {
        return Ok((
            Vec::new(),
            vec!["the raw text has no searchable terms".into()],
        ));
    }

    let mut out = Vec::new();
    let mut notes = Vec::new();

    for kind in ["topic", "person"] {
        let Ok(result) = super::search(
            engine,
            wiki_name,
            &super::SearchParams {
                query: &query,
                type_filter: Some(kind),
                no_excerpt: true,
                top_k: Some(CANDIDATES_PER_KIND),
                include_sections: false,
                cross_wiki: false,
            },
        ) else {
            continue;
        };
        let mut scores: Vec<f32> = result.results.iter().map(|p| p.score).collect();
        if scores.is_empty() {
            continue;
        }
        let top = scores[0];
        scores.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median = scores[scores.len() / 2];

        // A ranking is only informative if something stands out. When every
        // result scores about the same, they are all matching the corpus's
        // common vocabulary — a meeting note that names people by opaque IDs
        // produces exactly that. Presenting the top of a flat list as a
        // "candidate" would be inventing a lead.
        if scores.len() >= MIN_RESULTS_TO_JUDGE_SPREAD
            && median > 0.0
            && top < median * DISTINCTIVENESS
        {
            notes.push(format!(
                "no clearly relevant {kind} pages — every match scored about the same, so the text likely does not name any in a form this wiki indexes. Look yourself before concluding none apply."
            ));
            continue;
        }

        // The median floor only applies once there is a distribution to speak
        // of; with two results the median is one of them, and `median * 1.3`
        // would exclude the top hit itself.
        let floor = if scores.len() >= MIN_RESULTS_TO_JUDGE_SPREAD {
            (top * RELEVANCE_FLOOR).max(median * MEDIAN_FLOOR)
        } else {
            top * RELEVANCE_FLOOR
        };
        for page in result.results {
            if page.score < floor {
                continue;
            }
            out.push(Candidate {
                slug: page.slug,
                title: page.title,
                kind: kind.to_string(),
                score: page.score,
                why: format!(
                    "matches the source text ({kind} relevance {:.1})",
                    page.score
                ),
            });
        }
    }
    out.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    if !out.is_empty() {
        notes.push(
            "candidates are the strongest matches, not a complete list — search for anything the source discusses that they do not cover"
                .into(),
        );
    }
    Ok((out, notes))
}

/// How far the best match must stand above the median for the ranking to mean
/// anything. Below this the results are undifferentiated noise.
const DISTINCTIVENESS: f32 = 1.8;

/// Fewest results needed before a spread is worth judging. A wiki with two
/// topic pages has no distribution to be flat.
const MIN_RESULTS_TO_JUDGE_SPREAD: usize = 4;

/// Floor relative to the median, so a long flat tail is not all "relevant".
/// Tuned against this wiki: it keeps the pages a meeting note genuinely bears
/// on while cutting the ones matching only shared vocabulary.
const MEDIAN_FLOOR: f32 = 1.2;

/// Candidates returned per layer before the relevance floor is applied.
const CANDIDATES_PER_KIND: usize = 8;

/// Fraction of the top score a candidate must reach to be worth showing.
const RELEVANCE_FLOOR: f32 = 0.45;

/// Tokens the query never carries, because they describe how the text was
/// transported rather than what it is about.
///
/// Slack and web exports are dense with these; left in, they match pages that
/// merely contain a link.
const TRANSPORT_NOISE: &[&str] = &[
    "http", "https", "www", "com", "net", "org", "io", "md", "html", "png", "jpg", "amp", "utm",
    "slack", "archives", "docs", "team", "thread", "ts", "cid", "gmt", "am", "pm",
];

/// Turn raw body text into one search query.
///
/// Deduplicated so a word repeated forty times does not dominate, capped so the
/// query stays cheap to parse, and stripped of the characters tantivy's query
/// parser treats as syntax.
fn build_query(body: &str) -> String {
    let mut seen = std::collections::HashSet::new();
    let mut terms = Vec::new();
    for word in body.split(|c: char| !c.is_alphanumeric()) {
        let w = word.trim().to_lowercase();
        if w.chars().count() < 2
            || w.chars().all(|c| c.is_ascii_digit())
            || TRANSPORT_NOISE.contains(&w.as_str())
        {
            continue;
        }
        if seen.insert(w.clone()) {
            terms.push(w);
        }
        if terms.len() >= MAX_QUERY_TERMS {
            break;
        }
    }
    terms.join(" ")
}

/// Upper bound on query terms — enough to characterise a meeting note, few
/// enough that parsing stays trivial.
const MAX_QUERY_TERMS: usize = 60;

/// Source pages whose `raw_source_path` names this raw slug.
///
/// Prefers the index, but falls back to reading the source pages when
/// `raw_source_path` is not an indexed field — a wiki that has not declared it
/// in a schema would otherwise be told "no duplicates" for every raw file,
/// which is the one answer this must never give wrongly.
fn sources_citing(engine: &EngineState, wiki_name: &str, raw_slug: &str) -> Result<Vec<String>> {
    let space = engine.space(wiki_name)?;
    let searcher = space.index_manager.searcher()?;
    let is = &space.index_schema;
    let Some(field) = is.try_field("raw_source_path") else {
        return Ok(scan_sources_citing(space, raw_slug));
    };
    use tantivy::schema::Value;
    let query = tantivy::query::TermQuery::new(
        tantivy::Term::from_field_text(field, raw_slug),
        tantivy::schema::IndexRecordOption::Basic,
    );
    let docs = searcher.search(&query, &tantivy::collector::DocSetCollector)?;
    let f_slug = is.field("slug");
    let mut out: Vec<String> = docs
        .into_iter()
        .filter_map(|addr| {
            let doc: tantivy::TantivyDocument = searcher.doc(addr).ok()?;
            doc.get_first(f_slug)
                .and_then(|v| v.as_str())
                .map(str::to_string)
        })
        .collect();
    out.sort();
    Ok(out)
}

/// Read every compiled page looking for one that cites `raw_slug`.
///
/// Only reached when the field is unindexed; the compiled layer is small enough
/// that a walk costs less than a wrong answer.
fn scan_sources_citing(space: &crate::engine::SpaceContext, raw_slug: &str) -> Vec<String> {
    let mut out = Vec::new();
    for entry in walkdir::WalkDir::new(space.roots.primary())
        .into_iter()
        .filter_map(|e| e.ok())
    {
        let path = entry.path();
        if !path.is_file() || path.extension().and_then(|e| e.to_str()) != Some("md") {
            continue;
        }
        let Ok(slug) = space.roots.slug_from_path(path) else {
            continue;
        };
        if space.roots.derives_types() && space.roots.page_kind(slug.as_str()) != Some("source") {
            continue;
        }
        let Ok(text) = std::fs::read_to_string(path) else {
            continue;
        };
        let cited = frontmatter::parse(&text)
            .frontmatter
            .get("raw_source_path")
            .and_then(|v| v.as_str())
            .map(|s| s.trim_end_matches(".md").to_string());
        if cited.as_deref() == Some(raw_slug) {
            out.push(slug.as_str().to_string());
        }
    }
    out.sort();
    out
}

// ── Apply ─────────────────────────────────────────────────────────────────────

/// One change, resolved against the filesystem and classified by layer.
struct Resolved {
    slug: String,
    path: std::path::PathBuf,
    content: String,
    kind: Option<String>,
    /// False when the proposed content already matches what is on disk.
    changes_anything: bool,
    existed: bool,
}

/// Validate a complete change set and, if it holds together, write and commit it.
pub fn apply(
    engine: &EngineState,
    manager: &WikiEngine,
    wiki_name: &str,
    req: &ApplyRequest,
) -> Result<ApplyReport> {
    let space = engine.space(wiki_name)?;
    if req.changes.is_empty() {
        bail!("no changes given — `changes` must hold every page this ingest writes");
    }

    // Held from the first read of on-disk state through commit, so what is
    // validated is what gets committed.
    let _lock = if req.dry_run {
        None
    } else {
        Some(RepoLock::for_space(space, "mcp:apply")?)
    };

    if let Some(expected) = req.expected_head.as_deref().filter(|s| !s.is_empty()) {
        let actual = git::current_head(&space.repo_root).unwrap_or_default();
        if !actual.is_empty() && actual != expected {
            bail!(
                "the repository moved since this change set was planned (planned against \
                 {expected}, now {actual}). Re-read the pages you are updating and apply again — \
                 committing on top of a plan that no longer matches would overwrite whatever \
                 landed in between."
            );
        }
    }

    let resolved = resolve_changes(space, &req.changes)?;
    let mut warnings = validate(space, req, &resolved)?;

    let effective: Vec<&Resolved> = resolved.iter().filter(|r| r.changes_anything).collect();
    let mut report = build_report(req, &resolved);

    if effective.is_empty() {
        warnings.push("every requested page already had this content; nothing to commit".into());
        report.warnings = warnings;
        return Ok(report);
    }

    let message = req
        .message
        .clone()
        .unwrap_or_else(|| derive_message(&report));
    report.message = message.clone();

    if req.dry_run {
        report.warnings = warnings;
        return Ok(report);
    }

    // Everything validated: writing can no longer leave a partial state behind.
    for r in &effective {
        if let Some(parent) = r.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&r.path, &r.content)?;
    }

    let paths: Vec<&std::path::Path> = effective.iter().map(|r| r.path.as_path()).collect();
    report.commit = git::commit_paths(&space.repo_root, &paths, &message)?;

    if let Err(e) = manager.refresh_index(wiki_name) {
        warnings.push(format!("index update failed after apply: {e}"));
    }
    report.warnings = warnings;
    Ok(report)
}

fn resolve_changes(
    space: &crate::engine::SpaceContext,
    changes: &[Change],
) -> Result<Vec<Resolved>> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();

    for change in changes {
        let raw = change.path.trim();
        let slug_str = raw.strip_suffix(".md").unwrap_or(raw);
        let slug = Slug::try_from(slug_str)?;
        if !seen.insert(slug.as_str().to_string()) {
            bail!("`{slug}` appears twice in changes — each page may be written once");
        }

        let existing = space.roots.resolve(&slug).ok();
        let existed = existing.is_some();
        let current = existing
            .as_ref()
            .and_then(|p| std::fs::read_to_string(p).ok());
        let path = existing.unwrap_or_else(|| {
            space
                .roots
                .base_for(slug.as_str())
                .join(format!("{slug}.md"))
        });

        out.push(Resolved {
            changes_anything: current.as_deref() != Some(change.content.as_str()),
            slug: slug.as_str().to_string(),
            kind: space.roots.page_kind(slug.as_str()).map(str::to_string),
            path,
            content: change.content.clone(),
            existed,
        });
    }
    Ok(out)
}

/// Check the change set against its mode. Returns warnings; errors abort.
fn validate(
    space: &crate::engine::SpaceContext,
    req: &ApplyRequest,
    resolved: &[Resolved],
) -> Result<Vec<String>> {
    let mut warnings = Vec::new();

    // Preserved sources are create-only wherever they are written from.
    for r in resolved {
        if space.roots.is_external(&r.slug) && r.existed && r.changes_anything {
            bail!(
                "`{}` is preserved source material and is not rewritten. Add an addendum beside \
                 it, or compile the correction into a `wiki/` page.",
                r.slug
            );
        }
    }

    // A page that must start as Markdown, and never as a tool's own output.
    for r in resolved {
        if !r.changes_anything {
            continue;
        }
        let head = r.content.trim_start();
        if head.starts_with("{\"jsonrpc\"")
            || head.starts_with("{\"result\"")
            || head.starts_with("{\"content\"")
        {
            bail!(
                "`{}` looks like an MCP response envelope rather than page content. Unwrap the \
                 tool result before writing it.",
                r.slug
            );
        }
        if !head.starts_with("---") && !head.starts_with('#') {
            warnings.push(format!(
                "{}: content starts with neither frontmatter nor a heading",
                r.slug
            ));
        }
    }

    if !space.roots.derives_types() {
        warnings.push(
            "this wiki declares no `type_by_prefix`, so layer rules (raw / source / topic) cannot \
             be checked — only shape was validated"
                .into(),
        );
        return Ok(warnings);
    }

    let changed = |kind: &str| -> Vec<&Resolved> {
        resolved
            .iter()
            .filter(|r| r.changes_anything && r.kind.as_deref() == Some(kind))
            .collect()
    };
    let sources = changed("source");
    let topics = changed("topic");
    let people = changed("person");
    let raws = changed("raw");

    match req.mode {
        ApplyMode::Archive => {
            if !sources.is_empty() {
                bail!(
                    "mode `archive` preserves source material only, but this change set writes \
                     the compiled page `{}`. Use mode `knowledge` — archive is not a way past its \
                     rules.",
                    sources[0].slug
                );
            }
            if raws.is_empty() {
                bail!("mode `archive` expects at least one page under a preserved-source root");
            }
        }
        ApplyMode::Generated => {
            for r in resolved.iter().filter(|r| r.changes_anything) {
                let generated = r.kind.as_deref() == Some("policy")
                    || frontmatter::parse(&r.content)
                        .frontmatter
                        .get("managed_by")
                        .and_then(|v| v.as_str())
                        == Some("harness");
                if !generated {
                    bail!(
                        "mode `generated` is for harness output, but `{}` is neither in a \
                         generated location nor marked `managed_by: harness`",
                        r.slug
                    );
                }
            }
        }
        ApplyMode::Knowledge | ApplyMode::Deferred => {
            let Some(source) = sources.first() else {
                bail!(
                    "mode `{}` compiles knowledge, so the change set must include a source page. \
                     To preserve raw material without compiling it, use mode `archive`.",
                    req.mode.as_str()
                );
            };
            let fm = frontmatter::parse(&source.content);
            let raw_ref = fm
                .frontmatter
                .get("raw_source_path")
                .and_then(|v| v.as_str())
                .map(|s| s.trim_end_matches(".md").to_string());

            let Some(raw_ref) = raw_ref.filter(|s| !s.is_empty()) else {
                bail!(
                    "`{}` has no `raw_source_path`. A compiled page must name the preserved \
                     original it was derived from, or nothing downstream can be checked against \
                     evidence.",
                    source.slug
                );
            };

            let in_change_set = resolved.iter().any(|r| r.slug == raw_ref);
            let on_disk = Slug::try_from(raw_ref.as_str())
                .ok()
                .and_then(|s| space.roots.resolve(&s).ok())
                .is_some();
            if !in_change_set && !on_disk {
                bail!(
                    "`{}` cites `{raw_ref}`, which is neither in this change set nor already \
                     preserved. Write the original first — it is the evidence this page rests on.",
                    source.slug
                );
            }

            if topics.is_empty() && people.is_empty() {
                if req.mode == ApplyMode::Knowledge {
                    bail!(
                        "`{}` updates no topic or person page. One source normally moves several \
                         pages; a source page alone is an incomplete ingest. Update the pages it \
                         bears on, or — if it genuinely belongs to no existing topic — apply with \
                         mode `deferred` and a reason.",
                        source.slug
                    );
                }
                match req
                    .reason
                    .as_deref()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                {
                    Some(reason) => warnings.push(format!(
                        "deferred: no topic or person updated — {reason}. \
                         `{}` is recorded as needing integration.",
                        source.slug
                    )),
                    None => bail!(
                        "mode `deferred` requires `reason` — an unexplained gap is \
                         indistinguishable from an unfinished ingest"
                    ),
                }
            }

            // Linking a topic that was not touched is the shape the incident
            // took: the page names its topics and none of them learn anything.
            let linked: Vec<String> = links::extract_body_wikilinks(&fm.body)
                .into_iter()
                .chain(fm.string_list("topics").into_iter().map(str::to_string))
                .collect();
            let untouched: Vec<&String> = linked
                .iter()
                .filter(|slug| {
                    space.roots.page_kind(slug) == Some("topic")
                        && !topics.iter().any(|t| t.slug == **slug)
                })
                .collect();
            if !untouched.is_empty() {
                warnings.push(format!(
                    "{} links topics that this change set does not update: {}",
                    source.slug,
                    untouched
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                ));
            }
        }
    }

    Ok(warnings)
}

fn build_report(req: &ApplyRequest, resolved: &[Resolved]) -> ApplyReport {
    let mut report = ApplyReport {
        mode: req.mode.as_str().to_string(),
        dry_run: req.dry_run,
        ..Default::default()
    };
    for r in resolved {
        if !r.changes_anything {
            report.unchanged.push(r.slug.clone());
            continue;
        }
        match r.kind.as_deref() {
            Some("raw") => report.raw.push(r.slug.clone()),
            Some("source") => report.sources.push(r.slug.clone()),
            Some("topic") => report.topics.push(r.slug.clone()),
            Some("person") => report.people.push(r.slug.clone()),
            _ => report.other.push(r.slug.clone()),
        }
    }
    report
}

/// Build a commit message from what actually changed.
///
/// The old message counted the files a walk visited, which is why a commit
/// touching several pages could read `+1 pages`. This counts the diff.
fn derive_message(report: &ApplyReport) -> String {
    let subject = report
        .sources
        .first()
        .or_else(|| report.raw.first())
        .or_else(|| report.topics.first())
        .cloned()
        .unwrap_or_else(|| "wiki".to_string());

    let mut parts = Vec::new();
    let mut push = |n: usize, label: &str| {
        if n > 0 {
            parts.push(format!("{n} {label}"));
        }
    };
    push(report.raw.len(), "raw");
    push(report.sources.len(), "source");
    push(report.topics.len(), "topics");
    push(report.people.len(), "people");
    push(report.other.len(), "other");

    let mut body = String::new();
    for group in [
        &report.raw,
        &report.sources,
        &report.topics,
        &report.people,
        &report.other,
    ] {
        for slug in group {
            body.push_str("\n  ");
            body.push_str(slug);
        }
    }

    format!(
        "ingest({}): {subject} — {}\n{body}",
        report.mode,
        parts.join(", ")
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mode_names_parse_and_unknown_names_list_the_alternatives() {
        assert_eq!(ApplyMode::parse("knowledge").unwrap(), ApplyMode::Knowledge);
        assert_eq!(ApplyMode::parse("  ARCHIVE ").unwrap(), ApplyMode::Archive);
        let err = ApplyMode::parse("lenient").unwrap_err().to_string();
        assert!(err.contains("archive"), "error should list modes: {err}");
    }

    #[test]
    fn derived_message_counts_the_diff_not_the_request() {
        let report = ApplyReport {
            mode: "knowledge".into(),
            raw: vec!["raw/meetings/scrum".into()],
            sources: vec!["sources/scrum-summary".into()],
            topics: vec!["topics/t-a".into(), "topics/t-b".into()],
            ..Default::default()
        };
        let msg = derive_message(&report);
        assert!(msg.starts_with("ingest(knowledge): sources/scrum-summary — "));
        assert!(msg.contains("1 raw"));
        assert!(msg.contains("2 topics"));
        assert!(msg.contains("topics/t-b"), "body should list every path");
    }
}
