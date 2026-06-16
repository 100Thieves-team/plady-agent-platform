package io.plady._00thieveswikimcp.wiki.api

import java.time.Instant

data class WikiValidationIssue(
    val code: String,
    val severity: String,
    val path: String? = null,
    val message: String,
)

data class WikiValidationResult(
    val ok: Boolean,
    val issues: List<WikiValidationIssue> = emptyList(),
)

data class WikiDiffSnapshot(
    val id: String,
    val path: String? = null,
    val hash: String? = null,
    val lineCount: Int = 0,
)

data class WikiRunTaskResponse(
    val ok: Boolean,
    val status: String,
    val pendingChangeId: String? = null,
    val summary: String,
    val touchedFiles: List<String> = emptyList(),
    val diffSnapshot: WikiDiffSnapshot? = null,
    val validation: WikiValidationResult = WikiValidationResult(ok = true),
    val lockExpiresAt: Instant? = null,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiPendingResponse(
    val ok: Boolean,
    val pendingChangeId: String? = null,
    val status: String? = null,
    val summary: String? = null,
    val diff: String? = null,
    val diffSnapshot: WikiDiffSnapshot? = null,
    val validation: WikiValidationResult? = null,
    val touchedFiles: List<String> = emptyList(),
    val lockExpiresAt: Instant? = null,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiCommitPendingResponse(
    val ok: Boolean,
    val pendingChangeId: String,
    val status: String,
    val commitSha: String? = null,
    val prUrl: String? = null,
    val pushResult: String? = null,
    val validation: WikiValidationResult = WikiValidationResult(ok = true),
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiAbortPendingResponse(
    val ok: Boolean,
    val pendingChangeId: String,
    val status: String,
    val archivedDiffSnapshotId: String? = null,
    val resetPerformed: Boolean,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class WikiExtendPendingLockResponse(
    val ok: Boolean,
    val pendingChangeId: String,
    val status: String,
    val lockExpiresAt: Instant? = null,
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)

data class PendingChangeRecord(
    val pendingChangeId: String,
    val jobId: String,
    val status: String,
    val baseCommit: String,
    val targetBranch: String,
    val lockOwner: String,
    val lockExpiresAt: Instant,
    val summary: String,
    val touchedFiles: List<String>,
    val diffSnapshotPath: String,
    val diffHash: String,
    val validationOk: Boolean,
    val validationIssues: List<WikiValidationIssue>,
    val createdAt: Instant,
    val updatedAt: Instant,
    val commitSha: String? = null,
    val prUrl: String? = null,
)
