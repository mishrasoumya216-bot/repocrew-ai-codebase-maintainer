# RepoCrew sandbox image: docker build -t repocrew-sandbox ./sandbox
# Isolated per-run environment for the Tester agent: pytest preinstalled,
# git required for `git apply` inside the container. Runtime flags in
# backend/sandbox.py add: --network none --memory 256m --cpus 0.5
# --pids-limit 128 --read-only --tmpfs /tmp --rm (60s hard timeout).
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest>=8.0

WORKDIR /work
CMD ["python", "-m", "pytest", "-q"]
