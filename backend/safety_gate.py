"""RepoCrew Safety & Scoring Gate.

Confidence score (0-1):
    0.5 * tests_passed
  + 0.3 * reviewer_score        (APPROVE=1.0, CHANGES_REQUESTED=0.4, REJECT=0)
  + 0.1 * small_diff            (1 if diff <= 40 changed lines)
  + 0.1 * includes_test_change

A PR is allowed only if score >= 0.8 AND no blocked path is touched.
Blocked paths: .github/**, .env*, anything matching *secret*, *.pem, *.key,
Dockerfile*, and CI config files.
"""
from __future__ import annotations

from .diffutil import changed_paths, count_changed_lines

THRESHOLD = 0.8
SMALL_DIFF_LIMIT = 40

REVIEWER_SCORES = {"APPROVE": 1.0, "CHANGES_REQUESTED": 0.4, "REJECT": 0.0}

CI_CONFIG_NAMES = {
    ".gitlab-ci.yml", ".gitlab-ci.yaml", ".travis.yml", ".drone.yml",
    "azure-pipelines.yml", "bitbucket-pipelines.yml", "Jenkinsfile",
    "appveyor.yml", "buildkite.yml",
}
CI_CONFIG_DIRS = (".github/", ".circleci/", ".buildkite/", ".gitea/workflows/")


def blocked_reason(path: str) -> str | None:
    """Return the reason a path is blocked, or None if it is safe."""
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    base = p.rsplit("/", 1)[-1]
    if any(p.startswith(d) for d in CI_CONFIG_DIRS) or p in CI_CONFIG_NAMES or base in CI_CONFIG_NAMES:
        return f"{path} modifies CI/CD configuration"
    if base.startswith(".env"):
        return f"{path} touches environment files (.env*)"
    if "secret" in p.lower():
        return f"{path} matches *secret*"
    if base.endswith(".pem") or base.endswith(".key"):
        return f"{path} is a key/certificate file"
    if base.startswith("Dockerfile"):
        return f"{path} modifies container build files"
    return None


def includes_test_change(paths: list[str]) -> bool:
    return any(
        p.startswith("tests/") or "/tests/" in p or "test_" in p.rsplit("/", 1)[-1]
        for p in paths
    )


def evaluate(diff_text: str, tests_passed: bool, reviewer_verdict: str) -> dict:
    """Compute the structured gate result for a candidate patch."""
    paths = changed_paths(diff_text)
    changed = count_changed_lines(diff_text)
    blocked = [r for r in (blocked_reason(p) for p in paths) if r]

    small_diff = changed <= SMALL_DIFF_LIMIT
    has_test = includes_test_change(paths)
    reviewer_score = REVIEWER_SCORES.get(reviewer_verdict, 0.0)

    score = (
        0.5 * (1.0 if tests_passed else 0.0)
        + 0.3 * reviewer_score
        + 0.1 * (1.0 if small_diff else 0.0)
        + 0.1 * (1.0 if has_test else 0.0)
    )
    score = round(score, 3)

    checks = [
        {
            "name": "Tests pass in sandbox",
            "passed": bool(tests_passed),
            "detail": f"weight 0.5 -> {'1.0' if tests_passed else '0.0'} (real pytest in sandbox)",
        },
        {
            "name": "Reviewer verdict",
            "passed": reviewer_verdict == "APPROVE",
            "detail": f"weight 0.3 -> {reviewer_score} ({reviewer_verdict})",
        },
        {
            "name": "Small diff (<= 40 changed lines)",
            "passed": small_diff,
            "detail": f"weight 0.1 -> {'1.0' if small_diff else '0.0'} ({changed} changed lines)",
        },
        {
            "name": "Includes a test change",
            "passed": has_test,
            "detail": f"weight 0.1 -> {'1.0' if has_test else '0.0'}",
        },
        {
            "name": "No blocked paths touched",
            "passed": not blocked,
            "detail": "none" if not blocked else "; ".join(blocked),
        },
    ]

    allowed = score >= THRESHOLD and not blocked
    return {
        "score": score,
        "threshold": THRESHOLD,
        "checks": checks,
        "blocked_reasons": blocked,
        "allowed": allowed,
        "changed_lines": changed,
        "paths": paths,
    }
