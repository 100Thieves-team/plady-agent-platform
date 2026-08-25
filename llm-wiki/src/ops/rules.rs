//! Agent rules — the schema layer of the three-layer model, made reachable.
//!
//! A wiki's operating rules live in a Markdown file at the repository root
//! (`AGENTS.md` by default). That file sits outside the wiki root, so before
//! this module it could not be read through any tool: an agent had to already
//! know the conventions in order to follow them, and the one that did not
//! quietly invented its own.
//!
//! Two paths make it reachable:
//!
//! * `instructions_for` builds the short contract handed to every client in the
//!   MCP handshake, so the rules arrive before the first tool call rather than
//!   depending on the agent choosing to look them up.
//! * [`rules`] returns the full document, or one section of it, on demand.
//!
//! The handshake text is delimited in the rules file itself:
//!
//! ```markdown
//! <!-- mcp-instructions:start -->
//! …the contract every agent must have in context…
//! <!-- mcp-instructions:end -->
//! ```
//!
//! Keeping it inside the rules file means there is one source of truth to edit
//! and no Rust rebuild when the team changes a convention. Without the markers
//! a leading excerpt is used instead, so an un-marked wiki still gets something
//! useful.

use anyhow::{Result, bail};

use crate::engine::EngineState;

/// Marker opening the section injected into the MCP handshake.
const START_MARKER: &str = "<!-- mcp-instructions:start -->";
/// Marker closing the section injected into the MCP handshake.
const END_MARKER: &str = "<!-- mcp-instructions:end -->";

/// Upper bound on handshake instructions. Everything past this is the client's
/// context budget spent on text it did not ask for; the full document is one
/// `wiki_rules` call away.
const MAX_INSTRUCTIONS: usize = 4096;

/// Read the rules document of `wiki_name`.
///
/// Returns `None` when the wiki declares no rules file or the file is missing —
/// a wiki without written conventions is unusual but not an error.
pub fn rules_text(engine: &EngineState, wiki_name: &str) -> Option<String> {
    let space = engine.space(wiki_name).ok()?;
    let wiki_cfg = crate::config::load_wiki(&space.repo_root).ok()?;
    let name = wiki_cfg.rules_file.trim();
    if name.is_empty() {
        return None;
    }
    // The rules file is named relative to the repo root and must stay there:
    // it is configuration, not content an agent can redirect.
    if name.contains("..") || name.starts_with('/') {
        tracing::warn!(wiki = %wiki_name, rules_file = %name, "ignoring rules_file outside repo root");
        return None;
    }
    std::fs::read_to_string(space.repo_root.join(name)).ok()
}

/// Extract the handshake contract from a rules document.
///
/// Prefers the explicitly marked region; falls back to a leading excerpt cut at
/// a heading boundary so the client never receives half a sentence.
pub fn extract_instructions(text: &str) -> String {
    if let Some(start) = text.find(START_MARKER) {
        let after = &text[start + START_MARKER.len()..];
        let body = match after.find(END_MARKER) {
            Some(end) => &after[..end],
            None => after,
        };
        return truncate_at_boundary(body.trim(), MAX_INSTRUCTIONS);
    }
    truncate_at_boundary(text.trim(), MAX_INSTRUCTIONS)
}

/// Trim to `max` bytes, preferring to end at the last heading that fits so the
/// excerpt reads as whole sections rather than a severed paragraph.
fn truncate_at_boundary(text: &str, max: usize) -> String {
    if text.len() <= max {
        return text.to_string();
    }
    let mut cut = max;
    while cut > 0 && !text.is_char_boundary(cut) {
        cut -= 1;
    }
    let head = &text[..cut];
    let trimmed = match head.rfind("\n#") {
        Some(pos) if pos > max / 2 => &head[..pos],
        _ => head,
    };
    format!(
        "{}\n\n…truncated — call `wiki_rules` for the full document.",
        trimmed.trim_end()
    )
}

/// Build the instructions string sent in the MCP handshake for `wiki_name`.
///
/// The returned text names the tool that returns the rest, so a client that
/// wants the complete document knows where to look without being told twice.
pub fn instructions_for(engine: &EngineState, wiki_name: &str) -> Option<String> {
    let text = rules_text(engine, wiki_name)?;
    let contract = extract_instructions(&text);
    if contract.is_empty() {
        return None;
    }
    Some(format!(
        "Operating rules for the `{wiki_name}` wiki. These govern how pages are \
         written and ingested — follow them rather than inferring conventions \
         from existing pages. Call `wiki_rules` for the full document.\n\n{contract}"
    ))
}

/// Return the wiki's rules document, or one section of it.
///
/// `section` matches a Markdown heading case-insensitively by substring, so
/// `"ingest"` finds `## MCP ingest workflow`. The returned slice runs to the
/// next heading of the same or higher level.
pub fn rules(engine: &EngineState, wiki_name: &str, section: Option<&str>) -> Result<String> {
    let Some(text) = rules_text(engine, wiki_name) else {
        bail!(
            "wiki \"{wiki_name}\" has no rules file (set `rules_file` in wiki.toml; default is AGENTS.md)"
        );
    };
    let Some(section) = section.map(str::trim).filter(|s| !s.is_empty()) else {
        return Ok(text);
    };
    match extract_section(&text, section) {
        Some(found) => Ok(found),
        None => {
            let headings = list_headings(&text).join("\n  ");
            bail!("no section matching \"{section}\". Available:\n  {headings}")
        }
    }
}

/// Return the heading whose text contains `needle`, plus its body.
fn extract_section(text: &str, needle: &str) -> Option<String> {
    let needle = needle.to_lowercase();
    let lines: Vec<&str> = text.lines().collect();
    let start = lines
        .iter()
        .position(|line| heading_level(line).is_some() && line.to_lowercase().contains(&needle))?;
    let level = heading_level(lines[start])?;
    let end = lines[start + 1..]
        .iter()
        .position(|line| heading_level(line).is_some_and(|l| l <= level))
        .map(|offset| start + 1 + offset)
        .unwrap_or(lines.len());
    Some(lines[start..end].join("\n").trim_end().to_string())
}

/// Heading level of a Markdown ATX heading line, if it is one.
fn heading_level(line: &str) -> Option<usize> {
    let hashes = line.chars().take_while(|c| *c == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    line[hashes..].starts_with(' ').then_some(hashes)
}

/// All headings in the document, for the "no such section" error.
fn list_headings(text: &str) -> Vec<String> {
    text.lines()
        .filter(|line| heading_level(line).is_some())
        .map(|line| line.trim().to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    const DOC: &str = "\
# Agent rules

Intro paragraph.

<!-- mcp-instructions:start -->
Raw is immutable. One source touches several pages.
<!-- mcp-instructions:end -->

## MCP ingest workflow

1. Preserve the original.
2. Compile.

### Nested detail

Deeper text.

## Migration safety rules

Do not mass-delete.
";

    #[test]
    fn marked_region_wins_over_leading_text() {
        let out = extract_instructions(DOC);
        assert_eq!(out, "Raw is immutable. One source touches several pages.");
    }

    #[test]
    fn falls_back_to_leading_text_without_markers() {
        let out = extract_instructions("# Rules\n\nBe careful.\n");
        assert_eq!(out, "# Rules\n\nBe careful.");
    }

    #[test]
    fn long_documents_are_truncated_with_a_pointer() {
        let long = format!("# A\n\n{}\n\n# B\n\n{}", "x".repeat(3000), "y".repeat(3000));
        let out = extract_instructions(&long);
        assert!(out.len() < long.len());
        assert!(
            out.contains("wiki_rules"),
            "truncation must say where the rest is"
        );
    }

    #[test]
    fn truncation_respects_char_boundaries() {
        let long = "한글".repeat(4000);
        let out = truncate_at_boundary(&long, MAX_INSTRUCTIONS);
        assert!(out.starts_with("한글"));
    }

    #[test]
    fn section_lookup_is_substring_and_case_insensitive() {
        let out = extract_section(DOC, "ingest").unwrap();
        assert!(out.starts_with("## MCP ingest workflow"));
        assert!(out.contains("1. Preserve the original."));
    }

    #[test]
    fn section_includes_nested_headings_but_stops_at_a_sibling() {
        let out = extract_section(DOC, "ingest").unwrap();
        assert!(out.contains("### Nested detail"), "nested heading dropped");
        assert!(
            !out.contains("Migration safety"),
            "section ran past its sibling"
        );
    }

    #[test]
    fn unknown_section_returns_none() {
        assert!(extract_section(DOC, "nonexistent").is_none());
    }

    #[test]
    fn heading_level_rejects_non_headings() {
        assert_eq!(heading_level("## Real"), Some(2));
        assert_eq!(heading_level("#NoSpace"), None);
        assert_eq!(heading_level("plain text"), None);
        assert_eq!(heading_level("####### too deep"), None);
    }
}
