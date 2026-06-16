package io.plady._00thieveswikimcp.wiki.infrastructure

import io.plady._00thieveswikimcp.wiki.api.PendingChangeRecord
import io.plady._00thieveswikimcp.wiki.api.WikiValidationIssue
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import org.springframework.stereotype.Repository
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import java.util.Properties
import kotlin.io.path.createDirectories
import kotlin.io.path.exists
import kotlin.io.path.inputStream
import kotlin.io.path.outputStream

@Repository
class FilePendingChangeStore(
    private val properties: WikiProperties,
) : PendingChangeStore {
    private val root: Path get() = properties.pendingStoreRoot.toAbsolutePath().normalize()

    override fun save(record: PendingChangeRecord) {
        root.createDirectories()
        val file = root.resolve("${record.pendingChangeId}.properties")
        val props = Properties()
        props["pendingChangeId"] = record.pendingChangeId
        props["jobId"] = record.jobId
        props["status"] = record.status
        props["baseCommit"] = record.baseCommit
        props["targetBranch"] = record.targetBranch
        props["lockOwner"] = record.lockOwner
        props["lockExpiresAt"] = record.lockExpiresAt.toString()
        props["summary"] = record.summary
        props["touchedFiles"] = record.touchedFiles.joinToString("\n")
        props["diffSnapshotPath"] = record.diffSnapshotPath
        props["diffHash"] = record.diffHash
        props["validationOk"] = record.validationOk.toString()
        props["validationIssues"] = record.validationIssues.joinToString("\n") { issue ->
            listOf(issue.code, issue.severity, issue.path.orEmpty(), issue.message).joinToString("\t")
        }
        props["createdAt"] = record.createdAt.toString()
        props["updatedAt"] = record.updatedAt.toString()
        record.commitSha?.let { props["commitSha"] = it }
        record.prUrl?.let { props["prUrl"] = it }
        file.outputStream().use { props.store(it, "LLM Wiki pending change") }
    }

    override fun find(pendingChangeId: String): PendingChangeRecord? {
        val file = root.resolve("$pendingChangeId.properties")
        return if (file.exists()) read(file) else null
    }

    override fun list(): List<PendingChangeRecord> {
        if (!root.exists()) return emptyList()
        return Files.list(root).use { stream ->
            stream.filter { it.fileName.toString().endsWith(".properties") }
                .map { read(it) }
                .filter { it != null }
                .map { it!! }
                .toList()
                .sortedByDescending { it.updatedAt }
        }
    }

    private fun read(file: Path): PendingChangeRecord? = runCatching {
        val props = Properties()
        file.inputStream().use { props.load(it) }
        PendingChangeRecord(
            pendingChangeId = props.getProperty("pendingChangeId"),
            jobId = props.getProperty("jobId"),
            status = props.getProperty("status"),
            baseCommit = props.getProperty("baseCommit"),
            targetBranch = props.getProperty("targetBranch"),
            lockOwner = props.getProperty("lockOwner"),
            lockExpiresAt = Instant.parse(props.getProperty("lockExpiresAt")),
            summary = props.getProperty("summary", ""),
            touchedFiles = props.getProperty("touchedFiles", "").lines().filter { it.isNotBlank() },
            diffSnapshotPath = props.getProperty("diffSnapshotPath", ""),
            diffHash = props.getProperty("diffHash", ""),
            validationOk = props.getProperty("validationOk", "false").toBoolean(),
            validationIssues = props.getProperty("validationIssues", "").lines().filter { it.isNotBlank() }.map { line ->
                val parts = line.split('\t', limit = 4)
                WikiValidationIssue(
                    code = parts.getOrElse(0) { "UNKNOWN" },
                    severity = parts.getOrElse(1) { "warning" },
                    path = parts.getOrNull(2)?.takeIf { it.isNotBlank() },
                    message = parts.getOrElse(3) { line },
                )
            },
            createdAt = Instant.parse(props.getProperty("createdAt")),
            updatedAt = Instant.parse(props.getProperty("updatedAt")),
            commitSha = props.getProperty("commitSha"),
            prUrl = props.getProperty("prUrl"),
        )
    }.getOrNull()
}
