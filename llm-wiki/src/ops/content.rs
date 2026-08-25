use std::path::{Path, PathBuf};

use anyhow::{Result, bail};
use serde::Serialize;
use tantivy::{
    Searcher, Term,
    query::TermQuery,
    schema::{IndexRecordOption, Value},
};

use crate::config;
use crate::content_roots::ContentRoots;
use crate::engine::EngineState;
use crate::git;
use crate::index_schema::IndexSchema;
use crate::markdown;
use crate::repo_lock::RepoLock;
use crate::slug::{
    ReadTarget, Slug, WikiUri, WriteTarget, resolve_entry_and_rel, resolve_read_target,
    resolve_write_target,
};

/// A page that links to a given target — slug and display title.
#[derive(Debug, Clone, Serialize)]
pub struct BacklinkRef {
    /// Slug of the linking page.
    pub slug: String,
    /// Title of the linking page.
    pub title: String,
}

/// Query the index for all pages that contain a link to `target_slug`.
pub fn backlinks_query(
    searcher: &Searcher,
    is: &IndexSchema,
    target_slug: &str,
) -> Result<Vec<BacklinkRef>> {
    let f_body_links = is.field("body_links");
    let f_slug = is.field("slug");
    let f_title = is.field("title");

    let term = Term::from_field_text(f_body_links, target_slug);
    let query = TermQuery::new(term, IndexRecordOption::Basic);

    let doc_addrs = searcher.search(&query, &tantivy::collector::DocSetCollector)?;

    let mut refs: Vec<BacklinkRef> = doc_addrs
        .into_iter()
        .filter_map(|addr| {
            let doc: tantivy::TantivyDocument = searcher.doc(addr).ok()?;
            let slug = doc
                .get_first(f_slug)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let title = doc
                .get_first(f_title)
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            if slug.is_empty() {
                None
            } else {
                Some(BacklinkRef { slug, title })
            }
        })
        .collect();

    refs.sort_by(|a, b| a.slug.cmp(&b.slug));
    Ok(refs)
}

/// Return all pages linking to `target_slug` in the named wiki.
pub fn backlinks_for(
    engine: &EngineState,
    wiki_name: &str,
    target_slug: &str,
) -> Result<Vec<BacklinkRef>> {
    let space = engine.space(wiki_name)?;
    let searcher = space.index_manager.searcher()?;
    backlinks_query(&searcher, &space.index_schema, target_slug)
}

/// Result of a content read — page text, asset list, or binary asset.
#[derive(Debug)]
pub enum ContentReadResult {
    /// Page markdown content (possibly with frontmatter stripped).
    Page(String),
    /// List of co-located asset filenames.
    Assets(Vec<String>),
    /// The resolved target is a binary file — read it directly from disk.
    Binary,
}

/// Read a wiki page, a co-located asset, or list a page's assets.
///
/// Asset reads are wider than asset writes: any non-.md extension resolves to a
/// file read (matching the long-standing `resolve_read_target` rule), while
/// writes are limited to text formats. Path-traversal defenses are shared.
pub fn content_read(
    engine: &EngineState,
    uri: &str,
    wiki_flag: Option<&str>,
    no_frontmatter: bool,
    list_assets: bool,
) -> Result<ContentReadResult> {
    // Entry resolution is split from path validation so extension-bearing asset
    // paths survive to resolve_read_target instead of being rejected up front.
    let (entry, rel) = resolve_entry_and_rel(uri, wiki_flag, &engine.config)?;
    let roots = engine.space(&entry.name)?.roots.clone();

    if list_assets {
        // Unchanged: asset listing keys off the parent (extensionless) slug
        let slug = Slug::try_from(rel.as_str())?;
        let assets = markdown::list_assets(&slug, &roots)?;
        return Ok(ContentReadResult::Assets(assets));
    }

    // A read for `index.md` or `log.md` is an agent looking for the catalogue or
    // the timeline by the names this model gives them. "Page not found" is
    // correct and useless; the tool that answers costs one line to name.
    let target =
        resolve_read_target(&rel, &roots).map_err(|e| {
            match super::suggestion_for_missing(&rel) {
                Some(hint) => anyhow::anyhow!("{e} — {hint}"),
                None => e,
            }
        })?;

    match target {
        ReadTarget::Page(_) => {
            let slug = Slug::try_from(rel.as_str())?;
            let wiki_cfg = config::load_wiki(&PathBuf::from(&entry.path)).unwrap_or_default();
            let resolved = config::resolve(&engine.config, &wiki_cfg);
            let strip = no_frontmatter || resolved.read.no_frontmatter;
            let content = markdown::read_page(&slug, &roots, strip)?;
            Ok(ContentReadResult::Page(content))
        }
        ReadTarget::Asset(parent_slug, filename) => {
            let parent = Slug::try_from(parent_slug.as_str())?;
            let bytes = markdown::read_asset(&parent, &filename, &roots)?;
            match String::from_utf8(bytes) {
                Ok(text) => Ok(ContentReadResult::Page(text)),
                Err(_) => Ok(ContentReadResult::Binary),
            }
        }
    }
}

/// Result of a content write operation.
#[derive(Debug)]
pub struct WriteResult {
    /// Number of bytes written to disk.
    pub bytes_written: usize,
    /// Absolute path of the written file.
    pub path: PathBuf,
    /// True when the write targeted a co-located asset rather than a page.
    pub asset: bool,
}

/// Reject an overwrite of preserved source material.
///
/// Files in an external root (`raw/`) are the wiki's evidence base: agents read
/// them and compile from them, but rewriting one destroys the record a compiled
/// page was derived from. Creating a new file there is allowed — only replacing
/// an existing one is refused, and the message points at the two legitimate
/// alternatives (an addendum, or an edit to the compiled page).
fn guard_external_overwrite(
    roots: &ContentRoots,
    slug: &str,
    existing: Option<PathBuf>,
) -> Result<()> {
    let Some(root) = roots.external_prefix(slug) else {
        return Ok(());
    };
    if let Some(path) = existing {
        bail!(
            "`{root}/` holds preserved source material and is not rewritten: {} already exists. \
             Add a new file alongside it as an addendum, or compile the correction into a \
             `wiki/` page instead.",
            path.display()
        );
    }
    Ok(())
}

/// Write content to a wiki page or co-located text asset.
///
/// Extensionless slugs are written as pages (unchanged semantics). Paths whose
/// last segment carries an allowed text extension (yaml/yml/json/txt/csv) are
/// written as assets — the write-side mirror of the asset fallback in
/// `resolve_read_target`. Asset writes skip frontmatter parsing and lint.
pub fn content_write(
    engine: &EngineState,
    uri: &str,
    wiki_flag: Option<&str>,
    content: &str,
) -> Result<WriteResult> {
    match resolve_write_target(uri, wiki_flag, &engine.config)? {
        WriteTarget::Page(entry, slug) => {
            let space = engine.space(&entry.name)?;
            let _lock = RepoLock::for_space(space, "mcp:content_write")?;
            let roots = space.roots.clone();
            guard_external_overwrite(&roots, slug.as_str(), roots.resolve(&slug).ok())?;
            let path = markdown::write_page(slug.as_str(), content, &roots)?;
            Ok(WriteResult {
                bytes_written: content.len(),
                path,
                asset: false,
            })
        }
        WriteTarget::Asset(entry, parent, filename) => {
            let space = engine.space(&entry.name)?;
            let _lock = RepoLock::for_space(space, "mcp:content_write")?;
            let roots = space.roots.clone();
            let dir = roots.base_for(parent.as_str()).join(parent.as_str());
            let existing = dir.join(&filename);
            guard_external_overwrite(
                &roots,
                parent.as_str(),
                existing.is_file().then_some(existing),
            )?;
            std::fs::create_dir_all(&dir)?;
            let path = dir.join(&filename);
            std::fs::write(&path, content)?;
            Ok(WriteResult {
                bytes_written: content.len(),
                path,
                asset: true,
            })
        }
    }
}

/// Result of creating a new wiki page or section.
pub struct ContentNewResult {
    /// `wiki://` URI for the created page.
    pub uri: String,
    /// Slug of the created page.
    pub slug: String,
    /// Absolute filesystem path of the created file.
    pub path: PathBuf,
    /// Absolute path to the wiki root directory.
    pub wiki_root: PathBuf,
    /// True if the page was created as a bundle (folder + index.md).
    pub bundle: bool,
}

/// Create a new wiki page or section with scaffolded frontmatter.
pub fn content_new(
    engine: &EngineState,
    uri: &str,
    wiki_flag: Option<&str>,
    section: bool,
    bundle: bool,
    name: Option<&str>,
    type_: Option<&str>,
) -> Result<ContentNewResult> {
    let (entry, slug) = WikiUri::resolve(uri, wiki_flag, &engine.config)?;
    let repo_root = PathBuf::from(&entry.path);
    let space = engine.space(&entry.name)?;
    let _lock = RepoLock::for_space(space, "mcp:content_new")?;
    let roots = space.roots.clone();
    let wiki_root = space.wiki_root.clone();

    let type_name = if section {
        "section"
    } else {
        type_.unwrap_or("page")
    };
    let body_template = resolve_body_template(&repo_root, type_name);

    let path = if section {
        markdown::create_section(&slug, &roots, body_template.as_deref())?
    } else {
        markdown::create_page(&slug, bundle, &roots, name, type_, body_template.as_deref())?
    };

    Ok(ContentNewResult {
        uri: format!("wiki://{}/{slug}", entry.name),
        slug: slug.as_str().to_string(),
        path,
        wiki_root,
        bundle,
    })
}

/// Resolve a body template for a type.
/// 1. `schemas/<type>.md` in the wiki repo
/// 2. Embedded default template
/// 3. None
fn resolve_body_template(repo_root: &Path, type_name: &str) -> Option<String> {
    let template_path = repo_root.join("schemas").join(format!("{type_name}.md"));
    if template_path.is_file() {
        return std::fs::read_to_string(&template_path).ok();
    }
    crate::default_schemas::embedded_body_template(type_name).map(|s| s.to_string())
}

/// Commit specified slugs (or all uncommitted files) to git and return the commit hash.
pub fn content_commit(
    engine: &EngineState,
    wiki_name: &str,
    slugs: &[String],
    all: bool,
    message: Option<&str>,
) -> Result<String> {
    let space = engine.space(wiki_name)?;

    if slugs.is_empty() && !all {
        bail!("specify slugs or --all");
    }

    // Held across staging and commit so a sidecar cannot commit a partial page
    // set out from under us, or stage files into the tree we are about to write.
    let _lock = RepoLock::for_space(space, "mcp:content_commit")?;

    if all {
        let msg = message.unwrap_or("commit: all");
        return git::commit(&space.repo_root, msg);
    }

    let mut paths = Vec::new();
    for s in slugs {
        let slug = Slug::try_from(s.as_str())?;
        let resolved = space.roots.resolve(&slug)?;
        if resolved.file_name() == Some(std::ffi::OsStr::new("index.md")) {
            let bundle_dir = resolved.parent().unwrap();
            for entry in walkdir::WalkDir::new(bundle_dir)
                .into_iter()
                .filter_map(|e| e.ok())
            {
                if entry.path().is_file() {
                    paths.push(entry.path().to_path_buf());
                }
            }
        } else {
            paths.push(resolved);
        }
    }
    let path_refs: Vec<&Path> = paths.iter().map(|p| p.as_path()).collect();
    let default_msg = format!("commit: {}", slugs.join(", "));
    let msg = message.unwrap_or(&default_msg);
    git::commit_paths(&space.repo_root, &path_refs, msg)
}
