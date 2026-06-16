package io.plady._00thieveswikimcp.wiki

import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Test
import org.springframework.boot.test.context.SpringBootTest
import org.springframework.boot.test.web.server.LocalServerPort
import org.springframework.test.context.DynamicPropertyRegistry
import org.springframework.test.context.DynamicPropertySource
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.createDirectories
import kotlin.io.path.deleteIfExists
import kotlin.io.path.exists
import kotlin.io.path.isDirectory
import kotlin.io.path.listDirectoryEntries
import kotlin.io.path.writeText
import kotlin.test.assertTrue

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class McpE2ETest {
    @LocalServerPort
    private var port: Int = 0

    private val client = HttpClient.newHttpClient()

    @BeforeEach
    fun resetWikiFixture() {
        deleteChildren(repoRoot)
        deleteChildren(pendingRoot)
        repoRoot.createDirectories()
        pendingRoot.createDirectories()
        writeMarkdown(repoRoot, "wiki/decision-backlog.md", """
            ---
            type: Backlog
            status: Draft
            ---
            # Decision Backlog
            - [ ] Decide MCP deployment policy.
        """)
        writeMarkdown(repoRoot, "wiki/sources/pla-229.md", """
            ---
            type: Source
            status: Draft
            tags: [mcp]
            ---
            # PLA-229 LLM Wiki MCP
            PLA-229 defines wiki_search, wiki_get, and pending approval workflow.
            Open question: when should PR creation be enabled?
        """)
    }

    @Test
    fun `MCP initialize and list endpoints expose the planned contract`() {
        val session = initializeSession()

        val tools = rpc(session, 2, "tools/list")
        assertTrue(tools.contains("wiki_search"))
        assertTrue(tools.contains("wiki_get"))
        assertTrue(tools.contains("wiki_get_related_context"))
        assertTrue(tools.contains("wiki_triage"))
        assertTrue(tools.contains("wiki_lint"))
        assertTrue(tools.contains("wiki_run_task"))
        assertTrue(tools.contains("wiki_get_pending"))
        assertTrue(tools.contains("wiki_commit_pending"))
        assertTrue(tools.contains("wiki_abort_pending"))
        assertTrue(tools.contains("wiki_extend_pending_lock"))
        assertTrue(tools.contains("\"required\":[\"query\"]"), "wiki_search should require only query among its optional arguments")

        val resources = rpc(session, 3, "resources/list")
        assertTrue(resources.contains("wiki://backlog"))

        val templates = rpc(session, 4, "resources/templates/list")
        assertTrue(templates.contains("wiki://raw/{path}"))
        assertTrue(templates.contains("wiki://source/{slug}"))
        assertTrue(templates.contains("wiki://topic/{slug}"))
        assertTrue(templates.contains("wiki://adr/{id}"))
        assertTrue(templates.contains("wiki://spec/{id}"))
        assertTrue(templates.contains("wiki://review/{id}"))

        val prompts = rpc(session, 5, "prompts/list")
        assertTrue(prompts.contains("wiki_create_adr_draft"))
        assertTrue(prompts.contains("wiki_create_spec_draft"))
        assertTrue(prompts.contains("wiki_summarize_review"))
        assertTrue(prompts.contains("wiki_maintain_decision_backlog"))
        assertTrue(prompts.contains("wiki_propose_doc_patch"))
    }

    @Test
    fun `MCP tools call search get and fail-closed workflow without exposing git primitives`() {
        val session = initializeSession()

        val search = toolCall(
            session,
            10,
            "wiki_search",
            """{"query":"PLA-229 pending","types":["source"],"tags":["mcp"],"limit":5}""",
        )
        assertTrue(search.contains("\"ok\":true"))
        assertTrue(search.contains("wiki://source/pla-229"))

        val get = toolCall(
            session,
            11,
            "wiki_get",
            """{"uri":"wiki://source/pla-229"}""",
        )
        assertTrue(get.contains("\"ok\":true"))
        assertTrue(get.contains("github.com/100Thieves-team/team-wiki/blob/main/wiki/sources/pla-229.md"))
        assertTrue(get.contains("pending approval workflow"))

        val dryRun = toolCall(
            session,
            12,
            "wiki_run_task",
            """{"taskType":"ingest","instructions":"Index PLA-229 notes","dryRun":true}""",
        )
        assertTrue(dryRun.contains("DRY_RUN"))
        assertTrue(dryRun.contains("\"ok\":true"))

        val failClosed = toolCall(
            session,
            13,
            "wiki_run_task",
            """{"taskType":"ingest","instructions":"Run external agent on a clean repo"}""",
        )
        assertTrue(failClosed.contains("PENDING_ENGINE_UNAVAILABLE"))
        assertTrue(failClosed.contains("\"ok\":false"))
    }

    private fun initializeSession(): String {
        val response = post(
            """
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"mcp-e2e-test","version":"0.0.1"}}}
            """.trimIndent(),
        )
        val session = response.headers().firstValue("Mcp-Session-Id").orElseThrow()
        assertTrue(response.body().contains("100Thieves LLM Wiki MCP"))
        post("""{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}""", session)
        return session
    }

    private fun rpc(session: String, id: Int, method: String): String = eventData(
        post("""{"jsonrpc":"2.0","id":$id,"method":"$method","params":{}}""", session).body(),
    )

    private fun toolCall(session: String, id: Int, name: String, argumentsJson: String): String = eventData(
        post(
            """{"jsonrpc":"2.0","id":$id,"method":"tools/call","params":{"name":"$name","arguments":$argumentsJson}}""",
            session,
        ).body(),
    )

    private fun post(json: String, sessionId: String? = null): HttpResponse<String> {
        val builder = HttpRequest.newBuilder(URI.create("http://localhost:$port/mcp"))
            .header("Content-Type", "application/json")
            .header("Accept", "application/json, text/event-stream")
            .POST(HttpRequest.BodyPublishers.ofString(json))
        sessionId?.let { builder.header("Mcp-Session-Id", it) }
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString())
    }

    private fun eventData(body: String): String = Regex("(?m)^data:(.*)$")
        .find(body)
        ?.groupValues
        ?.get(1)
        ?: body

    private fun deleteChildren(path: Path) {
        if (!path.exists() || !path.isDirectory()) return
        path.listDirectoryEntries().forEach { child ->
            if (child.isDirectory()) deleteChildren(child)
            child.deleteIfExists()
        }
    }

    companion object {
        private val repoRoot: Path = Files.createTempDirectory("plady-wiki-e2e-repo")
        private val pendingRoot: Path = Files.createTempDirectory("plady-wiki-e2e-pending")

        @JvmStatic
        @DynamicPropertySource
        fun dynamicProperties(registry: DynamicPropertyRegistry) {
            registry.add("plady.wiki.repo-root") { repoRoot.toString() }
            registry.add("plady.wiki.pending-store-root") { pendingRoot.toString() }
            registry.add("plady.wiki.workflow.agent-runtime-enabled") { "false" }
            registry.add("plady.wiki.workflow.capture-existing-dirty") { "true" }
            registry.add("plady.wiki.workflow.push-enabled") { "false" }
        }
    }
}
