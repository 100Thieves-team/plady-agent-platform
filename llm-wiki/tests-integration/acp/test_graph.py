from acp.conftest import make_acp_env


async def test_graph_default_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:graph",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_graph_missing_slug_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:graph zzz-missing-root-slug",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_graph_prompt_stop_reason_end_turn(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:graph",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"
