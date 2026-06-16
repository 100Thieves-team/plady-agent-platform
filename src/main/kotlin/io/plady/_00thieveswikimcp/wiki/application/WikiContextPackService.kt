package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiContextItem
import io.plady._00thieveswikimcp.wiki.api.WikiRelatedContextResponse
import io.plady._00thieveswikimcp.wiki.api.WikiToolError
import org.springframework.stereotype.Service

@Service
class WikiContextPackService(
    private val searchService: WikiSearchService,
) {
    fun getRelatedContext(
        linearIssueId: String?,
        types: List<String> = emptyList(),
        includeOpenQuestions: Boolean = true,
        limit: Int = 10,
    ): WikiRelatedContextResponse {
        if (linearIssueId.isNullOrBlank()) {
            return WikiRelatedContextResponse(
                ok = false,
                linearIssueId = "",
                summary = "linearIssueId is required",
                contextItems = emptyList(),
                error = WikiToolError("INVALID_LINEAR_ISSUE", "linearIssueId is required"),
            )
        }

        val search = searchService.search(
            query = linearIssueId,
            types = types,
            linearIssueId = linearIssueId,
            limit = limit.coerceIn(1, 30),
        )
        if (!search.ok) {
            return WikiRelatedContextResponse(
                ok = false,
                linearIssueId = linearIssueId,
                summary = search.error?.message ?: "Search failed",
                contextItems = emptyList(),
                error = search.error,
            )
        }

        val items = search.results.map { result ->
            WikiContextItem(
                uri = result.uri,
                title = result.title,
                type = result.type,
                status = result.status,
                reason = "Matched Linear issue id or related terms for $linearIssueId",
                snippet = result.snippet,
                githubUrl = result.githubUrl,
            )
        }
        val openQuestions = if (includeOpenQuestions) extractOpenQuestions(items) else emptyList()
        val summary = if (items.isEmpty()) {
            "No related LLM Wiki context found for $linearIssueId."
        } else {
            "Found ${items.size} related LLM Wiki context item(s) for $linearIssueId."
        }
        return WikiRelatedContextResponse(
            ok = true,
            linearIssueId = linearIssueId,
            summary = summary,
            contextItems = items,
            openQuestions = openQuestions,
        )
    }

    private fun extractOpenQuestions(items: List<WikiContextItem>): List<String> = items
        .mapNotNull { item ->
            item.snippet.takeIf { snippet ->
                val lower = snippet.lowercase()
                lower.contains("open question") || lower.contains("열린 질문") || lower.contains("todo") || lower.contains("미정")
            }?.let { "${item.uri}: $it" }
        }
        .distinct()
        .take(10)
}
