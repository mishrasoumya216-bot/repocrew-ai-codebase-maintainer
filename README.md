# RepoCrew

**RepoCrew is an AI junior maintainer for GitHub repositories.** It turns GitHub issues
into **tested, reviewed pull requests** — with a human maintainer always making the
final merge decision. RepoCrew **never merges anything** and contains no merge code anywhere.

```
Intake -> Triage -> Coder -> Tester (real sandbox) -> Reviewer -> Safety Gate
       -> Human approval -> Pull request
```

The Coder <-> Tester/Reviewer feedback loop retries with concrete test and reviewer
diagnostics, capped at a **hard limit of 3 attempts**. If the attempt limit is hit,
the run stops in `STOPPED_NEEDS_HUMAN` with a structured summary of what was learned.

---

## Architecture

```
                +-------------------------- RepoCrew ---------------------------+
                |                                                                |
 GitHub webhook |   +-------------+     in-process asyncio queue (runs)          |
  or UI trigger |   |  React+Vite | <--- WebSocket /ws/runs/{id} ----------------+--.
       |        |   |  frontend   |       SSE /api/stream / REST /api/*          |  |
       v        |   +------+------+                                              |  |
  POST /trigger |          |                                                     |  |
       |        |          v                                                     |  |
       |        |   +------------------------------------------------------+     |  |
       |        |   |                 ORCHESTRATOR                         |     |  |
       |        |   |  passes context between agents, enforces 3-attempt   |     |  |
       |        |   |  limit, records every event, broadcasts over WS/SSE  |     |  |
       |        |   +----+-------+-------+----------+-----------+----------+     |  |
       |        |        |       |       |          |           |                |  |
       |        |        v       v       v          v           v                |  |
       |        |   +-------+ +------+ +--------+ +---------+ +------+           |  |
       |        |   |Triage | |Coder | | Tester | |Reviewer | |Gate  |           |  |
       |        |   |gate   | |guard-| |(ALWAYS | |indep-   | |score |           |  |
       |        |   |scope  | |rails | |  REAL) | |endent)  | |+block|           |  |
       |        |   +-------+ +------+ +----+---+ +---------+ +--+---+           |  |
       |        |                            |                     |             |  |
       |        |                            v                     v             |  |
       |        |              +--------------------------+  allowed?            |  |
       |        |              |  SANDBOX (Docker image   |      |               |  |
       |        |              |  repocrew-sandbox:       |      v               |  |
       |        |              |  --network none, 256MB,  |  AWAITING_HUMAN --+  |  |
       |        |              |  0.5 CPU, read-only,     |      | Approve    |  |  |
       |        |              |  tmpfs /tmp, 60s, --rm)  |      v            |  |  |
       |        |              +--------------------------+  PR via GitHub API / |  |
       |        |                                            PR preview + .patch v  |
       |        |   storage: SQLite repocrew.db (WAL mode, Postgres-compatible)  |  |
       |        +----------------------------------------------------------------+--+
       v
  sample_repo (miniutils package - seeded bugs, pytest suite, CI config)
```

### Modules and Code Organization

| Module | File(s) | Description |
| --- | --- | --- |
| **Orchestrator** | `backend/orchestrator.py` | State machine, retry limit enforcement, event recording, approve/reject handlers |
| **Agents** | `backend/agents.py`, `backend/llm.py` | Triage, Coder, Tester, Reviewer implementations (deterministic demo vs. live Claude tool-use) |
| **Sandbox** | `backend/sandbox.py`, `sandbox/Dockerfile` | Isolated Docker execution (`--network none`, 256MB limit, read-only) with local subprocess fallback |
| **Safety Gate** | `backend/safety_gate.py` | Deterministic guardrails: max 3 files, ~40 lines, blocked CI paths, test integrity |
| **Database** | `backend/database.py`, `backend/models.py` | SQLAlchemy models, SQLite thread-safe WAL configuration, Postgres-compatible schema |
| **API & Events** | `backend/main.py`, `backend/events.py` | FastAPI endpoints, SSE stream (`/api/stream`), WebSocket (`/ws/runs/{id}`), GitHub webhooks |
| **Frontend** | `frontend/src/` | React 18, Vite, TypeScript, Tailwind CSS dashboard |

---

## Setup From Scratch

### Prerequisites
- Python 3.11+ (Python 3.12 recommended)
- Node.js 18+ and npm
- Docker (optional; enables sandbox isolation, otherwise safe local fallback is used)

### 1. Clone & Configure
```bash
cp .env.example .env
```

### 2. Backend Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. Frontend Setup
```bash
cd frontend
npm ci
npm run build
cd ..
```

### 4. Run Locally
Start the backend (which also serves the compiled frontend on `http://127.0.0.1:8000`):
```bash
source .venv/bin/activate
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```
Or start dev mode using the helper script:
```bash
./run.sh
```

---

## Environment Variables

All variables are configured via `.env` (see `.env.example`):

| Variable | Default | Description |
| --- | --- | --- |
| `RC_MODE` | `demo` | `demo` (scripted trajectories, real pytest) or `live` (Claude agents) |
| `ANTHROPIC_API_KEY` | *(empty)* | Anthropic API key (required only for `RC_MODE=live`) |
| `RC_MODEL` | `claude-sonnet-5-5` | LLM model identifier for live agents |
| `RC_DEMO_SPEED` | `normal` | `normal` (realistic pacing) or `fast` (instant test execution) |
| `GITHUB_TOKEN` | *(empty)* | Optional: GitHub personal access token for opening real pull requests |
| `RC_GITHUB_REPO` | *(empty)* | Target GitHub repository (`owner/name`) for PR creation |
| `GITHUB_WEBHOOK_SECRET` | *(empty)* | Secret for validating incoming GitHub webhook HMAC-SHA256 signatures |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated list of allowed origins (never wildcard in production) |
| `VITE_API_URL` | *(empty)* | Base URL for the backend API (leave empty for same-origin) |

---

## Running Tests

Run the full pytest suite with coverage:
```bash
.venv/bin/python -m pytest backend/tests -v --cov=backend
```

All 50 unit and integration tests execute offline with zero external network access:
- **Coder Guardrails**: Maximum 3 files, ~40 changed lines, snippet must match once, no test/CI edits.
- **Triage Gate**: In-scope issues proceed; out-of-scope issues exit cleanly with handback comment.
- **Sandbox**: Patch application, test failures, regression detection, malformed patch handling.
- **Reviewer**: Mandatory rejection if any test assertions or test lines are deleted.
- **Webhook**: Missing, invalid, and valid HMAC-SHA256 signatures, duplicate delivery idempotency.
- **API Robustness**: 404s on unknown IDs, 422s on invalid types, huge payloads, SSE streaming.
- **Zero Merge Policy**: Asserts complete absence of merge functionality across all source code.

---

## Deployment

### Using Docker Compose
```bash
docker compose up --build -d
```
The container builds the frontend in a multi-stage process and runs the FastAPI backend on port 8000.

### Health Check Endpoint
- `GET /health` or `GET /api/health`
```json
{
  "status": "ok",
  "service": "RepoCrew",
  "mode": "demo",
  "model": "claude-sonnet-5-5",
  "sandbox": {
    "available": true,
    "isolated": true,
    "engine": "docker",
    "image": "repocrew-sandbox:latest",
    "message": "Docker available; sandbox runs are isolated."
  },
  "github_configured": false
}
```

---

## Known Limitations & Design Stance

1. **Human Always Decides**: RepoCrew will never merge code automatically. Even when every test passes and the reviewer approves, the PR remains in `AWAITING_HUMAN` status.
2. **Deterministic Code Guardrails**: Agent prompts are backed by Python-level enforcement. If an LLM hallucinates an edit to a workflow file or deletes a test, the gate terminates or rejects the patch.
3. **Sandbox Fallback**: When Docker is not installed on the host, RepoCrew runs pytest in a temporary local workspace with subprocess timeouts (`TEST_TIMEOUT_SECONDS`). For production deployments, Docker or a microVM hypervisor (e.g., Firecracker / gVisor) is recommended.
