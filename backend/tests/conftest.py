"""RepoCrew backend test configuration.

Sets an isolated SQLite database and fast delays BEFORE importing any backend
module, then initializes the schema and seeds the five issues once per test
session.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_TMP_DB = Path(tempfile.mkdtemp(prefix="repocrew-test-")) / "repocrew-test.db"
os.environ["RC_DB_PATH"] = str(_TMP_DB)
os.environ["RC_MODE"] = "demo"
os.environ["RC_DEMO_SPEED"] = "fast"

import pytest  # noqa: E402

from backend.database import init_db  # noqa: E402
from backend.seed import seed_issues  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _fresh_db():
    init_db()
    seed_issues()
    yield
