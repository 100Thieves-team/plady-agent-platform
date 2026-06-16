package io.plady._00thieveswikimcp.wiki.api

data class WikiSearchResult(
    val uri: String,
    val title: String,
    val type: WikiDocumentType,
    val status: String? = null,
    val score: Double,
    val snippet: String,
    val path: String,
    val githubUrl: String? = null,
)

data class WikiSearchResponse(
    val ok: Boolean,
    val query: String,
    val results: List<WikiSearchResult>,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiGetResponse(
    val ok: Boolean,
    val resource: WikiResourceContent? = null,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiContextItem(
    val uri: String,
    val title: String,
    val type: WikiDocumentType,
    val status: String? = null,
    val reason: String,
    val snippet: String,
    val githubUrl: String? = null,
)

data class WikiRelatedContextResponse(
    val ok: Boolean,
    val linearIssueId: String,
    val summary: String,
    val contextItems: List<WikiContextItem>,
    val openQuestions: List<String> = emptyList(),
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiTriageResponse(
    val ok: Boolean,
    val needsAdr: Boolean,
    val needsTechSpec: Boolean,
    val needsBacklog: Boolean,
    val rationale: List<String>,
    val suggestedNextActions: List<String>,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiLintFinding(
    val code: String,
    val severity: String,
    val uri: String? = null,
    val path: String? = null,
    val message: String,
    val suggestion: String? = null,
)

data class WikiLintResponse(
    val ok: Boolean,
    val summary: String,
    val findings: List<WikiLintFinding>,
    val suggestedTasks: List<String>,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)
