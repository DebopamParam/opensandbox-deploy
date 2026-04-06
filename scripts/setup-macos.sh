#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Checking Docker (OrbStack)..."
if ! docker version &>/dev/null; then
  echo "ERROR: Docker not reachable. Is OrbStack running?"
  exit 1
fi
echo "    Docker OK: $(docker info --format '{{.ServerVersion}}' 2>/dev/null)"

echo "==> Creating project-local venv..."
uv venv .venv

echo "==> Installing opensandbox-server + SDK into .venv..."
uv pip install --python .venv/bin/python opensandbox-server opensandbox opensandbox-code-interpreter

echo "==> Pulling execd image..."
docker pull opensandbox/execd:v1.0.6

echo ""
echo "Done. Next steps:"
echo "  1. Edit .env (set SANDBOX_API_KEY, SANDBOX_IMAGE)"
echo "  2. If using a local image: docker build -t my-sandbox:latest -f images/Dockerfile.example ."
echo "  3. Run: ./scripts/start-server.sh macos"
echo "  4. Test: .venv/bin/python test-sandbox.py"