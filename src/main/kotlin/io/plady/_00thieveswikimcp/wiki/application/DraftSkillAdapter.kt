package io.plady._00thieveswikimcp.wiki.application

/**
 * Integration seam for the separately-developed Plady ADR/Tech Spec/Review skills.
 *
 * PLA-229 keeps MCP prompt wrappers stable even if the concrete skill runtime is wired
 * later. Adapters return null when the backing skill is unavailable; the deterministic
 * local draft templates in [WikiDraftService] then act as a safe fallback and still do
 * not write files directly.
 */
interface DraftSkillAdapter {
    val available: Boolean

    fun createAdrDraft(request: AdrDraftRequest): String? = null
    fun createSpecDraft(request: SpecDraftRequest): String? = null
    fun summarizeReview(request: ReviewSummaryRequest): String? = null
    fun maintainDecisionBacklog(request: DecisionBacklogRequest): String? = null
    fun proposeDocPatch(request: DocPatchRequest): String? = null
}

data class AdrDraftRequest(
    val title: String,
    val context: String?,
    val decisionDrivers: List<String>,
    val options: List<String>,
    val linearIssueId: String?,
    val contextUris: List<String>,
)

data class SpecDraftRequest(
    val title: String,
    val problem: String?,
    val goals: List<String>,
    val requirements: List<String>,
    val constraints: List<String>,
    val linearIssueId: String?,
    val contextUris: List<String>,
)

data class ReviewSummaryRequest(val reviewText: String?, val context: String?)

data class DecisionBacklogRequest(val context: String?, val request: String?)

data class DocPatchRequest(val targetUris: List<String>, val requestedChange: String?)
