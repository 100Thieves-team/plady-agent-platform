from conftest import SPACE_NAME


async def test_spaces_list_returns_research(mcp_env):
    text = await mcp_env.call("wiki_spaces_list")
    assert SPACE_NAME in text


async def test_spaces_list_json_contains_research(mcp_env):
    data = await mcp_env.json("wiki_spaces_list")
    assert any(w["name"] == SPACE_NAME for w in data)


async def test_spaces_set_default_research(mcp_env):
    text = await mcp_env.call("wiki_spaces_set_default", {"name": SPACE_NAME})
    assert SPACE_NAME in text
