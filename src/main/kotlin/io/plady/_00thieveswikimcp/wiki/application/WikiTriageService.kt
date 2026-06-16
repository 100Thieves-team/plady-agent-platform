package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiTriageResponse
import org.springframework.stereotype.Service

@Service
class WikiTriageService {
    fun triage(summary: String?, linearIssueId: String? = null, changedAreas: List<String> = emptyList()): WikiTriageResponse {
        val text = listOfNotNull(summary, linearIssueId, changedAreas.joinToString(" ")).joinToString(" ").lowercase()
        val rationale = mutableListOf<String>()
        val actions = mutableListOf<String>()

        val decisionKeywords = listOf("adr", "decision", "결정", "tradeoff", "대안", "supersede", "accepted")
        val specKeywords = listOf("api", "db", "schema", "security", "auth", "async", "event", "payment", "credit", "metric", "로그", "상태", "ai", "llm", "mcp")
        val backlogKeywords = listOf("open question", "미정", "todo", "follow-up", "defer", "나중", "질문")

        val needsAdr = decisionKeywords.any { text.contains(it) }
        val needsTechSpec = specKeywords.any { text.contains(it) }
        val needsBacklog = backlogKeywords.any { text.contains(it) }

        if (needsAdr) {
            rationale += "The change appears to involve a durable technical decision or accepted/superseded ADR policy."
            actions += "If the decision is new or changes an accepted decision, draft a Proposed ADR instead of editing an Accepted ADR decision body."
        }
        if (needsTechSpec) {
            rationale += "The change touches implementation contracts such as API, DB, security, async flow, AI I/O, metrics, or state."
            actions += "Create or update a Tech Spec draft, then apply it through wiki_run_task and pending approval."
        }
        if (needsBacklog) {
            rationale += "The change contains unresolved questions or deferred follow-ups."
            actions += "Record unresolved decisions in the Decision Backlog or include them in the context pack output."
        }
        if (rationale.isEmpty()) {
            rationale += "No strong ADR/Tech Spec/Backlog signal was found by deterministic keyword triage."
            actions += "Proceed with implementation, but run wiki_get_related_context before coding if a Linear issue is available."
        }

        return WikiTriageResponse(
            ok = true,
            needsAdr = needsAdr,
            needsTechSpec = needsTechSpec,
            needsBacklog = needsBacklog,
            rationale = rationale,
            suggestedNextActions = actions,
        )
    }
}
