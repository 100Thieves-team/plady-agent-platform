package io.plady._00thieveswikimcp.wiki.infrastructure

import io.plady._00thieveswikimcp.wiki.api.WikiDocument
import io.plady._00thieveswikimcp.wiki.api.WikiDocumentType
import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import org.springframework.stereotype.Repository
import java.nio.file.Files
import java.nio.file.Path
import java.time.Instant
import kotlin.io.path.exists
import kotlin.io.path.invariantSeparatorsPathString
import kotlin.io.path.isRegularFile
import kotlin.io.path.nameWithoutExtension
import kotlin.io.path.readText

@Repository
class LocalWikiRepository(
    private val properties: WikiProperties,
    private val markdownReader: MarkdownFrontmatterReader,
    private val uriMapper: WikiUriMapper,
) {
    private val root: Path get() = properties.repoRoot.toAbsolutePath().normalize()

    fun isAvailable(): Boolean = root.exists() && Files.isDirectory(root)

    fun listDocuments(): List<WikiDocument> {
        if (!isAvailable()) return emptyList()
        return Files.walk(root).use { stream ->
            stream
                .filter { it.isRegularFile() && it.fileName.toString().endsWith(".md", ignoreCase = true) }
                .map { toDocument(it) }
                .toList()
                .sortedBy { it.path }
        }
    }

    fun findByUri(uri: String): WikiDocument? {
        if (!isAvailable()) return null
        val byCandidate = uriMapper.candidatesFor(uri)
            .asSequence()
            .map { safeResolve(it) }
            .firstOrNull { it != null && it.exists() && it.isRegularFile() }
            ?.let { toDocument(it) }
        if (byCandidate != null) return byCandidate

        val wantedSlug = uriMapper.slugFromUri(uri).lowercase()
        return listDocuments().firstOrNull { document ->
            document.uri == uri || document.path.removeSuffix(".md").substringAfterLast('/').lowercase() == wantedSlug
        }
    }

    fun toReference(document: WikiDocument) = io.plady._00thieveswikimcp.wiki.api.WikiResourceReference(
        uri = document.uri,
        title = document.title,
        type = document.type,
        status = document.status,
        path = document.path,
        githubUrl = document.githubUrl,
        tags = document.tags,
    )

    fun safeResolve(relativePath: String): Path? {
        val resolved = root.resolve(relativePath).normalize()
        return if (resolved.startsWith(root)) resolved else null
    }

    private fun toDocument(path: Path): WikiDocument {
        val relative = root.relativize(path).normalize()
        val relativeString = relative.invariantSeparatorsPathString
        val raw = path.readText()
        val parsed = markdownReader.parse(raw)
        val title = extractTitle(parsed.frontmatter, parsed.body, path.nameWithoutExtension)
        val type = uriMapper.typeFor(relative, parsed.frontmatter)
        val status = parsed.frontmatter["status"]?.toString()
        val tags = extractTags(parsed.frontmatter)
        val uri = uriMapper.toUri(relative, parsed.frontmatter)
        val githubUrl = "${properties.githubBaseUrl.trimEnd('/')}/$relativeString"
        val modified = Files.getLastModifiedTime(path).toInstant()
        return WikiDocument(
            path = relativeString,
            absolutePath = path.toAbsolutePath().normalize().toString(),
            uri = uri,
            title = title,
            type = type,
            status = status,
            frontmatter = parsed.frontmatter,
            body = parsed.body,
            rawContent = raw,
            githubUrl = githubUrl,
            tags = tags,
            lastModifiedAt = modified,
        )
    }

    private fun extractTitle(frontmatter: Map<String, Any?>, body: String, fallback: String): String {
        frontmatter["title"]?.toString()?.takeIf { it.isNotBlank() }?.let { return it }
        frontmatter["aliases"]?.let { aliases ->
            when (aliases) {
                is List<*> -> aliases.firstOrNull()?.toString()?.takeIf { it.isNotBlank() }?.let { return it }
                else -> aliases.toString().takeIf { it.isNotBlank() }?.let { return it }
            }
        }
        return body.lines().firstOrNull { it.startsWith("# ") }?.removePrefix("# ")?.trim()?.takeIf { it.isNotBlank() }
            ?: fallback
    }

    private fun extractTags(frontmatter: Map<String, Any?>): List<String> {
        val raw = frontmatter["tags"] ?: return emptyList()
        return when (raw) {
            is List<*> -> raw.mapNotNull { it?.toString()?.trim() }
            else -> raw.toString().split(',', ' ').map { it.trim() }
        }.filter { it.isNotBlank() }
    }
}
