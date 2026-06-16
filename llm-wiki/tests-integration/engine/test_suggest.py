def test_suggest_returns_results(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("suggest", "concepts/mixture-of-experts")
    assert result.returncode == 0


def test_suggest_json_is_array(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("suggest", "concepts/mixture-of-experts")
    assert isinstance(data, list)
