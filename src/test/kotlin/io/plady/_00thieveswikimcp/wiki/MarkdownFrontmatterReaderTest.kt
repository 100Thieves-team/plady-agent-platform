package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.infrastructure.MarkdownFrontmatterReader
import kotlin.test.Test
import kotlin.test.assertEquals

class MarkdownFrontmatterReaderTest {
    private val reader = MarkdownFrontmatterReader()

    @Test
    fun `parses scalar and list frontmatter`() {
        val parsed = reader.parse(
            """
            ---
            type: ADR
            status: Proposed
            tags: [planning, mcp]
            related:
              - [[ADR]]
              - [[Tech Spec]]
            ---
            # Title
            Body
            """.trimIndent(),
        )

        assertEquals("ADR", parsed.frontmatter["type"])
        assertEquals("Proposed", parsed.frontmatter["status"])
        assertEquals(listOf("planning", "mcp"), parsed.frontmatter["tags"])
        assertEquals(listOf("[[ADR]]", "[[Tech Spec]]"), parsed.frontmatter["related"])
        assertEquals("# Title\nBody", parsed.body.trim())
    }
}
