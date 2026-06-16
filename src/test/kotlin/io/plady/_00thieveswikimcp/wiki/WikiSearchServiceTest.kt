package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.WikiSearchService
import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WikiSearchServiceTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `search returns wiki URI results with snippets`() {
        writeMarkdown(root, "wiki/sources/llm-wiki-mcp.md", """
            ---
            type: Source
            tags: [mcp]
            ---
            # LLM Wiki MCP
            PLA-229 defines pending approval workflow and wiki_run_task.
        """)
        writeMarkdown(root, "wiki/topics/other.md", "# Other\nNothing")

        val response = WikiSearchService(localRepository(root)).search(query = "PLA-229 pending", tags = listOf("mcp"))

        assertTrue(response.ok)
        assertEquals(1, response.results.size)
        assertEquals("wiki://source/llm-wiki-mcp", response.results.first().uri)
        assertTrue(response.results.first().snippet.contains("PLA-229"))
    }

    @Test
    fun `search can filter spec results by type status tag and Linear metadata`() {
        writeMarkdown(root, "wiki/specs/pla-229.md", """
            ---
            type: Tech Spec
            status: Draft
            tags: [mcp, platform]
            linear: PLA-229
            ---
            # PLA-229 Runtime Context
            Runtime design for PLA-229 should be discoverable through structured filters.
        """)
        writeMarkdown(root, "wiki/specs/pla-229-wrong-status.md", """
            ---
            type: Tech Spec
            status: Proposed
            tags: [mcp, platform]
            linear: PLA-229
            ---
            # PLA-229 Proposed Alternative
            Runtime design for PLA-229 with the wrong status.
        """)
        writeMarkdown(root, "wiki/topics/pla-229.md", """
            ---
            type: Topic
            status: Draft
            tags: [mcp, platform]
            ---
            # PLA-229 Topic
            Runtime design for PLA-229 with the wrong type.
        """)
        writeMarkdown(root, "wiki/specs/pla-229-wrong-tag.md", """
            ---
            type: Tech Spec
            status: Draft
            tags: [docs]
            linear: PLA-229
            ---
            # PLA-229 Docs Spec
            Runtime design for PLA-229 with the wrong tag.
        """)

        val response = WikiSearchService(localRepository(root)).search(
            query = "runtime",
            types = listOf("spec"),
            statuses = listOf("draft"),
            tags = listOf("#mcp"),
            linearIssueId = "PLA-229",
        )

        assertTrue(response.ok)
        assertEquals("runtime PLA-229", response.query)
        assertEquals(1, response.results.size)
        val result = response.results.first()
        assertEquals("wiki://spec/pla-229", result.uri)
        assertEquals(WikiDocumentType.SPEC, result.type)
        assertEquals("Draft", result.status)
        assertEquals("wiki/specs/pla-229.md", result.path)
        assertTrue(result.githubUrl?.endsWith("/wiki/specs/pla-229.md") == true)
        assertTrue(result.snippet.contains("PLA-229"))
    }

    @Test
    fun `search can filter ADR results by status and tag while using Linear text as a query term`() {
        writeMarkdown(root, "wiki/adrs/pla-229-workflow.md", """
            ---
            type: ADR
            status: Proposed
            tags: [mcp, workflow]
            ---
            # PLA-229 Workflow ADR
            PLA-229 chooses a pending approval workflow.
        """)
        writeMarkdown(root, "wiki/specs/pla-229-accepted.md", """
            ---
            type: Tech Spec
            status: Accepted
            tags: [mcp]
            ---
            # PLA-229 Accepted Spec
            Should not match Proposed ADR filter.
        """)

        val response = WikiSearchService(localRepository(root)).search(
            query = "pending approval",
            types = listOf("adr"),
            statuses = listOf("Proposed"),
            tags = listOf("workflow"),
            linearIssueId = "PLA-229",
        )

        assertTrue(response.ok)
        assertEquals(1, response.results.size)
        assertEquals("wiki://adr/pla-229-workflow", response.results.single().uri)
        assertEquals("Proposed", response.results.single().status)
    }

}
