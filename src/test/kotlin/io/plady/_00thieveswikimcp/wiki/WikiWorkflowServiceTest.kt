package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.PendingChangeService
import io.plady._00thieveswikimcp.wiki.application.PendingTimeoutSweeper
import io.plady._00thieveswikimcp.wiki.application.WikiValidationService
import io.plady._00thieveswikimcp.wiki.application.WikiWorkflowService
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.FilePendingChangeStore
import io.plady._00thieveswikimcp.wiki.infrastructure.GitRepositoryService
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import java.security.MessageDigest
import java.time.Instant
import kotlin.io.path.createDirectories
import kotlin.io.path.exists
import kotlin.io.path.notExists
import kotlin.io.path.readText
import kotlin.io.path.writeText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class WikiWorkflowServiceTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `run task fails closed when agent runtime is unavailable and repo is clean`() {
        initGitRepo(root)
        val service = workflow(root)

        val response = service.runTask("ingest", "Add notes", dryRun = false)

        assertEquals(false, response.ok)
        assertEquals("PENDING_ENGINE_UNAVAILABLE", response.status)
        assertEquals("PENDING_ENGINE_UNAVAILABLE", response.error?.code)
    }

    @Test
    fun `run task captures dirty working tree with durable diff snapshot and get pending returns it`() {
        initGitRepo(root)
        val raw = root.resolve("raw/note.md")
        raw.parent.createDirectories()
        raw.writeText("# Note\nPLA-229 pending content\n")
        val service = workflow(root)

        val response = service.runTask("ingest", "Capture dirty note", linearIssueId = "PLA-229")

        assertTrue(response.ok)
        assertEquals("PENDING_APPROVAL", response.status)
        assertEquals("ingest for PLA-229: Capture dirty note", response.summary)
        val pendingId = assertNotNull(response.pendingChangeId)
        assertTrue(response.touchedFiles.contains("raw/note.md"))
        assertTrue(response.validation.ok)
        assertNotNull(response.lockExpiresAt)

        val snapshot = assertNotNull(response.diffSnapshot)
        assertEquals("$pendingId-initial", snapshot.id)
        val snapshotPath = Path.of(assertNotNull(snapshot.path))
        assertTrue(snapshotPath.exists(), "initial diff snapshot should be persisted")
        val snapshotText = snapshotPath.readText()
        assertTrue(snapshotText.contains("# git status --porcelain"))
        assertTrue(snapshotText.contains("?? raw/note.md"))
        assertTrue(snapshotText.contains("PLA-229 pending content"))
        assertEquals(sha256(snapshotText), snapshot.hash)
        assertTrue(snapshot.lineCount > 0)

        val pending = service.getPending(pendingId)
        assertTrue(pending.ok)
        assertEquals("PENDING_APPROVAL", pending.status)
        assertEquals(response.summary, pending.summary)
        assertEquals(listOf("raw/note.md"), pending.touchedFiles)
        assertEquals(snapshotText, pending.diff)
        assertEquals(snapshot.hash, pending.diffSnapshot?.hash)
        assertEquals(response.lockExpiresAt, pending.lockExpiresAt)

        val reloadedService = workflow(root)
        val reloaded = reloadedService.getPending(pendingId)
        assertTrue(reloaded.ok)
        assertEquals("PENDING_APPROVAL", reloaded.status)
        assertEquals(snapshotText, reloaded.diff)
        assertEquals(listOf("raw/note.md"), reloaded.touchedFiles)
    }

    @Test
    fun `run task returns busy while another pending change is active`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/first.md").writeText("# First\n")
        val service = workflow(root)
        val active = service.runTask("ingest", "Capture first note")
        assertTrue(active.ok)

        root.resolve("raw/second.md").writeText("# Second\n")
        val response = service.runTask("ingest", "Capture second note")

        assertFalse(response.ok)
        assertEquals("BUSY", response.status)
        assertEquals(active.pendingChangeId, response.pendingChangeId)
        assertEquals("PENDING_CHANGE_EXISTS", response.error?.code)
        assertEquals(true, response.error?.retryable)
        assertEquals(listOf("raw/first.md"), response.touchedFiles)
        assertEquals(active.diffSnapshot?.hash, response.diffSnapshot?.hash)
    }

    @Test
    fun `extend lock updates pending record`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/note.md").writeText("# Note\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture dirty note").pendingChangeId!!
        val before = assertNotNull(service.getPending(pending).lockExpiresAt)

        val response = service.extendPendingLock(pending, 120)

        assertTrue(response.ok)
        assertEquals("PENDING_APPROVAL", response.status)
        val after = assertNotNull(response.lockExpiresAt)
        assertTrue(after.isAfter(before), "lock expiry should move forward")
        assertEquals(after, service.getPending(pending).lockExpiresAt)
    }

    @Test
    fun `commit pending creates deterministic local commit and leaves working tree clean`() {
        initGitRepo(root)
        seedTrackedFile("raw/note.md", "# Note\nBefore\n")
        root.resolve("raw/note.md").writeText("# Note\nAfter\n")
        run(root, "git", "add", "raw/note.md")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Commit approved note", linearIssueId = "PLA-229")
        assertTrue(pending.ok, pending.toString())

        val response = service.commitPending(
            pendingChangeId = pending.pendingChangeId,
            approvedBy = "Jean",
            approvalNote = "Looks good",
        )

        assertTrue(response.ok)
        assertEquals("COMMITTED", response.status)
        assertEquals("skipped: push disabled", response.pushResult)
        assertEquals(run(root, "git", "rev-parse", "HEAD").trim(), response.commitSha)
        assertEquals(
            """
            docs(wiki): apply pending LLM Wiki change

            ingest for PLA-229: Commit approved note
            Approved-by: Jean
            Approval-note: Looks good
            """.trimIndent(),
            run(root, "git", "log", "-1", "--pretty=%B").trim(),
        )
        assertEquals("", gitStatus(root))
        assertEquals("# Note\nAfter\n", root.resolve("raw/note.md").readText())
        assertEquals("COMMITTED", service.getPending(pending.pendingChangeId).status)
    }

    @Test
    fun `commit marks pending conflicted when working tree diff changes after capture`() {
        initGitRepo(root)
        seedTrackedFile("raw/note.md", "# Note\nBefore\n")
        root.resolve("raw/note.md").writeText("# Note\nCaptured\n")
        run(root, "git", "add", "raw/note.md")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture tracked edit")
        assertTrue(pending.ok, pending.toString())

        root.resolve("raw/note.md").writeText("# Note\nChanged after capture\n")
        val response = service.commitPending(pending.pendingChangeId, approvedBy = "Jean")

        assertFalse(response.ok)
        assertEquals("CONFLICTED", response.status)
        assertEquals("DIFF_CHANGED", response.error?.code)
        assertEquals(false, response.validation.ok)
        assertEquals("CONFLICTED", service.getPending(pending.pendingChangeId).status)
        assertTrue(conflictSnapshotFiles(pending.pendingChangeId!!).isNotEmpty())
        assertEquals("seed raw/note.md", run(root, "git", "log", "-1", "--pretty=%s").trim())
    }

    @Test
    fun `commit rejects disallowed paths before creating a local commit`() {
        initGitRepo(root)
        val initialHead = run(root, "git", "rev-parse", "HEAD").trim()
        root.resolve("secrets.txt").writeText("do not commit\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Try to capture disallowed path")
        assertFalse(pending.ok)
        assertEquals("PENDING_APPROVAL", pending.status)
        assertEquals("VALIDATION_FAILED", pending.error?.code)
        assertTrue(pending.validation.issues.any { it.code == "OUTSIDE_ALLOWED_WIKI_PATHS" && it.path == "secrets.txt" })

        val response = service.commitPending(pending.pendingChangeId, approvedBy = "Jean")

        assertFalse(response.ok)
        assertEquals("PENDING_APPROVAL", response.status)
        assertEquals("VALIDATION_FAILED", response.error?.code)
        assertTrue(response.validation.issues.any { it.code == "OUTSIDE_ALLOWED_WIKI_PATHS" && it.path == "secrets.txt" })
        assertEquals(initialHead, run(root, "git", "rev-parse", "HEAD").trim())
        assertTrue(gitStatus(root).contains("?? secrets.txt"))
    }

    @Test
    fun `commit marks pending timed out when lock expires before approval`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/note.md").writeText("# Note\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture note before lock expiry")
        assertTrue(pending.ok, pending.toString())

        expirePendingLock(pending.pendingChangeId!!)
        val response = service.commitPending(pending.pendingChangeId, approvedBy = "Jean")

        assertFalse(response.ok)
        assertEquals("TIMED_OUT", response.status)
        assertEquals("LOCK_EXPIRED", response.error?.code)
        assertEquals("TIMED_OUT", service.getPending(pending.pendingChangeId).status)
        assertEquals("true", response.error?.details?.get("resetPerformed"))
        assertEquals("", gitStatus(root))
        assertTrue(root.resolve("raw/note.md").notExists())
    }

    @Test
    fun `abort pending archives current diff snapshot and resets dirty working tree`() {
        initGitRepo(root)
        seedTrackedFile("raw/note.md", "# Note\nBefore\n")
        root.resolve("raw/note.md").writeText("# Note\nCaptured\n")
        run(root, "git", "add", "raw/note.md")
        root.resolve("raw/draft.md").writeText("# Draft\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture changes to abort")
        assertTrue(pending.ok, pending.toString())

        root.resolve("raw/note.md").writeText("# Note\nChanged before abort\n")
        root.resolve("raw/extra.md").writeText("# Extra\n")
        val response = service.abortPending(pending.pendingChangeId, reason = "user rejected")

        assertTrue(response.ok)
        assertEquals("ABORTED", response.status)
        assertEquals(true, response.resetPerformed)
        val archiveId = assertNotNull(response.archivedDiffSnapshotId)
        val archive = pendingRoot(root).resolve("diffs/${pending.pendingChangeId}/$archiveId.diff")
        assertTrue(archive.exists(), "abort should archive the final dirty diff before reset")
        val archiveText = archive.readText()
        assertTrue(archiveText.contains("raw/extra.md"))
        assertTrue(archiveText.contains("Changed before abort"))
        assertEquals("", gitStatus(root))
        assertEquals("# Note\nBefore\n", root.resolve("raw/note.md").readText())
        assertTrue(root.resolve("raw/draft.md").notExists())
        assertTrue(root.resolve("raw/extra.md").notExists())
        assertEquals("ABORTED", service.getPending(pending.pendingChangeId).status)
    }

    @Test
    fun `abort expired pending marks timeout and resets dirty working tree`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/timeout.md").writeText("# Timeout\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture expiring change")
        assertTrue(pending.ok, pending.toString())

        expirePendingLock(pending.pendingChangeId!!)
        val response = service.abortPending(pending.pendingChangeId, reason = "lock expired")

        assertTrue(response.ok)
        assertEquals("TIMED_OUT", response.status)
        assertEquals(true, response.resetPerformed)
        assertEquals("", gitStatus(root))
        assertTrue(root.resolve("raw/timeout.md").notExists())
        assertEquals("TIMED_OUT", service.getPending(pending.pendingChangeId).status)
    }

    @Test
    fun `timeout sweeper aborts expired pending through reset layer`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/swept.md").writeText("# Swept\n")
        val service = workflow(root)
        val pending = service.runTask("ingest", "Capture stale approval")
        assertTrue(pending.ok, pending.toString())

        expirePendingLock(pending.pendingChangeId!!)
        val swept = timeoutSweeper(root, service).sweepExpired()

        assertEquals(1, swept)
        assertEquals("TIMED_OUT", service.getPending(pending.pendingChangeId).status)
        assertEquals("", gitStatus(root))
        assertTrue(root.resolve("raw/swept.md").notExists())
    }

    private fun workflow(root: Path): WikiWorkflowService {
        val props = properties(root)
        val git = GitRepositoryService(props)
        val validation = WikiValidationService()
        val store = FilePendingChangeStore(props)
        val pending = PendingChangeService(props, store, git, validation)
        return WikiWorkflowService(props, pending, git)
    }

    private fun timeoutSweeper(root: Path, workflow: WikiWorkflowService): PendingTimeoutSweeper {
        val props = properties(root)
        val git = GitRepositoryService(props)
        val validation = WikiValidationService()
        val store = FilePendingChangeStore(props)
        val pending = PendingChangeService(props, store, git, validation)
        return PendingTimeoutSweeper(pending, workflow)
    }

    private fun pendingRoot(root: Path): Path = root.resolve(".pending-test")

    private fun properties(root: Path): WikiProperties = WikiProperties(repoRoot = root, pendingStoreRoot = pendingRoot(root))

    private fun expirePendingLock(pendingChangeId: String) {
        val store = FilePendingChangeStore(properties(root))
        val record = requireNotNull(store.find(pendingChangeId))
        store.save(record.copy(lockExpiresAt = Instant.now().minusSeconds(1), updatedAt = Instant.now().minusSeconds(1)))
    }

    private fun initGitRepo(root: Path) {
        run(root, "git", "init")
        run(root, "git", "config", "user.email", "test@example.com")
        run(root, "git", "config", "user.name", "Test User")
        root.resolve(".gitignore").writeText(".pending-test/\n")
        root.resolve("README.md").writeText("# Fixture\n")
        run(root, "git", "add", ".gitignore", "README.md")
        run(root, "git", "commit", "-m", "initial")
    }

    private fun seedTrackedFile(path: String, content: String) {
        val file = root.resolve(path)
        file.parent?.createDirectories()
        file.writeText(content)
        run(root, "git", "add", path)
        run(root, "git", "commit", "-m", "seed $path")
    }

    private fun conflictSnapshotFiles(pendingChangeId: String): List<Path> {
        val dir = pendingRoot(root).resolve("diffs/$pendingChangeId")
        return if (dir.exists()) {
            java.nio.file.Files.list(dir).use { stream ->
                stream.filter { it.fileName.toString().contains("conflicted-") }.toList()
            }
        } else {
            emptyList()
        }
    }

    private fun gitStatus(root: Path): String = run(root, "git", "status", "--porcelain", "--untracked-files=all").trim()

    private fun run(cwd: Path, vararg command: String): String {
        val process = ProcessBuilder(command.toList()).directory(cwd.toFile()).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().readText()
        val exit = process.waitFor()
        check(exit == 0) { "${command.joinToString(" ")} failed: $output" }
        return output
    }

    private fun sha256(value: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }
}
