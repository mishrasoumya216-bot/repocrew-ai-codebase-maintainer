#!/bin/bash
# RepoCrew EC2 bootstrap (paste into the instance's "User data" field at launch).
# Installs Docker, clones this repo, and runs it via the existing
# Dockerfile + docker-compose.yml — no code changes needed.
set -euo pipefail

REPO_URL="https://github.com/mishrasoumya216-bot/repocrew-ai-codebase-maintainer.git"
APP_DIR="/opt/repocrew"

apt-get update -y
apt-get install -y ca-certificates curl gnupg git

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable docker
systemctl start docker

mkdir -p "$APP_DIR"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone --depth 1 "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
docker compose up --build -d
