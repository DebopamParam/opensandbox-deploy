#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

ENV=${1:-}
if [[ -z "$ENV" ]]; then
  echo "Usage: ./scripts/start-server.sh <macos|gcp>"
  exit 1
fi

# Load .env
set -a
source .env
set +a

# Pick template
case "$ENV" in
  macos) TEMPLATE="configs/macos.sandbox.toml" ;;
  gcp)   TEMPLATE="configs/gcp-gvisor.sandbox.toml" ;;
  *)     echo "Unknown env: $ENV (use macos or gcp)"; exit 1 ;;
esac

# Render template → ~/.sandbox.toml
RENDERED="$HOME/.sandbox.toml"
sed \
  -e "s|{{SANDBOX_PORT}}|${SANDBOX_PORT:-8080}|g" \
  -e "s|{{SANDBOX_LOG_LEVEL}}|${SANDBOX_LOG_LEVEL:-INFO}|g" \
  -e "s|{{SANDBOX_API_KEY}}|${SANDBOX_API_KEY}|g" \
  "$TEMPLATE" > "$RENDERED"

echo "Config written to $RENDERED (env=$ENV)"
echo "Image configured: ${SANDBOX_IMAGE}"

# If SANDBOX_IMAGE looks like a remote ref, pre-pull it
if [[ "$SANDBOX_IMAGE" == *"/"* ]] || [[ "$SANDBOX_IMAGE" == *":"* && "$SANDBOX_IMAGE" != *"localhost"* ]]; then
  if ! docker image inspect "$SANDBOX_IMAGE" &>/dev/null; then
    echo "Pulling image: $SANDBOX_IMAGE ..."
    docker pull "$SANDBOX_IMAGE"
  fi
fi

# Use project-local venv if present, else system
if [[ -x ".venv/bin/opensandbox-server" ]]; then
  SERVER=".venv/bin/opensandbox-server"
else
  SERVER="opensandbox-server"
fi

echo "Starting opensandbox-server on :${SANDBOX_PORT:-8080} ..."
exec "$SERVER"