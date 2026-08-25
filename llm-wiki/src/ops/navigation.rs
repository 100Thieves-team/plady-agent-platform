//! Catalog and timeline — the two things an agent asks a wiki before reading it.
//!
//! Karpathy's model names an `index.md` catalogue and an append-only `log.md`.
//! Both are files there because that LLM reads the repository directly. Here the
//! agent has tools, and a tool answer is strictly better on both counts:
//!
//! * A catalogue file regenerated on every ingest is a hot file — it appears in
//!   every commit, conflicts between concurrent writers, and is stale between
//!   the write and the regeneration. Built from the index on demand, it cannot
//!   be stale and costs nothing when unread.
//! * A hand-maintained log duplicates what git already records perfectly, and
//!   the copy is the one that drifts. [`recent`] reads the history instead.
//!
//! This is not theory: the first agent to use the rebuilt wiki opened by trying
//! to read `SCHEMA.md`, `index.md`, and `log.md`, and got three "page not
//! found"s. It went looking for this layer unprompted.

use anyhow::Result;
use serde::Serialize;

use crate::engine::EngineState;
use crate::git;

// ── Catalog ───────────────────────────────────────────────────────────────────

/// One page as it appears in the catalogue.
#[derive(Debug, Clone, Serialize)]
pub struct CatalogEntry {
    /// Page slug.
    pub slug: String,
    /// Display title.
    pub title: String,
    /// One-line scope, when the page states one.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub summary: Option<String>,
}

/// Pages of one kind.
#[derive(Debug, Clone, Serialize)]
pub struct CatalogSection {
    /// The layer these pages belong to (`topic`, `source`, …).
    pub kind: String,
    /// How many pages the wiki holds of this kind.
    pub total: usize,
    /// The entries listed, which may be fewer than `total`.
    pub entries: Vec<CatalogEntry>,
}

/// What the wiki contains, grouped by layer.
#[derive(Debug, Clone, Serialize)]
pub struct Catalog {
    /// Wiki this describes.
    pub wiki: String,
    /// Total indexed pages.
    pub total_pages: usize,
    /// One group per page kind, compiled layers before preserved sources.
    pub sections: Vec<CatalogSection>,
    /// How to read this, and what it does not include.
    pub notes: Vec<String>,
}

/// Order the layers are presented in.
///
/// Compiled knowledge first because that is what an agent should read before
/// going to the evidence; `raw` last because it is large and rarely the right
/// starting point.
const KIND_ORDER: &[&str] = &["topic", "person", "source", "policy", "raw"];

/// Entries listed per kind when the caller does not name a section.
///
/// A full listing of a large layer is not a catalogue, it is a directory dump —
/// and it would crowd out the layers that fit.
const OVERVIEW_LIMIT: usize = 25;

/// Entries listed when one section is asked for by name.
const SECTION_LIMIT: usize = 300;

/// Describe what the wiki holds.
///
/// With `section`, that layer is listed in depth; without, every layer is
/// sampled so the shape of the wiki is visible in one answer.
pub fn catalog(engine: &EngineState, wiki_name: &str, section: Option<&str>) -> Result<Catalog> {
    let wanted = section.map(str::trim).filter(|s| !s.is_empty());
    let limit = if wanted.is_some() {
        SECTION_LIMIT
    } else {
        OVERVIEW_LIMIT
    };

    // One unfiltered listing gives the per-kind totals; the facet is the
    // authority on which kinds exist, so a wiki with its own layers is
    // described in its own terms rather than only the ones named here.
    let overview = super::list(engine, wiki_name, None, None, 1, Some(1))?;
    let mut kinds: Vec<(String, usize)> = overview
        .facets
        .r#type
        .iter()
        .map(|(kind, count)| (kind.clone(), *count as usize))
        .collect();
    kinds.sort_by_key(|(kind, _)| {
        KIND_ORDER
            .iter()
            .position(|k| k == kind)
            .unwrap_or(KIND_ORDER.len())
    });

    let mut sections = Vec::new();
    let mut notes = Vec::new();

    for (kind, total) in kinds {
        if kind == "section" {
            continue; // structural index pages, not knowledge
        }
        if let Some(want) = wanted
            && want != kind
        {
            continue;
        }
        let listing = super::list(engine, wiki_name, Some(&kind), None, 1, Some(limit))?;
        let entries: Vec<CatalogEntry> = listing
            .pages
            .into_iter()
            .map(|p| CatalogEntry {
                slug: p.slug,
                title: p.title,
                summary: p.summary,
            })
            .collect();
        if entries.len() < total {
            notes.push(format!(
                "`{kind}`: showing {} of {total} — call `wiki_catalog` with section \"{kind}\" for \
                 the rest, or `wiki_search` to find a specific one",
                entries.len()
            ));
        }
        sections.push(CatalogSection {
            kind,
            total,
            entries,
        });
    }

    if let Some(want) = wanted
        && sections.is_empty()
    {
        notes.push(format!(
            "no pages of kind \"{want}\" — omit `section` to see which kinds exist"
        ));
    }

    Ok(Catalog {
        wiki: wiki_name.to_string(),
        total_pages: overview.total,
        sections,
        notes,
    })
}

// ── Recent activity ───────────────────────────────────────────────────────────

/// One commit, with the wiki pages it touched.
#[derive(Debug, Clone, Serialize)]
pub struct RecentChange {
    /// Abbreviated commit hash.
    pub commit: String,
    /// ISO-8601 author date.
    pub date: String,
    /// Commit subject.
    pub message: String,
    /// Who made it.
    pub author: String,
    /// Slugs of the content pages this commit changed.
    pub pages: Vec<String>,
}

/// What has changed in the wiki lately.
#[derive(Debug, Clone, Serialize)]
pub struct RecentReport {
    /// Wiki this describes.
    pub wiki: String,
    /// Most recent first.
    pub changes: Vec<RecentChange>,
    /// How this was derived.
    pub notes: Vec<String>,
}

/// Default number of commits reported.
const RECENT_LIMIT: usize = 20;

/// Read recent wiki activity from git history.
///
/// `since` accepts anything `git log --since` does — `"2 weeks ago"`,
/// `"2026-08-01"` — because the question is usually "what happened while I was
/// away", not "what were the last N commits".
pub fn recent(
    engine: &EngineState,
    wiki_name: &str,
    limit: Option<usize>,
    since: Option<&str>,
) -> Result<RecentReport> {
    let space = engine.space(wiki_name)?;
    let prefixes = space.roots.repo_relative_prefixes();
    let entries = git::recent_changes(
        &space.repo_root,
        limit.unwrap_or(RECENT_LIMIT),
        since,
        &prefixes,
    )?;

    let changes = entries
        .into_iter()
        .map(|e| RecentChange {
            commit: e.hash.chars().take(8).collect(),
            date: e.date,
            message: e.message,
            author: e.author,
            pages: e
                .paths
                .iter()
                .filter_map(|p| {
                    space
                        .roots
                        .slug_from_repo_relative(std::path::Path::new(p))
                        .ok()
                        .map(|s| s.as_str().to_string())
                })
                .collect(),
        })
        .collect::<Vec<_>>();

    let mut notes = vec![
        "derived from git history — commits that touched no content page are omitted".to_string(),
    ];
    if since.is_none() {
        notes.push(format!(
            "showing the last {} commits; pass `since` (e.g. \"2 weeks ago\") for a time window",
            limit.unwrap_or(RECENT_LIMIT)
        ));
    }

    Ok(RecentReport {
        wiki: wiki_name.to_string(),
        changes,
        notes,
    })
}

// ── Misdirected reads ─────────────────────────────────────────────────────────

/// The tool that answers what a well-known filename was reaching for.
///
/// An agent that has read about this wiki model looks for `index.md` and
/// `log.md` by name. Answering "page not found" is technically right and
/// useless; naming the tool that does the job costs one line.
pub fn suggestion_for_missing(slug: &str) -> Option<&'static str> {
    let name = slug.rsplit('/').next().unwrap_or(slug).to_ascii_lowercase();
    let stem = name.strip_suffix(".md").unwrap_or(&name);
    match stem {
        "index" | "catalog" | "catalogue" | "_index" => {
            Some("`wiki_catalog` describes what this wiki contains, grouped by kind")
        }
        "log" | "changelog" | "history" => {
            Some("`wiki_recent` reports recent changes, derived from git history")
        }
        "schema" | "agents" | "claude" | "readme" | "conventions" => {
            Some("`wiki_rules` returns this wiki's operating rules and conventions")
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn well_known_names_point_at_the_tool_that_answers_them() {
        assert!(
            suggestion_for_missing("index.md")
                .unwrap()
                .contains("wiki_catalog")
        );
        assert!(
            suggestion_for_missing("log.md")
                .unwrap()
                .contains("wiki_recent")
        );
        assert!(
            suggestion_for_missing("SCHEMA.md")
                .unwrap()
                .contains("wiki_rules")
        );
        assert!(
            suggestion_for_missing("AGENTS.md")
                .unwrap()
                .contains("wiki_rules")
        );
    }

    #[test]
    fn the_suggestion_ignores_case_extension_and_directory() {
        assert!(suggestion_for_missing("wiki/INDEX").is_some());
        assert!(suggestion_for_missing("Log").is_some());
    }

    #[test]
    fn an_ordinary_page_gets_no_suggestion() {
        assert!(suggestion_for_missing("topics/t-foo").is_none());
        assert!(suggestion_for_missing("sources/indexing-notes").is_none());
    }

    #[test]
    fn compiled_layers_are_ordered_before_preserved_sources() {
        let topic = KIND_ORDER.iter().position(|k| *k == "topic").unwrap();
        let raw = KIND_ORDER.iter().position(|k| *k == "raw").unwrap();
        assert!(
            topic < raw,
            "raw should not be the first thing an agent reads"
        );
    }
}
