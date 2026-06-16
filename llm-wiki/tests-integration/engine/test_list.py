def test_list_returns_pages(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("list")
    assert "concept" in result.stdout


def test_list_json_has_pages(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("list")
    assert len(data["pages"]) > 0


def test_list_type_filter(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("list", "--type", "concept")
    assert "concept" in result.stdout


def test_list_json_type_filter(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("list", "--type", "concept")
    assert all(p["type"] == "concept" for p in data["pages"])


def test_list_pagination(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("list", "--page", "1", "--page-size", "2")
    assert "Page 1" in result.stdout
