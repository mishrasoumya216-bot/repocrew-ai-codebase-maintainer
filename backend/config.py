"""RepoCrew configuration.

All environment variables use the ``RC_`` prefix (plus the upstream
``ANTHROPIC_API_KEY`` and ``GITHUB_TOKEN`` secrets). No secrets are ever
hardcoded; everything is read from ``os.environ`` (optionally via a local
``.env`` file at the repository root).
"""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = BACKEND_DIR.parent
SAMPLE_REPO_DIR = ROOT_DIR / "sample_repo"
SANDBOX_DIR = ROOT_DIR / "sandbox"


def _load_dotenv() -> None:
    """Minimal .env loader (avoids a hard dependency at import time)."""
    env_path = ROOT_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# --- RepoCrew settings -------------------------------------------------------
RC_MODE = os.environ.get("RC_MODE", "demo").lower()  # "demo" (default) or "live"
RC_MODEL = os.environ.get("RC_MODEL", "claude-sonnet-5-5")
RC_DB_PATH = os.environ.get("RC_DB_PATH", str(ROOT_DIR / "repocrew.db"))
RC_DEMO_SPEED = os.environ.get("RC_DEMO_SPEED", "normal").lower()  # "fast" skips delays

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
RC_GITHUB_REPO = os.environ.get("RC_GITHUB_REPO", "")
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", os.environ.get("RC_WEBHOOK_SECRET", ""))
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

MAX_ATTEMPTS = 3              # hard retry limit between Coder and Tester/Reviewer
MAX_AGENT_TOOL_STEPS = 12     # tool-use cap per agent in live mode
TEST_TIMEOUT_SECONDS = 60     # hard timeout for sandboxed pytest runs
DOCKER_IMAGE = "repocrew-sandbox"

# RepoCrew never merges anything. There is intentionally no merge code anywhere.


def github_configured() -> bool:
    return bool(GITHUB_TOKEN and RC_GITHUB_REPO)

