def test_content_read_by_slug(wiki_env):
    result = wiki_env.run("content", "read", "concepts/mixture-of-experts")
    assert "Mixture of Experts" in result.stdout


def test_content_read_cross_wiki_uri(wiki_env):
    result = wiki_env.run("content", "read", "wiki://notes/concepts/attention-mechanism")
    assert result.returncode == 0
