package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.AdrDraftRequest
import io.plady._00thieveswikimcp.wiki.application.DecisionBacklogRequest
import io.plady._00thieveswikimcp.wiki.application.DocPatchRequest
import io.plady._00thieveswikimcp.wiki.application.DraftSkillAdapter
import io.plady._00thieveswikimcp.wiki.application.ReviewSummaryRequest
import io.plady._00thieveswikimcp.wiki.application.SpecDraftRequest
import io.plady._00thieveswikimcp.wiki.application.WikiDraftService
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WikiDraftPolicyTest {
    private val service = WikiDraftService()

    @Test
    fun `adr draft defaults to Proposed and warns about accepted ADR policy`() {
        val draft = service.createAdrDraft("Choose MCP workflow", context = "Need deterministic approval.")
        assertTrue(draft.markdown.contains("status: Proposed"))
        assertTrue(draft.markdown.contains("Do not mark it Accepted"))
        assertTrue(draft.metadata.getValue("policy").contains("superseding ADR"))
    }

    @Test
    fun `accepted ADR direct edit is blocked`() {
        assertTrue(service.acceptedAdrEditBlockedMessage("wiki://adr/001").contains("blocked"))
        assertTrue(service.acceptedAdrEditBlockedMessage("wiki://adr/001").contains("supersedes"))
    }

    @Test
    fun `draft prompt services only produce drafts and direct writes through wiki_run_task`() {
        val drafts = listOf(
            service.createAdrDraft("ADR", contextUris = listOf("wiki://spec/pla-229")),
            service.createSpecDraft("Spec", linearIssueId = "PLA-229"),
            service.summarizeReview("Looks good", "Review context"),
            service.maintainDecisionBacklog("Open decisions"),
            service.proposeDocPatch(listOf("wiki://topic/mcp"), "Clarify MCP workflow"),
        )

        assertEquals(
            setOf(
                "wiki_create_adr_draft",
                "wiki_create_spec_draft",
                "wiki_summarize_review",
                "wiki_maintain_decision_backlog",
                "wiki_propose_doc_patch",
            ),
            drafts.map { it.name }.toSet(),
        )
        drafts.forEach { draft ->
            assertTrue(draft.ok)
            assertTrue(draft.markdown.isNotBlank())
            assertTrue(draft.writePath.contains("wiki_run_task"))
            assertTrue(draft.writePath.contains("never write files directly"))
        }
    }

    @Test
    fun `external draft skill adapter is used when available while preserving prompt contract`() {
        val adapter = RecordingDraftSkillAdapter()
        val adapted = WikiDraftService(adapter).createAdrDraft(
            title = "Adapter ADR",
            context = "Use the dedicated ADR skill",
            decisionDrivers = listOf("auditability"),
            options = listOf("pending approval"),
            linearIssueId = "PLA-229",
            contextUris = listOf("wiki://topic/mcp"),
        )

        assertEquals("# Adapter ADR\n\nexternal adapter draft", adapted.markdown)
        assertEquals("external", adapted.metadata["adapter"])
        assertEquals("Adapter ADR", adapter.adrRequest?.title)
        assertEquals("PLA-229", adapter.adrRequest?.linearIssueId)
        assertTrue(adapted.writePath.contains("wiki_run_task"))
    }

    private class RecordingDraftSkillAdapter : DraftSkillAdapter {
        override val available: Boolean = true
        var adrRequest: AdrDraftRequest? = null

        override fun createAdrDraft(request: AdrDraftRequest): String {
            adrRequest = request
            return "# ${request.title}\n\nexternal adapter draft"
        }

        override fun createSpecDraft(request: SpecDraftRequest): String? = null
        override fun summarizeReview(request: ReviewSummaryRequest): String? = null
        override fun maintainDecisionBacklog(request: DecisionBacklogRequest): String? = null
        override fun proposeDocPatch(request: DocPatchRequest): String? = null
    }
}
