package io.plady._00thieveswikimcp.wiki.infrastructure

import org.springframework.stereotype.Component

@Component
class MarkdownFrontmatterReader {
    data class ParsedMarkdown(
        val frontmatter: Map<String, Any?>,
        val body: String,
        val raw: String,
    )

    fun parse(raw: String): ParsedMarkdown {
        val normalized = raw.replace("\r\n", "\n")
        if (!normalized.startsWith("---\n")) {
            return ParsedMarkdown(emptyMap(), normalized, raw)
        }

        val closing = normalized.indexOf("\n---", startIndex = 4)
        if (closing < 0) {
            return ParsedMarkdown(emptyMap(), normalized, raw)
        }

        val yamlBlock = normalized.substring(4, closing).trim('\n')
        val bodyStart = closing + "\n---".length
        val body = normalized.substring(bodyStart).trimStart('\n')
        return ParsedMarkdown(parseSimpleYaml(yamlBlock), body, raw)
    }

    /**
     * Intentionally small YAML-frontmatter parser for Obsidian-style markdown metadata.
     * It supports scalar keys and simple block/inline lists without making the read path
     * depend on a broad YAML object model.
     */
    private fun parseSimpleYaml(block: String): Map<String, Any?> {
        val result = linkedMapOf<String, Any?>()
        var currentListKey: String? = null
        val currentItems = mutableListOf<String>()

        fun flushList() {
            val key = currentListKey ?: return
            result[key] = currentItems.toList()
            currentItems.clear()
            currentListKey = null
        }

        block.lines().forEach { rawLine ->
            val line = rawLine.trimEnd()
            if (line.isBlank() || line.trimStart().startsWith("#")) return@forEach

            if (line.startsWith("  - ") || line.startsWith("- ")) {
                currentListKey?.let { currentItems.add(cleanScalar(line.substringAfter("- ").trim())) }
                return@forEach
            }

            flushList()
            val separator = line.indexOf(':')
            if (separator <= 0) return@forEach
            val key = line.substring(0, separator).trim()
            val value = line.substring(separator + 1).trim()
            if (value.isEmpty()) {
                currentListKey = key
            } else {
                result[key] = parseValue(value)
            }
        }
        flushList()
        return result
    }

    private fun parseValue(value: String): Any? {
        val clean = cleanScalar(value)
        if (clean.equals("null", ignoreCase = true) || clean == "~") return null
        if (clean.equals("true", ignoreCase = true)) return true
        if (clean.equals("false", ignoreCase = true)) return false
        if (clean.startsWith("[") && clean.endsWith("]")) {
            return clean.removePrefix("[").removeSuffix("]")
                .split(',')
                .map { cleanScalar(it.trim()) }
                .filter { it.isNotBlank() }
        }
        return clean
    }

    private fun cleanScalar(value: String): String = value
        .trim()
        .removeSurrounding("\"")
        .removeSurrounding("'")
}
