#!/bin/bash

PRESETS_FILE="presets.json"
SKIP_PROMPTS=false

echo -e "\033[1;34m=== OpenSandbox Server Test Runner ===\033[0m"

# ==========================================
# 1. Load Presets & Fast-Track Prompt
# ==========================================
if [[ -f "$PRESETS_FILE" ]]; then
    echo -e "\033[1;32mFound previous configuration ($PRESETS_FILE):\033[0m"
    
    # Safely extract JSON keys and export them as Bash variables
    eval $(python3 -c '
import json, shlex
try:
    with open("'$PRESETS_FILE'") as f:
        d = json.load(f)
        for k, v in d.items():
            if v is not None:
                print(f"export {k}={shlex.quote(str(v))}")
except Exception as e:
    print(f"echo Error loading presets: {e}")
')

    # Display the loaded configuration
    echo -e "  \033[1mDomain:\033[0m        ${DOMAIN}"
    echo -e "  \033[1mProtocol:\033[0m      ${PROTOCOL}"
    echo -e "  \033[1mAPI Key:\033[0m       ${API_KEY:-<none>}"
    echo -e "  \033[1mProxy:\033[0m         ${USE_PROXY}"
    echo -e "  \033[1mImage:\033[0m         ${IMAGE}"
    echo -e "  \033[1mTimeout:\033[0m       ${READY_TIMEOUT}s"
    echo -e "  \033[1mSkip Tests:\033[0m    ${SKIP_TESTS:-<none>}"
    echo -e "  \033[1mOnly Tests:\033[0m    ${ONLY_TESTS:-<none>}"
    echo

    read -p "Use these last settings and skip prompts? (Y/n) [Y]: " FAST_TRACK
    FAST_TRACK=${FAST_TRACK:-Y}

    if [[ "$FAST_TRACK" =~ ^[Yy]$ ]]; then
        SKIP_PROMPTS=true
    fi
fi

# ==========================================
# 2. Interactive Prompts (if not fast-tracked)
# ==========================================
if [ "$SKIP_PROMPTS" = false ]; then
    echo
    echo "Press [ENTER] to accept the default values (shown in brackets)."
    echo

    read -p "Domain (host:port) [${DOMAIN:-localhost:8080}]: " INPUT_DOMAIN
    export DOMAIN=${INPUT_DOMAIN:-${DOMAIN:-localhost:8080}}

    read -p "Protocol (http/https) [${PROTOCOL:-http}]: " INPUT_PROTOCOL
    export PROTOCOL=${INPUT_PROTOCOL:-${PROTOCOL:-http}}

    read -p "API Key (leave blank for none) [${API_KEY:-}]: " INPUT_API_KEY
    export API_KEY=${INPUT_API_KEY:-${API_KEY:-}}

    read -p "Use Server Proxy? (y/N) [${USE_PROXY:-N}]: " INPUT_USE_PROXY
    export USE_PROXY=${INPUT_USE_PROXY:-${USE_PROXY:-N}}

    read -p "Docker Image [${IMAGE:-python:3.13-slim}]: " INPUT_IMAGE
    export IMAGE=${INPUT_IMAGE:-${IMAGE:-python:3.13-slim}}

    read -p "Ready Timeout in seconds [${READY_TIMEOUT:-60}]: " INPUT_READY_TIMEOUT
    export READY_TIMEOUT=${INPUT_READY_TIMEOUT:-${READY_TIMEOUT:-60}}

    read -p "Tests to SKIP (comma-separated) [${SKIP_TESTS:-}]: " INPUT_SKIP_TESTS
    export SKIP_TESTS=${INPUT_SKIP_TESTS:-${SKIP_TESTS:-}}

    read -p "Tests to run ONLY (comma-separated) [${ONLY_TESTS:-}]: " INPUT_ONLY_TESTS
    export ONLY_TESTS=${INPUT_ONLY_TESTS:-${ONLY_TESTS:-}}

    read -p "Enable verbose error outputs? (y/N) [${VERBOSE:-N}]: " INPUT_VERBOSE
    export VERBOSE=${INPUT_VERBOSE:-${VERBOSE:-N}}

    read -p "Disable colored terminal output? (y/N) [${NO_COLOR:-N}]: " INPUT_NO_COLOR
    export NO_COLOR=${INPUT_NO_COLOR:-${NO_COLOR:-N}}

    # Save new presets
    python3 -c '
import json, os
data = {
    "DOMAIN": os.environ.get("DOMAIN", ""),
    "PROTOCOL": os.environ.get("PROTOCOL", ""),
    "API_KEY": os.environ.get("API_KEY", ""),
    "USE_PROXY": os.environ.get("USE_PROXY", ""),
    "IMAGE": os.environ.get("IMAGE", ""),
    "READY_TIMEOUT": os.environ.get("READY_TIMEOUT", ""),
    "SKIP_TESTS": os.environ.get("SKIP_TESTS", ""),
    "ONLY_TESTS": os.environ.get("ONLY_TESTS", ""),
    "VERBOSE": os.environ.get("VERBOSE", ""),
    "NO_COLOR": os.environ.get("NO_COLOR", "")
}
with open("'$PRESETS_FILE'", "w") as f:
    json.dump(data, f, indent=4)
'
    echo
    echo -e "\033[1;32m✓ Saved current configuration to $PRESETS_FILE\033[0m"
fi

# ==========================================
# 3. Build and Execute Command
# ==========================================
# UPDATED FILENAME HERE
CMD=(python3 tests/test_functioning.py)

CMD+=(--domain "$DOMAIN")
CMD+=(--protocol "$PROTOCOL")
CMD+=(--image "$IMAGE")
CMD+=(--ready-timeout "$READY_TIMEOUT")

if [[ -n "$API_KEY" ]]; then
    CMD+=(--api-key "$API_KEY")
fi

if [[ "$USE_PROXY" =~ ^[Yy]$ ]]; then
    CMD+=(--use-server-proxy)
fi

if [[ "$VERBOSE" =~ ^[Yy]$ ]]; then
    CMD+=(-v)
fi

if [[ "$NO_COLOR" =~ ^[Yy]$ ]]; then
    CMD+=(--no-color)
fi

if [[ -n "$SKIP_TESTS" ]]; then
    IFS=',' read -ra ADDR <<< "$SKIP_TESTS"
    for test_name in "${ADDR[@]}"; do
        CMD+=(--skip "$(echo "$test_name" | xargs)")
    done
fi

if [[ -n "$ONLY_TESTS" ]]; then
    IFS=',' read -ra ADDR <<< "$ONLY_TESTS"
    for test_name in "${ADDR[@]}"; do
        CMD+=(--only "$(echo "$test_name" | xargs)")
    done
fi

echo
echo -e "\033[1;33m======================================\033[0m"
echo -e "Executing: \033[1;36m${CMD[*]}\033[0m"
echo -e "\033[1;33m======================================\033[0m"
echo

# Execute
"${CMD[@]}"