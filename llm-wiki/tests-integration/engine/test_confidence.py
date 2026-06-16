import pytest


def test_high_confidence_ranks_first(wiki_env):
    wiki_env.run("index", "rebuild", "--wiki", "research")
    data = wiki_env.json("search", "mixture experts compute")
    results = data.get("results", [])
    if len(results) < 2:
        pytest.skip("corpus too small for ranking test")
    assert results[0]["confidence"] >= results[1].get("confidence", 0)
