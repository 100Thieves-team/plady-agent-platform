package io.plady._00thieveswikimcp.wiki.tool

import io.plady._00thieveswikimcp.wiki.api.WikiAbortPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiCommitPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiExtendPendingLockResponse
import io.plady._00thieveswikimcp.wiki.api.WikiPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiRunTaskResponse
import io.plady._00thieveswikimcp.wiki.application.WikiWorkflowService
import org.springframework.ai.mcp.annotation.McpTool
import org.springframework.ai.mcp.annotation.McpToolParam
import org.springframework.stereotype.Component

@Component
class WikiWorkflowTools(
    private val workflowService: WikiWorkflowService,
) {
    @McpTool(
        name = "wiki_run_task",
        title = "Run LLM Wiki Task",
        description = "Acquire the repo workflow entrypoint for ingest/maintain/doc-write tasks. Mutating calls either create a real pending change from a dirty working tree or fail closed; they never fake success or expose git primitives.",
        annotations = McpTool.McpAnnotations(readOnlyHint = false, destructiveHint = false, idempotentHint = false, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiRunTask(
        @McpToolParam(description = "Task type such as ingest, maintain, doc_patch, adr_review.", required = true) taskType: String?,
        @McpToolParam(description = "Human-readable task instructions. Required for agent runtime execution.", required = true) instructions: String?,
        @McpToolParam(required = false, description = "Optional raw source text or external source pointer.") source: String?,
        @McpToolParam(required = false, description = "Optional wiki:// context URIs.") contextUris: List<String>?,
        @McpToolParam(required = false, description = "Optional Linear issue identifier.") linearIssueId: String?,
        @McpToolParam(required = false, description = "Optional timeout in seconds.") timeoutSeconds: Long?,
        @McpToolParam(required = false, description = "If true, return a dry-run task plan and validation without mutation.") dryRun: Boolean?,
    ): WikiRunTaskResponse = workflowService.runTask(
        taskType = taskType,
        instructions = instructions,
        source = source,
        contextUris = contextUris.orEmpty(),
        linearIssueId = linearIssueId,
        timeoutSeconds = timeoutSeconds,
        dryRun = dryRun ?: false,
    )

    @McpTool(
        name = "wiki_get_pending",
        title = "Get Pending Wiki Change",
        description = "Read pending approval state, diff snapshot, validation result, touched files, and lock expiry by pending_change_id.",
        annotations = McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiGetPending(
        @McpToolParam(description = "Stable pending_change_id.", required = true) pendingChangeId: String?,
    ): WikiPendingResponse = workflowService.getPending(pendingChangeId)

    @McpTool(
        name = "wiki_commit_pending",
        title = "Commit Pending Wiki Change",
        description = "Human approval gate. Deterministically validates, adds allowed files, commits, and optionally pushes a pending change. The client cannot specify file lists, git commands, or commit messages.",
        annotations = McpTool.McpAnnotations(readOnlyHint = false, destructiveHint = false, idempotentHint = false, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiCommitPending(
        @McpToolParam(description = "Stable pending_change_id.", required = true) pendingChangeId: String?,
        @McpToolParam(required = false, description = "Optional human approver name.") approvedBy: String?,
        @McpToolParam(required = false, description = "Optional approval note stored in deterministic commit message.") approvalNote: String?,
    ): WikiCommitPendingResponse = workflowService.commitPending(pendingChangeId, approvedBy, approvalNote)

    @McpTool(
        name = "wiki_abort_pending",
        title = "Abort Pending Wiki Change",
        description = "Reject or timeout a pending change. Archives the current diff snapshot and runs reset/clean through the Spring deterministic layer only.",
        annotations = McpTool.McpAnnotations(readOnlyHint = false, destructiveHint = true, idempotentHint = false, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiAbortPending(
        @McpToolParam(description = "Stable pending_change_id.", required = true) pendingChangeId: String?,
        @McpToolParam(required = false, description = "Optional abort reason.") reason: String?,
    ): WikiAbortPendingResponse = workflowService.abortPending(pendingChangeId, reason)

    @McpTool(
        name = "wiki_extend_pending_lock",
        title = "Extend Pending Wiki Lock",
        description = "Extend the lock TTL for a pending approval when humans need more review time.",
        annotations = McpTool.McpAnnotations(readOnlyHint = false, destructiveHint = false, idempotentHint = false, openWorldHint = false),
        generateOutputSchema = true,
    )
    fun wikiExtendPendingLock(
        @McpToolParam(description = "Stable pending_change_id.", required = true) pendingChangeId: String?,
        @McpToolParam(description = "Seconds to extend by, clamped by server policy.", required = true) extendBySeconds: Long?,
    ): WikiExtendPendingLockResponse = workflowService.extendPendingLock(pendingChangeId, extendBySeconds)
}
