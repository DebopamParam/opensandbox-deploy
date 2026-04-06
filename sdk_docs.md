# OpenSandbox Python SDK — Complete Reference

> Compiled from official OpenSandbox documentation at
> [mintlify.com/alibaba/OpenSandbox](https://www.mintlify.com/alibaba/OpenSandbox),
> [github.com/alibaba/OpenSandbox](https://github.com/alibaba/OpenSandbox),
> and [PyPI: opensandbox](https://pypi.org/project/opensandbox/).
>
> Last updated: April 2026

---

## Table of Contents

- [1. Installation](#1-installation)
- [2. Quick Start](#2-quick-start)
- [3. Connection Configuration](#3-connection-configuration)
- [4. Sandbox Lifecycle](#4-sandbox-lifecycle)
- [5. Command Execution](#5-command-execution)
- [6. File Operations](#6-file-operations)
- [7. Sandbox Management (Admin)](#7-sandbox-management-admin)
- [8. Networking](#8-networking)
- [9. System Metrics](#9-system-metrics)
- [10. Code Interpreter SDK](#10-code-interpreter-sdk)
- [11. Error Handling](#11-error-handling)
- [12. API Reference Summary](#12-api-reference-summary)
- [13. Environment Variables](#13-environment-variables)
- [14. Practical Notes & Gotchas](#14-practical-notes--gotchas)

---

## 1. Installation

### Base SDK (sandbox lifecycle, commands, files)

```bash
pip install opensandbox
# or
uv add opensandbox
```

### Code Interpreter SDK (multi-language code execution with state)

```bash
pip install opensandbox-code-interpreter
# or
uv add opensandbox-code-interpreter
```

Both are pure Python, async-first with a sync wrapper available.

---

## 2. Quick Start

### Async (recommended)

```python
import asyncio
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.exceptions import SandboxException

async def main():
    config = ConnectionConfig(
        domain="localhost:8080",
        api_key="your-api-key",
        use_server_proxy=True,       # Required on macOS / Docker bridge
    )

    try:
        sandbox = await Sandbox.create(
            "python:3.13-slim",
            connection_config=config,
            entrypoint=["sleep", "infinity"],  # keeps container alive
        )
        async with sandbox:
            execution = await sandbox.commands.run("echo 'Hello Sandbox!'")
            print(execution.logs.stdout[0].text)
            await sandbox.kill()

    except SandboxException as e:
        print(f"Sandbox Error: [{e.error.code}] {e.error.message}")

asyncio.run(main())
```

### Sync

```python
from datetime import timedelta
import httpx
from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync

config = ConnectionConfigSync(
    domain="localhost:8080",
    api_key="your-api-key",
    request_timeout=timedelta(seconds=30),
    transport=httpx.HTTPTransport(limits=httpx.Limits(max_connections=20)),
)

sandbox = SandboxSync.create(
    "python:3.13-slim",
    connection_config=config,
    entrypoint=["sleep", "infinity"],
)
with sandbox:
    execution = sandbox.commands.run("echo 'Hello Sandbox!'")
    print(execution.logs.stdout[0].text)
    sandbox.kill()
```

---

## 3. Connection Configuration

### `ConnectionConfig` (async) / `ConnectionConfigSync` (sync)

| Parameter | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `api_key` | `str` | **required** | `OPEN_SANDBOX_API_KEY` | Server authentication key |
| `domain` | `str` | **required** | `OPEN_SANDBOX_DOMAIN` | Server host:port (e.g. `localhost:8080`) |
| `protocol` | `str` | `"http"` | — | `http` or `https` |
| `request_timeout` | `timedelta` | 30s | — | Timeout for API requests |
| `debug` | `bool` | `False` | — | Enable debug logging for HTTP requests |
| `headers` | `dict` | `{}` | — | Custom HTTP headers sent with every request |
| `transport` | `httpx.AsyncHTTPTransport` | SDK default | — | Shared httpx transport (pool/proxy/retry) |
| `use_server_proxy` | `bool` | `False` | — | Proxy execd requests through the server (required on macOS with bridge networking) |

#### Advanced: shared transport

When creating many `Sandbox` instances, share a single transport to avoid opening excessive connections:

```python
import httpx
from datetime import timedelta

config = ConnectionConfig(
    api_key="your-key",
    domain="localhost:8080",
    headers={"X-Custom-Header": "value"},
    transport=httpx.AsyncHTTPTransport(
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=50,
            keepalive_expiry=30.0,
        )
    ),
)
# If you provide a custom transport, close it yourself:
# await config.transport.aclose()
```

---

## 4. Sandbox Lifecycle

### States

| State | Description |
|---|---|
| **Pending** | Image pulling, execd injection, container starting |
| **Running** | Fully operational — accepts commands, code, files |
| **Pausing** | Transitional — stopping execution |
| **Paused** | Suspended — state preserved, no execution |
| **Stopping** | Transitional — being terminated |
| **Terminated** | Final — resources released (permanent) |
| **Failed** | Unrecoverable error during provisioning or execution |

### `Sandbox.create()` — Full Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `image` | `str` | **required** | Docker image URI |
| `connection_config` | `ConnectionConfig` | **required** | Connection settings |
| `timeout` | `timedelta` | 10 minutes | Auto-termination TTL (60s–24h) |
| `entrypoint` | `list[str]` | `["tail", "-f", "/dev/null"]` | Container entrypoint command |
| `resource` | `dict` | `{"cpu": "1", "memory": "2Gi"}` | CPU/memory limits (K8s notation) |
| `env` | `dict` | `{}` | Environment variables |
| `metadata` | `dict` | `{}` | Custom metadata tags |
| `network_policy` | `NetworkPolicy` | `None` | Outbound network rules |
| `health_check` | `Callable` | default ping | Custom health check function |
| `ready_timeout` | `timedelta` | 30s | Max wait for sandbox readiness |

### Lifecycle Operations

```python
from datetime import timedelta

# Create
sandbox = await Sandbox.create("python:3.13-slim", connection_config=config,
                                entrypoint=["sleep", "infinity"],
                                timeout=timedelta(minutes=30))

# Renew (reset expiration to now + duration)
await sandbox.renew(timedelta(minutes=30))

# Get info
info = await sandbox.get_info()
print(f"State: {info.status.state}")

# Pause (suspends all processes, state preserved)
await sandbox.pause()

# Resume
sandbox = await Sandbox.resume(
    sandbox_id=sandbox.id,
    connection_config=config,
)

# Kill (immediate termination)
await sandbox.kill()
```

### Custom Health Check

Override the default ping check to wait for your service to be ready:

```python
async def custom_health_check(sbx: Sandbox) -> bool:
    try:
        endpoint = await sbx.get_endpoint(80)
        # your connection check here
        return True
    except Exception:
        return False

sandbox = await Sandbox.create(
    "nginx:latest",
    connection_config=config,
    health_check=custom_health_check,
)
```

### Context Manager

```python
async with sandbox:
    # sandbox is usable here
    await sandbox.commands.run("echo hello")
# local resources cleaned up on exit (sandbox is NOT auto-killed)
# call sandbox.kill() explicitly to terminate the remote instance
```

---

## 5. Command Execution

Access via `sandbox.commands`.

### Foreground (blocking)

```python
result = await sandbox.commands.run(
    "pip install numpy pandas",
    working_dir="/workspace"
)
print(result.logs.stdout[0].text)
print(f"Exit code: {result.exit_code}")
```

### Background (detached)

```python
session = await sandbox.commands.run_background(
    "python train.py",
    working_dir="/workspace"
)

# Check later
status = await sandbox.commands.get_status(session)
if status.is_complete:
    output = await sandbox.commands.get_output(session)
    print(output.stdout)
```

### Streaming Output

```python
from opensandbox.models.execd import ExecutionHandlers

async def handle_stdout(msg):
    print(f"STDOUT: {msg.text}")

async def handle_stderr(msg):
    print(f"STDERR: {msg.text}")

async def handle_complete(complete):
    print(f"Done in {complete.execution_time_in_millis}ms")

handlers = ExecutionHandlers(
    on_stdout=handle_stdout,
    on_stderr=handle_stderr,
    on_execution_complete=handle_complete,
)

result = await sandbox.commands.run(
    "for i in {1..5}; do echo \"Count $i\"; sleep 0.5; done",
    handlers=handlers,
)
```

### Interruption

```python
import asyncio

task = asyncio.create_task(sandbox.commands.run("sleep 3600"))
await asyncio.sleep(5)
task.cancel()
```

---

## 6. File Operations

Access via `sandbox.files`.

### Write Files

```python
from opensandbox.models import WriteEntry
# or: from opensandbox.models.filesystem import WriteEntry

# Single or batch write
await sandbox.files.write_files([
    WriteEntry(path="/workspace/main.py", data="print('Hello')", mode=644),
    WriteEntry(path="/workspace/config.json", data='{"key": "value"}', mode=644),
])
```

### Read Files

```python
content = await sandbox.files.read_file("/workspace/output.txt")
print(content)
```

### Search Files

```python
from opensandbox.models.filesystem import SearchEntry

files = await sandbox.files.search(
    SearchEntry(path="/workspace", pattern="*.py")
)
for f in files:
    print(f.path)
```

### Delete Files

```python
await sandbox.files.delete_files(["/workspace/temp.txt"])
```

### File Metadata

```python
info = await sandbox.files.get_info("/workspace/script.py")
print(f"Size: {info.size}, Mode: {oct(info.mode)}, Owner: {info.owner}")
```

### Directory Operations

```python
# Create directory (with parents)
await sandbox.files.create_directory("/workspace/data", mode=0o755, parents=True)

# List directory
entries = await sandbox.files.list_directory("/workspace")
for entry in entries:
    print(f"{entry.name} ({'dir' if entry.is_directory else 'file'})")

# Delete directory
await sandbox.files.delete_directory("/workspace/temp", recursive=True)
```

### Permissions

```python
await sandbox.files.set_permissions("/workspace/run.sh", mode=0o755)
await sandbox.files.set_permissions("/workspace/data.txt", owner="user", group="users")
```

---

## 7. Sandbox Management (Admin)

Use `SandboxManager` for listing/managing multiple sandboxes:

```python
from opensandbox.manager import SandboxManager
from opensandbox.models.sandboxes import SandboxFilter

async with await SandboxManager.create(connection_config=config) as manager:
    sandboxes = await manager.list_sandbox_infos(
        SandboxFilter(states=["RUNNING"], page_size=10)
    )
    for info in sandboxes.sandbox_infos:
        print(f"Sandbox: {info.id}")
        await manager.kill_sandbox(info.id)
```

---

## 8. Networking

### Network Policies (Egress Control)

Restrict outbound access at sandbox creation:

```python
from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule

sandbox = await Sandbox.create(
    "python:3.13-slim",
    connection_config=config,
    entrypoint=["sleep", "infinity"],
    network_policy=NetworkPolicy(
        defaultAction="deny",
        egress=[
            NetworkRule(action="allow", target="pypi.org"),
            NetworkRule(action="allow", target="github.com"),
        ],
    ),
)
```

Requires `[egress] image = "opensandbox/egress:v1.0.1"` in server config and `network_mode = "bridge"`.

### Port Forwarding / Endpoints

```python
# Start a web server inside sandbox
await sandbox.commands.run("python -m http.server 8000", background=True)

# Get external endpoint
endpoint = await sandbox.get_endpoint(8000)
print(f"Access at: http://{endpoint.endpoint}")
```

### `use_server_proxy`

On macOS (OrbStack/Docker Desktop), the host cannot directly reach Docker bridge IPs. Set `use_server_proxy=True` in `ConnectionConfig` to route execd traffic through the opensandbox-server.

---

## 9. System Metrics

### Snapshot

```python
metrics = await sandbox.get_metrics()
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_used_in_mib} MiB / {metrics.memory_total_in_mib} MiB")
```

### Streaming

```python
async for metrics in sandbox.watch_metrics():
    print(f"CPU: {metrics.cpu_percent}% | Mem: {metrics.memory_percent}%")
    if metrics.memory_percent > 80:
        print("Warning: high memory")
        break
```

---

## 10. Code Interpreter SDK

Higher-level SDK for executing code with state persistence. Requires `opensandbox-code-interpreter` package and the `opensandbox/code-interpreter` Docker image.

### Setup

```python
from code_interpreter import CodeInterpreter, SupportedLanguage
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from datetime import timedelta

config = ConnectionConfig(domain="localhost:8080", api_key="your-key", use_server_proxy=True)

sandbox = await Sandbox.create(
    "opensandbox/code-interpreter:v1.0.1",
    connection_config=config,
    entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    env={
        "PYTHON_VERSION": "3.11",
        "JAVA_VERSION": "17",
        "NODE_VERSION": "20",
        "GO_VERSION": "1.24",
    },
    timeout=timedelta(minutes=30),
)
```

### Supported Languages

| Enum | Kernel | Version Env Var |
|---|---|---|
| `SupportedLanguage.PYTHON` | IPython | `PYTHON_VERSION` |
| `SupportedLanguage.JAVA` | IJava | `JAVA_VERSION` |
| `SupportedLanguage.GO` | Gophernotes | `GO_VERSION` |
| `SupportedLanguage.TYPESCRIPT` | ITypeScript | `NODE_VERSION` |
| `SupportedLanguage.JAVASCRIPT` | IJavaScript | `NODE_VERSION` |

### Creating Contexts & Running Code

```python
async with sandbox:
    interpreter = await CodeInterpreter.create(sandbox=sandbox)

    # Explicit context (state persists across runs)
    ctx = await interpreter.codes.create_context(SupportedLanguage.PYTHON)

    await interpreter.codes.run("x = 42", context=ctx)
    result = await interpreter.codes.run("result = x * 2\nresult", context=ctx)
    print(result.result[0].text)  # "84"

    await sandbox.kill()
```

### Default Context (no explicit create)

```python
# Omitting context= uses a default per-language session
result = await interpreter.codes.run(
    "result = 2 + 2\nresult",
    language=SupportedLanguage.PYTHON,
)
print(result.result[0].text)  # "4"

# State still persists within the default context
await interpreter.codes.run("x = 42", language=SupportedLanguage.PYTHON)
result = await interpreter.codes.run("result = x\nresult", language=SupportedLanguage.PYTHON)
print(result.result[0].text)  # "42"
```

### Multi-Language Isolation

```python
py_ctx = await interpreter.codes.create_context(SupportedLanguage.PYTHON)
go_ctx = await interpreter.codes.create_context(SupportedLanguage.GO)

await interpreter.codes.run("print('Python')", context=py_ctx)
await interpreter.codes.run(
    'package main\nfunc main() { println("Go") }',
    context=go_ctx,
)
```

### Java Example

```python
ctx = await interpreter.codes.create_context(SupportedLanguage.JAVA)
result = await interpreter.codes.run(
    'int a = 10;\nint b = 20;\nSystem.out.println("Sum: " + (a + b));\na + b',
    context=ctx,
)
for msg in result.logs.stdout:
    print(msg.text)
```

### TypeScript Example

```python
ctx = await interpreter.codes.create_context(SupportedLanguage.TYPESCRIPT)
result = await interpreter.codes.run(
    'const sum = (a: number, b: number): number => a + b;\nconsole.log(`Sum: ${sum(10, 20)}`);',
    context=ctx,
)
for msg in result.logs.stdout:
    print(msg.text)
```

### Streaming with Code Interpreter

```python
from opensandbox.models.execd import ExecutionHandlers

async def on_stdout(msg):
    print("STDOUT:", msg.text)

handlers = ExecutionHandlers(on_stdout=on_stdout)
ctx = await interpreter.codes.create_context(SupportedLanguage.PYTHON)

await interpreter.codes.run(
    "import time\nfor i in range(5):\n    print(i)\n    time.sleep(0.5)",
    context=ctx,
    handlers=handlers,
)
```

### Installing Packages at Runtime

```python
ctx = await interpreter.codes.create_context(SupportedLanguage.PYTHON)
await interpreter.codes.run(
    "import subprocess\nsubprocess.run(['pip', 'install', 'requests'])",
    context=ctx,
)
result = await interpreter.codes.run(
    "import requests\nresponse = requests.get('https://api.github.com')\nprint(f'Status: {response.status_code}')",
    context=ctx,
)
```

### Sync API

```python
from code_interpreter import CodeInterpreterSync
from opensandbox import SandboxSync
from opensandbox.config import ConnectionConfigSync

sandbox = SandboxSync.create(
    "opensandbox/code-interpreter:v1.0.1",
    connection_config=config,
    entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    env={"PYTHON_VERSION": "3.11"},
)
with sandbox:
    interpreter = CodeInterpreterSync.create(sandbox=sandbox)
    result = interpreter.codes.run("result = 2 + 2\nresult")
    print(result.result[0].text)  # "4"
    sandbox.kill()
```

### Code Interpreter vs Base SDK

| Feature | Code Interpreter SDK | Base Sandbox SDK |
|---|---|---|
| Use case | Execute code snippets in multiple languages | General-purpose sandbox operations |
| State persistence | Built-in | Manual |
| Multi-language | Python, Java, Go, TypeScript | Manual setup |
| Execution contexts | Isolated per language | N/A |
| File operations | Via underlying Sandbox | Full API |
| Command execution | Language-specific | Shell commands |

---

## 11. Error Handling

### Exception Hierarchy

```python
from opensandbox.exceptions import (
    SandboxException,         # Base exception
    SandboxNotFoundError,     # Sandbox ID doesn't exist
    SandboxTimeoutError,      # Operation timed out
    SandboxReadyTimeoutException,  # Health check timed out
)
```

### Usage

```python
try:
    sandbox = await Sandbox.create("ubuntu", connection_config=config)
    execution = await sandbox.commands.run("ls -la")
except SandboxTimeoutError as e:
    print(f"Timeout: {e.error.message}")
except SandboxNotFoundError as e:
    print(f"Not found: {e.error.message}")
except SandboxException as e:
    print(f"Error [{e.error.code}]: {e.error.message}")
```

### Common Error Codes from execd

| Code | Description | Solution |
|---|---|---|
| `EXECD_NOT_READY` | execd daemon not started yet | Wait and retry |
| `COMMAND_FAILED` | Non-zero exit code | Check exit code and stderr |
| `FILE_NOT_FOUND` | File path doesn't exist | Verify path |
| `PERMISSION_DENIED` | Insufficient permissions | Check file mode/ownership |
| `CONTEXT_NOT_FOUND` | Code execution context expired | Create a new context |
| `EXECUTION_TIMEOUT` | Code execution timed out | Increase timeout or optimize |

### Retry Pattern

```python
for attempt in range(3):
    try:
        sandbox = await Sandbox.create("python:3.11", connection_config=config)
        break
    except SandboxException:
        if attempt == 2:
            raise
        await asyncio.sleep(5)
```

---

## 12. API Reference Summary

### `Sandbox` Class

| Method/Property | Type | Description |
|---|---|---|
| `Sandbox.create(image, ...)` | classmethod (async) | Create and initialize a new sandbox |
| `Sandbox.resume(sandbox_id, ...)` | classmethod (async) | Resume a paused sandbox |
| `sandbox.commands` | property → `CommandsClient` | Command execution interface |
| `sandbox.files` | property → `FilesClient` | File system interface |
| `sandbox.renew(duration)` | async method | Extend expiration |
| `sandbox.pause()` | async method | Suspend all processes |
| `sandbox.kill()` | async method | Terminate immediately |
| `sandbox.get_info()` | async method → `SandboxInfo` | Current sandbox state/metadata |
| `sandbox.get_endpoint(port)` | async method → `SandboxEndpoint` | External endpoint for a port |
| `sandbox.get_metrics()` | async method | Current CPU/memory snapshot |
| `sandbox.watch_metrics()` | async generator | Streaming metrics via SSE |

### `CodeInterpreter` Class

| Method/Property | Type | Description |
|---|---|---|
| `CodeInterpreter.create(sandbox=...)` | classmethod (async) | Create interpreter from existing sandbox |
| `interpreter.codes` | property → `CodesClient` | Code execution interface |

### `CodesClient` Methods

| Method | Description |
|---|---|
| `create_context(language)` | Create isolated execution context |
| `run(code, context=, language=, handlers=)` | Execute code, returns `Execution` |

---

## 13. Environment Variables

| Variable | Description |
|---|---|
| `OPEN_SANDBOX_API_KEY` | Default API key (if not set in ConnectionConfig) |
| `OPEN_SANDBOX_DOMAIN` | Default domain (if not set in ConnectionConfig) |
| `SANDBOX_CONFIG_PATH` | Override server config file location |
| `DOCKER_HOST` | Docker daemon URL (e.g. `unix:///var/run/docker.sock`) |

---

## 14. Practical Notes & Gotchas

### Entrypoint must stay alive

The bootstrap script backgrounds `execd` then runs `exec "$@"` (your entrypoint) as PID 1. If PID 1 exits, the container dies and takes execd with it. Use `["sleep", "infinity"]` for generic images or the image's own long-running process (e.g. `/opt/opensandbox/code-interpreter.sh`).

### `use_server_proxy=True` on macOS

macOS cannot route to Docker bridge IPs. The SDK must proxy requests through the opensandbox-server, which reaches containers via the Docker socket. Set this in `ConnectionConfig`. On Linux (GCP), direct access works, but proxying is also fine.

### Resource limits use K8s notation

`"500m"` = 0.5 CPU, `"1"` = 1 core, `"512Mi"` = 512 MiB, `"4Gi"` = 4 GiB.

### `resourceLimits` is required in REST API

When using `curl` against the REST API directly, the `resourceLimits` field is mandatory. The SDK provides defaults.

### Network policy requires egress image

Egress control only works with `network_mode = "bridge"` and `[egress] image = "opensandbox/egress:v1.0.1"` in server config.

### Pause/resume limitations

Currently supported in Docker runtime only. Kubernetes support is planned.

### File write batching

Prefer `write_files([...])` over multiple `write_file()` calls — single network round-trip.

---

## Sources

- [Python SDK docs](https://www.mintlify.com/alibaba/OpenSandbox/sdks/python)
- [Code Interpreter SDK docs](https://www.mintlify.com/alibaba/OpenSandbox/sdks/code-interpreter)
- [SDK Overview](https://www.mintlify.com/alibaba/OpenSandbox/sdks/overview)
- [Execution API concepts](https://www.mintlify.com/alibaba/OpenSandbox/concepts/execution-api)
- [Sandbox Lifecycle](https://www.mintlify.com/alibaba/OpenSandbox/concepts/sandbox-lifecycle)
- [Networking](https://www.mintlify.com/alibaba/OpenSandbox/concepts/networking)
- [Docker Runtime Setup](https://www.mintlify.com/alibaba/OpenSandbox/deployment/docker-runtime)
- [Server README](https://github.com/alibaba/OpenSandbox/blob/main/server/README.md)
- [Secure Container Guide](https://github.com/alibaba/OpenSandbox/blob/main/docs/secure-container.md)
- [GitHub: alibaba/OpenSandbox](https://github.com/alibaba/OpenSandbox)