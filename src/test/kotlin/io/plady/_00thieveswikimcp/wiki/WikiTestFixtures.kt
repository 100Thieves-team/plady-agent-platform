package io.plady._00thieveswikimcp.wiki

import io.plady._00thieveswikimcp.wiki.config.WikiProperties
import io.plady._00thieveswikimcp.wiki.infrastructure.LocalWikiRepository
import io.plady._00thieveswikimcp.wiki.infrastructure.MarkdownFrontmatterReader
import io.plady._00thieveswikimcp.wiki.infrastructure.WikiUriMapper
import java.nio.file.Path
import kotlin.io.path.createDirectories
import kotlin.io.path.writeText

internal fun wikiProperties(repoRoot: Path, pendingRoot: Path = repoRoot.resolve(".pending")) = WikiProperties(
    repoRoot = repoRoot,
    githubBaseUrl = "https://github.com/100Thieves-team/team-wiki/blob/main",
    pendingStoreRoot = pendingRoot,
)

internal fun localRepository(root: Path): LocalWikiRepository = LocalWikiRepository(
    properties = wikiProperties(root),
    markdownReader = MarkdownFrontmatterReader(),
    uriMapper = WikiUriMapper(),
)

internal fun writeMarkdown(root: Path, relative: String, content: String) {
    val file = root.resolve(relative)
    file.parent.createDirectories()
    file.writeText(content.trimIndent())
}
