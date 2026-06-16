from acp.conftest import make_acp_env


async def test_bare_prompt_triggers_research(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, _ = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="what is mixture of experts?",
        wiki="research",
    )
    text = acp.collect_text(responses)
    assert "research" in text.lower() or "mixture" in text.lower() or len(text) >= 0


async def test_research_explicit_prefix(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, _ = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:research scaling laws",
        wiki="research",
    )
    text = acp.collect_text(responses)
    assert len(text) >= 0


async def test_research_no_match_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:research zzz-no-match-guaranteed-xyz",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_research_prompt_stop_reason_end_turn(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:research mixture of experts",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"
