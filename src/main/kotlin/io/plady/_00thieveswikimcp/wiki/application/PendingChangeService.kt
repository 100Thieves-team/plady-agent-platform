package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.api.PendingChangeRecord
import io.plady._00thieveswikimcp.wiki.api.WikiDiffSnapshot
import io.plady._00thieveswikimcp.wiki.api.WikiValidationResult
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.FilePendingChangeStore
import io.plady._00thieveswikimcp.wiki.infrastructure.GitRepositoryService
import org.springframework.stereotype.Service
import java.nio.file.Files
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID
import kotlin.io.path.createDirectories
import kotlin.io.path.readText
import kotlin.io.path.writeText

@Service
class PendingChangeService(
    private val properties: WikiProperties,
    private val store: FilePendingChangeStore,
    private val git: GitRepositoryService,
    private val validationService: WikiValidationService,
) {
    fun activePending(): PendingChangeRecord? = store.list().firstOrNull { it.status == "PENDING_APPROVAL" }

    fun pendingApprovals(): List<PendingChangeRecord> = store.list().filter { it.status == "PENDING_APPROVAL" }

    fun get(pendingChangeId: String): PendingChangeRecord? = store.find(pendingChangeId)

    fun readDiff(record: PendingChangeRecord): String = runCatching {
        java.nio.file.Path.of(record.diffSnapshotPath).readText()
    }.getOrDefault("")

    fun createFromCurrentDirty(summary: String, targetBranch: String = properties.targetBranch): Pair<PendingChangeRecord, WikiDiffSnapshot> {
        val touchedFiles = git.touchedFiles()
        val validation = validationService.validateTouchedFiles(touchedFiles, properties.repoRoot)
        val diff = currentDiffWithStatus()
        val pendingId = "pc_${UUID.randomUUID().toString().replace("-", "").take(16)}"
        val jobId = "job_${UUID.randomUUID().toString().replace("-", "").take(16)}"
        val snapshot = writeSnapshot(pendingId, diff, suffix = "initial")
        val now = Instant.now()
        val record = PendingChangeRecord(
            pendingChangeId = pendingId,
            jobId = jobId,
            status = "PENDING_APPROVAL",
            baseCommit = git.headSha(),
            targetBranch = targetBranch,
            lockOwner = properties.workflow.lockOwner,
            lockExpiresAt = now.plusSeconds(properties.workflow.defaultLockTtlSeconds),
            summary = summary,
            touchedFiles = touchedFiles,
            diffSnapshotPath = snapshot.path.orEmpty(),
            diffHash = snapshot.hash.orEmpty(),
            validationOk = validation.ok,
            validationIssues = validation.issues,
            createdAt = now,
            updatedAt = now,
        )
        store.save(record)
        return record to snapshot
    }

    fun update(record: PendingChangeRecord): PendingChangeRecord {
        store.save(record)
        return record
    }

    fun validateCurrentMatches(record: PendingChangeRecord): Boolean = sha256(currentDiffWithStatus()) == record.diffHash

    fun currentValidation(): WikiValidationResult = validationService.validateTouchedFiles(git.touchedFiles(), properties.repoRoot)

    fun writeAbortSnapshot(record: PendingChangeRecord): WikiDiffSnapshot = writeSnapshot(
        record.pendingChangeId,
        currentDiffWithStatus(),
        suffix = "abort-${Instant.now().toEpochMilli()}",
    )

    fun currentSnapshotFor(record: PendingChangeRecord, suffix: String): WikiDiffSnapshot = writeSnapshot(
        record.pendingChangeId,
        currentDiffWithStatus(),
        suffix = suffix,
    )

    fun writeOrphanSnapshot(): WikiDiffSnapshot = writeSnapshot(
        pendingId = "orphan",
        diff = currentDiffWithStatus(),
        suffix = "startup-${Instant.now().toEpochMilli()}",
    )

    fun toDiffSnapshot(record: PendingChangeRecord): WikiDiffSnapshot = WikiDiffSnapshot(
        id = java.nio.file.Path.of(record.diffSnapshotPath).fileName?.toString()?.removeSuffix(".diff") ?: record.pendingChangeId,
        path = record.diffSnapshotPath,
        hash = record.diffHash,
        lineCount = readDiff(record).lineSequence().count(),
    )

    fun currentDiffWithStatus(): String = buildString {
        appendLine("# git status --porcelain")
        appendLine(git.statusPorcelain())
        appendLine()
        appendLine("# git diff --binary")
        append(git.diff())
    }

    private fun writeSnapshot(pendingId: String, diff: String, suffix: String): WikiDiffSnapshot {
        val dir = properties.pendingStoreRoot.toAbsolutePath().normalize().resolve("diffs").resolve(pendingId)
        dir.createDirectories()
        val snapshotId = "$pendingId-$suffix"
        val file = dir.resolve("$snapshotId.diff")
        file.writeText(diff)
        return WikiDiffSnapshot(
            id = snapshotId,
            path = file.toString(),
            hash = sha256(diff),
            lineCount = diff.lineSequence().count(),
        )
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }
}
