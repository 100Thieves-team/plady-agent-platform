package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import io.plady._00thieveswikimcp.wiki.api.WikiLintFinding
import io.plady._00thieveswikimcp.wiki.api.WikiLintResponse
import io.plady._00thieveswikimcp.wiki.api.WikiToolError
import io.plady._00thieveswikimcp.wiki.api.normalizeType
import io.plady._00thieveswikimcp.wiki.infrastructure.LocalWikiRepository
import org.springframework.stereotype.Service
import java.time.Instant
import java.time.temporal.ChronoUnit

@Service
class WikiLintService(
    private val repository: LocalWikiRepository,
) {
    fun lint(scope: String? = null, types: List<String> = emptyList(), since: String? = null, limit: Int = 50): WikiLintResponse {
        if (!repository.isAvailable()) {
            return WikiLintResponse(
                ok = false,
                summary = "Configured wiki repo is not available",
                findings = emptyList(),
                suggestedTasks = emptyList(),
                error = WikiToolError("REPO_UNAVAILABLE", "Configured wiki repo is not available"),
            )
        }
        val wantedTypes = types.map { it.normalizeType() }.filter { it != WikiDocumentType.UNKNOWN }.toSet()
        val staleCutoff = Instant.now().minus(90, ChronoUnit.DAYS)
        val findings = mutableListOf<WikiLintFinding>()
        val docs = repository.listDocuments().filter { wantedTypes.isEmpty() || it.type in wantedTypes }

        docs.forEach { doc ->
            if (!doc.frontmatter.containsKey("type")) {
                findings += WikiLintFinding(
                    code = "MISSING_TYPE_FRONTMATTER",
                    severity = "warning",
                    uri = doc.uri,
                    path = doc.path,
                    message = "Document is missing frontmatter `type`.",
                    suggestion = "Add the appropriate LLM Wiki type metadata.",
                )
            }
            val h1 = doc.body.lines().firstOrNull { it.startsWith("# ") }?.removePrefix("# ")?.trim()
            val filenameTitle = doc.path.substringAfterLast('/').removeSuffix(".md")
            if (!h1.isNullOrBlank() && doc.frontmatter["title"] == null && !sameTitleSlug(filenameTitle, h1)) {
                findings += WikiLintFinding(
                    code = "TITLE_DRIFT",
                    severity = "info",
                    uri = doc.uri,
                    path = doc.path,
                    message = "Filename/frontmatter title and H1 differ.",
                    suggestion = "Align filename, H1, or explicit title frontmatter if this is intentional.",
                )
            }
            if ((doc.type == WikiDocumentType.ADR || doc.type == WikiDocumentType.SPEC) && doc.status.equals("Proposed", ignoreCase = true)
                && doc.lastModifiedAt != null && doc.lastModifiedAt.isBefore(staleCutoff)
            ) {
                findings += WikiLintFinding(
                    code = "STALE_PROPOSED_DOC",
                    severity = "warning",
                    uri = doc.uri,
                    path = doc.path,
                    message = "Proposed ADR/Spec has not changed for about 90 days.",
                    suggestion = "Review whether this should be accepted, superseded, or moved to backlog.",
                )
            }
            if (doc.body.contains("[[") && doc.body.contains("]]")) {
                Regex("\\[\\[([^]|#]+)(?:[#|][^]]*)?]]").findAll(doc.body).forEach { match ->
                    val target = match.groupValues[1].trim()
                    if (target.isBlank()) {
                        findings += WikiLintFinding(
                            code = "EMPTY_WIKILINK",
                            severity = "error",
                            uri = doc.uri,
                            path = doc.path,
                            message = "Document contains an empty wikilink.",
                        )
                    }
                }
            }
        }

        val capped = findings.take(limit.coerceIn(1, 250))
        val suggestedTasks = capped.groupBy { it.code }.keys.map { code -> "Address $code findings via wiki_run_task so changes enter pending approval." }
        return WikiLintResponse(
            ok = true,
            summary = "Found ${findings.size} lint finding(s) across ${docs.size} document(s).",
            findings = capped,
            suggestedTasks = suggestedTasks,
        )
    }

    private fun sameTitleSlug(left: String, right: String): Boolean = slugify(left) == slugify(right)

    private fun slugify(value: String): String =
        value
            .trim()
            .lowercase()
            .replace(Regex("[^a-z0-9가-힣]+"), "-")
            .trim('-')
}
