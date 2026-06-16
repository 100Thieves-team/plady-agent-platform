package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.WikiResourceService
import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class WikiResourceServiceTest {
    @TempDir
    lateinit var root: Path

    @Test
    fun `get dereferences wiki URI and includes metadata`() {
        writeMarkdown(root, "wiki/topics/mcp.md", """
            ---
            type: Topic
            status: Draft
            tags: [mcp, llm-wiki]
            ---
            # MCP
            Related to [[LLM Wiki]].
        """)

        val response = WikiResourceService(localRepository(root)).get("wiki://topic/mcp")

        assertTrue(response.ok)
        val resource = assertNotNull(response.resource)
        assertEquals("wiki://topic/mcp", resource.uri)
        assertEquals(WikiDocumentType.TOPIC, resource.type)
        assertEquals("Draft", resource.status)
        assertEquals("Topic", resource.frontmatter["type"])
        assertEquals("Draft", resource.frontmatter["status"])
        assertEquals(listOf("mcp", "llm-wiki"), resource.frontmatter["tags"])
        assertEquals("wiki/topics/mcp.md", resource.path)
        assertTrue(resource.githubUrl?.endsWith("/wiki/topics/mcp.md") == true)
        assertTrue(resource.content?.contains("# MCP") == true)
        assertTrue(resource.relatedUris.contains("wiki://raw/LLM Wiki"))
    }

    @Test
    fun `get can omit content and frontmatter while keeping resource metadata`() {
        writeMarkdown(root, "wiki/specs/pla-229.md", """
            ---
            type: Tech Spec
            status: Draft
            linear: PLA-229
            ---
            # PLA-229 LLM Wiki Application
            Implementation details are intentionally optional for lightweight reads.
        """)

        val response = WikiResourceService(localRepository(root)).get(
            uri = "wiki://spec/pla-229",
            includeContent = false,
            includeFrontmatter = false,
        )

        assertTrue(response.ok)
        val resource = assertNotNull(response.resource)
        assertEquals("wiki://spec/pla-229", resource.uri)
        assertEquals(WikiDocumentType.SPEC, resource.type)
        assertEquals("Draft", resource.status)
        assertEquals(emptyMap(), resource.frontmatter)
        assertEquals(null, resource.content)
        assertEquals("wiki/specs/pla-229.md", resource.path)
        assertTrue(resource.githubUrl?.endsWith("/wiki/specs/pla-229.md") == true)
    }

    @Test
    fun `get can omit content or frontmatter while retaining uri status and github metadata`() {
        writeMarkdown(root, "wiki/specs/contract.md", """
            ---
            type: Tech Spec
            status: Accepted
            related_documents: [wiki://adr/contract]
            ---
            # Contract
            Body should be optional.
        """)

        val response = WikiResourceService(localRepository(root)).get(
            uri = "wiki://spec/contract",
            includeContent = false,
            includeFrontmatter = false,
        )

        assertTrue(response.ok)
        val resource = assertNotNull(response.resource)
        assertEquals("wiki://spec/contract", resource.uri)
        assertEquals("Accepted", resource.status)
        assertEquals(null, resource.content)
        assertEquals(emptyMap(), resource.frontmatter)
        assertTrue(resource.githubUrl!!.endsWith("/wiki/specs/contract.md"))
    }

}
