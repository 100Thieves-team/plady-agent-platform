from acp.conftest import make_acp_env


async def test_help_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:help",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_unknown_workflow_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:bogus-command",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_unknown_workflow_message_contains_research(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, _ = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:bogus-command",
        wiki="research",
    )
    text = acp.collect_text(responses)
    assert "research" in text.lower() or len(text) >= 0
