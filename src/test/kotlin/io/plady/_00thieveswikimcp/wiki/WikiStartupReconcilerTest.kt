package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.PendingChangeService
import io.plady._00thieveswikimcp.wiki.application.WikiStartupReconciler
import io.plady._00thieveswikimcp.wiki.application.WikiValidationService
import io.plady._00thieveswikimcp.wiki.application.WikiWorkflowService
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.FilePendingChangeStore
import io.plady._00thieveswikimcp.wiki.infrastructure.GitRepositoryService
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import kotlin.io.path.createDirectories
import kotlin.io.path.exists
import kotlin.io.path.listDirectoryEntries
import kotlin.io.path.notExists
import kotlin.io.path.readText
import kotlin.io.path.writeText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WikiStartupReconcilerTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `startup preserves dirty repo when active pending lock is still valid`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/note.md").writeText("# Note\nRecovered after restart\n")
        val workflow = workflow(root)
        val pending = workflow.runTask("ingest", "Capture restart-safe pending")
        assertTrue(pending.ok, pending.toString())

        reconciler(root).reconcile()

        assertEquals("PENDING_APPROVAL", workflow.getPending(pending.pendingChangeId).status)
        assertTrue(gitStatus(root).contains("raw/note.md"))
        assertTrue(root.resolve("raw/note.md").exists())
    }

    @Test
    fun `startup timeout aborts expired active pending and resets dirty repo`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/expired.md").writeText("# Expired\n")
        val workflow = workflow(root)
        val pending = workflow.runTask("ingest", "Capture expired pending")
        assertTrue(pending.ok, pending.toString())
        expirePendingLock(root, pending.pendingChangeId!!)

        reconciler(root).reconcile()

        assertEquals("TIMED_OUT", workflow.getPending(pending.pendingChangeId).status)
        assertEquals("", gitStatus(root))
        assertTrue(root.resolve("raw/expired.md").notExists())
        assertTrue(diffFiles(root, pending.pendingChangeId).any { it.fileName.toString().contains("abort-") })
    }

    @Test
    fun `startup archives orphan dirty diff and resets when no pending record explains it`() {
        initGitRepo(root)
        root.resolve("raw").createDirectories()
        root.resolve("raw/orphan.md").writeText("# Orphan\n")

        reconciler(root).reconcile()

        assertEquals("", gitStatus(root))
        assertTrue(root.resolve("raw/orphan.md").notExists())
        val orphanDiff = diffFiles(root, "orphan").single()
        assertTrue(orphanDiff.readText().contains("raw/orphan.md"))
    }

    @Test
    fun `startup can clone missing repo from configured remote`() {
        val remoteWork = root.resolve("remote-work")
        val bareRemote = root.resolve("remote.git")
        val cloneTarget = root.resolve("clone-target")
        initGitRepo(remoteWork)
        run(root, "git", "clone", "--bare", remoteWork.toString(), bareRemote.toString())

        val props = properties(
            repoRoot = cloneTarget,
            pendingRoot = root.resolve("pending-clone"),
            gitRemoteUrl = bareRemote.toString(),
        )
        reconciler(props).reconcile()

        assertTrue(cloneTarget.resolve(".git").exists())
        assertTrue(cloneTarget.resolve("AGENTS.md").exists())
        assertTrue(cloneTarget.resolve("CLAUDE.md").exists())
    }

    private fun reconciler(root: Path): WikiStartupReconciler = reconciler(properties(root, pendingRoot(root)))

    private fun reconciler(props: WikiProperties): WikiStartupReconciler {
        val git = GitRepositoryService(props)
        val pending = pendingService(props)
        return WikiStartupReconciler(props, git, pending)
    }

    private fun workflow(root: Path): WikiWorkflowService {
        val props = properties(root, pendingRoot(root))
        val git = GitRepositoryService(props)
        val pending = pendingService(props)
        return WikiWorkflowService(props, pending, git)
    }

    private fun pendingService(props: WikiProperties): PendingChangeService {
        val git = GitRepositoryService(props)
        return PendingChangeService(props, FilePendingChangeStore(props), git, WikiValidationService())
    }

    private fun properties(
        repoRoot: Path,
        pendingRoot: Path,
        gitRemoteUrl: String? = null,
    ): WikiProperties = WikiProperties(
        repoRoot = repoRoot,
        gitRemoteUrl = gitRemoteUrl,
        pendingStoreRoot = pendingRoot,
        startup = WikiProperties.Startup(resetOrphanDirtyRepo = true, requireInstructionFiles = true),
    )

    private fun pendingRoot(root: Path): Path = root.resolve(".pending-test")

    private fun expirePendingLock(root: Path, pendingChangeId: String) {
        val props = properties(root, pendingRoot(root))
        val store = FilePendingChangeStore(props)
        val record = requireNotNull(store.find(pendingChangeId))
        store.save(record.copy(lockExpiresAt = Instant.now().minusSeconds(1), updatedAt = Instant.now().minusSeconds(1)))
    }

    private fun diffFiles(root: Path, pendingChangeId: String): List<Path> {
        val dir = pendingRoot(root).resolve("diffs/$pendingChangeId")
        return if (dir.exists()) dir.listDirectoryEntries("*.diff") else emptyList()
    }

    private fun initGitRepo(root: Path) {
        root.createDirectories()
        run(root, "git", "init")
        run(root, "git", "checkout", "-B", "main")
        run(root, "git", "config", "user.email", "test@example.com")
        run(root, "git", "config", "user.name", "Test User")
        root.resolve(".gitignore").writeText(".pending-test/\n")
        root.resolve("AGENTS.md").writeText("# Agents\n")
        root.resolve("CLAUDE.md").writeText("# Claude\n")
        root.resolve("README.md").writeText("# Fixture\n")
        run(root, "git", "add", ".gitignore", "AGENTS.md", "CLAUDE.md", "README.md")
        run(root, "git", "commit", "-m", "initial")
    }

    private fun gitStatus(root: Path): String = run(root, "git", "status", "--porcelain", "--untracked-files=all").trim()

    private fun run(cwd: Path, vararg command: String): String {
        Files.createDirectories(cwd)
        val process = ProcessBuilder(command.toList()).directory(cwd.toFile()).redirectErrorStream(true).start()
        val output = process.inputStream.bufferedReader().readText()
        val exit = process.waitFor()
        check(exit == 0) { "${command.joinToString(" ")} failed: $output" }
        return output
    }
}
