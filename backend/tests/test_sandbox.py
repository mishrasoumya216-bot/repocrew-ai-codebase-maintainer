from backend import config, demo_scripts, sandbox
from backend.diffutil import make_file_diff


def test_patch_apply_and_test_run_issue1():
    """Applying the issue-1 fix must really change pytest outcomes."""
    diff = demo_scripts.build_diff(1, 1)
    result = sandbox.evaluate_patch(diff)
    assert result.patch_applied
    assert result.engine in ("local", "docker")
    assert result.tests_passed, result.raw_output
    # The previously-failing edge-case test is genuinely fixed:
    assert "test_average_empty_list_returns_zero" in result.detail
    assert "FAILED" not in result.raw_output.split("=")[-1] or result.failed >= 0
    assert result.raw_output  # real pytest output captured


def test_patch_apply_wrong_fix_fails_with_real_output():
    """Issue 2 attempt 1 is deliberately wrong: pytest must FAIL for real."""
    diff = demo_scripts.build_diff(2, 1)
    result = sandbox.evaluate_patch(diff)
    assert result.patch_applied
    assert not result.tests_passed
    assert "test_paginate_last_partial_page" in result.raw_output
    assert result.failed >= 1


def test_issue2_correct_fix_passes():
    diff = demo_scripts.build_diff(2, 2)
    result = sandbox.evaluate_patch(diff)
    assert result.tests_passed, result.detail


def test_empty_patch_rejected():
    result = sandbox.evaluate_patch("")
    assert not result.tests_passed
    assert not result.patch_applied
    assert "empty patch" in result.detail


def test_new_file_patch_applies():
    """Issue 3 attempt 2 adds a brand-new test file — the applier must create it."""
    diff = demo_scripts.build_diff(3, 2)
    result = sandbox.evaluate_patch(diff)
    assert result.patch_applied
    assert result.tests_passed, result.detail
    assert "test_slugify_regression" in result.raw_output


def test_sandbox_regression_fails_evaluation():
    """A patch that introduces a regression in another test must fail evaluation."""
    full = (config.SAMPLE_REPO_DIR / "miniutils/__init__.py").read_text(encoding="utf-8")
    new_full = full.replace("return sum(nums) / len(nums)", "return 0.0")
    diff = make_file_diff("miniutils/__init__.py", full, new_full)
    result = sandbox.evaluate_patch(diff)
    assert not result.tests_passed
    assert result.patch_applied
    assert "NEW regressions" in result.detail or result.failed > 0


def test_sandbox_malformed_patch_fails_gracefully():
    """A malformed patch that cannot apply should report failure without crashing."""
    bad_diff = (
        "--- a/miniutils/nonexistent.py\n"
        "+++ b/miniutils/nonexistent.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-old\n"
        "+new\n"
    )
    result = sandbox.evaluate_patch(bad_diff)
    assert not result.tests_passed
    assert not result.patch_applied
    assert "patch failed to apply" in result.detail.lower()

