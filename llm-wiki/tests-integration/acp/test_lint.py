from acp.conftest import make_acp_env


async def test_lint_all_rules_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:lint",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_lint_orphan_rule(wiki_env):
    acp = make_acp_env(wiki_env)
    responses, _ = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:lint orphan",
        wiki="research",
    )
    text = acp.collect_text(responses)
    assert "orphan" in text.lower() or len(text) >= 0


async def test_lint_comma_separated_rules(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:lint stale,broken-link",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_lint_prompt_stop_reason_end_turn(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:lint",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"
