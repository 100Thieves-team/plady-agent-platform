def test_config_list_global(wiki_env):
    result = wiki_env.run("config", "list")
    assert result.returncode == 0


def test_config_get_graph_format(wiki_env):
    result = wiki_env.run("config", "get", "graph.format")
    assert result.returncode == 0
