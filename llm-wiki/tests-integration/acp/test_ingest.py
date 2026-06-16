from acp.conftest import make_acp_env


async def test_ingest_default_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:ingest",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_ingest_nonexistent_path_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:ingest /nonexistent-path-xyz",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_ingest_prompt_stop_reason_end_turn(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:ingest",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"
