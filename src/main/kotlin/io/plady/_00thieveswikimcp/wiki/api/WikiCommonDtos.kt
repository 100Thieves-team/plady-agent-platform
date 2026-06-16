package io.plady._00thieveswikimcp.wiki.api

import java.time.Instant

/** Common metadata attached to deterministic MCP responses. */
data class WikiToolMeta(
    val generatedAt: Instant = Instant.now(),
    val server: String = "100Thieves-wiki-mcp",
)

data class WikiToolError(
    val code: String,
    val message: String,
    val retryable: Boolean = false,
    val details: Map<String, String> = emptyMap(),
)

data class WikiAcknowledgement(
    val ok: Boolean,
    val status: String,
    val message: String,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

enum class WikiDocumentType {
    RAW,
    SOURCE,
    TOPIC,
    ADR,
    SPEC,
    REVIEW,
    BACKLOG,
    UNKNOWN,
}

fun String?.normalizeType(): WikiDocumentType = when (this?.trim()?.lowercase()) {
    "raw" -> WikiDocumentType.RAW
    "source", "wiki/source", "sources" -> WikiDocumentType.SOURCE
    "topic", "topics" -> WikiDocumentType.TOPIC
    "adr", "architecture-decision-record", "architecture decision record" -> WikiDocumentType.ADR
    "spec", "tech-spec", "tech spec", "technical specification" -> WikiDocumentType.SPEC
    "review", "review-summary", "review summary" -> WikiDocumentType.REVIEW
    "backlog", "decision-backlog", "decision backlog" -> WikiDocumentType.BACKLOG
    else -> WikiDocumentType.UNKNOWN
}
