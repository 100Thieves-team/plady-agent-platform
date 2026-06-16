import json

from acp.conftest import make_acp_env


async def test_use_existing_slug_returns_response(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = json.loads(wiki_env.run("list", "--wiki", "research", "--format", "json").stdout)
    slug = data["pages"][0]["slug"]

    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text=f"llm-wiki:use {slug}",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_use_without_slug_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:use",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"


async def test_use_missing_slug_returns_response(wiki_env):
    acp = make_acp_env(wiki_env)
    _, result = await acp.prompt(
        cwd=str(wiki_env.tmp),
        text="llm-wiki:use zzz-missing-slug-xyz",
        wiki="research",
    )
    assert result.get("stopReason") == "end_turn"
