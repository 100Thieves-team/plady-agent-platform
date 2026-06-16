package io.plady._00thieveswikimcp.wiki.infrastructure

import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import io.plady._00thieveswikimcp.wiki.api.normalizeType
import org.springframework.stereotype.Component
import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.nio.file.Path
import kotlin.io.path.extension
import kotlin.io.path.invariantSeparatorsPathString
import kotlin.io.path.nameWithoutExtension

@Component
class WikiUriMapper {
    fun toUri(relativePath: Path, frontmatter: Map<String, Any?> = emptyMap()): String {
        val path = relativePath.invariantSeparatorsPathString.trimStart('/')
        val type = frontmatter["type"]?.toString().normalizeType()
        return when {
            path == "wiki/decision-backlog.md" || path.equals("decision-backlog.md", ignoreCase = true) -> "wiki://backlog"
            path.startsWith("raw/") || path.startsWith("Clippings/") -> "wiki://raw/${encodePath(path.substringAfter('/'))}"
            path.startsWith("wiki/sources/") -> "wiki://source/${encodeSlug(relativePath.nameWithoutExtension)}"
            path.startsWith("wiki/topics/") -> "wiki://topic/${encodeSlug(relativePath.nameWithoutExtension)}"
            type == WikiDocumentType.ADR || path.contains("/adr", ignoreCase = true) || path.startsWith("adr", ignoreCase = true) -> "wiki://adr/${encodeSlug(relativePath.nameWithoutExtension)}"
            type == WikiDocumentType.SPEC || path.contains("spec", ignoreCase = true) -> "wiki://spec/${encodeSlug(relativePath.nameWithoutExtension)}"
            type == WikiDocumentType.REVIEW || path.contains("review", ignoreCase = true) -> "wiki://review/${encodeSlug(relativePath.nameWithoutExtension)}"
            else -> "wiki://raw/${encodePath(path)}"
        }
    }

    fun typeFor(relativePath: Path, frontmatter: Map<String, Any?> = emptyMap()): WikiDocumentType {
        val explicit = frontmatter["type"]?.toString().normalizeType()
        if (explicit != WikiDocumentType.UNKNOWN) return explicit
        val path = relativePath.invariantSeparatorsPathString.lowercase()
        return when {
            path.startsWith("raw/") || path.startsWith("clippings/") -> WikiDocumentType.RAW
            path.startsWith("wiki/sources/") -> WikiDocumentType.SOURCE
            path.startsWith("wiki/topics/") -> WikiDocumentType.TOPIC
            path == "wiki/decision-backlog.md" || path.endsWith("decision-backlog.md") -> WikiDocumentType.BACKLOG
            path.contains("adr") -> WikiDocumentType.ADR
            path.contains("spec") -> WikiDocumentType.SPEC
            path.contains("review") -> WikiDocumentType.REVIEW
            else -> WikiDocumentType.UNKNOWN
        }
    }

    fun candidatesFor(uri: String): List<String> {
        val normalized = uri.trim()
        require(normalized.startsWith("wiki://")) { "Unsupported wiki URI: $uri" }
        val rest = normalized.removePrefix("wiki://")
        val kind = rest.substringBefore('/', missingDelimiterValue = rest)
        val rawId = rest.substringAfter('/', missingDelimiterValue = "")
        val id = decode(rawId).trim('/').removeSuffix(".md")
        fun withMd(path: String): String = if (path.endsWith(".md")) path else "$path.md"

        return when (kind) {
            "raw" -> listOf(withMd("raw/$id"), withMd(id), withMd("Clippings/$id"))
            "source" -> listOf(withMd("wiki/sources/$id"), withMd("sources/$id"))
            "topic" -> listOf(withMd("wiki/topics/$id"), withMd("topics/$id"))
            "adr" -> listOf(withMd("wiki/adr/$id"), withMd("wiki/adrs/$id"), withMd("adr/$id"), withMd("adrs/$id"), withMd("wiki/ADR/$id"))
            "spec" -> listOf(withMd("wiki/specs/$id"), withMd("wiki/tech-specs/$id"), withMd("specs/$id"), withMd("tech-specs/$id"), withMd("wiki/spec/$id"))
            "review" -> listOf(withMd("wiki/reviews/$id"), withMd("wiki/review-summaries/$id"), withMd("reviews/$id"), withMd("review-summaries/$id"))
            "backlog" -> listOf("wiki/decision-backlog.md", "Decision Backlog.md", "decision-backlog.md", "wiki/backlog.md")
            else -> emptyList()
        }
    }

    fun slugFromUri(uri: String): String = decode(uri.substringAfterLast('/')).removeSuffix(".md")

    private fun encodePath(path: String): String = path.split('/').joinToString("/") { encodeSlug(it) }

    private fun encodeSlug(slug: String): String = URLEncoder.encode(slug, StandardCharsets.UTF_8).replace("+", "%20")

    private fun decode(value: String): String = URLDecoder.decode(value, StandardCharsets.UTF_8)
}
