package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.WikiLintService
import io.plady._00thieveswikimcp.wiki.application.WikiTriageService
import io.plady._00thieveswikimcp.wiki.tool.WikiReadTools
import org.junit.jupiter.api.io.TempDir
import org.springframework.ai.mcp.annotation.McpTool
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.attribute.FileTime
import java.time.Instant
import java.time.temporal.ChronoUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class WikiReadToolSpecificationTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `read tool annotations advertise read only closed-world behavior`() {
        val annotations = WikiReadTools::class.java.declaredMethods
            .mapNotNull { it.getAnnotation(McpTool::class.java) }
            .associateBy { it.name }

        listOf("wiki_search", "wiki_get", "wiki_get_related_context", "wiki_triage", "wiki_lint").forEach { name ->
            val annotation = assertNotNull(annotations[name])
            assertTrue(annotation.annotations.readOnlyHint)
            assertFalse(annotation.annotations.destructiveHint)
            assertTrue(annotation.annotations.idempotentHint)
            assertFalse(annotation.annotations.openWorldHint)
        }
    }

    @Test
    fun `triage separates durable decisions specs and open backlog questions`() {
        val response = WikiTriageService().triage(
            summary = "Change auth API state machine and DB schema; decision tradeoff is still an open question",
            linearIssueId = "PLA-229",
            changedAreas = listOf("security", "api"),
        )

        assertTrue(response.ok)
        assertTrue(response.needsAdr)
        assertTrue(response.needsTechSpec)
        assertTrue(response.needsBacklog)
        assertTrue(response.suggestedNextActions.any { it.contains("wiki_run_task") || it.contains("Tech Spec") })
    }

    @Test
    fun `lint reports missing type stale proposed docs title drift and suggested pending tasks`() {
        writeMarkdown(root, "wiki/adrs/stale.md", """
            ---
            type: ADR
            status: Proposed
            ---
            # Stale Proposed ADR
            Old decision candidate.
        """)
        writeMarkdown(root, "wiki/topics/no-type.md", """
            # Topic H1
            Missing type frontmatter.
        """)
        writeMarkdown(root, "wiki/topics/title-drift.md", """
            ---
            type: Topic
            ---
            # Different H1
            Content.
        """)
        Files.setLastModifiedTime(root.resolve("wiki/adrs/stale.md"), FileTime.from(Instant.now().minus(120, ChronoUnit.DAYS)))

        val response = WikiLintService(localRepository(root)).lint(limit = 20)

        assertTrue(response.ok)
        assertTrue(response.findings.any { it.code == "STALE_PROPOSED_DOC" && it.uri == "wiki://adr/stale" })
        assertTrue(response.findings.any { it.code == "MISSING_TYPE_FRONTMATTER" && it.path == "wiki/topics/no-type.md" })
        assertTrue(response.findings.any { it.code == "TITLE_DRIFT" && it.path == "wiki/topics/title-drift.md" })
        assertTrue(response.suggestedTasks.all { it.contains("wiki_run_task") })
    }

    @Test
    fun `context pack returns explicit empty summary when no related documents exist`() {
        val response = io.plady._00thieveswikimcp.wiki.application.WikiContextPackService(
            io.plady._00thieveswikimcp.wiki.application.WikiSearchService(localRepository(root)),
        ).getRelatedContext("PLA-999")

        assertTrue(response.ok)
        assertEquals(emptyList(), response.contextItems)
        assertTrue(response.summary.contains("No related LLM Wiki context found"))
    }
}
