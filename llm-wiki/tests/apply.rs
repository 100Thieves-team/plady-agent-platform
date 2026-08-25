//! Ingest as one transaction.
//!
//! The first test is the incident that motivated all of this: a Slack meeting
//! note ingested as a lone source page, with no preserved original and no topic
//! touched, reported as success.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops::{self, ApplyMode, ApplyRequest, Change};

const RAW: &str =
    "---\ntitle: \"Scrum 8-24\"\n---\n\n면접 준비 기능 방향 재정의. 배포 파이프라인 개선.\n";
const TOPIC: &str = "---\ntitle: \"면접 서비스 방향성\"\n---\n\n기존 내용.\n";
const PERSON: &str = "---\ntitle: \"배준서\"\n---\n\n기존 내용.\n";

fn source_page(raw: &str, topics: &[&str]) -> String {
    let list: String = topics
        .iter()
        .map(|t| format!("  - \"{t}\"\n"))
        .collect::<String>();
    let topics_block = if list.is_empty() {
        String::new()
    } else {
        format!("topics:\n{list}")
    };
    format!(
        "---\ntitle: \"스크럼 8-24 요약\"\ntype: source\nstatus: active\nsummary: \"S\"\n\
         last_updated: \"2026-08-24\"\ntags:\n  - team-meeting\n\
         raw_source_path: \"{raw}\"\n{topics_block}---\n\n요약 본문.\n"
    )
}

fn setup(dir: &Path) -> (PathBuf, PathBuf) {
    let config_path = dir.join("state").join("config.toml");
    let wiki_path = dir.join("test");
    llm_wiki::spaces::create(&wiki_path, "test", None, false, true, &config_path, None).unwrap();

    let wiki_toml = wiki_path.join("wiki.toml");
    let mut cfg = fs::read_to_string(&wiki_toml).unwrap_or_default();
    cfg.push_str(
        "\nexternal_roots = [\"raw\"]\nlock_timeout_secs = 2\n\n\
         [type_by_prefix]\n\
         sources = \"source\"\n\
         topics = \"topic\"\n\
         people = \"person\"\n\
         policy = \"policy\"\n\
         raw = \"raw\"\n",
    );
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    fs::create_dir_all(wiki_root.join("topics")).unwrap();
    fs::create_dir_all(wiki_root.join("people")).unwrap();
    fs::write(wiki_root.join("topics/t-면접-서비스-방향성.md"), TOPIC).unwrap();
    fs::write(wiki_root.join("people/p-배준서.md"), PERSON).unwrap();
    fs::create_dir_all(wiki_path.join("raw/meetings")).unwrap();

    llm_wiki::git::commit(&wiki_path, "seed").unwrap();
    (config_path, wiki_path.canonicalize().unwrap())
}

fn engine_for(config_path: &Path) -> WikiEngine {
    let m = WikiEngine::build(config_path).unwrap();
    m.rebuild_index("test").unwrap();
    m
}

fn req(mode: ApplyMode, changes: Vec<(&str, String)>) -> ApplyRequest {
    ApplyRequest {
        mode,
        changes: changes
            .into_iter()
            .map(|(path, content)| Change {
                path: path.to_string(),
                content,
            })
            .collect(),
        message: None,
        reason: None,
        expected_head: None,
        dry_run: false,
    }
}

// ── The incident ──────────────────────────────────────────────────────────────

#[test]
fn a_source_page_alone_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![(
            "sources/scrum-8-24",
            source_page("raw/meetings/scrum-8-24", &[]),
        )],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();

    assert!(
        err.contains("neither in this change set nor already preserved"),
        "the missing original should be the first thing reported: {err}"
    );
    assert!(
        !wiki_path.join("wiki/sources/scrum-8-24.md").exists(),
        "a rejected apply must leave nothing behind"
    );
}

#[test]
fn raw_plus_source_without_a_topic_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &[]),
            ),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();

    assert!(err.contains("incomplete ingest"), "unexpected error: {err}");
    assert!(err.contains("deferred"), "the escape hatch should be named");
    assert!(!wiki_path.join("raw/meetings/scrum-8-24.md").exists());
}

#[test]
fn a_complete_ingest_commits_every_layer_in_one_commit() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &["topics/t-면접-서비스-방향성"]),
            ),
            (
                "topics/t-면접-서비스-방향성",
                format!("{TOPIC}\n- [스크럼 8-24](sources/scrum-8-24)\n"),
            ),
            (
                "people/p-배준서",
                format!("{PERSON}\n- [스크럼 8-24](sources/scrum-8-24)\n"),
            ),
        ],
    );
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();

    assert_eq!(report.raw, ["raw/meetings/scrum-8-24"]);
    assert_eq!(report.sources, ["sources/scrum-8-24"]);
    assert_eq!(report.topics, ["topics/t-면접-서비스-방향성"]);
    assert_eq!(report.people, ["people/p-배준서"]);
    assert!(!report.commit.is_empty(), "nothing was committed");
    assert_eq!(report.written_count(), 4);

    // One commit, not four.
    let repo = git2::Repository::open(&wiki_path).unwrap();
    let head = repo.head().unwrap().peel_to_commit().unwrap();
    assert_eq!(head.id().to_string(), report.commit);
    let tree = head.tree().unwrap();
    for p in [
        "raw/meetings/scrum-8-24.md",
        "wiki/sources/scrum-8-24.md",
        "wiki/topics/t-면접-서비스-방향성.md",
        "wiki/people/p-배준서.md",
    ] {
        assert!(
            tree.get_path(Path::new(p)).is_ok(),
            "{p} missing from commit"
        );
    }
}

#[test]
fn the_commit_message_describes_the_actual_diff() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &[]),
            ),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nupdated\n")),
        ],
    );
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();

    assert!(report.message.contains("1 raw"), "{}", report.message);
    assert!(report.message.contains("1 source"), "{}", report.message);
    assert!(report.message.contains("1 topics"), "{}", report.message);
    assert!(
        !report.message.contains("+1 pages"),
        "the old misleading count is back: {}",
        report.message
    );
}

// ── Validation reads the diff, not the request ────────────────────────────────

#[test]
fn listing_a_topic_without_editing_it_does_not_satisfy_the_rule() {
    // The exact way an agent would work around a naive check: include the topic
    // in `changes` with its current content and call the ingest complete.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &[]),
            ),
            // Byte-identical to what is on disk.
            ("topics/t-면접-서비스-방향성", TOPIC.to_string()),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("incomplete ingest"),
        "an untouched topic passed as an update: {err}"
    );
}

#[test]
fn unchanged_pages_are_reported_but_not_committed() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &[]),
            ),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
            ("people/p-배준서", PERSON.to_string()), // identical
        ],
    );
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();
    assert_eq!(report.unchanged, ["people/p-배준서"]);
    assert!(report.people.is_empty());
}

// ── Modes ─────────────────────────────────────────────────────────────────────

#[test]
fn archive_mode_preserves_raw_without_demanding_a_topic() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Archive,
        vec![("raw/meetings/scrum-8-24", RAW.to_string())],
    );
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();
    assert_eq!(report.raw, ["raw/meetings/scrum-8-24"]);
    assert!(wiki_path.join("raw/meetings/scrum-8-24.md").is_file());
}

#[test]
fn archive_mode_cannot_smuggle_in_a_compiled_page() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Archive,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            (
                "sources/scrum-8-24",
                source_page("raw/meetings/scrum-8-24", &[]),
            ),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("not a way past its rules"),
        "archive became the escape hatch: {err}"
    );
}

#[test]
fn deferred_mode_needs_a_reason_and_records_it() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let changes = vec![
        ("raw/meetings/scrum-8-24", RAW.to_string()),
        (
            "sources/scrum-8-24",
            source_page("raw/meetings/scrum-8-24", &[]),
        ),
    ];

    let mut r = req(ApplyMode::Deferred, changes.clone());
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(err.contains("requires `reason`"), "unexpected error: {err}");

    r = req(ApplyMode::Deferred, changes);
    r.reason = Some("첫 ingest — 아직 해당 topic 없음".into());
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();
    assert!(
        report
            .warnings
            .iter()
            .any(|w| w.contains("needing integration")),
        "the gap should stay visible: {:?}",
        report.warnings
    );
}

// ── Safety ────────────────────────────────────────────────────────────────────

#[test]
fn an_mcp_response_envelope_is_refused_as_page_content() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Archive,
        vec![(
            "raw/meetings/scrum-8-24",
            r#"{"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"..."}]}}"#.to_string(),
        )],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(err.contains("response envelope"), "unexpected error: {err}");
}

#[test]
fn an_existing_raw_page_is_not_rewritten() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let first = req(
        ApplyMode::Archive,
        vec![("raw/meetings/scrum-8-24", RAW.to_string())],
    );
    ops::apply(&engine, &manager, "test", &first).unwrap();

    let second = req(
        ApplyMode::Archive,
        vec![(
            "raw/meetings/scrum-8-24",
            "---\ntitle: X\n---\n\n덮어쓰기.\n".to_string(),
        )],
    );
    let err = ops::apply(&engine, &manager, "test", &second)
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("preserved source material"),
        "unexpected: {err}"
    );
}

#[test]
fn a_stale_expected_head_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let mut r = req(
        ApplyMode::Archive,
        vec![("raw/meetings/scrum-8-24", RAW.to_string())],
    );
    r.expected_head = Some("0000000000000000000000000000000000000000".into());
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(err.contains("moved since"), "unexpected error: {err}");
}

#[test]
fn a_dry_run_validates_without_writing() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let mut r = req(
        ApplyMode::Archive,
        vec![("raw/meetings/scrum-8-24", RAW.to_string())],
    );
    r.dry_run = true;
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();

    assert!(report.dry_run);
    assert!(report.commit.is_empty());
    assert_eq!(report.raw, ["raw/meetings/scrum-8-24"]);
    assert!(!wiki_path.join("raw/meetings/scrum-8-24.md").exists());
}

#[test]
fn the_same_page_cannot_appear_twice() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Archive,
        vec![
            ("raw/meetings/scrum-8-24", RAW.to_string()),
            ("raw/meetings/scrum-8-24.md", RAW.to_string()),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(err.contains("appears twice"), "unexpected error: {err}");
}

// ── Plan ──────────────────────────────────────────────────────────────────────

#[test]
fn the_plan_surfaces_existing_topics_the_raw_text_points_at() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);

    {
        let engine = manager.state.read().unwrap();
        let r = req(
            ApplyMode::Archive,
            vec![("raw/meetings/scrum-8-24", RAW.to_string())],
        );
        ops::apply(&engine, &manager, "test", &r).unwrap();
    }

    let engine = manager.state.read().unwrap();
    let plan = ops::ingest_plan(&engine, "test", "raw/meetings/scrum-8-24").unwrap();

    assert!(plan.raw_exists);
    assert!(!plan.head.is_empty(), "plan must return a HEAD to pin to");
    assert!(
        plan.required.iter().any(|r| r.contains("topic or person")),
        "the plan must state the multi-page requirement: {:?}",
        plan.required
    );
    assert!(
        plan.candidates.iter().any(|c| c.slug.contains("면접")),
        "the topic named in the raw text was not surfaced: {:?}",
        plan.candidates
    );
}

#[test]
fn the_plan_reports_a_source_that_already_covers_this_raw_page() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);

    {
        let engine = manager.state.read().unwrap();
        let r = req(
            ApplyMode::Knowledge,
            vec![
                ("raw/meetings/scrum-8-24", RAW.to_string()),
                (
                    "sources/scrum-8-24",
                    source_page("raw/meetings/scrum-8-24", &[]),
                ),
                ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
            ],
        );
        ops::apply(&engine, &manager, "test", &r).unwrap();
    }

    let engine = manager.state.read().unwrap();
    let plan = ops::ingest_plan(&engine, "test", "raw/meetings/scrum-8-24").unwrap();
    assert_eq!(
        plan.existing_sources,
        ["sources/scrum-8-24"],
        "a duplicate ingest should be visible before it happens"
    );
}

// ── Conventions ───────────────────────────────────────────────────────────────

/// A source page with the tag duplication the 8/25 ingest actually produced.
fn source_with_tags(raw: &str, tags: &[&str]) -> String {
    let list: String = tags.iter().map(|t| format!("  - {t}\n")).collect();
    format!(
        "---\ntitle: \"요약\"\ntype: source\nstatus: active\nsummary: \"S\"\nlast_updated: \"2026-08-25\"\nraw_source_path: \"{raw}\"\ntags:\n{list}---\n\n본문.\n"
    )
}

#[test]
fn a_new_page_tagged_with_both_singular_and_plural_is_refused() {
    // This is what the first real ingest through wiki_apply wrote: `source`
    // and `sources` together, which AGENTS.md forbids in as many words and
    // nothing caught.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-25", RAW.to_string()),
            (
                "sources/scrum-8-25",
                source_with_tags(
                    "raw/meetings/scrum-8-25",
                    &["source", "sources", "team-meeting"],
                ),
            ),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();
    assert!(
        err.contains("`source` and `sources`"),
        "the duplicate facet was not caught: {err}"
    );
    assert!(
        err.contains("conventions"),
        "the error should say what kind of rule this is: {err}"
    );
}

#[test]
fn the_same_violation_on_an_existing_page_only_warns() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());

    // Seed a page that already carries the violation.
    let bad = source_with_tags("raw/meetings/scrum-8-25", &["source", "sources"]);
    fs::create_dir_all(wiki_path.join("wiki/sources")).unwrap();
    fs::write(wiki_path.join("wiki/sources/scrum-8-25.md"), &bad).unwrap();
    fs::write(wiki_path.join("raw/meetings/scrum-8-25.md"), RAW).unwrap();
    llm_wiki::git::commit(&wiki_path, "seed existing violation").unwrap();

    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("sources/scrum-8-25", format!("{bad}\n추가된 내용.\n")),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
        ],
    );
    let report = ops::apply(&engine, &manager, "test", &r)
        .expect("an existing page's inherited debt must not block the edit");
    assert!(
        report
            .warnings
            .iter()
            .any(|w| w.contains("`source` and `sources`")),
        "the debt should still be visible: {:?}",
        report.warnings
    );
}

#[test]
fn every_convention_violation_is_reported_at_once() {
    // One finding per round-trip is how an agent learns to stop calling the tool.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-25", RAW.to_string()),
            (
                "sources/scrum-8-25",
                "---\ntitle: \"요약\"\ntype: doc\nraw_source_path: \"raw/meetings/scrum-8-25\"\ntags:\n  - source\n  - sources\n---\n\n[[t-면접-서비스-방향성]] 참조.\n".to_string(),
            ),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
        ],
    );
    let err = ops::apply(&engine, &manager, "test", &r)
        .unwrap_err()
        .to_string();

    for expected in [
        "`source` and `sources`", // duplicate facet
        "type: doc",              // type contradicts location
        "collection prefix",      // unprefixed wikilink
        "status",                 // missing baseline field
    ] {
        assert!(
            err.contains(expected),
            "{expected} not reported together: {err}"
        );
    }
}

#[test]
fn a_conventional_new_page_passes() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let r = req(
        ApplyMode::Knowledge,
        vec![
            ("raw/meetings/scrum-8-25", RAW.to_string()),
            (
                "sources/scrum-8-25",
                source_with_tags("raw/meetings/scrum-8-25", &["team-meeting"]),
            ),
            ("topics/t-면접-서비스-방향성", format!("{TOPIC}\nnew\n")),
        ],
    );
    let report = ops::apply(&engine, &manager, "test", &r).unwrap();
    assert!(!report.commit.is_empty());
    assert!(
        !report
            .warnings
            .iter()
            .any(|w| w.contains("sources/scrum-8-25")),
        "the new page should have nothing reported: {:?}",
        report.warnings
    );
}
