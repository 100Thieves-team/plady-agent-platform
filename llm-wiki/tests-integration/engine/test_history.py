def test_history_returns_commits(wiki_env):
    result = wiki_env.run("history", "concepts/mixture-of-experts")
    assert result.returncode == 0
    assert len(result.stdout.strip()) > 0


def test_history_json_has_entries(wiki_env):
    data = wiki_env.json("history", "concepts/mixture-of-experts")
    assert "entries" in data
    assert len(data["entries"]) > 0
