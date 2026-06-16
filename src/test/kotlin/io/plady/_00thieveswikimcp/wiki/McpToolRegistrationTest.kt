package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.prompt.WikiPrompts
import io.plady._00thieveswikimcp.wiki.resource.WikiResources
import io.plady._00thieveswikimcp.wiki.tool.WikiReadTools
import io.plady._00thieveswikimcp.wiki.tool.WikiWorkflowTools
import org.springframework.ai.mcp.annotation.McpPrompt
import org.springframework.ai.mcp.annotation.McpResource
import org.springframework.ai.mcp.annotation.McpTool
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class McpToolRegistrationTest {
    @Test
    fun `read and workflow tools preserve source of truth names`() {
        val toolNames = (WikiReadTools::class.java.declaredMethods + WikiWorkflowTools::class.java.declaredMethods)
            .mapNotNull { it.getAnnotation(McpTool::class.java)?.name }
            .toSet()

        assertEquals(
            setOf(
                "wiki_search",
                "wiki_get",
                "wiki_get_related_context",
                "wiki_triage",
                "wiki_lint",
                "wiki_run_task",
                "wiki_get_pending",
                "wiki_commit_pending",
                "wiki_abort_pending",
                "wiki_extend_pending_lock",
            ),
            toolNames,
        )
        assertTrue(toolNames.none { it.contains("git", ignoreCase = true) || it.contains("file", ignoreCase = true) })
    }

    @Test
    fun `prompt wrappers preserve source of truth names`() {
        val prompts = WikiPrompts::class.java.declaredMethods
            .mapNotNull { it.getAnnotation(McpPrompt::class.java) }
        val promptNames = prompts.map { it.name }.toSet()

        assertEquals(
            setOf(
                "wiki_create_adr_draft",
                "wiki_create_spec_draft",
                "wiki_summarize_review",
                "wiki_maintain_decision_backlog",
                "wiki_propose_doc_patch",
            ),
            promptNames,
        )
        prompts.forEach { prompt ->
            assertTrue(
                prompt.description.contains("wiki_run_task"),
                "${prompt.name} must route file writes through wiki_run_task",
            )
        }
    }

    @Test
    fun `resources expose wiki URI patterns`() {
        val resourceUris = WikiResources::class.java.declaredMethods
            .mapNotNull { it.getAnnotation(McpResource::class.java)?.uri }
            .toSet()

        assertEquals(
            setOf(
                "wiki://raw/{path}",
                "wiki://source/{slug}",
                "wiki://topic/{slug}",
                "wiki://adr/{id}",
                "wiki://spec/{id}",
                "wiki://review/{id}",
                "wiki://backlog",
            ),
            resourceUris,
        )
    }

    @Test
    fun `commit approval tool does not accept client supplied git primitives`() {
        val method = assertNotNull(WikiWorkflowTools::class.java.declaredMethods.firstOrNull { it.name == "wikiCommitPending" })
        val tool = assertNotNull(method.getAnnotation(McpTool::class.java))

        assertEquals(3, method.parameterCount)
        assertEquals("wiki_commit_pending", tool.name)
        assertTrue(tool.description.contains("cannot specify file lists"))
        assertTrue(tool.description.contains("git commands"))
        assertTrue(tool.description.contains("commit messages"))
    }
}
