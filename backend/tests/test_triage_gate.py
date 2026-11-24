import asyncio
from backend import agents, orchestrator
from backend.database import SessionLocal
from backend.models import Issue, Patch, Run, TestResult


def test_triage_gate_proceed_on_in_scope(monkeypatch):
    session = SessionLocal()
    try:
        issue = Issue(
            number=701,
            title="Fix small bug",
            body="Off by one error",
            labels=["bug"],
            reporter="tester",
        )
        session.add(issue)
        session.commit()
        session.refresh(issue)
        issue_id = issue.id
    finally:
        session.close()

    # Mock triage to return in_scope=True
    async def mock_triage(run_id, issue_obj):
        return {
            "category": "bug",
            "difficulty": "easy",
            "confidence": 0.95,
            "in_scope": True,
            "reason": "Clear reproducible unit bug",
            "comment_to_reporter": None,
        }

    monkeypatch.setattr(agents, "run_triage", mock_triage)

    run_id = orchestrator.create_run(issue_id)
    # Start pipeline
    asyncio.run(orchestrator.run_pipeline(run_id))

    run, _ = orchestrator._get_run_and_issue(run_id)
    assert run.triage_result["in_scope"] is True
    assert run.status in ("AWAITING_HUMAN", "STOPPED_NEEDS_HUMAN", "BLOCKED_BY_GATE")
    assert run.agent_states.get("triage") == "passed"


def test_triage_gate_skip_on_out_of_scope(monkeypatch):
    session = SessionLocal()
    try:
        issue = Issue(
            number=702,
            title="Rewrite in another language",
            body="Rewrite everything",
            labels=["feature"],
            reporter="contributor",
        )
        session.add(issue)
        session.commit()
        session.refresh(issue)
        issue_id = issue.id
    finally:
        session.close()

    async def mock_triage(run_id, issue_obj):
        return {
            "category": "feature",
            "difficulty": "hard",
            "confidence": 0.99,
            "in_scope": False,
            "reason": "Architectural rewrite is outside automated maintenance scope.",
            "comment_to_reporter": "Thank you for the suggestion! Architectural overhauls require RFC discussion.",
        }

    monkeypatch.setattr(agents, "run_triage", mock_triage)

    run_id = orchestrator.create_run(issue_id)
    asyncio.run(orchestrator.run_pipeline(run_id))

    run, _ = orchestrator._get_run_and_issue(run_id)
    assert run.status == "OUT_OF_SCOPE"
    assert run.triage_result["in_scope"] is False
    assert "Architectural rewrite" in run.triage_result["reason"]
    assert run.agent_states.get("triage") == "failed"

    # Verify no patches or tests were generated
    session = SessionLocal()
    try:
        patches = session.query(Patch).filter_by(run_id=run_id).count()
        tests = session.query(TestResult).filter_by(run_id=run_id).count()
        assert patches == 0
        assert tests == 0
    finally:
        session.close()
