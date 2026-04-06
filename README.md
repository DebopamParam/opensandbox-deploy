# opensandbox-deploy

Scripts to run [OpenSandbox](https://github.com/alibaba/OpenSandbox) (Alibaba, Apache 2.0) in two environments:

| Environment | Runtime | Isolation | Use case |
|-------------|---------|-----------|----------|
| **macOS** (OrbStack) | `runc` | Process-level | Local dev |
| **GCP VM** (Ubuntu) | `gVisor/runsc` | Userspace kernel | Production |

Both support **local Docker images** and **Docker Hub / GHCR images** — set `SANDBOX_IMAGE` in `.env`.

## Quick Start

### macOS

```bash
./scripts/setup-macos.sh        # install server + SDK
cp .env.example .env && $EDITOR .env
./scripts/start-server.sh macos  # starts on :8080
# in another terminal:
source .env && uv run python test-sandbox.py
```

### GCP VM

```bash
# scp this repo to the VM, then SSH in:
./scripts/setup-gcp.sh          # install docker, gVisor, server
# log out/in if prompted for docker group
cp .env.example .env && $EDITOR .env
./scripts/start-server.sh gcp   # starts on :8080 with gVisor
source .env && uv run python test-sandbox.py
```

### Using a custom local image

```bash
docker build -t my-sandbox:latest -f images/Dockerfile.example .
# set SANDBOX_IMAGE=my-sandbox:latest in .env
```

## File structure

```
.env.example                 # config template
configs/
  macos.sandbox.toml         # server config (runc)
  gcp-gvisor.sandbox.toml    # server config (gVisor)
scripts/
  setup-macos.sh             # one-time macOS setup
  setup-gcp.sh               # one-time GCP VM setup
  start-server.sh <env>      # renders config + starts server
images/
  Dockerfile.example         # example custom sandbox image
test-sandbox.py              # smoke test
```

## Key env vars (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_API_KEY` | `change-me...` | Server auth key |
| `SANDBOX_IMAGE` | `python:3.11-slim` | Image for sandboxes (local or remote) |
| `SANDBOX_PORT` | `8080` | Server port |
| `SANDBOX_CPU` | `1` | CPU limit per sandbox |
| `SANDBOX_MEMORY` | `512Mi` | Memory limit per sandbox |
| `SANDBOX_TIMEOUT` | `1800` | Sandbox TTL in seconds |

## Links

- [OpenSandbox GitHub](https://github.com/alibaba/OpenSandbox)
- [Secure Container Runtime Guide](https://github.com/alibaba/OpenSandbox/blob/main/docs/secure-container.md)
- [Server README](https://github.com/alibaba/OpenSandbox/blob/main/server/README.md)
- [Python SDK](https://pypi.org/project/opensandbox/)
