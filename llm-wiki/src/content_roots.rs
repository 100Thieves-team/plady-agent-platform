//! Content roots — the directories whose Markdown files belong to a wiki space.
//!
//! The **primary root** (`<repo>/wiki` by default) holds compiled pages that
//! agents own and rewrite freely. **External roots** are siblings of it that
//! hold preserved source material — `<repo>/raw` in the Karpathy three-layer
//! model, where documents are read but never rewritten.
//!
//! A slug names its own root through its first segment: `sources/x` belongs to
//! the primary root, `raw/meetings/x` to the `raw` external root. Because an
//! external slug already carries its root's directory name, resolving it needs
//! only the *parent* of the primary root as the join base — so every existing
//! `wiki_root.join(slug)` becomes `roots.base_for(slug).join(slug)` with no
//! change to slug syntax and no change to links already written.
//!
//! External roots are opt-in per wiki (`external_roots` in `wiki.toml`). With
//! none configured a `ContentRoots` behaves exactly like the bare `wiki_root`
//! path it replaces.
//!
//! The same layout answers a second question: **what kind of page lives here**.
//! In this model the directory is the page kind — `sources/` holds source
//! summaries, `topics/` holds concepts, `raw/` holds preserved originals — so a
//! wiki can declare `type_by_prefix` and have the index derive each page's type
//! from its slug instead of depending on frontmatter that says `doc` everywhere.
//! See [`ContentRoots::page_kind`].

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use anyhow::{Result, bail};

use crate::slug::Slug;

/// The set of directories a wiki space draws Markdown pages from.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContentRoots {
    primary: PathBuf,
    repo_root: PathBuf,
    external: Vec<String>,
    type_by_prefix: BTreeMap<String, String>,
}

impl ContentRoots {
    /// Build roots for `primary` (the wiki root) plus `external` sibling
    /// directory names, which are resolved relative to `primary`'s parent.
    ///
    /// External names are normalized: surrounding slashes and whitespace are
    /// trimmed, empty names and names containing a separator or `..` are
    /// dropped, since an external root is always a single directory sitting
    /// beside the wiki root.
    pub fn new<I, S>(primary: impl Into<PathBuf>, external: I) -> Self
    where
        I: IntoIterator<Item = S>,
        S: AsRef<str>,
    {
        let primary = primary.into();
        let repo_root = primary
            .parent()
            .map(Path::to_path_buf)
            .unwrap_or_else(|| primary.clone());
        let mut names: Vec<String> = Vec::new();
        for raw in external {
            let name = raw.as_ref().trim().trim_matches('/').to_string();
            if name.is_empty() || name.contains('/') || name.contains('\\') || name.contains("..") {
                continue;
            }
            if !names.contains(&name) {
                names.push(name);
            }
        }
        Self {
            primary,
            repo_root,
            external: names,
            type_by_prefix: BTreeMap::new(),
        }
    }

    /// Declare slug-prefix → page-type mappings, e.g. `sources` → `source`.
    ///
    /// Prefixes match whole path segments, and the longest match wins, so a
    /// wiki can map `raw` broadly and `raw/product` specifically.
    pub fn with_type_by_prefix<I, K, V>(mut self, mapping: I) -> Self
    where
        I: IntoIterator<Item = (K, V)>,
        K: AsRef<str>,
        V: AsRef<str>,
    {
        self.type_by_prefix = mapping
            .into_iter()
            .filter_map(|(k, v)| {
                let key = k.as_ref().trim().trim_matches('/').to_string();
                let val = v.as_ref().trim().to_string();
                (!key.is_empty() && !val.is_empty()).then_some((key, val))
            })
            .collect();
        self
    }

    /// The page type this slug's location implies, if the wiki declares one.
    ///
    /// Matching is by whole segments — `sources` does not match `sources-archive`
    /// — and the most specific declared prefix wins.
    pub fn page_kind(&self, slug: &str) -> Option<&str> {
        self.type_by_prefix
            .iter()
            .filter(|(prefix, _)| {
                slug == prefix.as_str()
                    || slug
                        .strip_prefix(prefix.as_str())
                        .is_some_and(|rest| rest.starts_with('/'))
            })
            .max_by_key(|(prefix, _)| prefix.len())
            .map(|(_, kind)| kind.as_str())
    }

    /// Whether this wiki derives page types from slugs at all.
    pub fn derives_types(&self) -> bool {
        !self.type_by_prefix.is_empty()
    }

    /// Roots for a wiki with no external source directories — the behaviour of
    /// a plain `wiki_root` path.
    pub fn single(primary: impl Into<PathBuf>) -> Self {
        Self::new(primary, std::iter::empty::<&str>())
    }

    /// The primary (compiled-page) root.
    pub fn primary(&self) -> &Path {
        &self.primary
    }

    /// The repository root — the parent that external roots hang off.
    pub fn repo_root(&self) -> &Path {
        &self.repo_root
    }

    /// Configured external root names, in declaration order.
    pub fn external_names(&self) -> &[String] {
        &self.external
    }

    /// True when `slug`'s first segment names an external root.
    ///
    /// External pages are preserved source material: callers use this to keep
    /// them out of overwrite paths.
    pub fn is_external(&self, slug: &str) -> bool {
        self.external_prefix(slug).is_some()
    }

    /// The external root name owning `slug`, if any.
    pub fn external_prefix(&self, slug: &str) -> Option<&str> {
        let head = slug.split('/').next().unwrap_or(slug);
        self.external
            .iter()
            .find(|name| name.as_str() == head)
            .map(String::as_str)
    }

    /// The directory to join `slug` against.
    ///
    /// External slugs already carry their root's name, so they join against the
    /// repo root; everything else joins against the primary root.
    pub fn base_for(&self, slug: &str) -> &Path {
        if self.is_external(slug) {
            &self.repo_root
        } else {
            &self.primary
        }
    }

    /// Every directory to walk when indexing, paired with the base its files'
    /// slugs are relative to.
    ///
    /// Yields the primary root first, then each external root that exists on
    /// disk — a configured-but-absent root is skipped rather than failing the
    /// walk, so adding `raw` to a wiki that has none is harmless.
    pub fn walk_roots(&self) -> Vec<(PathBuf, &Path)> {
        let mut out: Vec<(PathBuf, &Path)> = vec![(self.primary.clone(), self.primary.as_path())];
        for name in &self.external {
            let dir = self.repo_root.join(name);
            if dir.is_dir() {
                out.push((dir, self.repo_root.as_path()));
            }
        }
        out
    }

    /// Repo-relative directory prefixes for every configured root, in walk
    /// order — `["wiki", "raw"]` for the default layout.
    ///
    /// Git reports paths relative to the repository root, so change detection
    /// filters on these rather than on absolute paths.
    pub fn repo_relative_prefixes(&self) -> Vec<PathBuf> {
        let mut out = vec![
            self.primary
                .strip_prefix(&self.repo_root)
                .map(Path::to_path_buf)
                .unwrap_or_else(|_| PathBuf::from("wiki")),
        ];
        out.extend(self.external.iter().map(PathBuf::from));
        out
    }

    /// Derive a slug from a repo-relative path such as git reports.
    ///
    /// A path under an external root keeps its root name in the slug, so
    /// nothing is stripped; a path under the primary root drops the primary
    /// prefix as before.
    pub fn slug_from_repo_relative(&self, rel: &Path) -> Result<Slug> {
        let head = rel
            .components()
            .next()
            .map(|c| c.as_os_str().to_string_lossy().into_owned())
            .unwrap_or_default();
        if self.external.contains(&head) {
            return Slug::from_path(rel, Path::new(""));
        }
        let primary_prefix = self
            .primary
            .strip_prefix(&self.repo_root)
            .map(Path::to_path_buf)
            .unwrap_or_else(|_| PathBuf::from("wiki"));
        Slug::from_path(rel, &primary_prefix)
    }

    /// Derive a slug from an absolute path in any of this space's roots.
    ///
    /// Tries the primary root first so a path under `<repo>/wiki` keeps its
    /// existing slug even if an external root shares a name with one of its
    /// subdirectories.
    pub fn slug_from_path(&self, path: &Path) -> Result<Slug> {
        if let Ok(slug) = Slug::from_path(path, &self.primary) {
            return Ok(slug);
        }
        for name in &self.external {
            let dir = self.repo_root.join(name);
            if path.starts_with(&dir) {
                return Slug::from_path(path, &self.repo_root);
            }
        }
        bail!("path is not under any content root: {}", path.display())
    }

    /// Resolve `slug` to an existing file in whichever root owns it.
    pub fn resolve(&self, slug: &Slug) -> Result<PathBuf> {
        slug.resolve(self.base_for(slug.as_str()))
    }

    /// True when `path` lies inside one of this space's roots.
    pub fn contains(&self, path: &Path) -> bool {
        if path.starts_with(&self.primary) {
            return true;
        }
        self.external
            .iter()
            .any(|name| path.starts_with(self.repo_root.join(name)))
    }
}

impl From<&Path> for ContentRoots {
    fn from(primary: &Path) -> Self {
        Self::single(primary)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roots() -> ContentRoots {
        ContentRoots::new(PathBuf::from("/repo/wiki"), ["raw"])
    }

    #[test]
    fn primary_slug_joins_against_wiki_root() {
        let r = roots();
        assert_eq!(r.base_for("sources/team-goals"), Path::new("/repo/wiki"));
    }

    #[test]
    fn external_slug_joins_against_repo_root() {
        let r = roots();
        assert_eq!(r.base_for("raw/meetings/scrum-8-24"), Path::new("/repo"));
        assert_eq!(
            r.base_for("raw/meetings/scrum")
                .join("raw/meetings/scrum")
                .with_extension("md"),
            Path::new("/repo/raw/meetings/scrum.md")
        );
    }

    #[test]
    fn external_prefix_matches_whole_segment_only() {
        let r = roots();
        // `rawdata/x` must not be mistaken for the `raw` root
        assert!(!r.is_external("rawdata/x"));
        assert!(r.is_external("raw/x"));
        assert_eq!(r.external_prefix("raw/meetings/x"), Some("raw"));
    }

    #[test]
    fn single_root_behaves_like_a_bare_wiki_root() {
        let r = ContentRoots::single("/repo/wiki");
        assert!(!r.is_external("raw/x"));
        assert_eq!(r.base_for("raw/x"), Path::new("/repo/wiki"));
        assert_eq!(r.walk_roots().len(), 1);
    }

    #[test]
    fn malformed_external_names_are_dropped() {
        let r = ContentRoots::new("/repo/wiki", ["", "  ", "../escape", "a/b", "raw", "raw"]);
        assert_eq!(r.external_names(), ["raw"]);
    }

    #[test]
    fn external_names_tolerate_surrounding_slashes() {
        let r = ContentRoots::new("/repo/wiki", ["/raw/"]);
        assert_eq!(r.external_names(), ["raw"]);
    }

    #[test]
    fn slug_from_path_covers_both_roots() {
        let r = roots();
        assert_eq!(
            r.slug_from_path(Path::new("/repo/wiki/sources/a.md"))
                .unwrap()
                .as_str(),
            "sources/a"
        );
        assert_eq!(
            r.slug_from_path(Path::new("/repo/raw/meetings/b.md"))
                .unwrap()
                .as_str(),
            "raw/meetings/b"
        );
        assert!(r.slug_from_path(Path::new("/elsewhere/c.md")).is_err());
    }

    #[test]
    fn slug_from_path_handles_bundle_index() {
        let r = roots();
        assert_eq!(
            r.slug_from_path(Path::new("/repo/raw/product/prd/index.md"))
                .unwrap()
                .as_str(),
            "raw/product/prd"
        );
    }

    #[test]
    fn page_kind_matches_whole_segments_only() {
        let r = roots().with_type_by_prefix([("sources", "source"), ("raw", "raw")]);
        assert_eq!(r.page_kind("sources/a"), Some("source"));
        assert_eq!(r.page_kind("sources"), Some("source"));
        assert_eq!(r.page_kind("sources-archive/a"), None);
        assert_eq!(r.page_kind("raw/meetings/x"), Some("raw"));
        assert_eq!(r.page_kind("topics/t"), None);
    }

    #[test]
    fn page_kind_prefers_the_most_specific_prefix() {
        let r = roots().with_type_by_prefix([("raw", "raw"), ("raw/product", "prd")]);
        assert_eq!(r.page_kind("raw/product/rooms"), Some("prd"));
        assert_eq!(r.page_kind("raw/meetings/x"), Some("raw"));
    }

    #[test]
    fn no_mapping_means_no_derived_types() {
        let r = roots();
        assert!(!r.derives_types());
        assert_eq!(r.page_kind("sources/a"), None);
    }

    #[test]
    fn repo_relative_prefixes_lists_primary_then_external() {
        let r = roots();
        assert_eq!(
            r.repo_relative_prefixes(),
            vec![PathBuf::from("wiki"), PathBuf::from("raw")]
        );
    }

    #[test]
    fn slug_from_repo_relative_keeps_external_root_in_slug() {
        let r = roots();
        assert_eq!(
            r.slug_from_repo_relative(Path::new("wiki/sources/a.md"))
                .unwrap()
                .as_str(),
            "sources/a"
        );
        assert_eq!(
            r.slug_from_repo_relative(Path::new("raw/meetings/b.md"))
                .unwrap()
                .as_str(),
            "raw/meetings/b"
        );
    }

    #[test]
    fn contains_tracks_configured_roots_only() {
        let r = roots();
        assert!(r.contains(Path::new("/repo/wiki/topics/t.md")));
        assert!(r.contains(Path::new("/repo/raw/jd/x.md")));
        assert!(!r.contains(Path::new("/repo/schemas/base.json")));
    }
}
