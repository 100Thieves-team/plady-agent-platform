def test_stats_returns_output(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("stats")
    assert "research" in result.stdout


def test_stats_json_pages(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("stats")
    assert data["pages"] > 0


def test_stats_json_fields(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("stats")
    assert "communities" in data
    assert "diameter" in data
    assert "radius" in data
    assert isinstance(data["center"], list)
