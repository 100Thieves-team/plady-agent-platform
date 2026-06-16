package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiDraftResponse
import org.springframework.stereotype.Service
import java.time.LocalDate

@Service
class WikiDraftService(
    private val adapter: DraftSkillAdapter = UnavailableDraftSkillAdapter(),
) {
    fun createAdrDraft(
        title: String?,
        context: String? = null,
        decisionDrivers: List<String> = emptyList(),
        options: List<String> = emptyList(),
        linearIssueId: String? = null,
        contextUris: List<String> = emptyList(),
    ): WikiDraftResponse {
        val safeTitle = title?.takeIf { it.isNotBlank() } ?: "Untitled ADR"
        adapter.createAdrDraft(
            AdrDraftRequest(
                title = safeTitle,
                context = context,
                decisionDrivers = decisionDrivers,
                options = options,
                linearIssueId = linearIssueId,
                contextUris = contextUris,
            ),
        )?.let { adapterMarkdown ->
            return WikiDraftResponse(
                ok = true,
                name = "wiki_create_adr_draft",
                title = safeTitle,
                markdown = adapterMarkdown,
                metadata = mapOf("adapter" to "external", "status" to "Proposed"),
            )
        }

        val markdown = buildString {
            appendLine("---")
            appendLine("type: ADR")
            appendLine("status: Proposed")
            appendLine("date: ${LocalDate.now()}")
            linearIssueId?.takeIf { it.isNotBlank() }?.let { appendLine("linear_issue: $it") }
            if (contextUris.isNotEmpty()) {
                appendLine("related_documents:")
                contextUris.forEach { appendLine("  - \"$it\"") }
            }
            appendLine("---")
            appendLine()
            appendLine("# $safeTitle")
            appendLine()
            appendLine("## Status")
            appendLine("Proposed")
            appendLine()
            appendLine("## Context")
            appendLine(context?.takeIf { it.isNotBlank() } ?: "Describe the decision context and constraints.")
            appendLine()
            appendLine("## Decision Drivers")
            appendChecklist(decisionDrivers, "Document the driver.")
            appendLine()
            appendLine("## Considered Options")
            appendChecklist(options, "Document an option and tradeoff.")
            appendLine()
            appendLine("## Decision")
            appendLine("This ADR is Proposed. Do not mark it Accepted without team approval.")
            appendLine()
            appendLine("## Consequences")
            appendLine("- Positive:")
            appendLine("- Negative:")
            appendLine("- Follow-ups:")
        }
        return WikiDraftResponse(
            ok = true,
            name = "wiki_create_adr_draft",
            title = safeTitle,
            markdown = markdown,
            metadata = mapOf("status" to "Proposed", "policy" to "Accepted ADR Decision bodies must not be edited directly; create a superseding ADR instead."),
        )
    }

    fun createSpecDraft(
        title: String?,
        problem: String? = null,
        goals: List<String> = emptyList(),
        requirements: List<String> = emptyList(),
        constraints: List<String> = emptyList(),
        linearIssueId: String? = null,
        contextUris: List<String> = emptyList(),
    ): WikiDraftResponse {
        val safeTitle = title?.takeIf { it.isNotBlank() } ?: "Untitled Tech Spec"
        adapter.createSpecDraft(
            SpecDraftRequest(
                title = safeTitle,
                problem = problem,
                goals = goals,
                requirements = requirements,
                constraints = constraints,
                linearIssueId = linearIssueId,
                contextUris = contextUris,
            ),
        )?.let { adapterMarkdown ->
            return WikiDraftResponse(
                ok = true,
                name = "wiki_create_spec_draft",
                title = safeTitle,
                markdown = adapterMarkdown,
                metadata = mapOf("adapter" to "external"),
            )
        }

        val markdown = buildString {
            appendLine("---")
            appendLine("type: Tech Spec")
            appendLine("status: Draft")
            appendLine("date: ${LocalDate.now()}")
            linearIssueId?.takeIf { it.isNotBlank() }?.let { appendLine("linear_issue: $it") }
            if (contextUris.isNotEmpty()) {
                appendLine("related_documents:")
                contextUris.forEach { appendLine("  - \"$it\"") }
            }
            appendLine("---")
            appendLine()
            appendLine("# $safeTitle")
            appendLine()
            appendLine("## Problem")
            appendLine(problem?.takeIf { it.isNotBlank() } ?: "Describe what is missing, broken, or insufficient.")
            appendLine()
            appendLine("## Goals")
            appendChecklist(goals, "Document a goal.")
            appendLine()
            appendLine("## Non-goals")
            appendLine("- ")
            appendLine()
            appendLine("## Requirements")
            appendChecklist(requirements, "Document a concrete requirement.")
            appendLine()
            appendLine("## Constraints")
            appendChecklist(constraints, "Document a technical or operational constraint.")
            appendLine()
            appendLine("## Design")
            appendLine("Describe API, data model, state transitions, async flow, AI I/O, security, logging, metrics, and operational concerns as relevant.")
            appendLine()
            appendLine("## Verification")
            appendLine("- Unit/integration tests:")
            appendLine("- Manual checks:")
        }
        return WikiDraftResponse(ok = true, name = "wiki_create_spec_draft", title = safeTitle, markdown = markdown)
    }

    fun summarizeReview(reviewText: String?, context: String? = null): WikiDraftResponse {
        val title = "Review Summary ${LocalDate.now()}"
        adapter.summarizeReview(ReviewSummaryRequest(reviewText, context))?.let { adapterMarkdown ->
            return WikiDraftResponse(
                ok = true,
                name = "wiki_summarize_review",
                title = title,
                markdown = adapterMarkdown,
                metadata = mapOf("adapter" to "external"),
            )
        }

        val markdown = buildString {
            appendLine("---")
            appendLine("type: Review Summary")
            appendLine("date: ${LocalDate.now()}")
            appendLine("---")
            appendLine()
            appendLine("# $title")
            appendLine()
            appendLine("## Context")
            appendLine(context?.takeIf { it.isNotBlank() } ?: "Review context not provided.")
            appendLine()
            appendLine("## Notes")
            appendLine(reviewText?.takeIf { it.isNotBlank() } ?: "Review text not provided.")
            appendLine()
            appendLine("## Decisions")
            appendLine("- ")
            appendLine()
            appendLine("## Follow-ups")
            appendLine("- ")
        }
        return WikiDraftResponse(ok = true, name = "wiki_summarize_review", title = title, markdown = markdown)
    }

    fun maintainDecisionBacklog(context: String?, request: String? = null): WikiDraftResponse {
        val title = "Decision Backlog Update"
        adapter.maintainDecisionBacklog(DecisionBacklogRequest(context, request))?.let { adapterMarkdown ->
            return WikiDraftResponse(
                ok = true,
                name = "wiki_maintain_decision_backlog",
                title = title,
                markdown = adapterMarkdown,
                metadata = mapOf("adapter" to "external"),
            )
        }

        val markdown = buildString {
            appendLine("## Proposed Decision Backlog Update")
            appendLine()
            appendLine("### Context")
            appendLine(context?.takeIf { it.isNotBlank() } ?: "Context not provided.")
            appendLine()
            appendLine("### Requested maintenance")
            appendLine(request?.takeIf { it.isNotBlank() } ?: "Identify open decisions, stale proposed docs, and follow-up candidates.")
            appendLine()
            appendLine("### Candidate entries")
            appendLine("- [ ] ")
        }
        return WikiDraftResponse(ok = true, name = "wiki_maintain_decision_backlog", title = title, markdown = markdown)
    }

    fun proposeDocPatch(targetUris: List<String> = emptyList(), requestedChange: String?): WikiDraftResponse {
        val title = "Document Patch Proposal"
        adapter.proposeDocPatch(DocPatchRequest(targetUris, requestedChange))?.let { adapterMarkdown ->
            return WikiDraftResponse(
                ok = true,
                name = "wiki_propose_doc_patch",
                title = title,
                markdown = adapterMarkdown,
                metadata = mapOf("adapter" to "external"),
            )
        }

        val markdown = buildString {
            appendLine("## Proposed Document Patch")
            appendLine()
            appendLine("### Target resources")
            if (targetUris.isEmpty()) appendLine("- <add wiki:// target>") else targetUris.forEach { appendLine("- $it") }
            appendLine()
            appendLine("### Requested change")
            appendLine(requestedChange?.takeIf { it.isNotBlank() } ?: "Describe the requested change.")
            appendLine()
            appendLine("### Application path")
            appendLine("Apply this through wiki_run_task so the result becomes a pending change with diff snapshot and approval gate.")
        }
        return WikiDraftResponse(ok = true, name = "wiki_propose_doc_patch", title = title, markdown = markdown)
    }

    fun acceptedAdrEditBlockedMessage(targetUri: String?): String =
        "Direct edits to an Accepted ADR Decision body are blocked. Create a new Proposed ADR that supersedes ${targetUri ?: "the accepted ADR"}, then mark the old ADR Superseded only after team approval."

    private fun StringBuilder.appendChecklist(values: List<String>, placeholder: String) {
        if (values.isEmpty()) appendLine("- $placeholder") else values.forEach { appendLine("- $it") }
    }
}
