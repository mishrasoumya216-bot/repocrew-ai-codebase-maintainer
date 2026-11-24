"""RepoCrew safety gate tests: scoring math and blocked paths."""
from backend import demo_scripts
from backend.safety_gate import (
    THRESHOLD, blocked_reason, evaluate, includes_test_change,
)


def test_blocked_paths():
    assert blocked_reason(".github/workflows/ci.yml") is not None
    assert blocked_reason(".env") is not None
    assert blocked_reason(".env.production") is not None
    assert blocked_reason("config/app_secret.txt") is not None
    assert blocked_reason("certs/server.pem") is not None
    assert blocked_reason("deploy/priv.key") is not None
    assert blocked_reason("Dockerfile") is not None
    assert blocked_reason("services/web/Dockerfile.web") is not None
    assert blocked_reason(".gitlab-ci.yml") is not None
    assert blocked_reason("miniutils/__init__.py") is None
    assert blocked_reason("tests/test_miniutils.py") is None


def test_full_score_allows_pr():
    diff = demo_scripts.build_diff(3, 2)  # code fix + new regression test
    result = evaluate(diff, tests_passed=True, reviewer_verdict="APPROVE")
    assert result["score"] == 1.0
    assert result["score"] >= THRESHOLD
    assert result["allowed"]
    assert result["blocked_reasons"] == []
    assert includes_test_change(result["paths"])


def test_ci_patch_blocked_even_with_perfect_signals():
    """Issue 5's exact situation: all signals great, path forbidden."""
    diff = demo_scripts.build_diff(5, 1)
    result = evaluate(diff, tests_passed=True, reviewer_verdict="APPROVE")
    assert result["score"] >= THRESHOLD  # signal quality is high
    assert not result["allowed"]  # but .github/** is a blocked path
    assert result["blocked_reasons"]
    blocked_check = [c for c in result["checks"] if c["name"] == "No blocked paths touched"][0]
    assert not blocked_check["passed"]


def test_reviewer_changes_requested_lowers_score():
    diff = demo_scripts.build_diff(1, 1)
    result = evaluate(diff, tests_passed=True, reviewer_verdict="CHANGES_REQUESTED")
    # 0.5*1 + 0.3*0.4 + 0.1*1 + 0.1*0 = 0.72 -> below threshold
    assert abs(result["score"] - 0.72) < 1e-6
    assert not result["allowed"]


def test_failing_tests_block_pr():
    diff = demo_scripts.build_diff(1, 1)
    result = evaluate(diff, tests_passed=False, reviewer_verdict="APPROVE")
    assert result["score"] < THRESHOLD
    assert not result["allowed"]
