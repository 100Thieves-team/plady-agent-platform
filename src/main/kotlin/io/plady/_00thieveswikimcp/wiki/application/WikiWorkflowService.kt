package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.WikiAbortPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiCommitPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiDiffSnapshot
import io.plady._00thieveswikimcp.wiki.api.WikiExtendPendingLockResponse
import io.plady._00thieveswikimcp.wiki.api.WikiPendingResponse
import io.plady._00thieveswikimcp.wiki.api.WikiRunTaskResponse
import io.plady._00thieveswikimcp.wiki.api.WikiToolError
import io.plady._00thieveswikimcp.wiki.api.WikiValidationResult
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.GitRepositoryService
import org.springframework.stereotype.Service
import java.time.Instant

@Service
class WikiWorkflowService(
    private val properties: WikiProperties,
    private val pendingService: PendingChangeService,
    private val git: GitRepositoryService,
) {
    fun runTask(
        taskType: String?,
        instructions: String?,
        source: String? = null,
        contextUris: List<String> = emptyList(),
        linearIssueId: String? = null,
        timeoutSeconds: Long? = null,
        dryRun: Boolean = false,
    ): WikiRunTaskResponse {
        val taskSummary = buildTaskSummary(taskType, instructions, linearIssueId)
        val existing = pendingService.activePending()
        if (existing != null) {
            return WikiRunTaskResponse(
                ok = false,
                status = "BUSY",
                pendingChangeId = existing.pendingChangeId,
                summary = "Another pending change is already awaiting approval.",
                touchedFiles = existing.touchedFiles,
                diffSnapshot = pendingService.toDiffSnapshot(existing),
                validation = WikiValidationResult(existing.validationOk, existing.validationIssues),
                lockExpiresAt = existing.lockExpiresAt,
                error = WikiToolError("PENDING_CHANGE_EXISTS", "A pending approval is already holding the repo write lock.", retryable = true),
            )
        }

        if (dryRun) {
            return WikiRunTaskResponse(
                ok = true,
                status = "DRY_RUN",
                summary = taskSummary,
                validation = pendingService.currentValidation(),
            )
        }

        if (!properties.workflow.agentRuntimeEnabled) {
            val dirtyFiles = git.touchedFiles()
            if (dirtyFiles.isEmpty() || !properties.workflow.captureExistingDirty) {
                return WikiRunTaskResponse(
                    ok = false,
                    status = "PENDING_ENGINE_UNAVAILABLE",
                    summary = taskSummary,
                    validation = pendingService.currentValidation(),
                    error = WikiToolError(
                        code = "PENDING_ENGINE_UNAVAILABLE",
                        message = "Claude Agent Runtime is not wired. wiki_run_task fails closed unless an already-dirty repo is explicitly captured.",
                        retryable = false,
                    ),
                )
            }
        }

        val (record, snapshot) = pendingService.createFromCurrentDirty(taskSummary)
        return WikiRunTaskResponse(
            ok = record.validationOk,
            status = record.status,
            pendingChangeId = record.pendingChangeId,
            summary = record.summary,
            touchedFiles = record.touchedFiles,
            diffSnapshot = snapshot,
            validation = WikiValidationResult(record.validationOk, record.validationIssues),
            lockExpiresAt = record.lockExpiresAt,
            error = if (record.validationOk) null else WikiToolError("VALIDATION_FAILED", "Pending change was captured but validation failed."),
        )
    }

    fun getPending(pendingChangeId: String?): WikiPendingResponse {
        if (pendingChangeId.isNullOrBlank()) {
            return WikiPendingResponse(ok = false, error = WikiToolError("INVALID_PENDING_ID", "pendingChangeId is required"))
        }
        val record = pendingService.get(pendingChangeId)
            ?: return WikiPendingResponse(ok = false, pendingChangeId = pendingChangeId, error = WikiToolError("PENDING_NOT_FOUND", "No pending change found."))
        return WikiPendingResponse(
            ok = true,
            pendingChangeId = record.pendingChangeId,
            status = record.status,
            summary = record.summary,
            diff = pendingService.readDiff(record),
            diffSnapshot = pendingService.toDiffSnapshot(record),
            validation = WikiValidationResult(record.validationOk, record.validationIssues),
            touchedFiles = record.touchedFiles,
            lockExpiresAt = record.lockExpiresAt,
        )
    }

    fun commitPending(pendingChangeId: String?, approvedBy: String? = null, approvalNote: String? = null): WikiCommitPendingResponse {
        val id = pendingChangeId.orEmpty()
        val record = pendingService.get(id)
            ?: return WikiCommitPendingResponse(false, id, "NOT_FOUND", error = WikiToolError("PENDING_NOT_FOUND", "No pending change found."))
        if (record.status != "PENDING_APPROVAL") {
            return WikiCommitPendingResponse(false, id, record.status, error = WikiToolError("INVALID_PENDING_STATUS", "Only PENDING_APPROVAL can be committed."))
        }
        if (record.lockExpiresAt.isBefore(Instant.now())) {
            val abort = abortPending(id, reason = "lock expired before approval")
            return WikiCommitPendingResponse(
                ok = false,
                pendingChangeId = id,
                status = abort.status,
                error = WikiToolError(
                    code = "LOCK_EXPIRED",
                    message = "Pending lock expired; timeout abort reset was attempted.",
                    details = mapOf(
                        "archivedDiffSnapshotId" to abort.archivedDiffSnapshotId.orEmpty(),
                        "resetPerformed" to abort.resetPerformed.toString(),
                    ),
                ),
            )
        }
        if (!pendingService.validateCurrentMatches(record)) {
            val conflictedSnapshot = pendingService.currentSnapshotFor(record, "conflicted-${Instant.now().toEpochMilli()}")
            val conflicted = pendingService.update(record.copy(status = "CONFLICTED", updatedAt = Instant.now()))
            return WikiCommitPendingResponse(
                ok = false,
                pendingChangeId = id,
                status = conflicted.status,
                validation = WikiValidationResult(false),
                error = WikiToolError("DIFF_CHANGED", "Working tree diff no longer matches the pending snapshot: ${conflictedSnapshot.id}"),
            )
        }
        val validation = pendingService.currentValidation()
        if (!validation.ok) {
            return WikiCommitPendingResponse(false, id, record.status, validation = validation, error = WikiToolError("VALIDATION_FAILED", "Current working tree failed deterministic validation."))
        }
        if (!properties.workflow.localCommitEnabled) {
            return WikiCommitPendingResponse(false, id, record.status, validation = validation, error = WikiToolError("COMMIT_DISABLED", "Local commit is disabled by configuration."))
        }

        val add = git.add(record.touchedFiles)
        if (!add.ok) {
            return WikiCommitPendingResponse(false, id, record.status, validation = validation, error = WikiToolError("GIT_ADD_FAILED", add.stderr.ifBlank { add.stdout }))
        }
        val message = buildCommitMessage(record.summary, approvedBy, approvalNote)
        val commit = git.commit(message)
        if (!commit.ok) {
            return WikiCommitPendingResponse(false, id, record.status, validation = validation, error = WikiToolError("GIT_COMMIT_FAILED", commit.stderr.ifBlank { commit.stdout }))
        }
        val commitSha = git.headSha()
        val postCommitStatus = git.statusPorcelain()
        if (postCommitStatus.isNotBlank()) {
            return WikiCommitPendingResponse(false, id, record.status, commitSha = commitSha, validation = validation, error = WikiToolError("POST_COMMIT_DIRTY", "Repository is not clean after deterministic commit: $postCommitStatus"))
        }
        val pushResult = if (properties.workflow.pushEnabled) {
            val push = git.push(git.currentBranch())
            if (!push.ok) "push failed: ${push.stderr.ifBlank { push.stdout }}" else "pushed"
        } else {
            "skipped: push disabled"
        }
        val committed = pendingService.update(record.copy(status = "COMMITTED", commitSha = commitSha, updatedAt = Instant.now()))
        return WikiCommitPendingResponse(
            ok = true,
            pendingChangeId = id,
            status = committed.status,
            commitSha = commitSha,
            prUrl = committed.prUrl,
            pushResult = pushResult,
            validation = validation,
        )
    }

    fun abortPending(pendingChangeId: String?, reason: String? = null): WikiAbortPendingResponse {
        val id = pendingChangeId.orEmpty()
        val record = pendingService.get(id)
            ?: return WikiAbortPendingResponse(false, id, "NOT_FOUND", resetPerformed = false, error = WikiToolError("PENDING_NOT_FOUND", "No pending change found."))
        if (record.status != "PENDING_APPROVAL" && record.status != "CONFLICTED") {
            return WikiAbortPendingResponse(false, id, record.status, resetPerformed = false, error = WikiToolError("INVALID_PENDING_STATUS", "Only PENDING_APPROVAL or CONFLICTED can be aborted."))
        }
        val snapshot = pendingService.writeAbortSnapshot(record)
        val reset = git.resetHardAndClean()
        val status = if (record.lockExpiresAt.isBefore(Instant.now())) "TIMED_OUT" else "ABORTED"
        val updated = pendingService.update(record.copy(status = status, updatedAt = Instant.now()))
        return WikiAbortPendingResponse(
            ok = reset.ok,
            pendingChangeId = id,
            status = updated.status,
            archivedDiffSnapshotId = snapshot.id,
            resetPerformed = reset.ok,
            error = if (reset.ok) null else WikiToolError("GIT_RESET_FAILED", reset.stderr.ifBlank { reset.stdout }),
        )
    }

    fun extendPendingLock(pendingChangeId: String?, extendBySeconds: Long?): WikiExtendPendingLockResponse {
        val id = pendingChangeId.orEmpty()
        val record = pendingService.get(id)
            ?: return WikiExtendPendingLockResponse(false, id, "NOT_FOUND", error = WikiToolError("PENDING_NOT_FOUND", "No pending change found."))
        if (record.status != "PENDING_APPROVAL") {
            return WikiExtendPendingLockResponse(false, id, record.status, record.lockExpiresAt, WikiToolError("INVALID_PENDING_STATUS", "Only PENDING_APPROVAL lock can be extended."))
        }
        val seconds = (extendBySeconds ?: properties.workflow.defaultLockTtlSeconds).coerceIn(60, properties.workflow.maxLockExtensionSeconds)
        val newExpiry = maxOf(record.lockExpiresAt, Instant.now()).plusSeconds(seconds)
        val updated = pendingService.update(record.copy(lockExpiresAt = newExpiry, updatedAt = Instant.now()))
        return WikiExtendPendingLockResponse(true, id, updated.status, updated.lockExpiresAt)
    }

    private fun buildTaskSummary(taskType: String?, instructions: String?, linearIssueId: String?): String = buildString {
        append(taskType?.takeIf { it.isNotBlank() } ?: "wiki_task")
        linearIssueId?.takeIf { it.isNotBlank() }?.let { append(" for ").append(it) }
        instructions?.takeIf { it.isNotBlank() }?.let { append(": ").append(it.take(240)) }
    }

    private fun buildCommitMessage(summary: String, approvedBy: String?, approvalNote: String?): String = buildString {
        appendLine("docs(wiki): apply pending LLM Wiki change")
        appendLine()
        appendLine(summary.take(500))
        approvedBy?.takeIf { it.isNotBlank() }?.let { appendLine("Approved-by: $it") }
        approvalNote?.takeIf { it.isNotBlank() }?.let { appendLine("Approval-note: ${it.take(300)}") }
    }.trim()
}
