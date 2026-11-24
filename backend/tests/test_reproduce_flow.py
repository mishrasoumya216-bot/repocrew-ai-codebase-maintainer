"""Tests for the RepoCrew 'reproduce first' flow.

Requirements covered:
1. In the Coder flow, before editing source files, the Coder must produce a failing test
   that proves the bug: either identify an existing test that already fails on the
   unpatched repo, or write ONE new test in a new file under tests/ (named test_repocrew_issue_<number>.py).
2. Run it in the sandbox on the UNPATCHED repo. If it does not fail, retry once with that feedback.
   If it still does not fail, mark the run "needs-human" with reason "could not reproduce" and comment on the issue.
3. After the fix, the same test must pass, and no previously passing test may fail.
4. Add a "reproduced" boolean and the test name to TesterResult in models.py. Write a "tester" event
   with summary "Bug reproduced: <test name>".
5. Include the new test file in the PR. The existing rule that the Coder cannot edit existing test files stays;
   only the new repro test file is allowed.
6. Tests: a bug that reproduces, a bug that cannot be reproduced, and a fix that breaks another test.
"""
import asyncio
import pytest

from backend import agents, config, demo_scripts, orchestrator, sandbox
from backend.database import SessionLocal
from backend.diffutil import make_file_diff, changed_paths
from backend.models import Event, Issue, Patch, Run, TestResult, TesterResult


def _create_and_run(issue_number: int) -> Run:
    session = SessionLocal()
    try:
        issue = session.query(Issue).filter_by(number=issue_number).one()
        run_id = orchestrator.create_run(issue.id)
    finally:
        session.close()

    asyncio.run(orchestrator.run_pipeline(run_id))

    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        session.expunge(run)
        return run
    finally:
        session.close()


def test_bug_reproduces_existing_test():
    """Requirement 1, 3, 4: Existing failing test proves the bug and passes after fix."""
    run = _create_and_run(1)

    assert run.status == "AWAITING_HUMAN"

    session = SessionLocal()
    try:
        # Check that TesterResult has reproduced=True and test_name set
        test_results = session.query(TesterResult).filter_by(run_id=run.id).all()
        assert len(test_results) >= 1
        last_tr = test_results[-1]
        assert last_tr.reproduced is True
        assert last_tr.test_name == "test_average_empty_list_returns_zero"
        assert last_tr.passed is True

        # Check tester event was written with summary "Bug reproduced: <test name>"
        events = session.query(Event).filter_by(run_id=run.id, agent="tester").all()
        repro_events = [
            e for e in events
            if e.text == "Bug reproduced: test_average_empty_list_returns_zero"
            or (e.data and e.data.get("summary") == "Bug reproduced: test_average_empty_list_returns_zero")
        ]
        assert len(repro_events) >= 1
        assert repro_events[0].data.get("reproduced") is True
        assert repro_events[0].data.get("test_name") == "test_average_empty_list_returns_zero"
    finally:
        session.close()


def test_bug_reproduces_with_new_test_file(monkeypatch):
    """Requirement 1, 4, 5: Coder writes ONE new test in tests/test_repocrew_issue_<number>.py,
    reproduces on unpatched repo, and the new test file is included in the PR."""
    repro_code = (
        'from miniutils import average\n\n'
        'def test_repocrew_issue_1_repro():\n'
        '    assert average([]) == 0.0\n'
    )
    new_test_diff = make_file_diff("tests/test_repocrew_issue_1.py", None, repro_code)

    async def coder_reproduce_new_file(run_id, issue, attempt, feedback=None):
        return {
            "strategy": "new",
            "test_name": "test_repocrew_issue_1_repro",
            "file_path": "tests/test_repocrew_issue_1.py",
            "diff": new_test_diff,
            "is_new_file": True,
        }

    monkeypatch.setattr(agents, "run_coder_reproduce", coder_reproduce_new_file)

    run = _create_and_run(1)

    assert run.status == "AWAITING_HUMAN"

    session = SessionLocal()
    try:
        # Check event
        events = session.query(Event).filter_by(run_id=run.id, agent="tester").all()
        repro_events = [
            e for e in events
            if "Bug reproduced: test_repocrew_issue_1_repro" in e.text
            or (e.data and "test_repocrew_issue_1_repro" in str(e.data.get("summary", "")))
        ]
        assert len(repro_events) >= 1

        # Check patch includes the new test file
        patches = session.query(Patch).filter_by(run_id=run.id).all()
        assert len(patches) >= 1
        last_patch = patches[-1]
        paths = changed_paths(last_patch.diff)
        assert "tests/test_repocrew_issue_1.py" in paths
        assert "miniutils/__init__.py" in paths

        # Check TesterResult
        tr = session.query(TesterResult).filter_by(run_id=run.id).first()
        assert tr.reproduced is True
        assert tr.test_name == "test_repocrew_issue_1_repro"
        assert tr.passed is True
    finally:
        session.close()


def test_bug_cannot_be_reproduced_marks_needs_human(monkeypatch):
    """Requirement 2, 6: If the test does not fail on unpatched repo, retry once with feedback.
    If still failing to reproduce, mark run 'needs-human' with reason 'could not reproduce'
    and comment on the issue."""
    attempts = []

    async def non_failing_reproduce(run_id, issue, attempt, feedback=None):
        attempts.append({"attempt": attempt, "feedback": feedback})
        # This test passes on unpatched repo (average of [1, 2, 3] is 2.0)
        return {
            "strategy": "existing",
            "test_name": "test_average_basic",
        }

    monkeypatch.setattr(agents, "run_coder_reproduce", non_failing_reproduce)

    run = _create_and_run(1)

    # Must be marked needs-human (supports both string equalities)
    assert run.status == "needs-human"
    assert run.status == "STOPPED_NEEDS_HUMAN"
    assert run.summary == "could not reproduce"

    # Must have retried once with feedback (total 2 reproduction attempts)
    assert len(attempts) == 2
    assert attempts[0]["attempt"] == 1
    assert attempts[1]["attempt"] == 2
    assert attempts[1]["feedback"] is not None
    assert "did not fail" in attempts[1]["feedback"]

    # Verify comment on issue event
    session = SessionLocal()
    try:
        events = session.query(Event).filter_by(run_id=run.id).all()
        comment_events = [
            e for e in events
            if "could not reproduce" in e.text.lower()
        ]
        assert len(comment_events) >= 1

        # Verify no source code patches were applied
        patches_count = session.query(Patch).filter_by(run_id=run.id).count()
        assert patches_count == 0
    finally:
        session.close()


def test_fix_breaks_another_test_fails_eval():
    """Requirement 3, 6: After the fix, no previously passing test may fail (regression)."""
    # A patch that fixes average([]) by hardcoding 0.0, but breaks average([1, 2, 3])
    source_file = config.SAMPLE_REPO_DIR / "miniutils" / "__init__.py"
    original = source_file.read_text(encoding="utf-8")
    breaking_replacement = original.replace(
        "    return sum(nums) / len(nums)",
        "    if not nums: return 0.0\n    return -999.0  # breaks other tests!",
    )
    diff = make_file_diff("miniutils/__init__.py", original, breaking_replacement)

    # Evaluate with repro_test
    eval_result = sandbox.evaluate_patch(diff, repro_test="test_average_empty_list_returns_zero")

    assert eval_result.patch_applied is True
    # Even though repro test passed, another test broke -> tests_passed must be False!
    assert eval_result.tests_passed is False
    assert "NEW regressions" in eval_result.detail
    assert "test_average_basic" in eval_result.detail


def test_coder_cannot_edit_existing_test_files():
    """Requirement 5: Existing test files cannot be modified; only new repro test files are allowed."""
    # Attempt to modify sample_repo/tests/test_miniutils.py (existing file)
    with pytest.raises(ValueError, match="cannot edit existing test file"):
        agents.validate_coder_paths(["tests/test_miniutils.py"])

    # Adding a brand-new test file named tests/test_repocrew_issue_1.py is allowed
    agents.validate_coder_paths(["tests/test_repocrew_issue_1.py"])
    agents.validate_coder_paths(["miniutils/__init__.py", "tests/test_repocrew_issue_42.py"])


def test_models_tester_result_and_app_import():
    """Requirement 4 & Schema requirement: schemas in app/models.py and models.py."""
    import app.models as app_models
    import backend.models as backend_models

    # Both must expose TesterResult and TestResult
    assert app_models.TesterResult is app_models.TestResult
    assert backend_models.TesterResult is backend_models.TestResult

    tr = app_models.TesterResult(
        run_id=999,
        attempt=1,
        reproduced=True,
        test_name="test_foo",
    )
    assert tr.reproduced is True
    assert tr.test_name == "test_foo"
    assert tr.repro_test == "test_foo"
