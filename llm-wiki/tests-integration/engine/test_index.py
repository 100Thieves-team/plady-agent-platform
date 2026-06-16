def test_index_rebuild_research(wiki_env):
    result = wiki_env.run("index", "rebuild", "--wiki", "research")
    assert "Indexed" in result.stdout


def test_index_status_research(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    result = wiki_env.run("index", "status", "--wiki", "research")
    assert "research" in result.stdout


def test_index_rebuild_notes(wiki_env):
    result = wiki_env.run("index", "rebuild", "--wiki", "notes")
    assert "Indexed" in result.stdout
