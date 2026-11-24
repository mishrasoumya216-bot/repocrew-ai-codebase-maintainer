"""RepoCrew seed data: the five seeded demo issues.

Seeded once on first startup when the ``issues`` table is empty.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .database import SessionLocal
from .models import Issue

SEED_ISSUES = [
    {
        "number": 1,
        "title": "average() crashes with ZeroDivisionError on empty list",
        "body": (
            "Calling `average([])` raises `ZeroDivisionError: division by zero`.\n\n"
            "Steps to reproduce:\n"
            "```python\nfrom miniutils import average\naverage([])\n```\n\n"
            "Expected behavior: for an empty input the function should return `0.0` "
            "instead of crashing. The happy-path tests pass; the edge case is the problem."
        ),
        "labels": ["good first issue"],
        "reporter": "dev-alice",
    },
    {
        "number": 2,
        "title": "paginate() drops the last page when items aren't evenly divisible",
        "body": (
            "`paginate([1, 2, 3, 4, 5], 2)` returns `[[1, 2], [3, 4]]` — the final "
            "partial page `[5]` is silently dropped.\n\n"
            "Evenly divisible inputs (e.g. 4 items with page size 2) work fine, so this "
            "looks like a classic off-by-one in the page-window computation."
        ),
        "labels": ["good first issue"],
        "reporter": "dev-bob",
    },
    {
        "number": 3,
        "title": "slugify() leaves trailing hyphens",
        "body": (
            "`slugify('Hello, World!')` returns `'hello-world-'` (note the trailing "
            "hyphen). Trailing punctuation should not leak into the slug; the expected "
            "output is `'hello-world'`."
        ),
        "labels": ["bug"],
        "reporter": "dev-carla",
    },
    {
        "number": 4,
        "title": "Rewrite the whole library in Rust and add a plugin system",
        "body": (
            "Have you considered rewriting miniutils in Rust for speed? Also it would be "
            "great to have a full plugin system with dynamic loading, a registry, and "
            "callbacks. This would make the library so much more powerful."
        ),
        "labels": ["enhancement"],
        "reporter": "dev-dan",
    },
    {
        "number": 5,
        "title": "Bump Python version in CI and rotate the deploy token",
        "body": (
            "CI is still running on Python 3.11 — please bump it to 3.12 in "
            "`.github/workflows/ci.yml`. Also the deployment token stored in the CI "
            "secrets is old and should be rotated."
        ),
        "labels": ["bug"],
        "reporter": "dev-erin",
    },
]


def seed_issues() -> None:
    """Insert the five seeded issues if the table is empty."""
    session = SessionLocal()
    try:
        if session.query(Issue).count() > 0:
            return
        base = datetime.now(timezone.utc) - timedelta(days=9)
        for i, data in enumerate(SEED_ISSUES):
            session.add(Issue(created_at=base + timedelta(days=i), **data))
        session.commit()
    finally:
        session.close()
