package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiGetResponse
import io.plady._00thieveswikimcp.wiki.api.WikiResourceContent
import io.plady._00thieveswikimcp.wiki.api.WikiToolError
import io.plady._00thieveswikimcp.wiki.infrastructure.LocalWikiRepository
import org.springframework.stereotype.Service

@Service
class WikiResourceService(
    private val repository: LocalWikiRepository,
) {
    fun get(uri: String?, includeContent: Boolean = true, includeFrontmatter: Boolean = true): WikiGetResponse {
        if (uri.isNullOrBlank()) {
            return error("INVALID_URI", "uri is required")
        }
        if (!uri.startsWith("wiki://")) {
            return error("INVALID_URI", "Only wiki:// resource URIs are supported: $uri")
        }
        if (!repository.isAvailable()) {
            return error("REPO_UNAVAILABLE", "Configured wiki repo is not available")
        }

        val document = repository.findByUri(uri) ?: return error("RESOURCE_NOT_FOUND", "No wiki resource found for $uri")
        val related = extractWikiLinks(document.body)
        return WikiGetResponse(
            ok = true,
            resource = WikiResourceContent(
                uri = document.uri,
                title = document.title,
                type = document.type,
                status = document.status,
                frontmatter = if (includeFrontmatter) document.frontmatter else emptyMap(),
                content = if (includeContent) document.body else null,
                githubUrl = document.githubUrl,
                relatedUris = related,
                path = document.path,
                lastModifiedAt = document.lastModifiedAt,
            ),
        )
    }

    fun resourceText(uri: String): String = get(uri).resource?.let { resource ->
        buildString {
            appendLine("# ${resource.title}")
            appendLine()
            appendLine("uri: ${resource.uri}")
            appendLine("type: ${resource.type}")
            resource.status?.let { appendLine("status: $it") }
            resource.githubUrl?.let { appendLine("github_url: $it") }
            appendLine()
            append(resource.content.orEmpty())
        }
    } ?: "Resource not found: $uri"

    private fun extractWikiLinks(body: String): List<String> = Regex("\\[\\[([^]|#]+)(?:[#|][^]]*)?]]")
        .findAll(body)
        .map { it.groupValues[1].trim() }
        .filter { it.isNotBlank() }
        .distinct()
        .take(50)
        .map { "wiki://raw/$it" }
        .toList()

    private fun error(code: String, message: String) = WikiGetResponse(
        ok = false,
        error = WikiToolError(code = code, message = message),
    )
}
