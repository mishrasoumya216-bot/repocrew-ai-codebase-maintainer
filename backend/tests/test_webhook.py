"""Tests for GitHub webhook integration and idempotency."""
import hashlib
import hmac
import json
import pytest
from fastapi.testclient import TestClient

from backend import config, orchestrator
from backend.database import SessionLocal
from backend.main import app
from backend.models import Issue, Run


@pytest.fixture
def client():
    return TestClient(app)


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_webhook_ping(client):
    res = client.post("/webhook/github", headers={"X-GitHub-Event": "ping"}, json={})
    assert res.status_code == 200
    assert res.json()["message"] == "pong"


def test_webhook_signature_missing_when_secret_configured(client, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_WEBHOOK_SECRET", "super-secret-token")
    payload = json.dumps({"action": "opened", "issue": {"number": 999, "title": "Test"}}).encode("utf-8")
    res = client.post(
        "/webhook/github",
        content=payload,
        headers={"Content-Type": "application/json", "X-GitHub-Event": "issues"},
    )
    assert res.status_code == 401
    assert "missing" in res.json()["detail"].lower()


def test_webhook_signature_invalid(client, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_WEBHOOK_SECRET", "super-secret-token")
    payload = json.dumps({"action": "opened", "issue": {"number": 999, "title": "Test"}}).encode("utf-8")
    res = client.post(
        "/webhook/github",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbad",
        },
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_webhook_signature_valid(client, monkeypatch):
    secret = "my-test-webhook-secret"
    monkeypatch.setattr(config, "GITHUB_WEBHOOK_SECRET", secret)
    payload_dict = {
        "action": "opened",
        "issue": {
            "number": 888,
            "title": "Webhook Issue Valid Sig",
            "body": "Bug report from webhook",
            "labels": [{"name": "bug"}],
            "user": {"login": "octocat"},
        },
    }
    raw = json.dumps(payload_dict).encode("utf-8")
    sig = _signature(secret, raw)

    res = client.post(
        "/webhook/github",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-Hub-Signature-256": sig,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("triggered", "already_active")
    assert data["issue_number"] == 888


def test_duplicate_issue_is_idempotent(client, monkeypatch):
    monkeypatch.setattr(config, "GITHUB_WEBHOOK_SECRET", "")
    monkeypatch.setattr(orchestrator, "start_run", lambda run_id: None)
    payload = {
        "action": "opened",
        "issue": {
            "number": 889,
            "title": "Idempotent Issue",
            "body": "Testing idempotency",
            "labels": [],
            "user": {"login": "testuser"},
        },
    }

    # First delivery
    res1 = client.post("/webhook/github", json=payload)
    assert res1.status_code == 200
    assert res1.json()["status"] == "triggered"

    # Second delivery with identical issue number
    res2 = client.post("/webhook/github", json=payload)
    assert res2.status_code == 200
    # Should recognize active run without duplicate creation
    assert res2.json()["status"] == "already_active"

    # Verify database only contains one issue with number 889
    session = SessionLocal()
    try:
        issues = session.query(Issue).filter_by(number=889).all()
        assert len(issues) == 1
        runs = session.query(Run).filter_by(issue_id=issues[0].id).all()
        assert len(runs) == 1
    finally:
        session.close()
