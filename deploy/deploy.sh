#!/usr/bin/env bash
# ============================================================================
# Deploy / redeploy the app on the VM. Run from the repo root on the VM:
#
#     ./deploy/deploy.sh
#
# It:
#   1. git pulls the latest code
#   2. rebuilds the Docker image
#   3. restarts the stack with zero state loss (named volume preserved)
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.production.example to .env and fill it in."
  exit 1
fi

echo "==> Pulling latest code..."
git pull --ff-only

echo "==> Building image (this can take a few minutes the first time)..."
docker compose build app

echo "==> Restarting stack..."
docker compose up -d --remove-orphans

echo
echo "==> Status:"
docker compose ps
echo
echo "==> Tailing app logs (Ctrl+C to detach; the app keeps running)..."
docker compose logs -f --tail=50 app
