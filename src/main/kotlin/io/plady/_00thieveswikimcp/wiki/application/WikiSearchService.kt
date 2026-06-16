package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiDocument
import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import io.plady._00thieveswikimcp.wiki.api.WikiSearchResponse
import io.plady._00thieveswikimcp.wiki.api.WikiSearchResult
import io.plady._00thieveswikimcp.wiki.api.WikiToolError
import io.plady._00thieveswikimcp.wiki.api.normalizeType
import io.plady._00thieveswikimcp.wiki.infrastructure.LocalWikiRepository
import org.springframework.stereotype.Service
import kotlin.math.min

@Service
class WikiSearchService(
    private val repository: LocalWikiRepository,
) {
    fun search(
        query: String?,
        types: List<String> = emptyList(),
        statuses: List<String> = emptyList(),
        tags: List<String> = emptyList(),
        linearIssueId: String? = null,
        limit: Int = 10,
    ): WikiSearchResponse {
        if (!repository.isAvailable()) {
            return WikiSearchResponse(
                ok = false,
                query = query.orEmpty(),
                results = emptyList(),
                error = WikiToolError("REPO_UNAVAILABLE", "Configured wiki repo is not available"),
            )
        }

        val safeLimit = limit.coerceIn(1, 50)
        val normalizedTypes = types.map { it.normalizeType() }.filter { it != WikiDocumentType.UNKNOWN }.toSet()
        val normalizedStatuses = statuses.map { it.lowercase() }.toSet()
        val normalizedTags = tags.map { it.lowercase().removePrefix("#") }.toSet()
        val searchText = listOfNotNull(query?.trim(), linearIssueId?.trim()).filter { it.isNotBlank() }.joinToString(" ")
        val terms = tokenize(searchText)

        val results = repository.listDocuments()
            .asSequence()
            .filter { normalizedTypes.isEmpty() || it.type in normalizedTypes }
            .filter { normalizedStatuses.isEmpty() || it.status?.lowercase() in normalizedStatuses }
            .filter { normalizedTags.isEmpty() || it.tags.map { tag -> tag.lowercase().removePrefix("#") }.any { tag -> tag in normalizedTags } }
            .mapNotNull { document -> score(document, terms)?.let { score -> document to score } }
            .sortedWith(compareByDescending<Pair<WikiDocument, Double>> { it.second }.thenBy { it.first.path })
            .take(safeLimit)
            .map { (document, score) ->
                WikiSearchResult(
                    uri = document.uri,
                    title = document.title,
                    type = document.type,
                    status = document.status,
                    score = score,
                    snippet = snippet(document, terms),
                    path = document.path,
                    githubUrl = document.githubUrl,
                )
            }
            .toList()

        return WikiSearchResponse(ok = true, query = searchText, results = results)
    }

    private fun score(document: WikiDocument, terms: List<String>): Double? {
        if (terms.isEmpty()) return 1.0
        val title = document.title.lowercase()
        val path = document.path.lowercase()
        val body = document.body.lowercase()
        val frontmatter = document.frontmatter.entries.joinToString(" ") { "${it.key} ${it.value}" }.lowercase()
        var score = 0.0
        terms.forEach { term ->
            when {
                title.contains(term) -> score += 8.0
                path.contains(term) -> score += 5.0
                frontmatter.contains(term) -> score += 3.0
                body.contains(term) -> score += 1.0
            }
        }
        return score.takeIf { it > 0.0 }
    }

    private fun snippet(document: WikiDocument, terms: List<String>): String {
        val compact = document.body.lines().map { it.trim() }.filter { it.isNotBlank() }
        if (compact.isEmpty()) return document.title
        val match = terms.asSequence().flatMap { term -> compact.asSequence().filter { it.lowercase().contains(term) } }.firstOrNull()
        val openQuestion = compact.firstOrNull { line ->
            val lower = line.lowercase()
            lower.contains("open question") || lower.contains("열린 질문") || lower.contains("todo") || lower.contains("미정")
        }
        val selected = when {
            match != null && openQuestion != null && match != openQuestion -> "$match / $openQuestion"
            match != null -> match
            openQuestion != null -> openQuestion
            else -> compact.first()
        }
        return selected.take(min(280, selected.length))
    }

    private fun tokenize(text: String): List<String> = text.lowercase()
        .split(Regex("[^a-z0-9가-힣_-]+"))
        .map { it.trim() }
        .filter { it.length >= 2 }
        .distinct()
}
