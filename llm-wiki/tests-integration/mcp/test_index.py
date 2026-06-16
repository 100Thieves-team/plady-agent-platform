from conftest import SPACE_NAME


async def test_index_rebuild_returns_pages_indexed(mcp_env):
    data = await mcp_env.json("wiki_index_rebuild", {"wiki": SPACE_NAME})
    assert data["pages_indexed"] > 0


async def test_index_status_has_built_timestamp(mcp_env):
    await mcp_env.call("wiki_index_rebuild", {"wiki": SPACE_NAME})
    data = await mcp_env.json("wiki_index_status", {"wiki": SPACE_NAME})
    assert isinstance(data["built"], str)


async def test_index_status_queryable(mcp_env):
    await mcp_env.call("wiki_index_rebuild", {"wiki": SPACE_NAME})
    data = await mcp_env.json("wiki_index_status", {"wiki": SPACE_NAME})
    assert data["queryable"] is True
