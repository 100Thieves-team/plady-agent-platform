def test_search_basic_returns_results(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("search", "mixture of experts")
    assert "mixture" in result.stdout.lower()


def test_search_type_filter(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("search", "routing", "--type", "concept")
    assert "concept" in result.stdout.lower() or result.stdout.strip()


def test_search_cross_wiki(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    wiki_env.run("index", "rebuild", "--wiki", "notes")
    result = wiki_env.run("search", "attention", "--cross-wiki")
    assert result.returncode == 0


def test_search_json_has_results(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("search", "transformer")
    assert len(data["results"]) > 0
