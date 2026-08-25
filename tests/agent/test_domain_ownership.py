"""Domain-ownership policy guard tests."""

from pathlib import Path


def test_atlas_can_edit_code_and_tests_without_approval():
    from agent.domain_ownership import check_paths

    result = check_paths(
        ["agent/communication_layer.py", "tests/agent/test_communication_layer.py"],
        actor="Atlas",
    )

    assert result.allowed is True
    assert result.violations == []


def test_sage_is_blocked_from_implementation_without_owner_approval():
    from agent.domain_ownership import check_paths

    result = check_paths(
        ["agent/communication_layer.py"],
        actor="Sage",
    )

    assert result.allowed is False
    assert result.violations
    assert result.violations[0].required_owner == "Atlas"
    assert "implementation" in result.violations[0].domain


def test_cross_lane_approval_allows_blocked_path():
    from agent.domain_ownership import check_paths

    result = check_paths(
        ["gateway/run.py"],
        actor="Atlas",
        approvals={"Fitz"},
    )

    assert result.allowed is True
    assert result.violations == []


def test_policy_artifact_loads_from_repo():
    from agent.domain_ownership import load_policy

    policy = load_policy(Path(__file__).resolve().parents[2] / "docs" / "domain-ownership.yaml")

    assert policy["owners"]["research"] == "Sage"
    assert policy["owners"]["implementation"] == "Atlas"
    assert policy["owners"]["runtime"] == "Fitz"
    assert policy["owners"]["orchestration"] == "Winston"
