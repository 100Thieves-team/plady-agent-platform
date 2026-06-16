package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiValidationIssue
import io.plady._00thieveswikimcp.wiki.api.WikiValidationResult
import org.springframework.stereotype.Service
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.exists
import kotlin.io.path.isRegularFile
import kotlin.io.path.nameWithoutExtension
import kotlin.io.path.readText

@Service
class WikiValidationService {
    private val allowedPrefixes = listOf(
        "raw/",
        "Clippings/",
        "wiki/",
        "views/",
    )
    private val allowedRootFiles = setOf(
        "adr.md",
        "tech-spec.md",
        "review-summary.md",
        "AGENTS.md",
        "CLAUDE.md",
    )

    fun validateTouchedFiles(files: List<String>, repoRoot: Path? = null): WikiValidationResult {
        val issues = files.flatMap { file ->
            validatePath(file) + validateMarkdownContent(file, repoRoot)
        }
        return WikiValidationResult(ok = issues.none { it.severity == "error" }, issues = issues)
    }

    private fun validatePath(path: String): List<WikiValidationIssue> {
        val issues = mutableListOf<WikiValidationIssue>()
        if (path.isBlank()) return issues
        if (path.contains("..") || path.startsWith("/") || path.startsWith(".git/")) {
            issues += WikiValidationIssue("DISALLOWED_PATH", "error", path, "Path escapes or targets protected git metadata.")
        }
        val allowed = allowedPrefixes.any { path.startsWith(it) } || path in allowedRootFiles
        if (!allowed) {
            issues += WikiValidationIssue(
                "OUTSIDE_ALLOWED_WIKI_PATHS",
                "error",
                path,
                "Only raw/, Clippings/, wiki/, views/, and known type documents may be changed through pending approval.",
            )
        }
        if (!path.endsWith(".md", ignoreCase = true) && path !in allowedRootFiles) {
            issues += WikiValidationIssue("NON_MARKDOWN_CHANGE", "warning", path, "Non-markdown changes require explicit review.")
        }
        return issues
    }

    private fun validateMarkdownContent(path: String, repoRoot: Path?): List<WikiValidationIssue> {
        if (repoRoot == null || !path.endsWith(".md", ignoreCase = true)) return emptyList()
        if (path.contains("..") || path.startsWith("/") || path.startsWith(".git/")) return emptyList()
        val root = repoRoot.toAbsolutePath().normalize()
        val file = root.resolve(path).normalize()
        if (!file.startsWith(root) || !file.exists() || !file.isRegularFile()) return emptyList()

        val raw = runCatching { file.readText() }.getOrNull() ?: return listOf(
            WikiValidationIssue("MARKDOWN_READ_FAILED", "error", path, "Markdown file could not be read for validation."),
        )
        val issues = mutableListOf<WikiValidationIssue>()
        if (raw.isBlank()) {
            issues += WikiValidationIssue("EMPTY_MARKDOWN", "error", path, "Markdown document is empty.")
            return issues
        }

        val body = raw.removeFrontmatter()
        val h1 = body.lines().firstOrNull { it.startsWith("# ") }?.removePrefix("# ")?.trim()
        if (h1.isNullOrBlank()) {
            issues += WikiValidationIssue("MISSING_H1", "warning", path, "Markdown document should include a top-level H1 heading.")
        } else if (raw.explicitFrontmatterTitle() == null && !sameTitleSlug(file.nameWithoutExtension, h1)) {
            issues += WikiValidationIssue("TITLE_DRIFT", "warning", path, "Filename and H1 differ; add explicit title frontmatter if intentional.")
        }

        val knownLinks = knownWikiLinkTargets(root)
        wikiLinks(body).forEach { target ->
            when {
                target.isBlank() -> issues += WikiValidationIssue("EMPTY_WIKILINK", "error", path, "Document contains an empty wikilink.")
                knownLinks.isNotEmpty() && slugify(target) !in knownLinks -> issues += WikiValidationIssue(
                    "BROKEN_WIKILINK",
                    "error",
                    path,
                    "Wikilink target does not resolve in the local wiki repo: $target",
                )
            }
        }

        return issues
    }

    private fun knownWikiLinkTargets(root: Path): Set<String> {
        if (!root.exists()) return emptySet()
        return Files.walk(root).use { stream ->
            stream
                .filter { it.isRegularFile() && it.fileName.toString().endsWith(".md", ignoreCase = true) }
                .flatMap { path ->
                    val raw = runCatching { path.readText() }.getOrDefault("")
                    val body = raw.removeFrontmatter()
                    val h1 = body.lines().firstOrNull { it.startsWith("# ") }?.removePrefix("# ")?.trim()
                    listOfNotNull(
                        slugify(path.nameWithoutExtension),
                        slugify(root.relativize(path).toString().replace('\\', '/').removeSuffix(".md")),
                        h1?.let { slugify(it) },
                        raw.explicitFrontmatterTitle()?.let { slugify(it) },
                    ).stream()
                }
                .filter { it.isNotBlank() }
                .toList()
                .toSet()
        }
    }

    private fun wikiLinks(markdown: String): List<String> =
        Regex("\\[\\[([^]|#]*)(?:[#|][^]]*)?]]")
            .findAll(markdown)
            .map { it.groupValues[1].trim() }
            .toList()

    private fun String.removeFrontmatter(): String =
        replaceFirst(Regex("^---\\R(?s:.*?)\\R---\\R?"), "")

    private fun String.explicitFrontmatterTitle(): String? =
        Regex("^---\\R(?s:(.*?))\\R---").find(this)
            ?.groupValues
            ?.get(1)
            ?.lines()
            ?.firstOrNull { it.trimStart().startsWith("title:") }
            ?.substringAfter(":")
            ?.trim()
            ?.trim('"', '\'')
            ?.takeIf { it.isNotBlank() }

    private fun sameTitleSlug(left: String, right: String): Boolean = slugify(left) == slugify(right)

    private fun slugify(value: String): String =
        value
            .trim()
            .lowercase()
            .replace(Regex("[^a-z0-9가-힣]+"), "-")
            .trim('-')
}
