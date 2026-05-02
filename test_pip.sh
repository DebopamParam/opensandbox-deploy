#!/usr/bin/env bash
# test_pip.sh — build the base image, start the server, run pip install tests, tear down.
set -euo pipefail
cd "$(dirname "$0")"

export PATH="$HOME/.local/bin:$PATH"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED="\033[31m"; GREEN="\033[32m"; YELLOW="\033[33m"; BLUE="\033[34m"
BOLD="\033[1m"; DIM="\033[2m"; RESET="\033[0m"
info()    { echo -e "${BLUE}▶${RESET}  $*"; }
success() { echo -e "${GREEN}✓${RESET}  $*"; }
warn()    { echo -e "${YELLOW}⚠${RESET}  $*"; }
die()     { echo -e "${RED}✗${RESET}  $*" >&2; exit 1; }

echo -e "${BOLD}=== OpenSandbox Pip Install Test ===${RESET}"
echo

# ─── 1. Load .env ─────────────────────────────────────────────────────────────
[[ -f .env ]] || die ".env not found. Copy .env.example → .env and fill in values."
set -a; source .env; set +a

SANDBOX_PORT="${SANDBOX_PORT:-8080}"
SANDBOX_API_KEY="${SANDBOX_API_KEY:-}"
SANDBOX_LOG_LEVEL="${SANDBOX_LOG_LEVEL:-INFO}"
SANDBOX_IMAGE="${SANDBOX_IMAGE:-opensandbox-base:latest}"

# ─── 2. Detect environment (macOS vs GCP/Linux) ───────────────────────────────
OS="$(uname -s)"
if [[ "$OS" == "Darwin" ]]; then
    ENV_NAME="macos"
    CONFIG_TEMPLATE="configs/macos.sandbox.toml"
else
    ENV_NAME="gcp"
    CONFIG_TEMPLATE="configs/gcp-gvisor.sandbox.toml"
fi
USE_PROXY_FLAG="--use-server-proxy"
info "Environment: ${ENV_NAME} (${OS})"

# ─── 3. Find the server binary ────────────────────────────────────────────────
if [[ -x ".venv/bin/opensandbox-server" ]]; then
    SERVER=".venv/bin/opensandbox-server"
elif command -v opensandbox-server &>/dev/null; then
    SERVER="opensandbox-server"
else
    die "opensandbox-server not found.\n\n  Install with:  pip install opensandbox-server\n  or activate the project venv."
fi
info "Server binary: ${SERVER}"

# ─── 4. Build the base image (if not present or if Dockerfile changed) ────────
IMAGE_TAG="opensandbox-base:latest"
if ! docker image inspect "$IMAGE_TAG" &>/dev/null; then
    info "Image ${IMAGE_TAG} not found — building..."
    docker build -f images/Dockerfile.base -t "$IMAGE_TAG" . \
        || die "Docker build failed."
    success "Image built: ${IMAGE_TAG}"
else
    info "Using existing image: ${IMAGE_TAG}"
    echo -e "  ${DIM}(run 'docker build -f images/Dockerfile.base -t ${IMAGE_TAG} .' to rebuild)${RESET}"
fi
echo

# ─── 5. Render server config ──────────────────────────────────────────────────
RENDERED="$HOME/.sandbox.toml"
TEMPLATE="$CONFIG_TEMPLATE"
[[ -f "$TEMPLATE" ]] || die "Config template not found: ${TEMPLATE}"

sed \
    -e "s|{{SANDBOX_PORT}}|${SANDBOX_PORT}|g" \
    -e "s|{{SANDBOX_LOG_LEVEL}}|${SANDBOX_LOG_LEVEL}|g" \
    -e "s|{{SANDBOX_API_KEY}}|${SANDBOX_API_KEY}|g" \
    "$TEMPLATE" > "$RENDERED"
info "Config written: ${RENDERED}"

# ─── 6. Export egress rules if configured ─────────────────────────────────────
if [[ -n "${SANDBOX_EGRESS_RULES:-}" ]]; then
    export OPENSANDBOX_EGRESS_RULES="$SANDBOX_EGRESS_RULES"
    info "Egress rules: $(echo "$OPENSANDBOX_EGRESS_RULES" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(f"defaultAction={d[\"defaultAction\"]}, {len(d.get(\"egress\",[]))} rule(s)")')"
fi
echo

# ─── 7. Start the server ──────────────────────────────────────────────────────
info "Starting server on port ${SANDBOX_PORT}..."
SERVER_LOG="$(mktemp /tmp/opensandbox-server-XXXXXX.log)"
"$SERVER" >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

cleanup() {
    echo
    info "Stopping server (PID ${SERVER_PID})..."
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    success "Server stopped."
    if [[ "${SHOW_SERVER_LOG:-}" == "1" ]]; then
        echo
        echo -e "${DIM}── server log ──${RESET}"
        cat "$SERVER_LOG"
        echo -e "${DIM}────────────────${RESET}"
    fi
    rm -f "$SERVER_LOG"
}
trap cleanup EXIT

# ─── 8. Wait for server to be ready ──────────────────────────────────────────
READY_TIMEOUT="${READY_TIMEOUT:-30}"
info "Waiting up to ${READY_TIMEOUT}s for server to be ready..."

python3 - <<PYEOF
import socket, sys, time
host, port = "localhost", int("$SANDBOX_PORT")
deadline = time.monotonic() + int("$READY_TIMEOUT")
while time.monotonic() < deadline:
    try:
        s = socket.create_connection((host, port), timeout=1)
        s.close()
        print("  server is listening")
        sys.exit(0)
    except OSError:
        time.sleep(0.4)
print("  timeout: server did not start in time", file=sys.stderr)
sys.exit(1)
PYEOF

# Give the server a moment to finish initializing after the port opens
sleep 1
success "Server ready at localhost:${SANDBOX_PORT}"
echo

# ─── 9. Run the pip install tests ─────────────────────────────────────────────
PYTHON="${PYTHON:-python3}"
DOMAIN="localhost:${SANDBOX_PORT}"

CMD=(
    "$PYTHON" tests/test_pip_install.py
    --domain  "$DOMAIN"
    --image   "$IMAGE_TAG"
    --ready-timeout "${SANDBOX_READY_TIMEOUT:-120}"
)

[[ -n "$SANDBOX_API_KEY" ]]  && CMD+=(--api-key "$SANDBOX_API_KEY")
[[ -n "$USE_PROXY_FLAG" ]]   && CMD+=("$USE_PROXY_FLAG")
[[ "${VERBOSE:-N}" =~ ^[Yy]$ ]] && CMD+=(-v)
[[ "${NO_COLOR:-N}" =~ ^[Yy]$ ]] && CMD+=(--no-color)

if [[ -n "${SKIP_TESTS:-}" ]]; then
    IFS=',' read -ra _skip <<< "$SKIP_TESTS"
    for t in "${_skip[@]}"; do CMD+=(--skip "$(echo "$t" | xargs)"); done
fi
if [[ -n "${ONLY_TESTS:-}" ]]; then
    IFS=',' read -ra _only <<< "$ONLY_TESTS"
    for t in "${_only[@]}"; do CMD+=(--only "$(echo "$t" | xargs)"); done
fi

echo -e "${BOLD}Executing: ${DIM}${CMD[*]}${RESET}"
echo

"${CMD[@]}"
EXIT_CODE=$?

echo
if [[ $EXIT_CODE -eq 0 ]]; then
    success "${BOLD}All pip install tests passed.${RESET}"
else
    warn "Some tests failed (exit code ${EXIT_CODE}). Run with SHOW_SERVER_LOG=1 to inspect server output."
fi

exit $EXIT_CODE
