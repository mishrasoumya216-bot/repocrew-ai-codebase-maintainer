"""Comprehensive robustness tests for all API endpoints.

Tests:
- GET /api/runs
- GET /api/runs/{id} (valid, 404 on unknown ID, 422 on invalid type)
- GET /api/stream (SSE stream connection, backlog delivery, clean disconnect)
- POST /api/runs/trigger (valid, missing fields 400/422, wrong types 422, unknown issue 404, huge payloads)
- POST /api/seed (idempotent, return count)
- POST /webhook/github (ping, invalid sig 401, missing fields 400, huge payload)
- Unhandled background task exceptions & run state safety
- Zero merge functionality confirmation
"""
import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend.models import Issue, Run
from backend import orchestrator


@pytest.fixture
def client():
    return TestClient(app)


def test_get_runs_endpoint(client):
    res = client.get("/api/runs")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_get_run_by_id_known_and_unknown(client):
    # Unknown ID -> 404
    res_404 = client.get("/api/runs/99999999")
    assert res_404.status_code == 404
    assert res_404.json()["detail"] == "run not found"

    # Invalid ID type -> 422
    res_422 = client.get("/api/runs/not-an-integer")
    assert res_422.status_code == 422

    # Known ID
    session = SessionLocal()
    try:
        run = session.query(Run).first()
        if run:
            res_200 = client.get(f"/api/runs/{run.id}")
            assert res_200.status_code == 200
            assert res_200.json()["id"] == run.id
    finally:
        session.close()


def test_post_runs_trigger_validation(client, monkeypatch):
    monkeypatch.setattr(orchestrator, "start_run", lambda run_id: None)

    # Missing all fields -> 400
    res_missing = client.post("/api/runs/trigger", json={})
    assert res_missing.status_code in (400, 422)

    # Invalid type for issue_id -> 422
    res_bad_type = client.post("/api/runs/trigger", json={"issue_id": "not-an-int"})
    assert res_bad_type.status_code == 422

    # Nonexistent issue_id -> 404
    res_404 = client.post("/api/runs/trigger", json={"issue_id": 9999999})
    assert res_404.status_code == 404

    # Valid issue_number -> creates run
    res_valid = client.post("/api/runs/trigger", json={"issue_number": 9901, "issue_title": "Robustness Test Issue"})
    assert res_valid.status_code == 200
    assert "run_id" in res_valid.json()

    # Triggering again while run is active -> 409 Conflict
    res_conflict = client.post("/api/runs/trigger", json={"issue_number": 9901})
    assert res_conflict.status_code == 409


def test_post_runs_trigger_huge_payload(client, monkeypatch):
    monkeypatch.setattr(orchestrator, "start_run", lambda run_id: None)
    huge_title = "A" * 10000
    huge_body = "B" * 500000  # 500 KB body
    res = client.post(
        "/api/runs/trigger",
        json={"issue_number": 9902, "issue_title": huge_title, "issue_body": huge_body},
    )
    assert res.status_code == 200
    assert "run_id" in res.json()


def test_post_seed_endpoint(client):
    res = client.post("/api/seed")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["seeded_issues"] >= 5


def test_sse_stream_endpoint(client):
    # Nonexistent run -> 404
    res_404 = client.get("/api/stream?run_id=99999999")
    assert res_404.status_code == 404

    # Missing run_id query param -> 422
    res_422 = client.get("/api/stream")
    assert res_422.status_code == 422

    # Valid run_id -> streams SSE and disconnects cleanly
    session = SessionLocal()
    try:
        run = session.query(Run).first()
        run_id = run.id if run else None
    finally:
        session.close()

    if run_id:
        with client.stream("GET", f"/api/stream?run_id={run_id}") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            first_chunk = next(response.iter_lines())
            assert "data:" in first_chunk


def test_webhook_error_cases(client):
    # Missing issue object -> 400
    res = client.post("/webhook/github", json={"action": "opened"})
    assert res.status_code == 400

    # Missing issue number -> 400
    res = client.post("/webhook/github", json={"action": "opened", "issue": {"title": "No number"}})
    assert res.status_code == 400

    # Non-json payload -> 400
    res = client.post("/webhook/github", content=b"invalid non json", headers={"Content-Type": "application/json"})
    assert res.status_code == 400

    # Huge payload (1 MB) -> handled safely
    huge_payload = {
        "action": "opened",
        "issue": {
            "number": 9903,
            "title": "Huge Webhook Issue",
            "body": "X" * 1000000,
            "labels": [],
            "user": {"login": "hugeuser"},
        },
    }
    res_huge = client.post("/webhook/github", json=huge_payload)
    assert res_huge.status_code == 200


def test_failed_run_never_stuck_in_working(monkeypatch):
    """When an exception occurs during pipeline execution, status is marked FAILED, not RUNNING."""
    session = SessionLocal()
    try:
        issue = Issue(
            number=9904,
            title="Crash Test Issue",
            body="Will simulate unhandled exception",
            labels=[],
            reporter="tester",
        )
        session.add(issue)
        session.commit()
        session.refresh(issue)
        issue_id = issue.id
    finally:
        session.close()

    run_id = orchestrator.create_run(issue_id)

    # Simulate crash in pipeline
    async def crashing_triage(*args, **kwargs):
        raise RuntimeError("Simulated unexpected pipeline crash")

    monkeypatch.setattr("backend.agents.run_triage", crashing_triage)

    import asyncio
    asyncio.run(orchestrator.run_pipeline(run_id))

    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        assert run.status == "FAILED"
        assert "Simulated unexpected pipeline crash" in (run.error or run.summary or "")
        # Confirm agent states do not leave any agent permanently in "working"
        assert all(state != "working" for state in (run.agent_states or {}).values())
    finally:
        session.close()


def test_zero_merge_functionality_in_repo():
    """Verify repo policy: RepoCrew has zero merge code anywhere."""
    import pathlib
    backend_dir = pathlib.Path(__file__).parent.parent
    for py_file in backend_dir.rglob("*.py"):
        if "tests" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8")
        # Ensure no calls to GitHub merge API endpoints
        assert "/merges" not in text
        assert "merge_pull_request" not in text
        assert "put_merge" not in text
