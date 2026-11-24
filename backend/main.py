"""RepoCrew FastAPI application.

Endpoints (all JSON unless noted):
  GET  /api/health
  GET  /api/issues
  GET  /api/issues/{id}
  POST /api/issues/{id}/run
  POST /api/run-all
  GET  /api/runs/{id}
  POST /api/runs/{id}/approve
  POST /api/runs/{id}/reject
  GET  /api/metrics
  WS   /ws/runs/{id}

Also serves the built frontend (frontend/dist) at "/" when present, so a
single `uvicorn backend.main:app` gives the full product.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from . import config, orchestrator, sandbox
from .database import SessionLocal, init_db
from .events import subscribe, unsubscribe
from .models import Event, Issue, Patch, PullRequest, Run, TestResult
from .seed import seed_issues

FRONTEND_DIST = config.ROOT_DIR / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    seed_issues()
    await asyncio.to_thread(sandbox.probe_docker)
    yield


app = FastAPI(title="RepoCrew", version="0.1.0", lifespan=lifespan)
_cors_origins = config.CORS_ORIGINS if config.CORS_ORIGINS else (
    ["*"] if config.RC_MODE == "demo" else ["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _issue_dict(session, issue: Issue) -> dict:
    latest = session.execute(
        select(Run).where(Run.issue_id == issue.id).order_by(Run.id.desc())
    ).scalars().first()
    return {
        "id": issue.id,
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "labels": issue.labels or [],
        "reporter": issue.reporter,
        "created_at": issue.created_at.isoformat(),
        "latest_run_id": latest.id if latest else None,
        "latest_run_status": latest.status if latest else None,
    }


def _event_dict(e: Event) -> dict:
    return {"id": e.id, "run_id": e.run_id, "ts": e.ts, "agent": e.agent,
            "type": e.type, "text": e.text, "data": e.data}


def _run_dict(session, run: Run, include_events: bool = True) -> dict:
    issue = session.get(Issue, run.issue_id)
    patches = session.execute(
        select(Patch).where(Patch.run_id == run.id).order_by(Patch.attempt)
    ).scalars().all()
    tests = session.execute(
        select(TestResult).where(TestResult.run_id == run.id).order_by(TestResult.attempt)
    ).scalars().all()
    pr = session.execute(
        select(PullRequest).where(PullRequest.run_id == run.id)
        .order_by(PullRequest.id.desc())
    ).scalars().first()
    events = []
    if include_events:
        events = [_event_dict(e) for e in session.execute(
            select(Event).where(Event.run_id == run.id).order_by(Event.id)
        ).scalars().all()]
    return {
        "id": run.id,
        "issue_id": run.issue_id,
        "issue_number": issue.number if issue else None,
        "issue_title": issue.title if issue else None,
        "status": run.status,
        "mode": run.mode,
        "attempts": run.attempts,
        "max_attempts": run.max_attempts,
        "current_agent": run.current_agent,
        "agent_states": run.agent_states or {},
        "triage_result": run.triage_result,
        "reviews": run.reviews or [],
        "gate_result": run.gate_result,
        "pr_title": run.pr_title,
        "pr_body": run.pr_body,
        "human_comment": run.human_comment,
        "summary": run.summary,
        "error": run.error,
        "created_at": run.created_at.isoformat(),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "patches": [{"id": p.id, "attempt": p.attempt, "diff": p.diff,
                     "created_at": p.created_at.isoformat()} for p in patches],
        "test_results": [{
            "id": t.id, "attempt": t.attempt, "passed": t.passed, "total": t.total,
            "failed": t.failed, "passed_count": t.passed_count,
            "raw_output": t.raw_output, "detail": t.detail, "engine": t.engine,
            "created_at": t.created_at.isoformat(),
            "reproduced": getattr(t, "reproduced", False),
            "test_name": getattr(t, "test_name", None),
        } for t in tests],
        "pull_request": ({
            "id": pr.id, "kind": pr.kind, "url": pr.url, "branch": pr.branch,
            "title": pr.title, "body": pr.body, "created_at": pr.created_at.isoformat(),
        } if pr else None),
        "events": events,
    }


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "RepoCrew",
        "mode": config.RC_MODE,
        "model": config.RC_MODEL,
        "sandbox": sandbox.sandbox_status(),
        "github_configured": config.github_configured(),
    }


@app.get("/api/issues")
def list_issues() -> list[dict]:
    session = SessionLocal()
    try:
        issues = session.execute(select(Issue).order_by(Issue.number)).scalars().all()
        return [_issue_dict(session, i) for i in issues]
    finally:
        session.close()


@app.get("/api/issues/{issue_id}")
def get_issue(issue_id: int) -> dict:
    session = SessionLocal()
    try:
        issue = session.get(Issue, issue_id)
        if not issue:
            raise HTTPException(404, "issue not found")
        data = _issue_dict(session, issue)
        runs = session.execute(
            select(Run).where(Run.issue_id == issue.id).order_by(Run.id.desc())
        ).scalars().all()
        data["runs"] = [{"id": r.id, "status": r.status, "attempts": r.attempts,
                         "created_at": r.created_at.isoformat()} for r in runs]
        return data
    finally:
        session.close()


@app.post("/api/issues/{issue_id}/run")
async def run_issue(issue_id: int) -> dict:
    session = SessionLocal()
    try:
        if not session.get(Issue, issue_id):
            raise HTTPException(404, "issue not found")
    finally:
        session.close()
    if orchestrator.has_active_run(issue_id):
        raise HTTPException(409, "an active run already exists for this issue")
    run_id = orchestrator.create_run(issue_id)
    orchestrator.start_run(run_id)
    return {"run_id": run_id}


@app.post("/api/run-all")
async def run_all() -> dict:
    """Run all in-scope-candidate issues sequentially (triage decides scope)."""
    session = SessionLocal()
    try:
        issues = session.execute(select(Issue).order_by(Issue.number)).scalars().all()
        issue_ids = [i.id for i in issues]
    finally:
        session.close()
    run_ids = []
    for iid in issue_ids:
        if orchestrator.has_active_run(iid):
            continue
        run_ids.append(orchestrator.create_run(iid))
    if run_ids:
        orchestrator.start_run_all(run_ids)
    return {"run_ids": run_ids}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    session = SessionLocal()
    try:
        runs = session.execute(select(Run).order_by(Run.id.desc())).scalars().all()
        return [_run_dict(session, r, include_events=False) for r in runs]
    finally:
        session.close()


class TriggerRequest(BaseModel):
    issue_id: int | None = None
    issue_number: int | None = None
    repo: str | None = None
    issue_title: str | None = None
    issue_body: str | None = None


@app.post("/api/runs/trigger")
async def trigger_run(req: TriggerRequest) -> dict:
    session = SessionLocal()
    try:
        issue = None
        if req.issue_id is not None:
            issue = session.get(Issue, req.issue_id)
            if not issue:
                raise HTTPException(404, "issue not found")
        elif req.issue_number is not None:
            issue = session.execute(
                select(Issue).where(Issue.number == req.issue_number)
            ).scalars().first()
            if not issue:
                issue = Issue(
                    number=req.issue_number,
                    title=req.issue_title or f"Issue #{req.issue_number}",
                    body=req.issue_body or "",
                    labels=[],
                    reporter="user",
                )
                session.add(issue)
                session.commit()
                session.refresh(issue)
        else:
            raise HTTPException(400, "issue_id or issue_number is required")
        issue_id = issue.id
    finally:
        session.close()

    if orchestrator.has_active_run(issue_id):
        raise HTTPException(409, "an active run already exists for this issue")
    run_id = orchestrator.create_run(issue_id)
    orchestrator.start_run(run_id)
    return {"run_id": run_id}


@app.post("/api/seed")
def seed_db() -> dict:
    seed_issues()
    session = SessionLocal()
    try:
        count = session.query(Issue).count()
        return {"status": "ok", "seeded_issues": count}
    finally:
        session.close()


@app.get("/api/stream")
async def stream_events(run_id: int):
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(404, "run not found")
        backlog = [_event_dict(e) for e in session.execute(
            select(Event).where(Event.run_id == run_id).order_by(Event.id)
        ).scalars().all()]
    finally:
        session.close()

    async def event_generator():
        yield f"data: {json.dumps({'kind': 'backlog', 'events': backlog})}\n\n"
        queue = subscribe(run_id)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps({'kind': 'event', 'event': payload})}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            unsubscribe(run_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/webhook/github")
async def github_webhook(request: Request) -> dict:
    raw_body = await request.body()
    secret = config.GITHUB_WEBHOOK_SECRET
    if secret:
        sig_header = request.headers.get("X-Hub-Signature-256")
        if not sig_header:
            raise HTTPException(401, "missing X-Hub-Signature-256 header")
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            raise HTTPException(401, "invalid webhook signature")

    try:
        payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        raise HTTPException(400, "invalid JSON payload")

    event_type = request.headers.get("X-GitHub-Event", "issues")
    if event_type == "ping":
        return {"status": "ok", "message": "pong"}
    if event_type != "issues":
        return {"status": "ignored", "reason": f"unhandled event type: {event_type}"}

    action = payload.get("action")
    issue_data = payload.get("issue")
    if not issue_data or not isinstance(issue_data, dict):
        raise HTTPException(400, "missing issue object in payload")

    issue_number = issue_data.get("number")
    if not issue_number:
        raise HTTPException(400, "missing issue number")

    if action not in ("opened", "reopened", "labeled"):
        return {"status": "ignored", "reason": f"unhandled issue action: {action}"}

    session = SessionLocal()
    try:
        existing = session.execute(
            select(Issue).where(Issue.number == issue_number)
        ).scalars().first()
        if not existing:
            existing = Issue(
                number=issue_number,
                title=issue_data.get("title", f"Issue #{issue_number}"),
                body=issue_data.get("body", "") or "",
                labels=[lbl.get("name", "") for lbl in issue_data.get("labels", []) if isinstance(lbl, dict)],
                reporter=(issue_data.get("user") or {}).get("login", "github-user"),
            )
            session.add(existing)
            session.commit()
            session.refresh(existing)
        issue_id = existing.id
    finally:
        session.close()

    if orchestrator.has_active_run(issue_id):
        return {"status": "already_active", "issue_id": issue_id, "issue_number": issue_number}

    run_id = orchestrator.create_run(issue_id)
    orchestrator.start_run(run_id)
    return {"status": "triggered", "issue_id": issue_id, "issue_number": issue_number, "run_id": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: int) -> dict:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if not run:
            raise HTTPException(404, "run not found")
        return _run_dict(session, run)
    finally:
        session.close()



class Decision(BaseModel):
    comment: str | None = None


@app.post("/api/runs/{run_id}/approve")
def approve(run_id: int, decision: Decision | None = None) -> dict:
    comment = decision.comment if decision else None
    try:
        run, pr = orchestrator.approve_run(run_id, comment)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"GitHub integration failed: {exc}")
    return {"status": run.status, "pull_request": {
        "url": pr.url, "branch": pr.branch, "kind": pr.kind, "title": pr.title, "body": pr.body,
    }}


@app.post("/api/runs/{run_id}/reject")
def reject(run_id: int, decision: Decision | None = None) -> dict:
    comment = decision.comment if decision else None
    try:
        orchestrator.reject_run(run_id, comment)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"status": "REJECTED_BY_HUMAN"}


@app.get("/api/metrics")
def metrics() -> dict:
    """All metrics computed from the database — no fake numbers."""
    session = SessionLocal()
    try:
        runs = session.query(Run).all()
        terminal = [r for r in runs if r.status in orchestrator.TERMINAL_STATUSES]
        issues_processed = len({r.issue_id for r in terminal})
        approved = sum(1 for r in terminal
                       if r.status in ("AWAITING_HUMAN", "PR_READY", "PR_CREATED"))
        tests = session.query(TestResult).all()
        pass_rate = (sum(1 for t in tests if t.passed) / len(tests)) if tests else 0.0
        retries = sum(max(0, (r.attempts or 0) - 1) for r in runs if (r.attempts or 0) >= 1)
        durations = [(r.finished_at - r.started_at).total_seconds()
                     for r in terminal if r.started_at and r.finished_at]
        avg_time = sum(durations) / len(durations) if durations else 0.0
        return {
            "issues_processed": issues_processed,
            "patches_approved": approved,
            "test_pass_rate": round(pass_rate, 3),
            "retries_used": retries,
            "avg_run_time_seconds": round(avg_time, 1),
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# WebSocket: live event stream per run
# ---------------------------------------------------------------------------

@app.websocket("/ws/runs/{run_id}")
async def run_events(ws: WebSocket, run_id: int) -> None:
    await ws.accept()
    session = SessionLocal()
    try:
        backlog = [_event_dict(e) for e in session.execute(
            select(Event).where(Event.run_id == run_id).order_by(Event.id)
        ).scalars().all()]
    finally:
        session.close()
    await ws.send_text(json.dumps({"kind": "backlog", "events": backlog}))
    queue = subscribe(run_id)
    try:
        while True:
            payload = await queue.get()
            await ws.send_text(json.dumps({"kind": "event", "event": payload}))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - client went away mid-send etc.
        pass
    finally:
        unsubscribe(run_id, queue)


# ---------------------------------------------------------------------------
# Serve the built frontend (single-server mode)
# ---------------------------------------------------------------------------

class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        from starlette.exceptions import HTTPException as StarletteHTTPException
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


if FRONTEND_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
