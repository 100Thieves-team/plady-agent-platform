use std::fmt;
use std::path::{Path, PathBuf};

use anyhow::{Result, bail};

/// A validated slug — path relative to wiki root, no extension.
///
/// Invariants enforced at construction:
/// - No `../` path traversal
/// - No file extension
/// - No leading `/`
/// - Non-empty
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct Slug(String);

impl Slug {
    /// Derive a slug from a file path relative to wiki root.
    ///
    /// - `concepts/moe.md` → `concepts/moe`
    /// - `concepts/moe/index.md` → `concepts/moe`
    pub fn from_path(path: &Path, wiki_root: &Path) -> Result<Self> {
        let rel = path
            .strip_prefix(wiki_root)
            .map_err(|_| anyhow::anyhow!("path is not under wiki root"))?;
        let raw = if rel.file_name() == Some(std::ffi::OsStr::new("index.md")) {
            rel.parent()
                .ok_or_else(|| anyhow::anyhow!("index.md has no parent"))?
                .to_string_lossy()
                .into_owned()
        } else {
            rel.with_extension("").to_string_lossy().into_owned()
        };
        Self::try_from(raw.as_str())
    }

    /// Resolve this slug to a file path. Checks flat then bundle.
    ///
    /// 1. `<wiki_root>/<slug>.md`
    /// 2. `<wiki_root>/<slug>/index.md`
    pub fn resolve(&self, wiki_root: &Path) -> Result<PathBuf> {
        let flat = wiki_root.join(format!("{}.md", self.0));
        if flat.is_file() {
            return Ok(flat);
        }
        let bundle = wiki_root.join(&self.0).join("index.md");
        if bundle.is_file() {
            return Ok(bundle);
        }
        bail!("page not found for slug: {}", self.0)
    }

    /// Derive a display title from the last slug segment.
    ///
    /// `concepts/mixture-of-experts` → `Mixture of Experts`
    pub fn title(&self) -> String {
        let last = self.0.rsplit('/').next().unwrap_or(&self.0);
        title_case(last)
    }

    /// Return the raw slug string slice.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl TryFrom<&str> for Slug {
    type Error = anyhow::Error;

    fn try_from(s: &str) -> Result<Self> {
        let s = s.trim();
        if s.is_empty() {
            bail!("slug cannot be empty");
        }
        if s.starts_with('/') {
            bail!("slug cannot start with /: {s}");
        }
        if s.contains("../") || s.contains("..\\") {
            bail!("slug cannot contain path traversal: {s}");
        }
        // Reject if the last segment has a file extension
        if let Some(last) = s.rsplit('/').next()
            && let Some(dot) = last.rfind('.')
        {
            let ext = &last[dot + 1..];
            if !ext.is_empty() {
                bail!("slug cannot have a file extension: {s}");
            }
        }
        Ok(Slug(s.to_string()))
    }
}

impl fmt::Display for Slug {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl AsRef<str> for Slug {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

/// A parsed `wiki://` URI or bare slug.
///
/// `wiki://research/concepts/moe` → wiki: Some("research"), slug: "concepts/moe"
/// `concepts/moe` → wiki: None, slug: "concepts/moe"
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WikiUri {
    /// Candidate wiki name — None for bare slugs.
    /// At parse time this is a candidate; WikiUri::resolve checks
    /// whether it's a registered wiki name.
    pub wiki: Option<String>,
    /// The slug portion.
    pub slug: Slug,
}

impl WikiUri {
    /// Parse a string into a WikiUri. Accepts both `wiki://` URIs and bare slugs.
    pub fn parse(input: &str) -> Result<Self> {
        let input = input.trim();
        if let Some(stripped) = input.strip_prefix("wiki://") {
            if stripped.is_empty() {
                bail!("invalid wiki URI: {input}");
            }
            let parts: Vec<&str> = stripped.splitn(2, '/').collect();
            if parts.len() == 2 && !parts[1].is_empty() {
                // wiki://candidate/slug — candidate may be wiki name or first slug segment
                Ok(WikiUri {
                    wiki: Some(parts[0].to_string()),
                    slug: Slug::try_from(parts[1])?,
                })
            } else {
                // wiki://slug (no slash, or trailing slash)
                Ok(WikiUri {
                    wiki: None,
                    slug: Slug::try_from(stripped.trim_end_matches('/'))?,
                })
            }
        } else {
            // Bare slug
            Ok(WikiUri {
                wiki: None,
                slug: Slug::try_from(input)?,
            })
        }
    }

    /// Resolve a URI or bare slug against the global config.
    ///
    /// - `wiki://` URIs: try candidate wiki name, fall back to default wiki
    /// - Bare slugs: use `wiki_flag` or default wiki
    ///
    /// Returns `(WikiEntry, Slug)`.
    pub fn resolve(
        input: &str,
        wiki_flag: Option<&str>,
        global: &crate::config::GlobalConfig,
    ) -> Result<(crate::config::WikiEntry, Slug)> {
        use crate::spaces;

        if input.starts_with("wiki://") {
            let parsed = Self::parse(input)?;
            if let Some(ref name) = parsed.wiki {
                if let Ok(entry) = spaces::resolve_name(name, global) {
                    return Ok((entry, parsed.slug));
                }
                // Not a wiki name — treat as slug segment
                let full_slug = format!("{name}/{}", parsed.slug);
                let slug = Slug::try_from(full_slug.as_str())?;
                let default = &global.global.default_wiki;
                let entry = spaces::resolve_name(default, global)?;
                return Ok((entry, slug));
            }
            let default = &global.global.default_wiki;
            let entry = spaces::resolve_name(default, global)?;
            Ok((entry, parsed.slug))
        } else {
            let wiki_name = wiki_flag.unwrap_or(&global.global.default_wiki);
            let entry = spaces::resolve_name(wiki_name, global)?;
            let slug = Slug::try_from(input)?;
            Ok((entry, slug))
        }
    }
}

/// Result of slug vs asset resolution for wiki_content_read.
#[derive(Debug)]
pub enum ReadTarget {
    /// Slug resolved to a page.
    Page(PathBuf),
    /// Slug resolved to a co-located asset: (parent slug, filename).
    Asset(String, String),
}

/// Two-step resolution: try page first, then asset fallback.
///
/// 1. Try `slug.resolve()` → page
/// 2. If the last segment has a non-.md extension, split into parent slug + filename → asset
///
/// Reads accept any non-.md extension (images and other binaries included);
/// writes narrow that to `WRITABLE_ASSET_EXTENSIONS`. Both share
/// `split_asset_path` so path-traversal defenses are identical.
pub fn resolve_read_target(input: &str, wiki_root: &Path) -> Result<ReadTarget> {
    // Step 1: try as page (may fail if input has an extension)
    if let Ok(slug) = Slug::try_from(input)
        && let Ok(path) = slug.resolve(wiki_root)
    {
        return Ok(ReadTarget::Page(path));
    }

    // Step 2: check last segment for non-.md extension (asset)
    if let Some(ext) = last_segment_extension(input)
        && ext != "md"
    {
        let (parent, filename) = split_asset_path(input)?;
        let path = wiki_root.join(parent.as_str()).join(&filename);
        if path.is_file() {
            return Ok(ReadTarget::Asset(parent.as_str().to_string(), filename));
        }
        bail!("asset not found: {input}");
    }

    bail!("page not found: {input}")
}

/// Extensions allowed for asset writes via wiki_content_write.
/// Text formats only — binaries, HTML, and scripts are rejected.
pub const WRITABLE_ASSET_EXTENSIONS: &[&str] = &["yaml", "yml", "json", "txt", "csv"];

/// Result of slug vs asset resolution for wiki_content_write.
#[derive(Debug)]
pub enum WriteTarget {
    /// Input is an extensionless slug — write as a page.
    Page(crate::config::WikiEntry, Slug),
    /// Input names a co-located text asset: (wiki entry, parent slug, filename).
    Asset(crate::config::WikiEntry, Slug, String),
}

/// Return the extension of the last path segment, if any.
pub fn last_segment_extension(input: &str) -> Option<&str> {
    let last = input.rsplit('/').next().unwrap_or(input);
    let dot = last.rfind('.')?;
    let ext = &last[dot + 1..];
    if ext.is_empty() { None } else { Some(ext) }
}

/// Resolve a slug or `wiki://` URI to its wiki space plus the path relative to
/// the wiki root, without validating that path.
///
/// Mirrors the wiki-name resolution in `WikiUri::resolve`, but leaves slug/asset
/// validation to the caller so read and write can apply their own rules to the
/// same relative path.
pub fn resolve_entry_and_rel(
    input: &str,
    wiki_flag: Option<&str>,
    global: &crate::config::GlobalConfig,
) -> Result<(crate::config::WikiEntry, String)> {
    use crate::spaces;

    let input = input.trim();
    if let Some(stripped) = input.strip_prefix("wiki://") {
        if stripped.is_empty() {
            bail!("invalid wiki URI: {input}");
        }
        let parts: Vec<&str> = stripped.splitn(2, '/').collect();
        if parts.len() == 2 && !parts[1].is_empty() {
            if let Ok(entry) = spaces::resolve_name(parts[0], global) {
                return Ok((entry, parts[1].to_string()));
            }
            // Candidate is not a wiki name — treat as first slug segment
            let entry = spaces::resolve_name(&global.global.default_wiki, global)?;
            return Ok((entry, format!("{}/{}", parts[0], parts[1])));
        }
        let entry = spaces::resolve_name(&global.global.default_wiki, global)?;
        Ok((entry, stripped.trim_end_matches('/').to_string()))
    } else {
        let wiki_name = wiki_flag.unwrap_or(&global.global.default_wiki);
        Ok((spaces::resolve_name(wiki_name, global)?, input.to_string()))
    }
}

/// Split a wiki-root-relative asset path into a validated parent slug and
/// filename. Shared by asset reads and writes so both reject the same paths.
///
/// Rejects path traversal (`../`, bare `..` segments), absolute paths, filenames
/// carrying separators, and filenames with an empty stem.
pub fn split_asset_path(rel: &str) -> Result<(Slug, String)> {
    let Some(pos) = rel.rfind('/') else {
        bail!("asset path needs a parent directory under the wiki root: {rel}");
    };
    let (parent, filename) = (&rel[..pos], &rel[pos + 1..]);

    // Every parent segment must be a plain name — closes the bare `..` hole
    // that the substring checks in Slug::try_from do not cover
    if parent.split('/').any(|s| s.is_empty() || s == "." || s == "..") {
        bail!("asset path cannot contain path traversal: {rel}");
    }
    // Parent goes through Slug validation — blocks ../ and absolute paths
    let parent = Slug::try_from(parent)?;

    // Filename hygiene: no separators or traversal, non-empty stem
    if filename.contains('\\') || filename.contains("..") {
        bail!("invalid asset filename: {filename}");
    }
    let Some(ext) = last_segment_extension(filename) else {
        bail!("asset filename needs an extension: {filename}");
    };
    if filename.len() == ext.len() + 1 {
        bail!("asset filename needs a name before the extension: {filename}");
    }

    Ok((parent, filename.to_string()))
}

/// Two-step resolution for wiki_content_write — write-side mirror of
/// `resolve_read_target`.
///
/// 1. Extensionless input → page write (existing slug semantics, unchanged)
/// 2. Last segment has an allowed text extension (yaml/yml/json/txt/csv) →
///    asset write, validated by `split_asset_path` so the target stays under
///    the wiki root.
pub fn resolve_write_target(
    input: &str,
    wiki_flag: Option<&str>,
    global: &crate::config::GlobalConfig,
) -> Result<WriteTarget> {
    let input = input.trim();
    let Some(ext) = last_segment_extension(input) else {
        // No extension — page write via the normal slug path
        let (entry, slug) = WikiUri::resolve(input, wiki_flag, global)?;
        return Ok(WriteTarget::Page(entry, slug));
    };

    if !WRITABLE_ASSET_EXTENSIONS.contains(&ext.to_ascii_lowercase().as_str()) {
        bail!(
            "unsupported asset extension .{ext}: {input} — allowed: {} (pages are written via extensionless slugs)",
            WRITABLE_ASSET_EXTENSIONS.join(", ")
        );
    }

    let (entry, rel) = resolve_entry_and_rel(input, wiki_flag, global)?;
    let (parent, filename) = split_asset_path(&rel)?;
    Ok(WriteTarget::Asset(entry, parent, filename))
}

fn title_case(segment: &str) -> String {
    segment
        .split('-')
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                None => String::new(),
                Some(first) => {
                    let upper: String = first.to_uppercase().collect();
                    upper + c.as_str()
                }
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}
