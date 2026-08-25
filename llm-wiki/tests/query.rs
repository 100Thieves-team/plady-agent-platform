//! Query end to end: assemble context, then keep the answer.

use std::fs;
use std::path::{Path, PathBuf};

use llm_wiki::engine::WikiEngine;
use llm_wiki::ops;

fn page(title: &str, body: &str) -> String {
    format!(
        "---\ntitle: \"{title}\"\nstatus: active\nsummary: \"요약\"\nlast_updated: \"2026-08-25\"\ntags:\n  - x\n---\n\n{body}\n"
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
         answers = \"answer\"\n\
         raw = \"raw\"\n",
    );
    fs::write(&wiki_toml, cfg).unwrap();

    let wiki_root = wiki_path.join("wiki");
    fs::create_dir_all(wiki_root.join("topics")).unwrap();
    fs::create_dir_all(wiki_root.join("sources")).unwrap();
    fs::write(
        wiki_root.join("topics/t-배포.md"),
        page(
            "배포 파이프라인",
            &"배포 파이프라인은 GHA 에서 ECR 로 이미지를 밀고 SSM 으로 EC2 에 적용한다. "
                .repeat(30),
        ),
    )
    .unwrap();
    fs::write(
        wiki_root.join("sources/s-배포회의.md"),
        page("배포 회의", &"배포 절차 개선을 논의했다. ".repeat(30)),
    )
    .unwrap();
    fs::write(
        wiki_root.join("topics/t-면접.md"),
        page("면접 서비스", "면접 준비 기능 이야기."),
    )
    .unwrap();
    llm_wiki::git::commit(&wiki_path, "seed").unwrap();
    (config_path, wiki_path.canonicalize().unwrap())
}

fn engine_for(config_path: &Path) -> WikiEngine {
    let m = WikiEngine::build(config_path).unwrap();
    m.rebuild_index("test").unwrap();
    m
}

// ── Context ───────────────────────────────────────────────────────────────────

#[test]
fn context_returns_page_bodies_not_just_slugs() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let bundle = ops::context(
        &engine,
        "test",
        "배포 파이프라인은 어떻게 동작하나?",
        None,
        None,
    )
    .unwrap();
    assert!(!bundle.pages.is_empty(), "nothing assembled");
    assert_eq!(bundle.pages[0].slug, "topics/t-배포");
    assert!(
        bundle.pages[0].body.contains("ECR"),
        "the point of this call is the body, not the slug"
    );
}

#[test]
fn frontmatter_is_stripped_so_the_budget_buys_prose() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let bundle = ops::context(&engine, "test", "배포", None, None).unwrap();
    assert!(
        !bundle.pages[0].body.contains("last_updated"),
        "metadata spent budget that belongs to content: {}",
        &bundle.pages[0].body[..80.min(bundle.pages[0].body.len())]
    );
}

#[test]
fn the_budget_is_respected_and_what_it_cost_is_reported() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let bundle = ops::context(&engine, "test", "배포", Some(700), None).unwrap();
    assert!(
        bundle.used_chars <= 900,
        "over budget: {}",
        bundle.used_chars
    );
    assert!(
        !bundle.omitted.is_empty(),
        "pages that did not fit should be named, not silently dropped"
    );
    assert!(
        bundle.notes.iter().any(|n| n.contains("budget")),
        "the omission should be explained: {:?}",
        bundle.notes
    );
}

#[test]
fn a_type_filter_narrows_the_bundle() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let bundle = ops::context(&engine, "test", "배포", None, Some("source")).unwrap();
    assert!(
        bundle.pages.iter().all(|p| p.kind == "source"),
        "{:?}",
        bundle.pages.iter().map(|p| &p.kind).collect::<Vec<_>>()
    );
}

#[test]
fn a_question_matching_nothing_says_where_to_look_instead() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let bundle = ops::context(&engine, "test", "zzzznonexistentzzzz", None, None).unwrap();
    assert!(bundle.pages.is_empty());
    assert!(
        bundle.notes.iter().any(|n| n.contains("wiki_catalog")),
        "an empty answer should point somewhere: {:?}",
        bundle.notes
    );
}

#[test]
fn an_empty_question_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    assert!(ops::context(&engine, "test", "   ", None, None).is_err());
}

// ── Saved answers ─────────────────────────────────────────────────────────────

#[test]
fn an_answer_is_saved_as_a_page_citing_its_sources() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, wiki_path) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let saved = ops::save_answer(
        &engine,
        &manager,
        "test",
        "배포는 어떻게 동작하나?",
        "GHA 가 ECR 에 밀고 SSM 이 EC2 에 적용한다.",
        &["topics/t-배포".to_string()],
        None,
    )
    .unwrap();

    assert!(saved.slug.starts_with("answers/"));
    assert!(!saved.commit.is_empty());
    let written = fs::read_to_string(wiki_path.join(format!("wiki/{}.md", saved.slug))).unwrap();
    assert!(written.contains("type: answer"));
    assert!(written.contains("[topics/t-배포](topics/t-배포)"));
    assert!(written.contains("GHA 가 ECR 에 밀고"));
}

#[test]
fn an_answer_citing_nothing_is_refused() {
    // A conclusion with no evidence cannot be checked later, and a wiki of
    // those is worse than no wiki.
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let err = ops::save_answer(&engine, &manager, "test", "질문?", "답변.", &[], None)
        .unwrap_err()
        .to_string();
    assert!(err.contains("cannot be checked against evidence"), "{err}");
}

#[test]
fn an_answer_citing_a_page_that_does_not_exist_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let err = ops::save_answer(
        &engine,
        &manager,
        "test",
        "질문?",
        "답변.",
        &["topics/t-지어낸것".to_string()],
        None,
    )
    .unwrap_err()
    .to_string();
    assert!(err.contains("is not a page in this wiki"), "{err}");
}

#[test]
fn re_asking_the_same_question_updates_one_page() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);
    let engine = manager.state.read().unwrap();

    let first = ops::save_answer(
        &engine,
        &manager,
        "test",
        "배포는 어떻게 동작하나?",
        "첫 답변.",
        &["topics/t-배포".to_string()],
        None,
    )
    .unwrap();
    let second = ops::save_answer(
        &engine,
        &manager,
        "test",
        "배포는 어떻게 동작하나?",
        "고쳐진 답변.",
        &["topics/t-배포".to_string()],
        None,
    )
    .unwrap();

    assert_eq!(first.slug, second.slug, "near-duplicates accumulated");
    assert!(
        second
            .warnings
            .iter()
            .any(|w| w.contains("already existed")),
        "replacing a page should be visible: {:?}",
        second.warnings
    );
}

#[test]
fn a_saved_answer_is_findable_afterwards() {
    let dir = tempfile::tempdir().unwrap();
    let (config_path, _) = setup(dir.path());
    let manager = engine_for(&config_path);

    {
        let engine = manager.state.read().unwrap();
        ops::save_answer(
            &engine,
            &manager,
            "test",
            "배포는 어떻게 동작하나?",
            "GHA 에서 ECR 로 밀고 SSM 으로 적용한다.",
            &["topics/t-배포".to_string()],
            None,
        )
        .unwrap();
    }

    // Reachable through the incremental index update alone — no rebuild.
    let engine = manager.state.read().unwrap();
    let bundle = ops::context(&engine, "test", "배포", None, Some("answer")).unwrap();
    assert!(
        bundle.pages.iter().any(|p| p.slug.starts_with("answers/")),
        "a saved answer that cannot be found again has not compounded anything"
    );
}
