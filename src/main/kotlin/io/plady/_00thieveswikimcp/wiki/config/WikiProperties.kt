package io.plady._00thieveswikimcp.wiki.config

import org.springframework.boot.context.properties.ConfigurationProperties
import java.nio.file.Path
import kotlin.io.path.Path

@ConfigurationProperties(prefix = "plady.wiki")
data class WikiProperties(
    /** Local clone of the Plady LLM Wiki. */
    val repoRoot: Path = Path("/srv/plady-llm-wiki/repo"),
    /** Optional remote used by startup reconciliation to clone/fetch the wiki repo. */
    val gitRemoteUrl: String? = null,
    /** GitHub tree URL used only as auxiliary resource metadata. */
    val githubBaseUrl: String = "https://github.com/100Thieves-team/team-wiki/blob/main",
    /** Durable pending-change store root. */
    val pendingStoreRoot: Path = Path("/srv/plady-llm-wiki/pending"),
    /** Default target branch for deterministic commit operations. */
    val targetBranch: String = "main",
    val startup: Startup = Startup(),
    val workflow: Workflow = Workflow(),
) {
    data class Startup(
        /** Run one-shot local clone initialization and dirty repo reconciliation on application startup. */
        val enabled: Boolean = true,
        /** If true, an unexplained dirty repo is snapshotted and reset on startup. Otherwise startup fails. */
        val resetOrphanDirtyRepo: Boolean = true,
        /** If true, missing CLAUDE.md/AGENTS.md fail startup instead of logging warnings. */
        val requireInstructionFiles: Boolean = false,
    )

    data class Workflow(
        /** wiki_run_task cannot invoke the external Claude Agent Runtime until this is wired. */
        val agentRuntimeEnabled: Boolean = false,
        /** If true, wiki_run_task may capture an already-dirty repo as a pending change. */
        val captureExistingDirty: Boolean = true,
        /** If true, wiki_commit_pending creates a local git commit after validation. */
        val localCommitEnabled: Boolean = true,
        /** If true, deterministic commit layer pushes after local commit. Defaults to false for safety. */
        val pushEnabled: Boolean = false,
        /** Default lock TTL in seconds. */
        val defaultLockTtlSeconds: Long = 3600,
        /** Maximum lock extension in seconds. */
        val maxLockExtensionSeconds: Long = 86_400,
        /** Logical owner string stored in pending records. */
        val lockOwner: String = "100Thieves-wiki-mcp",
        /** Background sweeper cadence for expired pending approvals. */
        val timeoutSweepIntervalMillis: Long = 60_000,
    )
}
