package io.plady._00thieveswikimcp.wiki.application

import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.GitRepositoryService
import org.slf4j.LoggerFactory
import org.springframework.boot.ApplicationArguments
import org.springframework.boot.ApplicationRunner
import org.springframework.stereotype.Component
import java.nio.file.Files
import java.nio.file.Path
import java.time.Duration
import java.time.Instant
import java.util.concurrent.TimeUnit
import kotlin.io.path.createDirectories
import kotlin.io.path.exists

@Component
class WikiStartupReconciler(
    private val properties: WikiProperties,
    private val git: GitRepositoryService,
    private val pendingService: PendingChangeService,
) : ApplicationRunner {
    private val log = LoggerFactory.getLogger(javaClass)
    private val repoRoot: Path get() = properties.repoRoot.toAbsolutePath().normalize()

    override fun run(args: ApplicationArguments) {
        reconcile()
    }

    fun reconcile() {
        if (!properties.startup.enabled) {
            log.info("LLM Wiki startup reconciliation is disabled.")
            return
        }
        ensureLocalClone()
        if (!git.isGitRepo()) {
            log.warn("LLM Wiki repo is not a git repository; startup reconciliation skipped: {}", repoRoot)
            return
        }

        val dirtyFiles = git.touchedFiles()
        if (dirtyFiles.isNotEmpty()) {
            reconcileDirtyRepo(dirtyFiles)
            verifyInstructionFiles()
            return
        }

        syncCleanRepoToOrigin()
        verifyInstructionFiles()
    }

    private fun ensureLocalClone() {
        if (git.isGitRepo()) return
        val remote = properties.gitRemoteUrl?.takeIf { it.isNotBlank() }
        if (remote == null) {
            log.warn("LLM Wiki git remote is not configured; cannot clone missing repo at {}", repoRoot)
            return
        }

        repoRoot.parent?.createDirectories()
        val result = runCommand(
            command = listOf("git", "clone", "--", remote, repoRoot.toString()),
            cwd = repoRoot.parent ?: Path.of("."),
            timeout = Duration.ofMinutes(2),
        )
        if (!result.ok) {
            throw IllegalStateException("Failed to clone LLM Wiki repo from $remote: ${result.stderr.ifBlank { result.stdout }}")
        }
        log.info("Cloned LLM Wiki repo from {} into {}", remote, repoRoot)
    }

    private fun reconcileDirtyRepo(dirtyFiles: List<String>) {
        val active = pendingService.activePending()
        when {
            active != null && active.lockExpiresAt.isAfter(Instant.now()) -> {
                log.warn(
                    "Recovered dirty LLM Wiki repo with active pending change {} and {} touched file(s); preserving working tree.",
                    active.pendingChangeId,
                    dirtyFiles.size,
                )
            }
            active != null -> {
                val snapshot = pendingService.writeAbortSnapshot(active)
                val reset = git.resetHardAndClean()
                val updated = pendingService.update(active.copy(status = "TIMED_OUT", updatedAt = Instant.now()))
                if (!reset.ok) {
                    throw IllegalStateException("Failed timeout abort reset for ${updated.pendingChangeId}: ${reset.stderr.ifBlank { reset.stdout }}")
                }
                log.warn(
                    "Timed out pending change {} during startup reconciliation; archived {} and reset dirty repo.",
                    updated.pendingChangeId,
                    snapshot.id,
                )
            }
            properties.startup.resetOrphanDirtyRepo -> {
                val snapshot = pendingService.writeOrphanSnapshot()
                val reset = git.resetHardAndClean()
                if (!reset.ok) {
                    throw IllegalStateException("Failed orphan dirty repo reset after snapshot ${snapshot.id}: ${reset.stderr.ifBlank { reset.stdout }}")
                }
                log.warn("Archived orphan dirty repo diff as {} and reset working tree.", snapshot.id)
            }
            else -> {
                throw IllegalStateException("LLM Wiki repo is dirty but no active pending change explains it: ${dirtyFiles.joinToString(", ")}")
            }
        }
    }

    private fun syncCleanRepoToOrigin() {
        val branch = properties.targetBranch
        if (git.hasOriginRemote()) {
            val fetch = git.fetchOrigin(branch)
            if (!fetch.ok) {
                log.warn("Failed to fetch origin/{} during startup reconciliation: {}", branch, fetch.stderr.ifBlank { fetch.stdout })
                return
            }
            val checkout = git.checkoutBranchFromRef(branch, "origin/$branch")
            if (!checkout.ok) {
                log.warn("Failed to checkout {} from origin/{}: {}", branch, branch, checkout.stderr.ifBlank { checkout.stdout })
                return
            }
            val reset = git.resetHard("origin/$branch")
            if (!reset.ok) {
                log.warn("Failed to reset {} to origin/{}: {}", branch, branch, reset.stderr.ifBlank { reset.stdout })
            }
            return
        }

        val checkout = git.checkout(branch)
        if (!checkout.ok) {
            log.warn("No origin remote configured and checkout {} failed: {}", branch, checkout.stderr.ifBlank { checkout.stdout })
        }
    }

    private fun verifyInstructionFiles() {
        val missing = listOf("CLAUDE.md", "AGENTS.md").filterNot { repoRoot.resolve(it).exists() }
        if (missing.isEmpty()) return
        val message = "LLM Wiki instruction file(s) missing: ${missing.joinToString(", ")}"
        if (properties.startup.requireInstructionFiles) {
            throw IllegalStateException(message)
        }
        log.warn(message)
    }

    private fun runCommand(command: List<String>, cwd: Path, timeout: Duration): GitRepositoryService.CommandResult {
        if (!Files.isDirectory(cwd)) {
            cwd.createDirectories()
        }
        val process = ProcessBuilder(command)
            .directory(cwd.toFile())
            .redirectErrorStream(false)
            .start()
        val finished = process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)
        if (!finished) {
            process.destroyForcibly()
            return GitRepositoryService.CommandResult(124, "", "${command.joinToString(" ")} timed out")
        }
        return GitRepositoryService.CommandResult(
            exitCode = process.exitValue(),
            stdout = process.inputStream.bufferedReader().readText(),
            stderr = process.errorStream.bufferedReader().readText(),
        )
    }
}
