package io.plady._00thieveswikimcp.wiki.infrastructure

import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import org.springframework.stereotype.Component
import java.nio.file.Files
import java.time.Duration
import java.util.concurrent.TimeUnit
import kotlin.io.path.exists

@Component
class GitRepositoryService(
    private val properties: WikiProperties,
) {
    data class CommandResult(val exitCode: Int, val stdout: String, val stderr: String) {
        val ok: Boolean = exitCode == 0
    }

    fun isGitRepo(): Boolean = properties.repoRoot.resolve(".git").exists()

    fun headSha(): String = runGit("rev-parse", "HEAD").stdout.trim().ifBlank { "unknown" }

    fun currentBranch(): String = runGit("branch", "--show-current").stdout.trim().ifBlank { properties.targetBranch }

    fun statusPorcelain(): String = runGit("status", "--porcelain", "--untracked-files=all").stdout.trim()

    fun touchedFiles(): List<String> = statusPorcelain().lines()
        .mapNotNull { line -> line.takeIf { it.length >= 4 }?.substring(3)?.trim() }
        .filter { it.isNotBlank() }
        .map { it.substringAfter(" -> ") }
        .distinct()

    fun untrackedFiles(): List<String> = runGit("ls-files", "--others", "--exclude-standard").stdout
        .lines()
        .map { it.trim() }
        .filter { it.isNotBlank() }

    fun diff(): String = buildString {
        append(runGit("diff", "--binary").stdout)
        val stagedDiff = runGit("diff", "--cached", "--binary").stdout
        if (stagedDiff.isNotBlank()) {
            if (isNotEmpty() && !endsWith("\n")) appendLine()
            append(stagedDiff)
        }
        untrackedFiles().forEach { file ->
            if (isSafeRelativePath(file)) {
                val untrackedDiff = runGit("diff", "--no-index", "--binary", "--", "/dev/null", file)
                if (untrackedDiff.stdout.isNotBlank()) {
                    if (isNotEmpty() && !endsWith("\n")) appendLine()
                    append(untrackedDiff.stdout)
                }
            }
        }
    }

    fun resetHardAndClean(): CommandResult {
        val reset = resetHard()
        if (!reset.ok) return reset
        return runGit("clean", "-fd")
    }

    fun checkout(branch: String): CommandResult = runGit("checkout", branch)

    fun checkoutBranchFromRef(branch: String, ref: String): CommandResult = runGit("checkout", "-B", branch, ref)

    fun fetchOrigin(branch: String = properties.targetBranch): CommandResult = runGit("fetch", "origin", branch)

    fun resetHard(ref: String? = null): CommandResult =
        if (ref.isNullOrBlank()) runGit("reset", "--hard") else runGit("reset", "--hard", ref)

    fun hasOriginRemote(): Boolean = runGit("remote", "get-url", "origin").ok

    fun add(files: List<String>): CommandResult {
        if (files.isEmpty()) return CommandResult(0, "", "")
        return runGit(*(listOf("add", "--") + files).toTypedArray())
    }

    fun commit(message: String): CommandResult = runGit("commit", "-m", message)

    fun push(branch: String = currentBranch()): CommandResult = runGit("push", "origin", branch)

    private fun isSafeRelativePath(path: String): Boolean = path.isNotBlank() && !path.startsWith("/") && !path.contains("..")

    fun runGit(vararg args: String, timeout: Duration = Duration.ofSeconds(30)): CommandResult {
        if (!Files.isDirectory(properties.repoRoot)) {
            return CommandResult(2, "", "Repo root does not exist: ${properties.repoRoot}")
        }
        val process = ProcessBuilder(listOf("git") + args)
            .directory(properties.repoRoot.toFile())
            .redirectErrorStream(false)
            .start()
        val finished = process.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)
        if (!finished) {
            process.destroyForcibly()
            return CommandResult(124, "", "git ${args.joinToString(" ")} timed out")
        }
        return CommandResult(
            exitCode = process.exitValue(),
            stdout = process.inputStream.bufferedReader().readText(),
            stderr = process.errorStream.bufferedReader().readText(),
        )
    }
}
