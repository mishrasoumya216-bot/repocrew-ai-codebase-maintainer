# Stage 1: Build Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend runtime
FROM python:3.12-slim

# Install system dependencies (git is needed for diff application and sandbox fallbacks)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI only (talks to the HOST daemon over the socket mounted by
# docker-compose.yml; no local daemon needed here). Without this binary the
# Tester silently falls back to the unisolated local sandbox even though the
# host socket is mounted, since probe_docker() just checks `which docker`.
COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend code, sample repository, sandbox build context, and built frontend.
# sandbox/ must be present so probe_docker() can build the repocrew-sandbox
# image (via the host daemon) the first time this container starts.
COPY backend/ ./backend/
COPY sample_repo/ ./sample_repo/
COPY sandbox/ ./sandbox/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist
COPY .env.example ./

ENV PYTHONUNBUFFERED=1 \
    RC_MODE=demo \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
