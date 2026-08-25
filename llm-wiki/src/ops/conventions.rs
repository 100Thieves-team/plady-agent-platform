//! Frontmatter and link conventions, checked at write time.
//!
//! A wiki's conventions live in its rules document, and an agent that has read
//! them still drifts: the ingest that prompted this module wrote a page tagged
//! both `source` and `sources`, which the rules forbid in as many words. Rules
//! an agent carries in context but nothing enforces are rules that leak.
//!
//! Severity follows a ratchet rather than a standard. A corpus that grew before
//! a rule existed will violate it everywhere — 191 of this wiki's 251 pages
//! declare a `type` that disagrees with where they live — so making that an
//! error would block every edit until someone ran a migration. Instead:
//!
//! * a **new** page must satisfy the conventions, so no new debt is created;
//! * an **existing** page reports the same finding as a warning, so the debt is
//!   visible at the moment someone is already editing that file.
//!
//! The effect is that conventions tighten as pages are touched, without a
//! flag day and without a rule nobody can afford to obey.

use serde::Serialize;

use crate::content_roots::ContentRoots;
use crate::frontmatter;

// One severity vocabulary for the crate. A second enum with the same two
// variants would make `ops::Severity` ambiguous and mean nothing extra.
pub use super::lint::Severity;

/// A convention a page does not satisfy.
#[derive(Debug, Clone, Serialize)]
pub struct Finding {
    /// Page the finding is about.
    pub slug: String,
    /// Whether it blocks.
    pub severity: Severity,
    /// What is wrong and what to do about it.
    pub message: String,
}

/// Facet names whose singular and plural forms mean the same thing.
///
/// Carrying both splits the facet in two: a search for one misses pages tagged
/// with the other, and neither count is the real count.
const PLURAL_PAIRS: &[(&str, &str)] = &[
    ("source", "sources"),
    ("topic", "topics"),
    ("person", "people"),
    ("meeting", "meetings"),
    ("tag", "tags"),
    ("decision", "decisions"),
];

/// Baseline frontmatter every compiled page carries.
///
/// Preserved sources are exempt: they arrive with whatever metadata they had,
/// and demanding more would mean editing the original.
const BASELINE_FIELDS: &[&str] = &["title", "type", "status", "summary", "last_updated", "tags"];

/// Check one page against the wiki's conventions.
///
/// `is_new` selects the ratchet: a page being created must comply, one being
/// edited only reports.
pub fn check(slug: &str, content: &str, roots: &ContentRoots, is_new: bool) -> Vec<Finding> {
    let severity = if is_new {
        Severity::Error
    } else {
        Severity::Warning
    };
    let page = frontmatter::parse(content);
    let derived = roots.page_kind(slug);
    let is_preserved = roots.is_external(slug);
    let mut findings = Vec::new();

    let mut add = |sev: Severity, message: String| {
        findings.push(Finding {
            slug: slug.to_string(),
            severity: sev,
            message,
        })
    };

    let tags: Vec<String> = page
        .string_list("tags")
        .into_iter()
        .map(str::to_string)
        .collect();

    for (singular, plural) in PLURAL_PAIRS {
        if tags.iter().any(|t| t == singular) && tags.iter().any(|t| t == plural) {
            add(
                severity,
                format!(
                    "tags carry both `{singular}` and `{plural}` — the same facet under two names \
                     splits it in two, so neither is searchable as the whole. Keep one."
                ),
            );
        }
    }

    for tag in &tags {
        if tag.chars().any(|c| c.is_uppercase()) || tag.contains(' ') || tag.contains('_') {
            add(
                Severity::Warning,
                format!(
                    "tag `{tag}` is not lowercase-hyphenated — `{}` would match how the rest of \
                     the wiki is tagged",
                    normalize_tag(tag)
                ),
            );
        }
    }

    // A page whose `type` contradicts its location is a file that misdescribes
    // itself. The index derives the real type either way, so the fix is to
    // agree or to say nothing.
    if let Some(kind) = derived
        && let Some(declared) = page.page_type()
        && declared != kind
        && declared != "section"
    {
        add(
            severity,
            format!(
                "declares `type: {declared}` but lives under `{kind}` — the index uses the \
                 location, so this field describes the page wrongly. Set `type: {kind}`, or omit \
                 `type` and let the location speak."
            ),
        );
    }

    if !is_preserved {
        for field in BASELINE_FIELDS {
            // `type` is covered above, and may legitimately be omitted.
            if *field == "type" {
                continue;
            }
            if !page.frontmatter.contains_key(*field) {
                add(severity, format!("missing baseline field `{field}`"));
            }
        }
    }

    findings.extend(check_links(slug, &page.body, severity));
    findings
}

/// Link forms the wiki does not accept, whatever the page.
fn check_links(slug: &str, body: &str, severity: Severity) -> Vec<Finding> {
    let mut findings = Vec::new();
    let mut rest = body;
    while let Some(start) = rest.find("[[") {
        let after = &rest[start + 2..];
        let Some(end) = after.find("]]") else { break };
        let target = after[..end].trim();
        rest = &after[end + 2..];

        // `[[1]](url)` is a bracketed link label, not a wikilink.
        if rest.starts_with('(') || target.is_empty() || target.chars().all(|c| c.is_ascii_digit())
        {
            continue;
        }
        if target.contains('|') {
            findings.push(Finding {
                slug: slug.to_string(),
                severity,
                message: format!(
                    "`[[{target}]]` uses alias syntax — the link extractor reads the pipe as part \
                     of the slug, so this resolves to nothing. Write `[label](slug)` instead."
                ),
            });
        } else if !target.contains('/') {
            findings.push(Finding {
                slug: slug.to_string(),
                severity,
                message: format!(
                    "`[[{target}]]` has no collection prefix — with `sources/`, `topics/`, and \
                     `people/` pages sharing names this is ambiguous. Write `[[topics/{target}]]` \
                     or `[label](topics/{target})`."
                ),
            });
        }
    }
    findings
}

/// The lowercase-hyphenated form of a tag, for the suggestion in a warning.
fn normalize_tag(tag: &str) -> String {
    tag.trim()
        .to_lowercase()
        .replace([' ', '_'], "-")
        .trim_matches('-')
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roots() -> ContentRoots {
        ContentRoots::new("/repo/wiki", ["raw"]).with_type_by_prefix([
            ("sources", "source"),
            ("topics", "topic"),
            ("raw", "raw"),
        ])
    }

    fn messages(f: &[Finding]) -> String {
        f.iter()
            .map(|x| x.message.clone())
            .collect::<Vec<_>>()
            .join(" | ")
    }

    const FULL: &str = "---\ntitle: T\ntype: source\nstatus: active\nsummary: S\nlast_updated: \"2026-08-25\"\ntags:\n  - team-meeting\n---\n\nbody\n";

    #[test]
    fn a_compliant_new_page_has_nothing_to_report() {
        let f = check("sources/a", FULL, &roots(), true);
        assert!(f.is_empty(), "unexpected findings: {}", messages(&f));
    }

    #[test]
    fn singular_and_plural_of_one_facet_is_refused_on_a_new_page() {
        let content = FULL.replace("  - team-meeting\n", "  - source\n  - sources\n");
        let f = check("sources/a", &content, &roots(), true);
        assert_eq!(f.len(), 1, "{}", messages(&f));
        assert_eq!(f[0].severity, Severity::Error);
        assert!(f[0].message.contains("`source` and `sources`"));
    }

    #[test]
    fn the_same_violation_only_warns_on_an_existing_page() {
        // The corpus predates the rule; blocking every edit would force a
        // migration before anyone could fix anything else.
        let content = FULL.replace("  - team-meeting\n", "  - source\n  - sources\n");
        let f = check("sources/a", &content, &roots(), false);
        assert_eq!(f[0].severity, Severity::Warning);
    }

    #[test]
    fn a_type_contradicting_the_location_is_reported() {
        let content = FULL.replace("type: source", "type: doc");
        let f = check("sources/a", &content, &roots(), true);
        assert!(
            f.iter().any(|x| x.message.contains("type: doc")),
            "{}",
            messages(&f)
        );
        assert!(
            f.iter().any(|x| x.message.contains("omit")),
            "the message should offer omission as a fix: {}",
            messages(&f)
        );
    }

    #[test]
    fn omitting_type_entirely_is_accepted() {
        let content = FULL.replace("type: source\n", "");
        let f = check("sources/a", &content, &roots(), true);
        assert!(f.is_empty(), "omission should be fine: {}", messages(&f));
    }

    #[test]
    fn section_pages_keep_their_structural_type() {
        let content = FULL.replace("type: source", "type: section");
        let f = check("sources/a", &content, &roots(), true);
        assert!(f.is_empty(), "{}", messages(&f));
    }

    #[test]
    fn preserved_sources_are_not_held_to_compiled_page_metadata() {
        // Demanding a summary of a raw file would mean editing the original.
        let f = check(
            "raw/meetings/m",
            "---\ntitle: T\n---\n\nbody\n",
            &roots(),
            true,
        );
        assert!(f.is_empty(), "{}", messages(&f));
    }

    #[test]
    fn a_compiled_page_missing_baseline_fields_is_reported() {
        let f = check("sources/a", "---\ntitle: T\n---\n\nbody\n", &roots(), true);
        for field in ["status", "summary", "last_updated", "tags"] {
            assert!(
                f.iter().any(|x| x.message.contains(field)),
                "{field} not reported: {}",
                messages(&f)
            );
        }
    }

    #[test]
    fn alias_wikilinks_are_refused() {
        let content = format!("{FULL}\nsee [[topics/t-a|the topic]] here\n");
        let f = check("sources/a", &content, &roots(), true);
        assert!(
            f.iter().any(|x| x.message.contains("alias syntax")),
            "{}",
            messages(&f)
        );
    }

    #[test]
    fn unprefixed_wikilinks_are_refused() {
        let content = format!("{FULL}\nsee [[t-a]] here\n");
        let f = check("sources/a", &content, &roots(), true);
        assert!(
            f.iter().any(|x| x.message.contains("collection prefix")),
            "{}",
            messages(&f)
        );
    }

    #[test]
    fn prefixed_wikilinks_and_footnote_markers_pass() {
        let content = format!("{FULL}\n[[topics/t-a]] and [[1]](https://example.com)\n");
        let f = check("sources/a", &content, &roots(), true);
        assert!(f.is_empty(), "{}", messages(&f));
    }

    #[test]
    fn uppercase_tags_only_warn_even_on_a_new_page() {
        // A proper noun in a tag is a judgement call, not a defect.
        let content = FULL.replace("  - team-meeting\n", "  - Team_Meeting\n");
        let f = check("sources/a", &content, &roots(), true);
        assert_eq!(f.len(), 1, "{}", messages(&f));
        assert_eq!(f[0].severity, Severity::Warning);
        assert!(
            f[0].message.contains("team-meeting"),
            "suggestion missing: {}",
            f[0].message
        );
    }

    #[test]
    fn a_wiki_without_type_mapping_skips_the_type_check() {
        let plain = ContentRoots::single("/repo/wiki");
        let content = FULL.replace("type: source", "type: anything");
        let f = check("sources/a", &content, &plain, true);
        assert!(
            !f.iter().any(|x| x.message.contains("lives under")),
            "{}",
            messages(&f)
        );
    }
}
