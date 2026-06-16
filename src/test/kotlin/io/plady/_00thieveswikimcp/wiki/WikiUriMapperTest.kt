package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import io.plady._00thieveswikimcp.wiki.infrastructure.WikiUriMapper
import kotlin.io.path.Path
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class WikiUriMapperTest {
    private val mapper = WikiUriMapper()

    @Test
    fun `maps source-of-truth paths to wiki URIs`() {
        assertEquals("wiki://raw/meeting.md", mapper.toUri(Path("raw/meeting.md")))
        assertEquals("wiki://source/meeting", mapper.toUri(Path("wiki/sources/meeting.md")))
        assertEquals("wiki://topic/auth", mapper.toUri(Path("wiki/topics/auth.md")))
        assertEquals("wiki://backlog", mapper.toUri(Path("wiki/decision-backlog.md")))
        assertEquals("wiki://adr/001-auth", mapper.toUri(Path("wiki/adrs/001-auth.md"), mapOf("type" to "ADR")))
        assertEquals(WikiDocumentType.SPEC, mapper.typeFor(Path("wiki/specs/api.md"), mapOf("type" to "Tech Spec")))
    }

    @Test
    fun `expands resource URI candidates`() {
        assertTrue("wiki/sources/meeting.md" in mapper.candidatesFor("wiki://source/meeting"))
        assertTrue("wiki/decision-backlog.md" in mapper.candidatesFor("wiki://backlog"))
    }
}
