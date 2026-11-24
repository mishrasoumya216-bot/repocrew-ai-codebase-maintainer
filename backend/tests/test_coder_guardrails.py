"""Tests for Coder guardrails:
- max 3 files
- ~40 lines
- snippet must match once
- no test / CI / dependency edits
"""
import pytest
from backend import agents
from backend.diffutil import check_snippet_matches_once, apply_unified_diff


def test_coder_guardrail_max_files():
    # 3 files is allowed
    agents.validate_coder_paths(["miniutils/a.py", "miniutils/b.py", "miniutils/c.py"])

    # 4 files violates guardrail
    with pytest.raises(ValueError, match="cannot modify more than 3 files"):
        agents.validate_coder_paths(["miniutils/a.py", "miniutils/b.py", "miniutils/c.py", "miniutils/d.py"])


def test_coder_guardrail_max_lines():
    # Small diff <= 40 lines is allowed
    small_diff = (
        "--- a/miniutils/__init__.py\n"
        "+++ b/miniutils/__init__.py\n"
        "@@ -1,3 +1,3 @@\n"
        "-old line\n"
        "+new line\n"
    )
    agents.validate_coder_diff(small_diff)

    # Large diff > 40 changed lines violates guardrail
    large_lines = ["-old line\n+new line\n" for _ in range(25)]  # 50 lines changed
    large_diff = (
        "--- a/miniutils/__init__.py\n"
        "+++ b/miniutils/__init__.py\n"
        "@@ -1,50 +1,50 @@\n"
        + "".join(large_lines)
    )
    with pytest.raises(ValueError, match="exceeds ~40 lines limit"):
        agents.validate_coder_diff(large_diff)


def test_coder_guardrail_no_dependency_edits():
    blocked_deps = [
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "setup.py",
        "Pipfile",
        "poetry.lock",
        "package.json",
        "package-lock.json",
    ]
    for dep in blocked_deps:
        with pytest.raises(ValueError, match="cannot edit dependency file"):
            agents.validate_coder_paths([dep])


def test_coder_guardrail_no_ci_edits():
    ci_paths = [
        ".github/workflows/ci.yml",
        ".gitlab-ci.yml",
        "Dockerfile",
        ".circleci/config.yml",
    ]
    for ci in ci_paths:
        with pytest.raises(ValueError, match="cannot edit CI/CD"):
            agents.validate_coder_paths([ci], enforce_ci_block=True)


def test_coder_guardrail_no_existing_test_edits():
    # Attempting to edit existing test file must be rejected
    with pytest.raises(ValueError, match="cannot edit existing test file"):
        agents.validate_coder_paths(["tests/test_miniutils.py"])


def test_snippet_must_match_once():
    sample_text = (
        "def calculate(x):\n"
        "    return x * 2\n"
        "\n"
        "def helper(y):\n"
        "    return y + 1\n"
    )

    # Context that matches once -> passes
    check_snippet_matches_once(sample_text, "return x * 2")

    # Context that matches 0 times -> error
    with pytest.raises(ValueError, match="context not found"):
        check_snippet_matches_once(sample_text, "return z * 99")

    # Context that matches multiple times (ambiguous) -> error
    with pytest.raises(ValueError, match="ambiguous snippet match.*must match once"):
        check_snippet_matches_once(sample_text, "def ")
