"""RepoCrew orchestrator.

Runs the pipeline per issue:
    Intake -> Triage -> Coder -> Tester (real sandbox) -> Reviewer
    -> Safety Gate -> Human approval -> Pull request

It passes context between agents, enforces the hard 3-attempt limit, records
every event to the DB and broadcasts it over WebSocket. If the retry limit is
hit, the run ends STOPPED_NEEDS_HUMAN with a summary of what was learned — it
never guesses and NEVER merges anything (there is no merge code anywhere).
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import select

from . import agents, config, demo_scripts, safety_gate, sandbox
from .database import SessionLocal
from .diffutil import changed_paths
from .events import emit
from .models import Issue, Run, Patch, TestResult, PullRequest

TERMINAL_STATUSES = {
    "AWAITING_HUMAN", "OUT_OF_SCOPE", "BLOCKED_BY_GATE", "STOPPED_NEEDS_HUMAN",
    "PR_READY", "PR_CREATED", "REJECTED_BY_HUMAN", "FAILED",
}

AGENTS_ORDER = ["triage", "coder", "tester", "reviewer", "gate"]


def _update_run(run_id: int, **fields) -> None:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        for key, value in fields.items():
            setattr(run, key, value)
        session.commit()
    finally:
        session.close()


def _get_run_and_issue(run_id: int) -> tuple[Run, Issue]:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        issue = session.get(Issue, run.issue_id)
        # detach lightweight copies
        session.expunge_all()
        return run, issue
    finally:
        session.close()


def _set_state(run_id: int, agent_states: dict, agent: str, state: str) -> None:
    agent_states[agent] = state
    _update_run(run_id, current_agent=agent, agent_states=dict(agent_states))


def create_run(issue_id: int) -> int:
    """Create a RUNNING-soon run row for an issue. Returns the run id."""
    session = SessionLocal()
    try:
        run = Run(
            issue_id=issue_id, status="QUEUED", mode=config.RC_MODE,
            max_attempts=config.MAX_ATTEMPTS,
            agent_states={a: "idle" for a in AGENTS_ORDER} | {"human": "idle"},
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id
    finally:
        session.close()


def has_active_run(issue_id: int) -> bool:
    session = SessionLocal()
    try:
        return session.query(Run).filter(
            Run.issue_id == issue_id, Run.status.in_(["QUEUED", "RUNNING"])
        ).count() > 0
    finally:
        session.close()


def _finish(run_id: int, status: str, summary: str | None = None) -> None:
    _update_run(run_id, status=status, summary=summary, finished_at=datetime.now(timezone.utc),
                current_agent="orchestrator")
    emit(run_id, "orchestrator", "status",
         f"Run finished with status {status}." + (f" {summary}" if summary else ""),
         {"status": status})


def build_pr_content(run: Run, issue: Issue, gate: dict, last_test: TestResult | None,
                     last_review: dict | None) -> tuple[str, str]:
    """Generate the PR title + full markdown body (summary, root cause, changes,
    test results, reviewer notes, confidence score)."""
    title = f"Fix #{issue.number}: {issue.title}"
    blurb = demo_scripts.PR_BLURBS.get(issue.number, {
        "summary": f"Automated fix for issue #{issue.number}: {issue.title}.",
        "root_cause": "See the triage reasoning and reviewer notes below.",
        "changes": [f"`{p}`" for p in (gate or {}).get("paths", [])],
    })
    lines = [
        "## Summary",
        f"- {blurb['summary']}",
        f"- Closes issue #{issue.number} ({issue.title}).",
        "",
        "## Root cause",
        blurb["root_cause"],
        "",
        "## Changes",
    ]
    lines += [f"- {c}" for c in blurb["changes"]]
    lines += ["", "## Test results (real pytest in the RepoCrew sandbox)"]
    if last_test is not None:
        lines += [
            f"- Verdict: **{'PASS' if last_test.passed else 'FAIL'}** "
            f"({last_test.passed_count} passed, {last_test.failed} failed; engine: {last_test.engine})",
            f"- {last_test.detail}",
        ]
    lines += ["", "## Reviewer notes"]
    if last_review:
        lines += [f"- Verdict: **{last_review['verdict']}**"]
        lines += [f"- {n}" for n in last_review.get("notes", [])]
    lines += ["", "## Confidence score (safety gate)"]
    if gate:
        lines.append(f"- Score **{gate['score']}** (threshold {gate['threshold']})")
        for check in gate.get("checks", []):
            mark = "x" if check["passed"] else " "
            lines.append(f"- [{mark}] {check['name']} — {check['detail']}")
    lines += [
        "",
        "_RepoCrew proposed these changes but does not merge them._",
        "",
        "Opened by RepoCrew. Human review required before merge.",
    ]
    return title, "\n".join(lines)


async def run_pipeline(run_id: int) -> None:
    """Full pipeline for one run. Intended to be scheduled as an asyncio task."""
    run, issue = _get_run_and_issue(run_id)
    states: dict = run.agent_states or {a: "idle" for a in AGENTS_ORDER} | {"human": "idle"}
    _update_run(run_id, status="RUNNING", started_at=datetime.now(timezone.utc))
    emit(run_id, "orchestrator", "status",
         f"Run #{run_id} started for issue #{issue.number} (mode={config.RC_MODE}, "
         f"model={config.RC_MODEL if config.RC_MODE == 'live' else 'scripted'}, "
         f"max_attempts={config.MAX_ATTEMPTS}).",
         {"status": "RUNNING"})
    learned: list[str] = []

    try:
        # --- Intake ---------------------------------------------------------
        emit(run_id, "orchestrator", "message",
             f"Intake: issue #{issue.number} \"{issue.title}\" queued by @{issue.reporter}. "
             "Handing it to the Triage agent.")
        # --- Triage ---------------------------------------------------------
        _set_state(run_id, states, "triage", "working")
        triage = await agents.run_triage(run_id, issue)
        _update_run(run_id, triage_result=triage)
        if not triage.get("in_scope"):
            _set_state(run_id, states, "triage", "failed")
            emit(run_id, "orchestrator", "message",
                 "Triage marked this issue OUT OF SCOPE — no code will be written. "
                 "The polite handback comment above is posted to the issue.")
            _finish(run_id, "OUT_OF_SCOPE", triage.get("reason"))
            return
        _set_state(run_id, states, "triage", "passed")
        emit(run_id, "orchestrator", "message",
             "Triage marked this issue in scope. Passing context to the Coder agent.")
        await agents.beat()

        # --- Reproduce first (before editing source files) -----------------
        intel = demo_scripts.CODER_INTEL.get(issue.number, {})
        target_files = intel.get("files", [])
        edits_source = any(f.endswith(".py") and not f.startswith("tests/") for f in target_files) if target_files else True

        reproduced = False
        repro_test_name: str | None = None
        new_test_diff: str | None = None
        new_test_path: str | None = None
        repro_feedback: str | None = None
        repro_eval: sandbox.TestEvaluation | None = None

        if edits_source:
            _set_state(run_id, states, "coder", "working")
            for repro_attempt in range(1, 3):  # 1 initial + 1 retry
                repro_plan = await agents.run_coder_reproduce(
                    run_id, issue, repro_attempt, repro_feedback
                )
                _set_state(run_id, states, "tester", "working")
                repro_eval = await asyncio.to_thread(
                    sandbox.evaluate_reproduction, issue.number, repro_plan
                )
                if repro_eval.reproduced:
                    reproduced = True
                    repro_test_name = repro_eval.test_name
                    if isinstance(repro_plan, dict) and (repro_plan.get("is_new_file") or repro_plan.get("strategy") == "new"):
                        new_test_path = repro_plan.get("file_path") or f"tests/test_repocrew_issue_{issue.number}.py"
                        new_test_diff = repro_plan.get("diff")
                    emit(
                        run_id, "tester", "message",
                        f"Bug reproduced: {repro_test_name}",
                        {
                            "summary": f"Bug reproduced: {repro_test_name}",
                            "reproduced": True,
                            "test_name": repro_test_name,
                        },
                    )
                    _set_state(run_id, states, "tester", "passed")
                    _set_state(run_id, states, "coder", "idle")
                    break
                else:
                    _set_state(run_id, states, "tester", "failed")
                    repro_feedback = (
                        f"Reproduction attempt {repro_attempt} did not fail on unpatched repo: {repro_eval.detail}"
                    )
                    emit(
                        run_id, "tester", "message",
                        f"Reproduction attempt {repro_attempt} failed: {repro_eval.detail}",
                    )
                    await agents.beat()

            if not reproduced:
                comment = (
                    f"RepoCrew could not reproduce the bug on the unpatched repository. "
                    f"Reason: could not reproduce."
                )
                emit(
                    run_id, "orchestrator", "message",
                    f"Run stopped: could not reproduce. Commenting on issue #{issue.number}: \"{comment}\"",
                )
                if config.github_configured():
                    try:
                        from . import github_client
                        github_client.comment_on_issue(issue.number, comment)
                    except Exception as exc:
                        emit(run_id, "orchestrator", "log", f"Failed to post GitHub comment: {exc}")
                _set_state(run_id, states, "coder", "failed")
                _finish(run_id, "STOPPED_NEEDS_HUMAN", "could not reproduce")
                return

        # --- Coder <-> Tester/Reviewer retry loop (hard limit) --------------
        prev_diff: str | None = None
        feedback: str | None = None
        last_test: TestResult | None = None
        review: dict | None = None

        for attempt in range(1, config.MAX_ATTEMPTS + 1):
            _update_run(run_id, attempts=attempt)
            emit(run_id, "orchestrator", "step",
                 f"Attempt {attempt}/{config.MAX_ATTEMPTS}: Coder -> Tester -> Reviewer",
                 {"attempt": attempt})

            # Coder
            _set_state(run_id, states, "coder", "working")
            try:
                diff = await agents.run_coder(run_id, issue, attempt, prev_diff, feedback)
            except KeyError:
                emit(run_id, "orchestrator", "message",
                     "The Coder has no further scripted/live output for this issue.")
                break

            # If a new repro test was written, include it in the candidate patch / PR
            if new_test_diff and new_test_path and new_test_path not in changed_paths(diff):
                if not diff.endswith("\n"):
                    diff = diff + "\n"
                diff = diff + new_test_diff

            # Enforce that Coder cannot edit existing test files
            try:
                agents.validate_coder_paths(changed_paths(diff))
            except ValueError as ve:
                _set_state(run_id, states, "coder", "failed")
                emit(run_id, "coder", "message", f"Rule violation: {ve}")
                feedback = str(ve)
                continue

            session = SessionLocal()
            try:
                session.add(Patch(run_id=run_id, attempt=attempt, diff=diff))
                session.commit()
            finally:
                session.close()
            _set_state(run_id, states, "coder", "passed")
            emit(run_id, "orchestrator", "message",
                 "Coder handed a candidate patch to the Tester (real sandbox run).")

            # Tester (always real)
            _set_state(run_id, states, "tester", "working")
            result = await agents.run_tester(run_id, issue, diff, attempt, repro_test=repro_test_name)
            session = SessionLocal()
            try:
                tr = TestResult(
                    run_id=run_id, attempt=attempt, passed=result.tests_passed,
                    total=result.total, failed=result.failed,
                    passed_count=result.passed_count, raw_output=result.raw_output,
                    detail=result.detail, engine=result.engine,
                    reproduced=reproduced,
                    test_name=repro_test_name,
                )
                session.add(tr)
                session.commit()
                session.refresh(tr)
                session.expunge(tr)
                last_test = tr
            finally:
                session.close()

            if not result.tests_passed:
                _set_state(run_id, states, "tester", "failed")
                feedback = (f"Tester run FAILED (attempt {attempt}): {result.detail}\n"
                            f"Pytest tail:\n" +
                            "\n".join(result.raw_output.splitlines()[-20:]))
                learned.append(f"Attempt {attempt}: tests failed — {result.detail}")
                prev_diff = diff
                emit(run_id, "orchestrator", "message",
                     f"Tester FAIL on attempt {attempt}. Sending the real failure log back "
                     f"to the Coder for a revision.")
                _set_state(run_id, states, "tester", "idle")
                _set_state(run_id, states, "coder", "idle")
                continue
            _set_state(run_id, states, "tester", "passed")
            emit(run_id, "orchestrator", "message",
                 "Tests pass in the sandbox. Handing the diff and test results to the "
                 "independent Reviewer.")

            # Reviewer (separate instance from Coder)
            _set_state(run_id, states, "reviewer", "working")
            review = await agents.run_reviewer(run_id, issue, diff, result, attempt)
            verdict = review.get("verdict", "CHANGES_REQUESTED")
            _record_review(run_id, attempt, review)

            if verdict == "APPROVE":
                _set_state(run_id, states, "reviewer", "passed")
            elif verdict == "REJECT":
                _set_state(run_id, states, "reviewer", "failed")
                learned.append(f"Attempt {attempt}: Reviewer REJECT — {'; '.join(review.get('notes', []))}")
                _finish(run_id, "STOPPED_NEEDS_HUMAN",
                        "Reviewer rejected the patch. Learned: " + " | ".join(learned))
                return
            else:  # CHANGES_REQUESTED
                _set_state(run_id, states, "reviewer", "failed")
                feedback = (f"Reviewer requested changes (attempt {attempt}): "
                            + "\n".join(f"- {n}" for n in review.get("notes", [])))
                learned.append(f"Attempt {attempt}: Reviewer asked for changes — "
                               + "; ".join(review.get("notes", [])))
                prev_diff = diff
                emit(run_id, "orchestrator", "message",
                     "Reviewer returned CHANGES_REQUESTED. Routing feedback to the Coder "
                     "for another attempt.")
                _set_state(run_id, states, "reviewer", "idle")
                _set_state(run_id, states, "coder", "idle")
                continue

            # --- Safety Gate ------------------------------------------------
            _set_state(run_id, states, "gate", "working")
            emit(run_id, "gate", "step", "Scoring the patch and checking blocked paths")
            await agents.beat()
            gate = safety_gate.evaluate(diff, result.tests_passed, verdict)
            _update_run(run_id, gate_result=gate)
            for check in gate["checks"]:
                emit(run_id, "gate", "log",
                     f"check: {check['name']} -> {'PASS' if check['passed'] else 'FAIL'} "
                     f"({check['detail']})")
                await agents.beat()
            emit(run_id, "gate", "message",
                 f"Confidence score {gate['score']} (threshold {gate['threshold']}); "
                 f"blocked paths: {len(gate['blocked_reasons'])}.",
                 {"gate": gate})
            if gate["allowed"]:
                _set_state(run_id, states, "gate", "passed")
                states["human"] = "working"
                _update_run(run_id, agent_states=dict(states))
                title, body = build_pr_content(run, issue, gate, last_test, review)
                _update_run(run_id, pr_title=title, pr_body=body)
                emit(run_id, "orchestrator", "message",
                     "Gate passed. The patch is now AWAITING_HUMAN approval — RepoCrew "
                     "never merges; a person makes the final call.")
                _finish(run_id, "AWAITING_HUMAN",
                        f"Ready for you: score {gate['score']}, attempt {attempt}.")
                return
            _set_state(run_id, states, "gate", "failed")
            reason = "; ".join(gate["blocked_reasons"]) or f"score {gate['score']} below threshold"
            emit(run_id, "orchestrator", "message",
                 f"Safety Gate BLOCKED the pull request: {reason}. "
                 "RepoCrew will not open this PR — a human must decide how to proceed "
                 "(e.g. split the CI change into a separate, manually-reviewed PR).")
            _finish(run_id, "BLOCKED_BY_GATE", f"Blocked: {reason}")
            return

        # --- Retry limit exhausted ------------------------------------------
        _set_state(run_id, states, "coder", "failed")
        summary = ("Stopped after the hard limit of "
                   f"{config.MAX_ATTEMPTS} attempts. What was learned: "
                   + (" | ".join(learned) if learned else "no attempts completed."))
        _finish(run_id, "STOPPED_NEEDS_HUMAN", summary)

    except Exception as exc:  # noqa: BLE001 - never crash the loop silently
        emit(run_id, "orchestrator", "log", f"Unhandled error: {exc}")
        for agent, st in list(states.items()):
            if st == "working":
                states[agent] = "failed"
        _update_run(run_id, error=traceback.format_exc(), agent_states=dict(states))
        _finish(run_id, "FAILED", str(exc))


def _record_review(run_id: int, attempt: int, review: dict) -> None:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        reviews = list(run.reviews or [])
        reviews.append({"attempt": attempt, **review})
        run.reviews = reviews
        session.commit()
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Human approval
# ---------------------------------------------------------------------------

def approve_run(run_id: int, comment: str | None) -> tuple[Run, PullRequest]:
    """Human approved: open a real PR via GitHub if configured, else a preview."""
    from . import github_client

    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        issue = session.get(Issue, run.issue_id)
        if run.status != "AWAITING_HUMAN":
            raise ValueError(f"run is not awaiting human approval (status={run.status})")
        last_patch = session.execute(
            select(Patch).where(Patch.run_id == run_id).order_by(Patch.attempt.desc())
        ).scalars().first()
        title = run.pr_title or f"Fix #{issue.number}: {issue.title}"
        body = run.pr_body or ""
        if not body.endswith("Opened by RepoCrew. Human review required before merge."):
            body = body.rstrip() + "\n\nOpened by RepoCrew. Human review required before merge."
        if comment:
            body = body.rstrip() + f"\n\nHuman approval note: {comment}"

        if config.github_configured():
            pr_info = github_client.open_pull_request(issue.number, title, body, last_patch.diff)
            pr = PullRequest(run_id=run_id, issue_id=issue.id, kind="github",
                             url=pr_info["url"], branch=pr_info["branch"],
                             title=title, body=body)
            run.status = "PR_CREATED"
            emit(run_id, "orchestrator", "status",
                 f"Human approved. Pull request opened on GitHub: {pr_info['url']}",
                 {"status": "PR_CREATED", "url": pr_info["url"]})
        else:
            pr = PullRequest(run_id=run_id, issue_id=issue.id, kind="preview",
                             url=None, branch=f"repocrew/issue-{issue.number}",
                             title=title, body=body)
            run.status = "PR_READY"
            emit(run_id, "orchestrator", "status",
                 "Human approved. PR preview generated (no GitHub token configured).",
                 {"status": "PR_READY"})
        run.human_comment = comment
        run.finished_at = datetime.now(timezone.utc)
        states = dict(run.agent_states or {})
        states["human"] = "passed"
        run.agent_states = states
        session.add(pr)
        session.commit()
        session.refresh(run)
        session.refresh(pr)
        session.expunge_all()
        return run, pr
    finally:
        session.close()


def reject_run(run_id: int, comment: str | None) -> None:
    session = SessionLocal()
    try:
        run = session.get(Run, run_id)
        if run.status != "AWAITING_HUMAN":
            raise ValueError(f"run is not awaiting human approval (status={run.status})")
        run.status = "REJECTED_BY_HUMAN"
        run.human_comment = comment
        run.finished_at = datetime.now(timezone.utc)
        states = dict(run.agent_states or {})
        states["human"] = "failed"
        run.agent_states = states
        session.commit()
    finally:
        session.close()
    emit(run_id, "orchestrator", "status",
         "Human rejected the patch." + (f" Reason: {comment}" if comment else ""),
         {"status": "REJECTED_BY_HUMAN"})


# ---------------------------------------------------------------------------
# Run-all
# ---------------------------------------------------------------------------

async def run_all_sequential(run_ids: list[int]) -> None:
    for rid in run_ids:
        await run_pipeline(rid)


def start_run(run_id: int) -> asyncio.Task:
    return asyncio.create_task(run_pipeline(run_id))


def start_run_all(run_ids: list[int]) -> asyncio.Task:
    return asyncio.create_task(run_all_sequential(run_ids))
