"""RepoCrew agents: Triage, Coder, Tester, Reviewer.

Demo mode runs deterministic scripted trajectories (backend/demo_scripts.py)
with realistic short delays; live mode runs real Claude tool-use loops
(backend/llm.py). Both emit the SAME event types. The Tester is always real:
it applies the patch in the sandbox and genuinely runs pytest.
"""
from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

from . import config, demo_scripts, llm, safety_gate, sandbox
from .diffutil import changed_paths, count_changed_lines
from .events import emit

# Deterministic short delays (0.5-1.5s) so the live timeline is visible.
_DELAY_CYCLE = itertools.cycle([0.8, 1.2, 0.6, 1.5, 0.9, 0.5, 1.1])


def _live() -> bool:
    return config.RC_MODE == "live" and bool(config.ANTHROPIC_API_KEY)


async def beat() -> None:
    if config.RC_DEMO_SPEED == "fast":
        return
    await asyncio.sleep(next(_DELAY_CYCLE))


def _truncate(text: str, limit: int = 1000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n..."


# ---------------------------------------------------------------------------
# Shared, read-only repo tools (restricted to the sample repo)
# ---------------------------------------------------------------------------

def _safe_path(rel: str) -> Path:
    p = (config.SAMPLE_REPO_DIR / rel).resolve()
    if not str(p).startswith(str(config.SAMPLE_REPO_DIR.resolve())) or not p.is_file():
        raise ValueError(f"path not allowed: {rel}")
    return p


def tool_search_code(query: str) -> str:
    hits: list[str] = []
    skip = {"__pycache__", ".git", ".pytest_cache"}
    for p in sorted(config.SAMPLE_REPO_DIR.rglob("*")):
        if not p.is_file() or any(part in skip for part in p.parts):
            continue
        rel = p.relative_to(config.SAMPLE_REPO_DIR)
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if query.lower() in line.lower():
                hits.append(f"{rel}:{i}: {line.strip()}")
        if len(hits) >= 20:
            break
    return "\n".join(hits) if hits else "(no matches)"


def tool_read_file(path: str) -> str:
    return _truncate(_safe_path(path).read_text(encoding="utf-8"), 4000)


# ---------------------------------------------------------------------------
# Triage Agent
# ---------------------------------------------------------------------------

async def run_triage(run_id: int, issue) -> dict:
    if _live():
        return await _live_triage(run_id, issue)
    emit(run_id, "triage", "step", "Reading issue body and repository file tree")
    await beat()
    result = demo_scripts.TRIAGE.get(issue.number, {
        "category": "bug",
        "difficulty": "medium",
        "confidence": 0.5,
        "in_scope": False,
        "reason": f"Issue #{issue.number} is outside demo scope.",
        "comment_to_reporter": "Thank you for the report! This issue will be reviewed by maintainers.",
    })
    scope = "IN SCOPE" if result["in_scope"] else "OUT OF SCOPE"
    emit(run_id, "triage", "message",
         f"Verdict: {scope} (category={result['category']}, difficulty={result['difficulty']}, "
         f"confidence={result['confidence']})",
         {"verdict": result})
    await beat()
    emit(run_id, "triage", "log", result["reason"])
    if result["comment_to_reporter"]:
        await beat()
        emit(run_id, "triage", "message",
             f"Posting handback comment to reporter @{issue.reporter}: "
             f"\"{result['comment_to_reporter']}\"")
    return result


# ---------------------------------------------------------------------------
# Coder Agent
# ---------------------------------------------------------------------------

DEPENDENCY_FILES = {
    "requirements.txt", "requirements-dev.txt", "pyproject.toml",
    "setup.py", "setup.cfg", "Pipfile", "Pipfile.lock", "poetry.lock",
    "package.json", "package-lock.json",
}


def validate_coder_paths(paths: list[str], enforce_ci_block: bool = False) -> None:
    if len(paths) > 3:
        raise ValueError(
            f"Coder guardrail violation: cannot modify more than 3 files (modified {len(paths)})"
        )
    for p in paths:
        norm = p.replace("\\", "/")
        while norm.startswith("./"):
            norm = norm[2:]
        base = norm.rsplit("/", 1)[-1]
        if norm in DEPENDENCY_FILES or base in DEPENDENCY_FILES:
            raise ValueError(f"Coder guardrail violation: cannot edit dependency file '{norm}'")
        if enforce_ci_block:
            ci_reason = safety_gate.blocked_reason(norm)
            if ci_reason:
                raise ValueError(f"Coder guardrail violation: cannot edit CI/CD file '{norm}': {ci_reason}")
        if norm.startswith("tests/") or "/tests/" in norm or norm.startswith("test_"):
            if (config.SAMPLE_REPO_DIR / norm).exists():
                raise ValueError(
                    f"Coder cannot edit existing test file '{norm}'. "
                    "Only a new repro test file (test_repocrew_issue_<number>.py) is allowed."
                )


def validate_coder_diff(diff: str, paths: list[str] | None = None) -> None:
    diff_paths = paths if paths is not None else changed_paths(diff)
    validate_coder_paths(diff_paths)
    lines_changed = count_changed_lines(diff)
    if lines_changed > 40:
        raise ValueError(
            f"Coder guardrail violation: diff exceeds ~40 lines limit ({lines_changed} changed lines)"
        )


def patch_deletes_tests(diff: str) -> bool:
    """Return True if candidate diff deletes test code or assertions."""
    in_test = False
    for line in diff.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            in_test = "test" in line
        elif in_test and line.startswith("-") and not line.startswith("---"):
            if line[1:].strip():
                return True
    return False



async def run_coder_reproduce(run_id: int, issue, attempt: int,
                              feedback: str | None = None) -> dict:
    if _live():
        return await _live_coder_reproduce(run_id, issue, attempt, feedback)
    emit(run_id, "coder", "step",
         f"Attempt {attempt}: reproducing bug before editing source files" if attempt == 1
         else f"Attempt {attempt}: revising reproduction test using feedback")
    await beat()
    if feedback:
        emit(run_id, "coder", "message", f"Reproduction feedback: {feedback}")
        await beat()

    repro = None
    if attempt > 1 and issue.number in demo_scripts.REPRODUCTIONS_RETRY:
        repro = demo_scripts.REPRODUCTIONS_RETRY[issue.number]
    elif issue.number in demo_scripts.REPRODUCTIONS:
        repro = demo_scripts.REPRODUCTIONS[issue.number]
    elif hasattr(issue, "repro_plan"):
        repro = issue.repro_plan
    else:
        repro = {"strategy": "existing", "test_name": f"test_repocrew_issue_{issue.number}"}

    strategy = repro.get("strategy", "existing")
    if strategy == "existing":
        tname = repro.get("test_name", "")
        emit(run_id, "coder", "message",
             f"Identified existing failing test to prove bug: {tname}")
    else:
        file_path = repro.get("file_path", f"tests/test_repocrew_issue_{issue.number}.py")
        tname = repro.get("test_name", f"{file_path}::test_repro")
        emit(run_id, "coder", "message",
             f"Wrote new reproduction test in {file_path}")
        if not repro.get("diff") and repro.get("content"):
            from .diffutil import make_file_diff
            repro["diff"] = make_file_diff(file_path, None, repro["content"])
            repro["is_new_file"] = True
    await beat()
    return repro


async def run_coder(run_id: int, issue, attempt: int,
                    prev_diff: str | None, feedback: str | None) -> str:
    if _live():
        return await _live_coder(run_id, issue, attempt, prev_diff, feedback)
    intel = demo_scripts.CODER_INTEL[issue.number]
    emit(run_id, "coder", "step",
         f"Attempt {attempt}: locating the relevant code" if attempt == 1
         else f"Attempt {attempt}: revising the patch using the feedback")
    await beat()
    if feedback:
        emit(run_id, "coder", "message",
             f"Feedback from attempt {attempt - 1} says: {feedback.splitlines()[0][:160]}")
        await beat()
    emit(run_id, "coder", "tool_call", f"search_code({intel['query']!r})",
         {"tool": "search_code", "input": {"query": intel["query"]}})
    await beat()
    emit(run_id, "coder", "tool_result",
         tool_search_code(intel["query"]).splitlines()[0], {"tool": "search_code"})
    await beat()
    for path in intel["files"]:
        emit(run_id, "coder", "tool_call", f"read_file({path!r})",
             {"tool": "read_file", "input": {"path": path}})
        await beat()
        emit(run_id, "coder", "tool_result", _truncate(tool_read_file(path), 320),
             {"tool": "read_file"})
    await beat()
    if attempt == 1:
        emit(run_id, "coder", "message", f"Root cause: {intel['root_cause']}")
        await beat()
        emit(run_id, "coder", "message", f"Plan: {intel['plan']}")
    else:
        emit(run_id, "coder", "message", f"Adjusted plan based on feedback: {intel['plan']}")
    await beat()
    diff = demo_scripts.build_diff(issue.number, attempt)
    changed = count_changed_lines(diff)
    emit(run_id, "coder", "tool_call",
         f"apply_patch(<unified diff>, files={changed_paths(diff)})",
         {"tool": "apply_patch", "input": {"files": changed_paths(diff)}})
    await beat()
    emit(run_id, "coder", "tool_result",
         f"patch recorded: {changed} changed line(s) across {len(changed_paths(diff))} file(s)",
         {"tool": "apply_patch", "changed_lines": changed})
    return diff


# ---------------------------------------------------------------------------
# Tester Agent (ALWAYS REAL — applies patch in the sandbox and runs pytest)
# ---------------------------------------------------------------------------

async def run_tester(run_id: int, issue, diff: str, attempt: int,
                     repro_test: str | None = None) -> sandbox.TestEvaluation:
    emit(run_id, "tester", "step",
         f"Attempt {attempt}: applying patch in the sandbox ({sandbox.engine()} engine)")
    await beat()
    emit(run_id, "tester", "message",
         "Copying the repo to a fresh temp dir, applying the patch, running the full pytest suite."
         + (" [Docker unavailable: local fallback, NOT isolated]" if sandbox.engine() == "local"
            else " [Docker: --network none, 256MB, 0.5 CPU, read-only root, 60s timeout]"))
    await beat()
    emit(run_id, "tester", "tool_call", "run_tests()", {"tool": "run_tests", "input": {}})
    result: sandbox.TestEvaluation = await asyncio.to_thread(sandbox.evaluate_patch, diff, repro_test=repro_test)
    await beat()
    verdict = "PASS" if result.tests_passed else "FAIL"
    emit(run_id, "tester", "tool_result",
         f"run_tests -> {verdict}: {result.passed_count} passed, {result.failed} failed "
         f"(patched copy, real pytest). {result.detail}",
         {"tool": "run_tests", "passed": result.tests_passed, "total": result.total,
          "failed": result.failed, "passed_count": result.passed_count})
    emit(run_id, "tester", "log", result.detail)
    if not result.tests_passed and result.raw_output:
        tail = "\n".join(result.raw_output.splitlines()[-14:])
        emit(run_id, "tester", "message", f"Failure tail for the Coder:\n{tail}")
    return result


# ---------------------------------------------------------------------------
# Reviewer Agent (separate instance/prompt from the Coder — never self-approves)
# ---------------------------------------------------------------------------

async def run_reviewer(run_id: int, issue, diff: str,
                       test_result: sandbox.TestEvaluation, attempt: int) -> dict:
    if patch_deletes_tests(diff):
        emit(run_id, "reviewer", "message", "Patch deletes existing test assertions. Rejecting.")
        return {"verdict": "REJECT", "notes": ["Rejected: candidate patch deletes test code from test files."]}
    if _live():
        return await _live_reviewer(run_id, issue, diff, test_result, attempt)
    emit(run_id, "reviewer", "step", f"Attempt {attempt}: independent review of diff + test results")

    await beat()
    intel = demo_scripts.CODER_INTEL[issue.number]
    for path in intel["files"]:
        emit(run_id, "reviewer", "tool_call", f"read_file({path!r})",
             {"tool": "read_file", "input": {"path": path}})
        await beat()
        emit(run_id, "reviewer", "tool_result", _truncate(tool_read_file(path), 240),
             {"tool": "read_file"})
        await beat()
    has_test = any(p.startswith("tests/") for p in changed_paths(diff))
    review = demo_scripts.REVIEWS[issue.number][attempt]
    for note in review["notes"]:
        emit(run_id, "reviewer", "log", note)
        await beat()
    if not has_test and review["verdict"] == "CHANGES_REQUESTED":
        emit(run_id, "reviewer", "message",
             "Diff contains no test change — requesting a regression test before approval.")
        await beat()
    emit(run_id, "reviewer", "message", f"Verdict: {review['verdict']}",
         {"verdict": review["verdict"], "notes": review["notes"]})
    return review


# ---------------------------------------------------------------------------
# Live-mode implementations (real Claude tool-use loops)
# ---------------------------------------------------------------------------

def _on_event(run_id: int, agent: str):
    def note(kind: str, text: str, data: dict | None = None) -> None:
        emit(run_id, agent, "tool_call" if kind == "tool_call" else "tool_result", text, data)
    return note


async def _live_triage(run_id: int, issue) -> dict:
    emit(run_id, "triage", "step", "Reading issue body and repository file tree (live)")
    tree = "\n".join(
        str(p.relative_to(config.SAMPLE_REPO_DIR))
        for p in sorted(config.SAMPLE_REPO_DIR.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    )
    prompt = (
        f"Issue #{issue.number}: {issue.title}\n\n{issue.body}\n\n"
        f"Labels: {', '.join(issue.labels)}\n\nRepository file tree:\n{tree}\n\n"
        "Return ONLY the JSON triage object."
    )
    text = await asyncio.to_thread(
        llm.run_agent_loop, llm.TRIAGE_SYSTEM, [], {}, prompt, _on_event(run_id, "triage")
    )
    result = llm.extract_json(text)
    emit(run_id, "triage", "message",
         f"Verdict: {'IN SCOPE' if result.get('in_scope') else 'OUT OF SCOPE'}",
         {"verdict": result})
    return result


async def _live_coder_reproduce(run_id: int, issue, attempt: int,
                                feedback: str | None = None) -> dict:
    emit(run_id, "coder", "step", f"Reproduction attempt {attempt}: live reproduction session")
    tools = [
        {"name": "search_code",
         "description": "Search sample repo for a string; returns path:line matches.",
         "input_schema": {"type": "object",
                          "properties": {"query": {"type": "string"}},
                          "required": ["query"]}},
        {"name": "read_file",
         "description": "Read a file from the sample repo (relative path).",
         "input_schema": {"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}},
    ]
    impls = {
        "search_code": lambda i: tool_search_code(i["query"]),
        "read_file": lambda i: tool_read_file(i["path"]),
    }
    prompt = (
        f"Issue #{issue.number}: {issue.title}\n\n{issue.body}\n\n"
        "Before editing source files, you must produce a failing test that proves the bug.\n"
        "Either identify an existing test that already fails on the unpatched repo, OR write ONE new test in a new file under tests/ (named test_repocrew_issue_<number>.py).\n"
        "Return ONLY a JSON object of one of the two forms:\n"
        '{"strategy": "existing", "test_name": "<existing_test_name>"}\n'
        'OR\n'
        f'{{"strategy": "new", "test_name": "test_repocrew_issue_{issue.number}.py::test_repro", "file_path": "tests/test_repocrew_issue_{issue.number}.py", "content": "<python test code>"}}'
    )
    if feedback:
        prompt += f"\n\nPrevious attempt failed feedback: {feedback}"
    text = await asyncio.to_thread(
        llm.run_agent_loop, llm.CODER_SYSTEM, tools, impls, prompt, _on_event(run_id, "coder")
    )
    result = llm.extract_json(text)
    return result


async def _live_coder(run_id: int, issue, attempt: int,
                      prev_diff: str | None, feedback: str | None) -> str:
    emit(run_id, "coder", "step", f"Attempt {attempt}: live tool-use coding session")
    holder: dict[str, str] = {}

    def apply_patch(inp: dict) -> str:
        diff = inp.get("unified_diff", "")
        paths = changed_paths(diff)
        if not diff.strip() or not paths:
            return "ERROR: empty or unparsable unified diff"
        if any(".." in p for p in paths):
            return "ERROR: path traversal is not allowed"
        try:
            validate_coder_paths(paths)
        except ValueError as err:
            return f"ERROR: {err}"
        holder["diff"] = diff
        return (f"patch recorded: {count_changed_lines(diff)} changed line(s), "
                f"files: {', '.join(paths)}")

    tools = [
        {"name": "search_code",
         "description": "Search sample repo for a string; returns path:line matches.",
         "input_schema": {"type": "object",
                          "properties": {"query": {"type": "string"}},
                          "required": ["query"]}},
        {"name": "read_file",
         "description": "Read a file from the sample repo (relative path).",
         "input_schema": {"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}},
        {"name": "apply_patch",
         "description": "Record the final unified diff (a/ b/ path prefixes).",
         "input_schema": {"type": "object",
                          "properties": {"unified_diff": {"type": "string"}},
                          "required": ["unified_diff"]}},
    ]
    impls = {
        "search_code": lambda i: tool_search_code(i["query"]),
        "read_file": lambda i: tool_read_file(i["path"]),
        "apply_patch": apply_patch,
    }
    prompt = f"Issue #{issue.number}: {issue.title}\n\n{issue.body}"
    if attempt > 1:
        prompt += (f"\n\nYour previous diff (attempt {attempt - 1}) was:\n{prev_diff}\n\n"
                   f"Feedback to address:\n{feedback}")
    prompt += "\n\nProduce a minimal fix and call apply_patch exactly once."
    await asyncio.to_thread(
        llm.run_agent_loop, llm.CODER_SYSTEM, tools, impls, prompt, _on_event(run_id, "coder")
    )
    if "diff" not in holder:
        raise RuntimeError("live Coder finished without calling apply_patch")
    return holder["diff"]


async def _live_reviewer(run_id: int, issue, diff: str,
                         test_result: sandbox.TestEvaluation, attempt: int) -> dict:
    emit(run_id, "reviewer", "step", f"Attempt {attempt}: independent live review")
    tools = [
        {"name": "read_file",
         "description": "Read a file from the sample repo (relative path).",
         "input_schema": {"type": "object",
                          "properties": {"path": {"type": "string"}},
                          "required": ["path"]}},
    ]
    impls = {"read_file": lambda i: tool_read_file(i["path"])}
    prompt = (
        f"Issue #{issue.number}: {issue.title}\n\n{issue.body}\n\n"
        f"Candidate diff (attempt {attempt}):\n```diff\n{diff}\n```\n\n"
        f"Sandbox test outcome: {'PASS' if test_result.tests_passed else 'FAIL'} "
        f"({test_result.passed_count} passed, {test_result.failed} failed). {test_result.detail}\n\n"
        "Return ONLY the JSON verdict object."
    )
    text = await asyncio.to_thread(
        llm.run_agent_loop, llm.REVIEWER_SYSTEM, tools, impls, prompt, _on_event(run_id, "reviewer")
    )
    result = llm.extract_json(text)
    notes = result.get("notes") or []
    if isinstance(notes, str):
        notes = [notes]
    review = {"verdict": result.get("verdict", "CHANGES_REQUESTED"), "notes": notes}
    emit(run_id, "reviewer", "message", f"Verdict: {review['verdict']}", {"verdict": review})
    return review
