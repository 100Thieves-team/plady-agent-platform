package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.application.WikiValidationService
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Path
import kotlin.io.path.createDirectories
import kotlin.io.path.writeText
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class WikiPendingChangeSpecificationTest {
    private val validation = WikiValidationService()

    @TempDir
    lateinit var root: Path

    @Test
    fun `allowed wiki paths pass pending change validation`() {
        val result = validation.validateTouchedFiles(
            listOf(
                "raw/note.md",
                "Clippings/source.md",
                "wiki/topic.md",
                "views/index.md",
                "adr.md",
                "tech-spec.md",
                "review-summary.md",
                "AGENTS.md",
                "CLAUDE.md",
            ),
        )

        assertTrue(result.ok)
        assertEquals(emptyList(), result.issues)
    }

    @Test
    fun `disallowed pending change paths are surfaced as validation errors`() {
        val result = validation.validateTouchedFiles(
            listOf(
                "../escape.md",
                "/tmp/wiki.md",
                ".git/config",
                "src/main/kotlin/App.kt",
                "raw/diagram.png",
            ),
        )

        assertFalse(result.ok)
        assertTrue(result.issues.any { it.code == "DISALLOWED_PATH" && it.path == "../escape.md" })
        assertTrue(result.issues.any { it.code == "DISALLOWED_PATH" && it.path == "/tmp/wiki.md" })
        assertTrue(result.issues.any { it.code == "DISALLOWED_PATH" && it.path == ".git/config" })
        assertTrue(result.issues.any { it.code == "OUTSIDE_ALLOWED_WIKI_PATHS" && it.path == "src/main/kotlin/App.kt" })
        assertTrue(result.issues.any { it.code == "NON_MARKDOWN_CHANGE" && it.path == "raw/diagram.png" && it.severity == "warning" })
    }

    @Test
    fun `markdown and wikilink validation runs against touched wiki files`() {
        root.resolve("wiki/topics").createDirectories()
        root.resolve("wiki/topics/existing.md").writeText("# Existing Topic\n")
        root.resolve("wiki/topics/title-drift.md").writeText(
            """
            # Different Heading
            Link to [[Existing Topic]], [[Missing Topic]], and [[]].
            """.trimIndent(),
        )

        val result = validation.validateTouchedFiles(listOf("wiki/topics/title-drift.md"), root)

        assertFalse(result.ok)
        assertTrue(result.issues.any { it.code == "TITLE_DRIFT" && it.severity == "warning" })
        assertTrue(result.issues.any { it.code == "BROKEN_WIKILINK" && it.severity == "error" })
        assertTrue(result.issues.any { it.code == "EMPTY_WIKILINK" && it.severity == "error" })
    }
}
