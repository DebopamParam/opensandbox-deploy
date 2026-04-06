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
if [ -d ".venv" ]; then
  echo "    .venv already exists, skipping creation."
else
  uv venv .venv
fi

echo "==> Installing opensandbox-server + SDK into .venv..."
uv pip install --python .venv/bin/python opensandbox-server opensandbox opensandbox-code-interpreter

echo "==> Building custom sandbox base image..."
docker build -t opensandbox-base:latest -f images/Dockerfile.base .

echo "==> Updating configuration files to use the custom image..."
for CONF_FILE in env.example .env.example .env; do
  if [ -f "$CONF_FILE" ]; then
    sed -i.bak 's|SANDBOX_IMAGE=.*|SANDBOX_IMAGE=opensandbox-base:latest|' "$CONF_FILE"
    rm -f "${CONF_FILE}.bak"
    echo "    Updated $CONF_FILE"
  fi
done

echo "==> Pulling execd image..."
docker pull opensandbox/execd:v1.0.10

echo ""
echo "Done. Next steps:"
echo "  1. Copy your config if you haven't: cp .env.example .env"
echo "  2. Edit .env (set SANDBOX_API_KEY)"
echo "  3. Run: ./scripts/start-server.sh macos"
echo "  4. Test: source .env && .venv/bin/python test-weasyprint.py"