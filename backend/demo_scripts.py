"""RepoCrew demo-mode scripts (RC_MODE=demo).

Deterministic scripted trajectories for the five seeded issues. They emit the
same event types as live mode; only the agent *reasoning* is scripted — the
Tester always genuinely applies the patch and runs pytest in the sandbox.

Diffs are generated with difflib from exact before/after file snippets, so
hunk headers are always valid for ``git apply`` (and for the pure-Python
applier fallback).
"""
from __future__ import annotations

from . import config
from .diffutil import make_file_diff

# ---------------------------------------------------------------------------
# Reproduction plans ("reproduce first" before fixing)
# ---------------------------------------------------------------------------

REPRODUCTIONS = {
    1: {
        "strategy": "existing",
        "test_name": "test_average_empty_list_returns_zero",
    },
    2: {
        "strategy": "existing",
        "test_name": "test_paginate_last_partial_page",
    },
    3: {
        "strategy": "existing",
        "test_name": "test_slugify_strips_trailing_hyphen",
    },
}

REPRODUCTIONS_RETRY: dict[int, dict] = {}

# ---------------------------------------------------------------------------
# Triage decisions
# ---------------------------------------------------------------------------

TRIAGE = {
    1: {
        "category": "bug",
        "difficulty": "easy",
        "confidence": 0.98,
        "in_scope": True,
        "reason": "Single guard clause in one function; an existing failing test already documents the expected behavior (return 0.0 on empty input). Small, low-risk, well-specified.",
        "comment_to_reporter": None,
    },
    2: {
        "category": "bug",
        "difficulty": "easy",
        "confidence": 0.95,
        "in_scope": True,
        "reason": "Classic off-by-one in the page-window computation of paginate(); a failing test (test_paginate_last_partial_page) pins the expected behavior. Small fix, clear signal.",
        "comment_to_reporter": None,
    },
    3: {
        "category": "bug",
        "difficulty": "easy",
        "confidence": 0.96,
        "in_scope": True,
        "reason": "One-line behavioral fix in slugify() plus a regression test. Low risk, well-specified expected output.",
        "comment_to_reporter": None,
    },
    4: {
        "category": "feature",
        "difficulty": "hard",
        "confidence": 0.99,
        "in_scope": False,
        "reason": "Full language rewrite plus a plugin system is far too large and risky for an autonomous maintenance run: it has no failing test to target, touches every module, and requires product-level architectural decisions.",
        "comment_to_reporter": (
            "Thanks for the suggestion! A full Rust rewrite and a plugin system are out of "
            "scope for RepoCrew's automated maintenance runs — this needs human design work "
            "and a roadmap discussion. If you can carve out a small, concrete piece (e.g. one "
            "function that would benefit from optimization), please open a focused issue and "
            "RepoCrew will happily pick it up."
        ),
    },
    5: {
        "category": "bug",
        "difficulty": "easy",
        "confidence": 0.9,
        "in_scope": True,
        "reason": "Small config change to the CI workflow. In scope for analysis, but note it touches .github/**, so the safety gate will review it strictly. Token rotation itself can never be done by an agent — no secrets are in the repo.",
        "comment_to_reporter": None,
    },
}

# ---------------------------------------------------------------------------
# Coder trajectories
# ---------------------------------------------------------------------------
# Per issue: which file the coder "reads", the search query, root-cause line.

CODER_INTEL = {
    1: {
        "query": "def average",
        "files": ["miniutils/__init__.py"],
        "root_cause": "no guard for empty input: sum([]) / len([]) divides by zero.",
        "plan": "return 0.0 for an empty list, one-line guard clause, no API change.",
    },
    2: {
        "query": "def paginate",
        "files": ["miniutils/__init__.py"],
        "root_cause": "the range() window stops before the final partial page, so a non-divisible tail is never yielded.",
        "plan": "compute the page count from the item count so the remainder page is included.",
    },
    3: {
        "query": "def slugify",
        "files": ["miniutils/__init__.py"],
        "root_cause": "re.sub('[^a-z0-9]+', '-') maps trailing punctuation to a trailing '-'; the result is never stripped.",
        "plan": "strip leading/trailing hyphens from the substituted slug.",
    },
    5: {
        "query": "python-version",
        "files": [".github/workflows/ci.yml"],
        "root_cause": "CI matrix pins python-version: \"3.11\".",
        "plan": "bump the pinned interpreter to 3.12 in .github/workflows/ci.yml. Token rotation requires a human with access to repository secrets — an agent must never handle that; a note goes into the PR body instead.",
    },
}

# Exact snippet replacements: (path, old_snippet, new_snippet).
PATCHES = {
    1: {
        1: [
            (
                "miniutils/__init__.py",
                (
                    'def average(nums):\n'
                    '    """Return the arithmetic mean of a non-empty list of numbers."""\n'
                    '    return sum(nums) / len(nums)'
                ),
                (
                    'def average(nums):\n'
                    '    """Return the arithmetic mean of a list of numbers.\n'
                    '\n'
                    '    Returns 0.0 for an empty list instead of raising ZeroDivisionError.\n'
                    '    """\n'
                    '    if not nums:\n'
                    '        return 0.0\n'
                    '    return sum(nums) / len(nums)'
                ),
            ),
        ],
    },
    2: {
        # Attempt 1 is deliberately, subtly wrong: it still uses floor division,
        # so the remainder page is dropped. The Tester catches it for real.
        1: [
            (
                "miniutils/__init__.py",
                (
                    "    return [items[i:i + page_size] for i in range(0, len(items) - page_size + 1, page_size)]"
                ),
                (
                    "    num_pages = len(items) // page_size\n"
                    "    return [items[i * page_size:(i + 1) * page_size] for i in range(num_pages)]"
                ),
            ),
        ],
        # Attempt 2 (after reading the real pytest failure log): ceiling division.
        2: [
            (
                "miniutils/__init__.py",
                (
                    "    return [items[i:i + page_size] for i in range(0, len(items) - page_size + 1, page_size)]"
                ),
                (
                    "    num_pages = (len(items) + page_size - 1) // page_size\n"
                    "    return [items[i * page_size:(i + 1) * page_size] for i in range(num_pages)]"
                ),
            ),
        ],
    },
    3: {
        # Attempt 1: behavior fix only — the Reviewer will demand a regression test.
        1: [
            (
                "miniutils/__init__.py",
                (
                    '    text = text.strip().lower()\n'
                    '    return re.sub(r"[^a-z0-9]+", "-", text)'
                ),
                (
                    '    text = text.strip().lower()\n'
                    '    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")'
                ),
            ),
        ],
        # Attempt 2: same fix + a new regression test file.
        2: [
            (
                "miniutils/__init__.py",
                (
                    '    text = text.strip().lower()\n'
                    '    return re.sub(r"[^a-z0-9]+", "-", text)'
                ),
                (
                    '    text = text.strip().lower()\n'
                    '    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")'
                ),
            ),
            (
                None,  # new file marker
                "tests/test_slugify_regression.py",
                (
                    '"""Regression tests for the slugify() trailing-hyphen bug (issue #3)."""\n'
                    "\n"
                    "from miniutils import slugify\n"
                    "\n"
                    "\n"
                    "def test_slugify_strips_trailing_hyphens():\n"
                    '    assert slugify("Hello, World!") == "hello-world"\n'
                    "\n"
                    "\n"
                    "def test_slugify_strips_leading_and_trailing_hyphens():\n"
                    '    assert slugify("==Already Loading==") == "already-loading"\n'
                ),
            ),
        ],
    },
    5: {
        1: [
            (
                ".github/workflows/ci.yml",
                '          python-version: "3.11"',
                '          python-version: "3.12"',
            ),
        ],
    },
}

# ---------------------------------------------------------------------------
# Reviewer verdicts (independent reviewer — never the author of the patch)
# ---------------------------------------------------------------------------

REVIEWS = {
    1: {
        1: {
            "verdict": "APPROVE",
            "notes": [
                "Guard clause directly addresses the reported ZeroDivisionError; behavior for non-empty input is unchanged.",
                "Diff is minimal: one function, no unrelated edits, style matches the module.",
                "The existing suite already covers the edge case; no new test strictly required.",
            ],
        },
    },
    2: {
        2: {
            "verdict": "APPROVE",
            "notes": [
                "Ceiling division fixes the dropped remainder page without changing the even-split behavior.",
                "Revision responds directly to the Tester's failure log — exactly what the retry loop is for.",
                "Diff stays within paginate(); no unrelated changes.",
            ],
        },
    },
    3: {
        1: {
            "verdict": "CHANGES_REQUESTED",
            "notes": [
                "The .strip('-') fix is correct and minimal, and the suite passes.",
                "However the diff adds no regression test: nothing would catch a future regression of trailing hyphens.",
                "Please add a dedicated test covering trailing (and leading) hyphens before this can be approved.",
            ],
        },
        2: {
            "verdict": "APPROVE",
            "notes": [
                "Fix unchanged and correct; the new tests/test_slugify_regression.py covers trailing and leading hyphens.",
                "Tests are focused and follow the existing pytest style.",
            ],
        },
    },
    5: {
        1: {
            "verdict": "APPROVE",
            "notes": [
                "Python version bump in the CI workflow is exactly what the issue asks for and nothing else.",
                "Token rotation is correctly NOT attempted by the agent — flagged for a human instead.",
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# PR blurbs used to generate real PR bodies
# ---------------------------------------------------------------------------

PR_BLURBS = {
    1: {
        "summary": "Fixes a crash in `average()` when called with an empty list.",
        "root_cause": "`average([])` computed `sum([]) / len([])`, dividing by zero. The function now returns `0.0` for empty input, as the issue requested.",
        "changes": ["`miniutils/__init__.py`: added an empty-input guard clause and updated the docstring."],
    },
    2: {
        "summary": "Fixes `paginate()` dropping the last partial page.",
        "root_cause": "The page window was computed with `range(0, len(items) - page_size + 1, page_size)`, which never reaches the final remainder page. The rewrite now derives the page count from the item count using ceiling division.",
        "changes": ["`miniutils/__init__.py`: replaced the range-window slicing with a page-count loop."],
    },
    3: {
        "summary": "Strips trailing hyphens from `slugify()` output and adds a regression test.",
        "root_cause": "Trailing punctuation mapped to a trailing `-` that was never stripped from the substituted slug.",
        "changes": [
            "`miniutils/__init__.py`: `.strip('-')` applied to the substituted slug.",
            "`tests/test_slugify_regression.py`: new regression tests for leading/trailing hyphens.",
        ],
    },
    5: {
        "summary": "Bumps the CI workflow from Python 3.11 to 3.12.",
        "root_cause": "The test matrix pinned `python-version: \"3.11\"`. The deploy-token rotation requested in the issue was deliberately NOT performed: tokens live in repository secrets and must be rotated by a human administrator.",
        "changes": ["`.github/workflows/ci.yml`: `python-version` 3.11 -> 3.12."],
    },
}


# ---------------------------------------------------------------------------
# Diff builder
# ---------------------------------------------------------------------------

def build_diff(issue_number: int, attempt: int) -> str:
    """Build the exact unified diff for a scripted attempt."""
    specs = PATCHES[issue_number][attempt]
    chunks: list[str] = []
    for path_or_none, a, b in [(s[0], s[1], s[2]) for s in specs]:
        if path_or_none is None:
            # new-file entry: a is the new file's path, b its content
            chunks.append(make_file_diff(a, None, b))
            continue
        path = path_or_none
        full = (config.SAMPLE_REPO_DIR / path).read_text(encoding="utf-8")
        if full.count(a) != 1:
            raise RuntimeError(
                f"demo script error: snippet for {path} not found exactly once "
                f"(issue #{issue_number}, attempt {attempt})"
            )
        new_full = full.replace(a, b)
        chunks.append(make_file_diff(path, full, new_full))
    return "".join(chunks)


def max_demo_attempts(issue_number: int) -> int:
    return max(PATCHES.get(issue_number, {1: None}).keys())
