package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.WikiContextPackService
import io.plady._00thieveswikimcp.wiki.application.WikiSearchService
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WikiContextPackServiceTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `context pack is built from Linear issue id matches`() {
        writeMarkdown(root, "wiki/specs/pla-229.md", """
            ---
            type: Tech Spec
            status: Draft
            ---
            # PLA-229 MCP Spec
            Open question: how to wire agent runtime?
        """)

        val service = WikiContextPackService(WikiSearchService(localRepository(root)))
        val response = service.getRelatedContext("PLA-229")

        assertTrue(response.ok)
        assertEquals(1, response.contextItems.size)
        assertTrue(response.openQuestions.isNotEmpty())
    }

    @Test
    fun `context pack summarizes when no related Linear issue context exists`() {
        writeMarkdown(root, "wiki/specs/pla-100.md", """
            ---
            type: Tech Spec
            status: Draft
            ---
            # PLA-100 Existing Spec
            This fixture should not match the requested issue.
        """)

        val service = WikiContextPackService(WikiSearchService(localRepository(root)))
        val response = service.getRelatedContext("PLA-404")

        assertTrue(response.ok)
        assertEquals("PLA-404", response.linearIssueId)
        assertEquals("No related LLM Wiki context found for PLA-404.", response.summary)
        assertEquals(emptyList(), response.contextItems)
        assertEquals(emptyList(), response.openQuestions)
    }
}
