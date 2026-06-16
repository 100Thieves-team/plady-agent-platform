import pytest


@pytest.mark.parametrize("rule", ["articulation-point", "bridge", "periphery"])
async def test_lint_structural_rule_findings_array(mcp_env, rule):
    await mcp_env.rebuild()
    data = await mcp_env.json("wiki_lint", {"rules": rule})
    assert isinstance(data["findings"], list)
    matching = [f for f in data["findings"] if f["rule"] == rule]
    for f in matching:
        assert isinstance(f.get("slug"), str)
        assert len(f["slug"]) > 0


async def test_lint_all_rules_includes_structural(mcp_env):
    await mcp_env.rebuild()
    data = await mcp_env.json("wiki_lint", {})
    rules_seen = {f["rule"] for f in data["findings"]}
    structural = {"articulation-point", "bridge", "periphery"}
    assert structural & rules_seen, f"no structural rules in: {rules_seen}"
