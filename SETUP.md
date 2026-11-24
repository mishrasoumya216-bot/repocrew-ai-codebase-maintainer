# RepoCrew setup

Prerequisites: **Python 3.11+**, **Node.js 18+**, optionally **Docker Desktop**
(for full sandbox isolation). Works on Windows 11 (PowerShell), macOS and Linux.

## Windows 11 (PowerShell) — from the repo root

```powershell
# 1. Backend environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt

# 2. Frontend
cd frontend
npm install
npm run build
cd ..

# 3. Sandbox image (optional but recommended)
docker build -t repocrew-sandbox .\sandbox

# 4. Configure (optional — demo mode needs nothing)
copy .env.example .env

# 5. Run everything (serves API + UI on http://localhost:8000)
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Or just run the one-shot script that does all of the above:

```powershell
.\run.ps1
```

Frontend dev mode with hot reload (in a second terminal):

```powershell
cd frontend
npm run dev    # http://localhost:5173, proxies /api and /ws to :8000
```

## macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build && cd ..
docker build -t repocrew-sandbox ./sandbox   # optional
cp .env.example .env                          # optional
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Or simply:

```bash
./run.sh
```

## Without Docker

Everything works — the Tester still applies patches to a fresh temp copy and
runs real pytest with a 60s timeout, but runs are **not isolated**. The UI
shows a yellow badge: *"Docker not found: running in local fallback (NOT
isolated)"*. With the `repocrew-sandbox` image present it shows a green
*"Sandbox: Docker isolated"* badge instead.

## Backend tests

```powershell
# PowerShell
.\.venv\Scripts\python -m pytest backend\tests -q
```

```bash
# macOS/Linux
.venv/bin/python -m pytest backend/tests -q
```

## Live mode (real Claude agents)

Set `RC_MODE=live`, `ANTHROPIC_API_KEY=...` and optionally `RC_MODEL` in `.env`,
then restart. Each agent runs a real tool-use loop (12 tool-step cap); the
Tester is unchanged — always real pytest in the sandbox.
