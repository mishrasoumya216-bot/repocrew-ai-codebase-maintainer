"""Tests for Reviewer guardrails:
- Reviewer must reject any candidate patch that deletes test assertions or test lines.
"""
import asyncio
from backend import agents
from backend.sandbox import TestEvaluation


def test_reviewer_rejects_on_deleted_test():
    async def _run():
        deleted_test_diff = (
            "--- a/tests/test_miniutils.py\n"
            "+++ b/tests/test_miniutils.py\n"
            "@@ -10,6 +10,3 @@\n"
            " def test_average():\n"
            "-    assert average([]) == 0\n"
            "-    assert average([1, 2]) == 1.5\n"
            "     pass\n"
        )

        eval_result = TestEvaluation(
            tests_passed=True,
            patch_applied=True,
            engine="local",
            detail="Suite green after deleting test",
            raw_output="2 passed in 0.05s",
            total=2,
            failed=0,
            passed_count=2,
        )

        class DummyIssue:
            number = 1

        review = await agents.run_reviewer(
            run_id=999,
            issue=DummyIssue(),
            diff=deleted_test_diff,
            test_result=eval_result,
            attempt=1,
        )

        assert review["verdict"] == "REJECT"
        assert any("deletes test" in note.lower() for note in review.get("notes", []))

    asyncio.run(_run())
