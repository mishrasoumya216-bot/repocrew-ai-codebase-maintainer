"""RepoCrew end-to-end demo-mode tests: one full run per seeded issue.

Expected final statuses:
  issue1 AWAITING_HUMAN (clean pass on attempt 1)
  issue2 AWAITING_HUMAN after 2 attempts (tester failure -> retry)
  issue3 AWAITING_HUMAN after reviewer feedback (CHANGES_REQUESTED -> attempt 2)
  issue4 OUT_OF_SCOPE (triage handback, no code written)
  issue5 BLOCKED_BY_GATE (CI-config change blocked by the safety gate)
"""
import asyncio

import pytest

from backend import orchestrator
from backend.database import SessionLocal
from backend.models import Issue, Patch, Run
from backend.models import TestResult as TestResultRow


def _run_issue(number: int) -> Run:
    session = SessionLocal()
    try:
        issue = session.query(Issue).filter_by(number=number).one()
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


def _counts(run_id: int):
    session = SessionLocal()
    try:
        patches = session.query(Patch).filter_by(run_id=run_id).count()
        tests = session.query(TestResultRow).filter_by(run_id=run_id).count()
        return patches, tests
    finally:
        session.close()


def test_issue1_clean_pass():
    run = _run_issue(1)
    assert run.status == "AWAITING_HUMAN"
    assert run.attempts == 1
    assert run.gate_result["allowed"]
    assert run.pr_body.endswith("Opened by RepoCrew. Human review required before merge.")


def test_issue2_retry_loop():
    run = _run_issue(2)
    assert run.status == "AWAITING_HUMAN"
    assert run.attempts == 2, "expected the tester to reject attempt 1 and pass attempt 2"
    patches, tests = _counts(run.id)
    assert patches == 2 and tests == 2


def test_issue3_reviewer_feedback_loop():
    run = _run_issue(3)
    assert run.status == "AWAITING_HUMAN"
    assert run.attempts == 2
    verdicts = [r["verdict"] for r in run.reviews]
    assert verdicts == ["CHANGES_REQUESTED", "APPROVE"]
    assert run.gate_result["score"] == 1.0  # fix + regression test


def test_issue4_out_of_scope():
    run = _run_issue(4)
    assert run.status == "OUT_OF_SCOPE"
    assert run.triage_result["in_scope"] is False
    assert run.triage_result["comment_to_reporter"]  # polite handback posted
    patches, tests = _counts(run.id)
    assert patches == 0 and tests == 0  # no code written, no tests run


def test_issue5_blocked_by_gate():
    run = _run_issue(5)
    assert run.status == "BLOCKED_BY_GATE"
    assert run.gate_result["allowed"] is False
    assert run.gate_result["blocked_reasons"]
    assert any(".github" in r for r in run.gate_result["blocked_reasons"])
    # reviewer still approved and tests passed — the gate alone blocked it
    assert run.reviews[-1]["verdict"] == "APPROVE"


def test_human_approve_creates_preview_pr():
    run = _run_issue(1)
    assert run.status == "AWAITING_HUMAN"
    approved, pr = orchestrator.approve_run(run.id, comment="looks good")
    assert approved.status in ("PR_READY", "PR_CREATED")
    assert pr.kind == "preview"  # no GITHUB_TOKEN configured in tests
    assert pr.body.endswith("Human approval note: looks good")
    assert "Opened by RepoCrew. Human review required before merge." in pr.body
    with pytest.raises(ValueError):
        orchestrator.approve_run(run.id, None)  # cannot approve twice


def test_human_reject_records_comment():
    run = _run_issue(1)
    orchestrator.reject_run(run.id, "not confident in the guard clause")
    session = SessionLocal()
    try:
        run = session.get(Run, run.id)
        assert run.status == "REJECTED_BY_HUMAN"
        assert run.human_comment == "not confident in the guard clause"
    finally:
        session.close()
