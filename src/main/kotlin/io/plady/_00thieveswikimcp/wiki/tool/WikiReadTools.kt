package io.plady._00thieveswikimcp.wiki.tool

import io.plady._00thieveswikimcp.wiki.api.WikiGetResponse
import io.plady._00thieveswikimcp.wiki.api.WikiLintResponse
import io.plady._00thieveswikimcp.wiki.api.WikiRelatedContextResponse
import io.plady._00thieveswikimcp.wiki.api.WikiSearchResponse
import io.plady._00thieveswikimcp.wiki.api.WikiTriageResponse
import io.plady._00thieveswikimcp.wiki.application.WikiContextPackService
import io.plady._00thieveswikimcp.wiki.application.WikiLintService
import io.plady._00thieveswikimcp.wiki.application.WikiResourceService
import io.plady._00thieveswikimcp.wiki.application.WikiSearchService
import io.plady._00thieveswikimcp.wiki.application.WikiTriageService
import org.springframework.ai.mcp.annotation.McpTool
import org.springframework.ai.mcp.annotation.McpToolParam
import org.springframework.stereotype.Component

@Component
class WikiReadTools(
    private val searchService: WikiSearchService,
    private val resourceService: WikiResourceService,
    private val contextPackService: WikiContextPackService,
    private val triageService: WikiTriageService,
    private val lintService: WikiLintService,
) {
    @McpTool(
        name = "wiki_search",
        title = "Search LLM Wiki",
        description = "Read-only natural language and structured search over the Plady LLM Wiki. Returns wiki:// resource URIs; never mutates files or git state.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiSearch(
        @McpToolParam(description = "Natural language or keyword query.", required = true) query: String?,
        @McpToolParam(required = false, description = "Optional document type filters: raw, source, topic, adr, spec, review, backlog.") types: List<String>?,
        @McpToolParam(required = false, description = "Optional status filters such as Proposed, Accepted, Draft.") statuses: List<String>?,
        @McpToolParam(required = false, description = "Optional tag filters without # prefix.") tags: List<String>?,
        @McpToolParam(required = false, description = "Optional Linear issue identifier such as PLA-229.") linearIssueId: String?,
        @McpToolParam(required = false, description = "Maximum results, 1-50.") limit: Int?,
    ): WikiSearchResponse = searchService.search(
        query = query,
        types = types.orEmpty(),
        statuses = statuses.orEmpty(),
        tags = tags.orEmpty(),
        linearIssueId = linearIssueId,
        limit = limit ?: 10,
    )

    @McpTool(
        name = "wiki_get",
        title = "Get LLM Wiki Resource",
        description = "Dereference a wiki:// URI and return body, frontmatter, related wikilinks, and GitHub permalink metadata. Read-only.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiGet(
        @McpToolParam(description = "wiki:// resource URI.", required = true) uri: String?,
        @McpToolParam(required = false, description = "Whether to include markdown body content. Defaults true.") includeContent: Boolean?,
        @McpToolParam(required = false, description = "Whether to include frontmatter metadata. Defaults true.") includeFrontmatter: Boolean?,
    ): WikiGetResponse = resourceService.get(
        uri = uri,
        includeContent = includeContent ?: true,
        includeFrontmatter = includeFrontmatter ?: true,
    )

    @McpTool(
        name = "wiki_get_related_context",
        title = "Get Linear Context Pack",
        description = "Build a deterministic context pack for a Linear issue from related ADR, Tech Spec, Review, Decision Backlog, Source, and Topic pages. Read-only.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiGetRelatedContext(
        @McpToolParam(description = "Linear issue identifier such as PLA-229.", required = true) linearIssueId: String?,
        @McpToolParam(required = false, description = "Optional document type filters.") types: List<String>?,
        @McpToolParam(required = false, description = "Whether to include open questions. Defaults true.") includeOpenQuestions: Boolean?,
        @McpToolParam(required = false, description = "Maximum context items, 1-30.") limit: Int?,
    ): WikiRelatedContextResponse = contextPackService.getRelatedContext(
        linearIssueId = linearIssueId,
        types = types.orEmpty(),
        includeOpenQuestions = includeOpenQuestions ?: true,
        limit = limit ?: 10,
    )

    @McpTool(
        name = "wiki_triage",
        title = "Triage Wiki Documentation Need",
        description = "Classify implementation context into ADR, Tech Spec, or Decision Backlog needs. Read-only recommendation; never writes files.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiTriage(
        @McpToolParam(description = "Implementation or issue summary to triage.", required = true) summary: String?,
        @McpToolParam(required = false, description = "Optional Linear issue identifier.") linearIssueId: String?,
        @McpToolParam(required = false, description = "Optional changed areas such as api, db, security.") changedAreas: List<String>?,
    ): WikiTriageResponse = triageService.triage(summary, linearIssueId, changedAreas.orEmpty())

    @McpTool(
        name = "wiki_lint",
        title = "Lint LLM Wiki",
        description = "Read-only lint report for stale Proposed ADR/Spec docs, metadata drift, thin docs, and wikilink issues. Does not mutate files.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiLint(
        @McpToolParam(required = false, description = "Optional scope label or path hint.") scope: String?,
        @McpToolParam(required = false, description = "Optional document type filters.") types: List<String>?,
        @McpToolParam(required = false, description = "Optional since marker reserved for future timestamp filtering.") since: String?,
        @McpToolParam(required = false, description = "Maximum findings, 1-250.") limit: Int?,
    ): WikiLintResponse = lintService.lint(scope, types.orEmpty(), since, limit ?: 50)
}
