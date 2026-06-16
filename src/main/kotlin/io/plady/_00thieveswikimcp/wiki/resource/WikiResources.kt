package io.plady._00thieveswikimcp.wiki.resource

import io.plady._00thieveswikimcp.wiki.application.WikiResourceService
import org.springframework.ai.mcp.annotation.McpResource
import org.springframework.stereotype.Component

@Component
class WikiResources(
    private val resourceService: WikiResourceService,
) {
    @McpResource(
        name = "wiki_raw",
        title = "LLM Wiki Raw Source",
        uri = "wiki://raw/{path}",
        description = "Read-only Raw source note from the Plady LLM Wiki.",
        mimeType = "text/markdown",
    )
    fun raw(path: String): String = resourceService.resourceText("wiki://raw/$path")

    @McpResource(
        name = "wiki_source",
        title = "LLM Wiki Source Summary",
        uri = "wiki://source/{slug}",
        description = "Read-only 1:1 source summary from wiki/sources.",
        mimeType = "text/markdown",
    )
    fun source(slug: String): String = resourceService.resourceText("wiki://source/$slug")

    @McpResource(
        name = "wiki_topic",
        title = "LLM Wiki Topic",
        uri = "wiki://topic/{slug}",
        description = "Read-only topic/index page from wiki/topics.",
        mimeType = "text/markdown",
    )
    fun topic(slug: String): String = resourceService.resourceText("wiki://topic/$slug")

    @McpResource(
        name = "wiki_adr",
        title = "LLM Wiki ADR",
        uri = "wiki://adr/{id}",
        description = "Read-only Architecture Decision Record with status metadata.",
        mimeType = "text/markdown",
    )
    fun adr(id: String): String = resourceService.resourceText("wiki://adr/$id")

    @McpResource(
        name = "wiki_spec",
        title = "LLM Wiki Tech Spec",
        uri = "wiki://spec/{id}",
        description = "Read-only Tech Spec with status metadata.",
        mimeType = "text/markdown",
    )
    fun spec(id: String): String = resourceService.resourceText("wiki://spec/$id")

    @McpResource(
        name = "wiki_review",
        title = "LLM Wiki Review Summary",
        uri = "wiki://review/{id}",
        description = "Read-only Review Summary document.",
        mimeType = "text/markdown",
    )
    fun review(id: String): String = resourceService.resourceText("wiki://review/$id")

    @McpResource(
        name = "wiki_backlog",
        title = "LLM Wiki Decision Backlog",
        uri = "wiki://backlog",
        description = "Read-only Decision Backlog document.",
        mimeType = "text/markdown",
    )
    fun backlog(): String = resourceService.resourceText("wiki://backlog")
}
