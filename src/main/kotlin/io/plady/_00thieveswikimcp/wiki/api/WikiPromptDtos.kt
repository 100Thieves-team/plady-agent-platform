package io.plady._00thieveswikimcp.wiki.api

data class WikiDraftResponse(
    val ok: Boolean,
    val name: String,
    val title: String,
    val markdown: String,
    val metadata: Map<String, String> = emptyMap(),
    val writePath: String = "Use wiki_run_task to apply this draft as a pending change; prompt wrappers never write files directly.",
    val error: WikiToolError? = null,
    val meta: WikiToolMeta = WikiToolMeta(),
)
