package io.plady._00thieveswikimcp.wiki.api

import java.time.Instant

data class WikiResourceReference(
    val uri: String,
    val title: String,
    val type: WikiDocumentType,
    val status: String? = null,
    val path: String,
    val githubUrl: String? = null,
    val tags: List<String> = emptyList(),
)

data class WikiResourceContent(
    val uri: String,
    val title: String,
    val type: WikiDocumentType,
    val status: String? = null,
    val frontmatter: Map<String, Any?> = emptyMap(),
    val content: String? = null,
    val githubUrl: String? = null,
    val relatedUris: List<String> = emptyList(),
    val path: String,
    val lastModifiedAt: Instant? = null,
)

/** Internal representation of a markdown document in the configured wiki repository. */
data class WikiDocument(
    val path: String,
    val absolutePath: String,
    val uri: String,
    val title: String,
    val type: WikiDocumentType,
    val status: String?,
    val frontmatter: Map<String, Any?>,
    val body: String,
    val rawContent: String,
    val githubUrl: String?,
    val tags: List<String>,
    val lastModifiedAt: Instant?,
)
