package io.plady._00thieveswikimcp.wiki.prompt

import io.plady._00thieveswikimcp.wiki.application.WikiDraftService
import org.springframework.ai.mcp.annotation.McpArg
import org.springframework.ai.mcp.annotation.McpPrompt
import org.springframework.stereotype.Component

@Component
class WikiPrompts(
    private val draftService: WikiDraftService,
) {
    @McpPrompt(
        name = "wiki_create_adr_draft",
        title = "Create Proposed ADR Draft",
        description = "Create a Proposed ADR draft. This prompt never writes files; apply through wiki_run_task for pending approval.",
    )
    fun createAdrDraft(
        @McpArg(description = "Draft title.", required = true) title: String?,
        @McpArg(description = "Decision context or background.") context: String?,
        @McpArg(description = "Decision drivers to include.") decisionDrivers: List<String>?,
        @McpArg(description = "Considered options and tradeoffs.") options: List<String>?,
        @McpArg(description = "Optional Linear issue identifier.") linearIssueId: String?,
        @McpArg(description = "Optional wiki:// context URIs.") contextUris: List<String>?,
    ): String = draftService.createAdrDraft(title, context, decisionDrivers.orEmpty(), options.orEmpty(), linearIssueId, contextUris.orEmpty()).markdown

    @McpPrompt(
        name = "wiki_create_spec_draft",
        title = "Create Tech Spec Draft",
        description = "Create a Tech Spec draft. This prompt never writes files; apply through wiki_run_task for pending approval.",
    )
    fun createSpecDraft(
        @McpArg(description = "Draft title.", required = true) title: String?,
        @McpArg(description = "Problem statement.") problem: String?,
        @McpArg(description = "Spec goals.") goals: List<String>?,
        @McpArg(description = "Concrete requirements.") requirements: List<String>?,
        @McpArg(description = "Technical or operational constraints.") constraints: List<String>?,
        @McpArg(description = "Optional Linear issue identifier.") linearIssueId: String?,
        @McpArg(description = "Optional wiki:// context URIs.") contextUris: List<String>?,
    ): String = draftService.createSpecDraft(title, problem, goals.orEmpty(), requirements.orEmpty(), constraints.orEmpty(), linearIssueId, contextUris.orEmpty()).markdown

    @McpPrompt(
        name = "wiki_summarize_review",
        title = "Summarize Review",
        description = "Create a Review Summary draft from review or meeting text. File writes must go through wiki_run_task.",
    )
    fun summarizeReview(@McpArg(description = "Review or meeting text to summarize.", required = true) reviewText: String?, @McpArg(description = "Optional review context.") context: String?): String = draftService.summarizeReview(reviewText, context).markdown

    @McpPrompt(
        name = "wiki_maintain_decision_backlog",
        title = "Maintain Decision Backlog",
        description = "Create a Decision Backlog maintenance proposal. File writes must go through wiki_run_task.",
    )
    fun maintainDecisionBacklog(@McpArg(description = "Context for backlog maintenance.", required = true) context: String?, @McpArg(description = "Specific maintenance request.") request: String?): String = draftService.maintainDecisionBacklog(context, request).markdown

    @McpPrompt(
        name = "wiki_propose_doc_patch",
        title = "Propose Wiki Document Patch",
        description = "Create a document patch proposal for target wiki:// URIs. File writes must go through wiki_run_task.",
    )
    fun proposeDocPatch(@McpArg(description = "Target wiki:// URIs.") targetUris: List<String>?, @McpArg(description = "Requested document change.", required = true) requestedChange: String?): String = draftService.proposeDocPatch(targetUris.orEmpty(), requestedChange).markdown
}
