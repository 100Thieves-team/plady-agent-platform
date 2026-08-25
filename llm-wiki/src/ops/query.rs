//! Query as a first-class operation: assemble context, then keep the answer.
//!
//! Karpathy lists query beside ingest and lint, and adds the part that makes a
//! wiki compound rather than merely accumulate: *"valuable outputs become new
//! wiki pages rather than disappearing into chat history."*
//!
//! Search alone does not give an agent that. Ranked slugs are an index into
//! work still to be done — one call to find the pages, N more to read them,
//! and the synthesis evaporates when the conversation ends. Two operations
//! close both halves:
//!
//! * [`context`] answers a question with the pages themselves, cited and fitted
//!   to a budget, in one call.
//! * [`save_answer`] writes a conclusion back as a page that cites the pages it
//!   came from. An answer with no citations is a guess, so it is refused.

use anyhow::{Result, bail};
use serde::Serialize;

use crate::engine::{EngineState, WikiEngine};
use crate::frontmatter;
use crate::git;
use crate::markdown;
use crate::repo_lock::RepoLock;
use crate::slug::Slug;

// ── Context ───────────────────────────────────────────────────────────────────

/// One page, as much of it as the budget allowed.
#[derive(Debug, Clone, Serialize)]
pub struct ContextPage {
    /// Slug, which is also how to cite it.
    pub slug: String,
    /// Display title.
    pub title: String,
    /// Layer it belongs to.
    pub kind: String,
    /// Relevance to the question, for judging what to trust.
    pub score: f32,
    /// Page body, possibly truncated.
    pub body: String,
    /// True when `body` stops short of the page.
    pub truncated: bool,
}

/// Pages assembled to answer one question.
#[derive(Debug, Clone, Serialize)]
pub struct ContextBundle {
    /// The question this was assembled for.
    pub question: String,
    /// Pages, most relevant first.
    pub pages: Vec<ContextPage>,
    /// Characters of page body returned.
    pub used_chars: usize,
    /// Pages that matched but did not fit.
    pub omitted: Vec<String>,
    /// How to read this bundle and what it is not.
    pub notes: Vec<String>,
}

/// Default character budget for a bundle.
///
/// Large enough for several pages of this wiki, small enough that an agent can
/// ask twice rather than once and blow its context.
const DEFAULT_BUDGET: usize = 12_000;

/// Never return less than this of a page — a hundred characters of a document
/// is not evidence, it is a teaser that forces a second call.
const MIN_USEFUL_SLICE: usize = 600;

/// How many candidates to consider before the budget decides.
const CANDIDATE_POOL: usize = 12;

/// Assemble the pages that answer `question`.
///
/// Bodies are included rather than excerpts because the caller's next move
/// after an excerpt is always to read the page. Frontmatter is stripped: it is
/// bookkeeping, and it would spend budget that belongs to prose.
pub fn context(
    engine: &EngineState,
    wiki_name: &str,
    question: &str,
    budget_chars: Option<usize>,
    types: Option<&str>,
) -> Result<ContextBundle> {
    let question = question.trim();
    if question.is_empty() {
        bail!("`question` is empty — context is assembled around a question, not a page list");
    }
    let budget = budget_chars.unwrap_or(DEFAULT_BUDGET).max(MIN_USEFUL_SLICE);
    let space = engine.space(wiki_name)?;

    let kinds: Vec<Option<String>> = match types.map(str::trim).filter(|s| !s.is_empty()) {
        Some(list) => list
            .split(',')
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(|s| Some(s.to_string()))
            .collect(),
        None => vec![None],
    };

    let mut ranked: Vec<(f32, String, String)> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    for kind in &kinds {
        let result = super::search(
            engine,
            wiki_name,
            &super::SearchParams {
                query: question,
                type_filter: kind.as_deref(),
                no_excerpt: true,
                top_k: Some(CANDIDATE_POOL),
                include_sections: false,
                cross_wiki: false,
            },
        )?;
        for page in result.results {
            if seen.insert(page.slug.clone()) {
                ranked.push((page.score, page.slug, page.title));
            }
        }
    }
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));

    let mut pages = Vec::new();
    let mut omitted = Vec::new();
    let mut used = 0usize;

    for (score, slug_str, title) in ranked {
        let remaining = budget.saturating_sub(used);
        if remaining < MIN_USEFUL_SLICE {
            omitted.push(slug_str);
            continue;
        }
        let Ok(slug) = Slug::try_from(slug_str.as_str()) else {
            continue;
        };
        // Frontmatter stripped: the caller asked a question, not for metadata.
        let Ok(body) = markdown::read_page(&slug, &space.roots, true) else {
            continue;
        };
        let body = body.trim();
        let (text, truncated) = truncate_chars(body, remaining);
        used += text.chars().count();
        pages.push(ContextPage {
            kind: space
                .roots
                .page_kind(&slug_str)
                .unwrap_or("page")
                .to_string(),
            slug: slug_str,
            title,
            score,
            body: text,
            truncated,
        });
    }

    let mut notes = vec![
        "cite pages by slug — every claim you carry forward should name the page it came from"
            .to_string(),
    ];
    if !omitted.is_empty() {
        notes.push(format!(
            "{} page(s) matched but did not fit the budget; raise `budget_chars` or narrow the \
             question to see them",
            omitted.len()
        ));
    }
    if pages.is_empty() {
        notes.push(
            "nothing matched — try `wiki_catalog` to see what this wiki covers, or different terms"
                .to_string(),
        );
    }

    Ok(ContextBundle {
        question: question.to_string(),
        pages,
        used_chars: used,
        omitted,
        notes,
    })
}

/// Cut `text` to `max` characters at a line boundary where one is close.
///
/// Splitting mid-sentence costs the reader more than the few characters saved.
fn truncate_chars(text: &str, max: usize) -> (String, bool) {
    if text.chars().count() <= max {
        return (text.to_string(), false);
    }
    let cut: String = text.chars().take(max).collect();
    let trimmed = match cut.rfind('\n') {
        Some(pos) if pos > max / 2 => &cut[..pos],
        _ => cut.as_str(),
    };
    (format!("{}\n\n…truncated", trimmed.trim_end()), true)
}

// ── Saved answers ─────────────────────────────────────────────────────────────

/// Where a saved answer lands, and what it cites.
#[derive(Debug, Clone, Serialize)]
pub struct SavedAnswer {
    /// Slug of the page written.
    pub slug: String,
    /// Commit that recorded it.
    pub commit: String,
    /// Pages it cites.
    pub sources: Vec<String>,
    /// Non-fatal observations.
    pub warnings: Vec<String>,
}

/// Slug prefix saved answers live under, unless the caller names a slug.
const ANSWER_PREFIX: &str = "answers";

/// Write a conclusion back into the wiki as a citable page.
///
/// `sources` must name pages that exist: an answer that cites nothing cannot be
/// checked against evidence later, and a wiki of unfalsifiable conclusions is
/// worse than no wiki. Everything else is deliberately thin — this is a way to
/// stop losing work, not a second page editor.
pub fn save_answer(
    engine: &EngineState,
    manager: &WikiEngine,
    wiki_name: &str,
    question: &str,
    answer: &str,
    sources: &[String],
    slug: Option<&str>,
) -> Result<SavedAnswer> {
    let question = question.trim();
    let answer = answer.trim();
    if question.is_empty() || answer.is_empty() {
        bail!("both `question` and `answer` are required — a saved answer records both");
    }
    if sources.is_empty() {
        bail!(
            "`sources` is empty. An answer that names no page it came from cannot be checked \
             against evidence later; cite the slugs `wiki_context` returned."
        );
    }

    let space = engine.space(wiki_name)?;
    let _lock = RepoLock::for_space(space, "mcp:save_answer")?;

    let mut warnings = Vec::new();
    for source in sources {
        let exists = Slug::try_from(source.as_str())
            .ok()
            .and_then(|s| space.roots.resolve(&s).ok())
            .is_some();
        if !exists {
            bail!(
                "cited source `{source}` is not a page in this wiki — cite the slugs from a \
                 `wiki_context` bundle rather than paraphrasing them"
            );
        }
    }

    // A caller-chosen slug wins; otherwise the question names the page, so two
    // askings of the same question update one page instead of accumulating
    // near-duplicates.
    let target = match slug.map(str::trim).filter(|s| !s.is_empty()) {
        Some(s) => Slug::try_from(s)?,
        None => Slug::try_from(answer_slug(question).as_str())?,
    };

    let path = space
        .roots
        .base_for(target.as_str())
        .join(format!("{target}.md"));
    if path.exists() {
        warnings.push(format!("{target} already existed and was replaced"));
    }

    let content = render_answer(question, answer, sources);
    for finding in
        super::conventions::check(target.as_str(), &content, &space.roots, !path.exists())
    {
        if finding.severity == super::conventions::Severity::Error {
            bail!("{}: {}", finding.slug, finding.message);
        }
        warnings.push(format!("{}: {}", finding.slug, finding.message));
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(&path, &content)?;

    let commit = git::commit_paths(
        &space.repo_root,
        &[path.as_path()],
        &format!("answer: {question}"),
    )?;
    if let Err(e) = manager.refresh_index(wiki_name) {
        warnings.push(format!("index update failed after save: {e}"));
    }

    Ok(SavedAnswer {
        slug: target.as_str().to_string(),
        commit,
        sources: sources.to_vec(),
        warnings,
    })
}

/// Build the page body for a saved answer.
fn render_answer(question: &str, answer: &str, sources: &[String]) -> String {
    let mut fm: std::collections::BTreeMap<String, serde_yaml::Value> =
        std::collections::BTreeMap::new();
    let put = |fm: &mut std::collections::BTreeMap<String, serde_yaml::Value>, k: &str, v: &str| {
        fm.insert(k.to_string(), serde_yaml::Value::String(v.to_string()));
    };
    put(&mut fm, "title", question);
    put(&mut fm, "type", "answer");
    put(&mut fm, "status", "active");
    put(&mut fm, "summary", &first_line(answer));
    put(&mut fm, "last_updated", &today());
    fm.insert(
        "tags".to_string(),
        serde_yaml::Value::Sequence(vec![serde_yaml::Value::String("answer".into())]),
    );
    fm.insert(
        "source_pages".to_string(),
        serde_yaml::Value::Sequence(
            sources
                .iter()
                .map(|s| serde_yaml::Value::String(s.clone()))
                .collect(),
        ),
    );

    let citations = sources
        .iter()
        .map(|s| format!("- [{s}]({s})"))
        .collect::<Vec<_>>()
        .join("\n");
    let body = format!(
        "## Question\n\n{question}\n\n## Answer\n\n{answer}\n\n## Sources\n\n{citations}\n"
    );
    frontmatter::write(&fm, &body)
}

/// First sentence-ish of the answer, for the `summary` field.
fn first_line(answer: &str) -> String {
    let line = answer
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty() && !l.starts_with('#'))
        .unwrap_or("");
    let trimmed: String = line.chars().take(200).collect();
    trimmed
}

/// Today's date, ISO-8601.
fn today() -> String {
    chrono::Utc::now().format("%Y-%m-%d").to_string()
}

/// Derive a slug for an answer from its question.
pub fn answer_slug(question: &str) -> String {
    let stem: String = question
        .chars()
        .map(|c| {
            if c.is_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect();
    let stem = stem
        .split('-')
        .filter(|s| !s.is_empty())
        .take(8)
        .collect::<Vec<_>>()
        .join("-");
    format!(
        "{ANSWER_PREFIX}/{}",
        if stem.is_empty() { "answer" } else { &stem }
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_short_page_is_returned_whole() {
        let (out, truncated) = truncate_chars("짧은 본문", 100);
        assert_eq!(out, "짧은 본문");
        assert!(!truncated);
    }

    #[test]
    fn truncation_prefers_a_line_boundary_and_says_so() {
        let text = "첫 줄입니다\n둘째 줄입니다\n셋째 줄입니다";
        let (out, truncated) = truncate_chars(text, 14);
        assert!(truncated);
        assert!(out.contains("…truncated"));
        assert!(!out.contains("셋째"));
    }

    #[test]
    fn truncation_counts_characters_not_bytes() {
        // A byte cut would split a Hangul syllable and produce invalid UTF-8.
        let text = "한".repeat(50);
        let (out, _) = truncate_chars(&text, 10);
        assert!(out.starts_with("한한"));
    }

    #[test]
    fn an_answer_slug_is_derived_from_the_question() {
        assert_eq!(
            answer_slug("What is the deploy pipeline?"),
            "answers/what-is-the-deploy-pipeline"
        );
        assert!(answer_slug("배포 파이프라인은?").starts_with("answers/"));
    }

    #[test]
    fn an_answer_slug_never_collapses_to_the_prefix_alone() {
        assert_eq!(answer_slug("???"), "answers/answer");
        assert_eq!(answer_slug(""), "answers/answer");
    }

    #[test]
    fn the_rendered_answer_cites_every_source() {
        let out = render_answer(
            "질문?",
            "답변 본문.",
            &["topics/t-a".to_string(), "sources/s-b".to_string()],
        );
        assert!(out.contains("type: answer"));
        assert!(out.contains("source_pages"));
        assert!(out.contains("[topics/t-a](topics/t-a)"));
        assert!(out.contains("[sources/s-b](sources/s-b)"));
        assert!(out.contains("## Question"));
    }

    #[test]
    fn the_summary_skips_headings_and_blank_lines() {
        assert_eq!(first_line("\n\n# 제목\n\n실제 첫 문장."), "실제 첫 문장.");
    }
}
