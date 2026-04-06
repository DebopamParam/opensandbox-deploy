#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Stopping opensandbox-server if running..."
pkill -f "opensandbox.server" 2>/dev/null && echo "    server stopped" || echo "    not running"
pkill -f "opensandbox_server" 2>/dev/null || true

echo "==> Killing all OpenSandbox-managed containers..."
SANDBOX_CONTAINERS=$(docker ps -a --filter "label=opensandbox" -q 2>/dev/null || true)
if [[ -z "$SANDBOX_CONTAINERS" ]]; then
  SANDBOX_CONTAINERS=$(docker ps -a -q --format '{{.ID}}' 2>/dev/null | while read cid; do
    docker inspect "$cid" --format '{{.Config.Labels}}' 2>/dev/null | grep -qi "sandbox" && echo "$cid"
  done || true)
fi
if [[ -z "$SANDBOX_CONTAINERS" ]]; then
  SANDBOX_CONTAINERS=$(docker ps -q 2>/dev/null | while read cid; do
    docker exec "$cid" sh -c 'ss -tlnp 2>/dev/null | grep -q 44772' 2>/dev/null && echo "$cid"
  done || true)
fi
if [[ -n "$SANDBOX_CONTAINERS" ]]; then
  echo "    found containers: $SANDBOX_CONTAINERS"
  echo "$SANDBOX_CONTAINERS" | xargs docker rm -f 2>/dev/null || true
else
  echo "    no sandbox containers found"
fi

echo "==> Removing project venv..."
rm -rf .venv

echo "==> Removing rendered config..."
rm -f "$HOME/.sandbox.toml"

echo "==> Removing Docker images..."
source .env 2>/dev/null || true
for img in \
  "opensandbox/execd:v1.0.6" \
  "opensandbox/egress:v1.0.1" \
  "${SANDBOX_IMAGE:-}"; do
  if [[ -n "$img" ]] && docker image inspect "$img" &>/dev/null; then
    echo "    docker rmi $img"
    docker rmi "$img" 2>/dev/null || true
  fi
done

echo "==> Pruning dangling images from sandbox builds..."
docker image prune -f 2>/dev/null || true

echo ""
echo "Done. Remaining artifacts:"
echo "  - Docker engine itself (OrbStack) — untouched"
echo "  - uv binary — untouched (system tool)"
echo "  - This folder: rm -rf $(pwd)"