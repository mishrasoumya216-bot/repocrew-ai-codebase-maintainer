"""RepoCrew orchestrator test: the hard 3-attempt retry limit."""
import asyncio

from backend import agents, orchestrator
from backend.database import SessionLocal
from backend.diffutil import make_file_diff
from backend import config
from backend.models import Issue, Run


def _breaking_diff() -> str:
    """A valid patch that breaks average() on purpose (tests will really fail)."""
    path = config.SAMPLE_REPO_DIR / "miniutils" / "__init__.py"
    full = path.read_text(encoding="utf-8")
    bad = full.replace(
        "    return sum(nums) / len(nums)",
        "    return -999  # deliberately wrong",
    )
    assert bad != full
    return make_file_diff("miniutils/__init__.py", full, bad)


def test_retry_limit_stops_run_needs_human(monkeypatch):
    async def always_wrong_coder(run_id, issue, attempt, prev_diff, feedback):
        return _breaking_diff()

    monkeypatch.setattr(agents, "run_coder", always_wrong_coder)

    session = SessionLocal()
    try:
        issue = session.query(Issue).filter_by(number=1).one()
        run_id = orchestrator.create_run(issue.id)
    finally:
        session.close()

    asyncio.run(orchestrator.run_pipeline(run_id))

    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        assert run.status == "STOPPED_NEEDS_HUMAN"
        assert run.attempts == 3 == run.max_attempts
        assert "attempts" in (run.summary or "")
        assert run.finished_at is not None
    finally:
        session.close()
