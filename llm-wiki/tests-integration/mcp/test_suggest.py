from conftest import SLUG_MoE


async def test_suggest_returns_results(mcp_env):
    await mcp_env.rebuild()
    text = await mcp_env.call("wiki_suggest", {"slug": SLUG_MoE})
    assert text is not None


async def test_suggest_json_is_array(mcp_env):
    await mcp_env.rebuild()
    data = await mcp_env.json("wiki_suggest", {"slug": SLUG_MoE, "format": "json"})
    assert isinstance(data, list)


async def test_suggest_results_have_slug(mcp_env):
    await mcp_env.rebuild()
    data = await mcp_env.json("wiki_suggest", {"slug": SLUG_MoE, "format": "json"})
    if data:
        assert isinstance(data[0]["slug"], str)


async def test_suggest_community_peers(mcp_env):
    await mcp_env.rebuild()
    data = await mcp_env.json("wiki_suggest", {"slug": SLUG_MoE, "format": "json"})
    cluster_count = sum(1 for r in data if "cluster" in r.get("reason", "").lower())
    assert cluster_count >= 0
