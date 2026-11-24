"""RepoCrew sandbox service.

The Tester is ALWAYS real, in demo and live mode alike:
  1. Copy the sample repo into a fresh temp dir.
  2. Apply the candidate patch (``git apply``, with a pure-Python fallback).
  3. Run the full pytest suite.
  4. Destroy the temp dir.

Docker mode uses the ``repocrew-sandbox`` image (see /sandbox/Dockerfile) with
hard isolation: no network, 256MB RAM, 0.5 CPU, 128 pids, read-only root fs,
tmpfs /tmp, only the work dir mounted rw, 60s timeout, --rm.
If Docker is unavailable the sandbox falls back to a local subprocess (still a
temp-dir copy + timeout, but NOT isolated) and the UI shows a yellow warning.

Because RepoCrew never merges (it only opens PRs), the ``main`` it patches is
intentionally red — the seeded bugs' exposing tests fail on the base repo.
The Tester therefore runs the suite TWICE (baseline on the unpatched copy and
on the patched copy) and uses SWE-bench style fail-to-pass semantics:
a patch passes if it introduces no regressions versus baseline AND either the
suite is fully green, at least one previously failing test is fixed, or the
patch contains no code changes at all (e.g. CI-config-only changes).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .diffutil import apply_unified_diff, changed_paths

PYTEST_CMD = "python -m pytest -v --tb=short -p no:cacheprovider"

_engine: str = "local"  # decided at startup by probe_docker()
_baseline_cache: dict[str, "PytestRun"] = {}


@dataclass
class PytestRun:
    exit_code: int
    raw_output: str
    passed_count: int
    failed_count: int
    total: int
    passed_tests: list[str] = field(default_factory=list)
    failed_tests: list[str] = field(default_factory=list)
    timed_out: bool = False


@dataclass
class TestEvaluation:
    __test__ = False
    tests_passed: bool          # classification used by the safety gate
    patch_applied: bool
    engine: str                 # "docker" | "local"
    detail: str
    raw_output: str             # real pytest output of the patched run
    total: int
    failed: int
    passed_count: int
    reproduced: bool = False
    test_name: str | None = None


# ---------------------------------------------------------------------------
# Docker detection
# ---------------------------------------------------------------------------

def probe_docker() -> str:
    """Detect Docker and the repocrew-sandbox image; build it if possible."""
    global _engine
    docker = shutil.which("docker")
    if not docker:
        _engine = "local"
        return _engine
    try:
        info = subprocess.run([docker, "info"], capture_output=True, timeout=20)
        if info.returncode != 0:
            _engine = "local"
            return _engine
        inspect = subprocess.run(
            [docker, "image", "inspect", config.DOCKER_IMAGE], capture_output=True, timeout=20
        )
        if inspect.returncode != 0:
            build = subprocess.run(
                [docker, "build", "-t", config.DOCKER_IMAGE, str(config.SANDBOX_DIR)],
                capture_output=True, timeout=600,
            )
            if build.returncode != 0:
                _engine = "local"
                return _engine
        _engine = "docker"
    except Exception:
        _engine = "local"
    return _engine


def engine() -> str:
    return _engine


# ---------------------------------------------------------------------------
# pytest output parsing
# ---------------------------------------------------------------------------

_TEST_LINE = re.compile(r"^(\S+?::\S+?)\s+(PASSED|FAILED|ERROR)\b", re.MULTILINE)


def _parse_pytest(proc_exit: int, output: str, timed_out: bool = False) -> PytestRun:
    passed_tests: list[str] = []
    failed_tests: list[str] = []
    for name, status in _TEST_LINE.findall(output):
        if status == "PASSED":
            passed_tests.append(name)
        else:
            failed_tests.append(name)
    passed_count = len(passed_tests)
    failed_count = len(failed_tests)
    return PytestRun(
        exit_code=proc_exit,
        raw_output=output,
        passed_count=passed_count,
        failed_count=failed_count,
        total=passed_count + failed_count,
        passed_tests=passed_tests,
        failed_tests=failed_tests,
        timed_out=timed_out,
    )


# ---------------------------------------------------------------------------
# Execution engines
# ---------------------------------------------------------------------------

def _run_pytest_docker(workdir: Path, patch_file: Path | None) -> PytestRun:
    """Run pytest inside an isolated repocrew-sandbox container."""
    docker = shutil.which("docker") or "docker"
    name = f"repocrew-run-{uuid.uuid4().hex[:8]}"
    patch_mount = []
    inner = PYTEST_CMD
    if patch_file is not None:
        patch_mount = ["-v", f"{patch_file}:/tmp/patch.diff:ro"]
        inner = f"git apply --whitespace=nowarn /tmp/patch.diff && {PYTEST_CMD}"
    cmd = [
        docker, "run", "--rm", "--name", name,
        "--network", "none",
        "--memory", "256m",
        "--cpus", "0.5",
        "--pids-limit", "128",
        "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,size=64m",
        "-v", f"{workdir}:/work:rw",
        *patch_mount,
        "-w", "/work",
        config.DOCKER_IMAGE,
        "sh", "-c", inner,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=config.TEST_TIMEOUT_SECONDS + 5
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return _parse_pytest(proc.returncode, output.strip())
    except subprocess.TimeoutExpired:
        subprocess.run([docker, "kill", name], capture_output=True)
        subprocess.run([docker, "rm", "-f", name], capture_output=True)
        return _parse_pytest(124, "REPOCREW: pytest run timed out (hard 60s limit).", timed_out=True)


def _run_pytest_local(workdir: Path, patch_file: Path | None) -> PytestRun:
    """Fallback: run pytest as a local subprocess on the temp copy (NOT isolated)."""
    if patch_file is not None:
        git = shutil.which("git")
        try:
            if git:
                proc = subprocess.run(
                    [git, "apply", "--whitespace=nowarn", str(patch_file)],
                    cwd=workdir, capture_output=True, text=True, timeout=30,
                )
                if proc.returncode != 0:
                    return _parse_pytest(100 + 1, f"REPOCREW: patch failed to apply:\n{proc.stderr}")
            else:
                apply_unified_diff(workdir, patch_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - report apply failures as test failure
            return PytestRun(
                exit_code=101, raw_output=f"REPOCREW: patch failed to apply: {exc}",
                passed_count=0, failed_count=0, total=0,
            )
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=short", "-p", "no:cacheprovider"],
            cwd=workdir, capture_output=True, text=True, timeout=config.TEST_TIMEOUT_SECONDS,
        )
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        return _parse_pytest(proc.returncode, output.strip())
    except subprocess.TimeoutExpired:
        return _parse_pytest(124, "REPOCREW: pytest run timed out (hard 60s limit).", timed_out=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _copy_repo() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="repocrew-sb-"))
    shutil.copytree(
        config.SAMPLE_REPO_DIR, tmp, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
    )
    return tmp


def baseline_run() -> PytestRun:
    """Suite result on the unpatched repo (cached per engine)."""
    if _engine in _baseline_cache:
        return _baseline_cache[_engine]
    tmp = _copy_repo()
    try:
        result = _run_pytest_docker(tmp, None) if _engine == "docker" else _run_pytest_local(tmp, None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _baseline_cache[_engine] = result
    return result


def _test_matches(full_name: str, target: str) -> bool:
    target_clean = target.strip()
    return (
        full_name == target_clean
        or full_name.endswith("::" + target_clean)
        or full_name.split("::")[-1] == target_clean
        or ("::" in target_clean and target_clean in full_name)
    )


def evaluate_reproduction(issue_number: int, repro: str | dict | None = None) -> TestEvaluation:
    """Run reproduction candidate on the UNPATCHED repo in the sandbox.

    Returns a TestEvaluation where ``reproduced=True`` if the specified test
    fails on the unpatched repo (thereby proving the bug).
    """
    if not repro:
        return TestEvaluation(
            tests_passed=False,
            patch_applied=False,
            engine=_engine,
            detail="No reproduction test provided",
            raw_output="",
            total=0,
            failed=0,
            passed_count=0,
            reproduced=False,
            test_name=None,
        )

    existing_test: str | None = None
    new_test_path: str | None = None
    new_test_code: str | None = None
    new_test_diff: str | None = None

    if isinstance(repro, dict):
        if repro.get("strategy") == "existing" or repro.get("existing_test"):
            existing_test = repro.get("test_name") or repro.get("existing_test")
        elif repro.get("strategy") == "new" or repro.get("new_test") or repro.get("is_new_file"):
            new_test_path = repro.get("file_path") or f"tests/test_repocrew_issue_{issue_number}.py"
            new_test_code = repro.get("code") or repro.get("content") or repro.get("new_test")
            new_test_diff = repro.get("diff")
            existing_test = repro.get("test_name")
        elif "test_name" in repro:
            existing_test = repro["test_name"]
    elif isinstance(repro, str):
        repro_str = repro.strip()
        if repro_str.startswith("diff --git") or repro_str.startswith("--- "):
            new_test_diff = repro_str
            new_test_path = f"tests/test_repocrew_issue_{issue_number}.py"
        elif "def test_" in repro_str:
            new_test_code = repro_str
            new_test_path = f"tests/test_repocrew_issue_{issue_number}.py"
        else:
            existing_test = repro_str

    # Case 1: Existing test identifier on unpatched repo
    if existing_test and not new_test_code and not new_test_diff:
        base = baseline_run()
        failed_match = [t for t in base.failed_tests if _test_matches(t, existing_test)]
        passed_match = [t for t in base.passed_tests if _test_matches(t, existing_test)]
        if failed_match:
            matched_name = existing_test
            return TestEvaluation(
                tests_passed=False,
                patch_applied=True,
                engine=_engine,
                detail=f"Bug reproduced: {matched_name} failed on unpatched repo",
                raw_output=base.raw_output,
                total=base.total,
                failed=base.failed_count,
                passed_count=base.passed_count,
                reproduced=True,
                test_name=matched_name,
            )
        elif passed_match:
            return TestEvaluation(
                tests_passed=True,
                patch_applied=True,
                engine=_engine,
                detail=f"Test '{existing_test}' PASSED on unpatched repo; did not reproduce bug",
                raw_output=base.raw_output,
                total=base.total,
                failed=base.failed_count,
                passed_count=base.passed_count,
                reproduced=False,
                test_name=existing_test,
            )
        else:
            return TestEvaluation(
                tests_passed=False,
                patch_applied=True,
                engine=_engine,
                detail=f"Test '{existing_test}' not found in unpatched repo suite",
                raw_output=base.raw_output,
                total=base.total,
                failed=base.failed_count,
                passed_count=base.passed_count,
                reproduced=False,
                test_name=existing_test,
            )

    # Case 2: New test file under tests/test_repocrew_issue_<number>.py
    tmp = _copy_repo()
    target_rel = new_test_path or f"tests/test_repocrew_issue_{issue_number}.py"
    target_file = tmp / target_rel
    target_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        if new_test_diff:
            patch_file = tmp.parent / f"{tmp.name}.diff"
            patch_file.write_text(new_test_diff, encoding="utf-8")
            try:
                if _engine == "docker":
                    run = _run_pytest_docker(tmp, patch_file)
                else:
                    run = _run_pytest_local(tmp, patch_file)
            finally:
                patch_file.unlink(missing_ok=True)
        elif new_test_code:
            target_file.write_text(new_test_code, encoding="utf-8")
            run = _run_pytest_docker(tmp, None) if _engine == "docker" else _run_pytest_local(tmp, None)
        else:
            return TestEvaluation(
                tests_passed=False, patch_applied=False, engine=_engine,
                detail="Invalid reproduction specification",
                raw_output="", total=0, failed=0, passed_count=0,
                reproduced=False, test_name=None,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    expected_file_sub = f"test_repocrew_issue_{issue_number}"
    repro_failed = [t for t in run.failed_tests if expected_file_sub in t or (existing_test and _test_matches(t, existing_test))]
    repro_passed = [t for t in run.passed_tests if expected_file_sub in t or (existing_test and _test_matches(t, existing_test))]

    if repro_failed:
        repro_test = existing_test or repro_failed[0].split("::")[-1]
        return TestEvaluation(
            tests_passed=False,
            patch_applied=True,
            engine=_engine,
            detail=f"Bug reproduced: {repro_test} failed on unpatched repo",
            raw_output=run.raw_output,
            total=run.total,
            failed=run.failed_count,
            passed_count=run.passed_count,
            reproduced=True,
            test_name=repro_test,
        )
    elif repro_passed:
        repro_test = existing_test or repro_passed[0].split("::")[-1]
        return TestEvaluation(
            tests_passed=True,
            patch_applied=True,
            engine=_engine,
            detail=f"Reproduction test {repro_test} PASSED on unpatched repo; did not reproduce bug",
            raw_output=run.raw_output,
            total=run.total,
            failed=run.failed_count,
            passed_count=run.passed_count,
            reproduced=False,
            test_name=repro_test,
        )
    else:
        return TestEvaluation(
            tests_passed=False,
            patch_applied=True,
            engine=_engine,
            detail=f"Reproduction test was not executed or failed to run: {run.raw_output[:200]}",
            raw_output=run.raw_output,
            total=run.total,
            failed=run.failed_count,
            passed_count=run.passed_count,
            reproduced=False,
            test_name=existing_test,
        )


def evaluate_patch(diff_text: str, repro_test: str | None = None) -> TestEvaluation:
    """Apply ``diff_text`` to a fresh repo copy and genuinely run the suite.

    If ``repro_test`` is provided:
      1. That test MUST pass on the patched repo.
      2. No previously passing test may fail (no regressions).
    """
    paths = changed_paths(diff_text)
    if not diff_text.strip() or not paths:
        return TestEvaluation(
            tests_passed=False, patch_applied=False, engine=_engine,
            detail="Coder produced an empty patch; nothing to test.",
            raw_output="", total=0, failed=0, passed_count=0,
            reproduced=bool(repro_test), test_name=repro_test,
        )

    tmp = _copy_repo()
    patch_file = tmp.parent / f"{tmp.name}.diff"
    patch_file.write_text(diff_text, encoding="utf-8")
    try:
        if _engine == "docker":
            patched = _run_pytest_docker(tmp, patch_file)
        else:
            patched = _run_pytest_local(tmp, patch_file)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        patch_file.unlink(missing_ok=True)

    if patched.exit_code in (101, 102) and "patch failed to apply" in patched.raw_output:
        return TestEvaluation(
            tests_passed=False, patch_applied=False, engine=_engine,
            detail="Patch failed to apply; the Coder must regenerate it against current files.",
            raw_output=patched.raw_output, total=0, failed=0, passed_count=0,
            reproduced=bool(repro_test), test_name=repro_test,
        )

    base = baseline_run()
    regressions = sorted(set(patched.failed_tests) - set(base.failed_tests))
    improvements = sorted(set(base.failed_tests) - set(patched.failed_tests))
    code_changed = any(p.endswith(".py") for p in paths)

    bits = []

    if repro_test:
        repro_failed = any(_test_matches(t, repro_test) for t in patched.failed_tests)
        repro_passed = any(_test_matches(t, repro_test) for t in patched.passed_tests) or any(_test_matches(t, repro_test) for t in improvements)

        if repro_failed or not repro_passed:
            tests_passed = False
            bits.append(f"reproduction test '{repro_test}' failed")
        elif regressions:
            tests_passed = False
            names = ", ".join(t.split("::")[-1] for t in regressions)
            bits.append(f"NEW regressions: {names}")
        else:
            tests_passed = True
            bits.append(f"reproduction test '{repro_test}' passed")
    else:
        green = patched.failed_count == 0 and patched.total > 0
        if regressions:
            tests_passed = False
        elif green or improvements:
            tests_passed = True
        else:
            # No regression, no improvement: acceptable only for non-code diffs
            # (e.g. CI config), where the suite cannot validate the change.
            tests_passed = not code_changed

    if improvements:
        names = ", ".join(t.split("::")[-1] for t in improvements)
        bits.append(f"fixed previously-failing: {names}")
    if regressions and not repro_test:
        names = ", ".join(t.split("::")[-1] for t in regressions)
        bits.append(f"NEW regressions: {names}")
    if patched.timed_out:
        bits.append("pytest timed out")
        tests_passed = False
    if not bits:
        if tests_passed and not code_changed:
            bits.append("no code change; no regressions (suite unchanged)")
        else:
            bits.append("no change in test outcomes")

    pre = f"baseline: {base.passed_count} passed, {base.failed_count} failed"
    now = f"patched: {patched.passed_count} passed, {patched.failed_count} failed"
    detail = f"[{pre} | {now}] " + "; ".join(bits)
    return TestEvaluation(
        tests_passed=tests_passed, patch_applied=True, engine=_engine,
        detail=detail, raw_output=patched.raw_output,
        total=patched.total, failed=patched.failed_count, passed_count=patched.passed_count,
        reproduced=bool(repro_test), test_name=repro_test,
    )


def sandbox_status() -> dict:
    """Reported by /api/health; drives the sandbox badge in the UI."""
    return {
        "engine": _engine,
        "isolated": _engine == "docker",
        "message": (
            "Docker isolated" if _engine == "docker"
            else "Docker not found: running in local fallback (NOT isolated)"
        ),
    }
