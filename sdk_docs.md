# OpenSandbox Python SDK — Complete Reference

---

## Table of Contents

- [1. Installation](#1-installation)
- [2. Quick Start](#2-quick-start)
- [3. Connection Configuration](#3-connection-configuration)
- [4. Sandbox Lifecycle](#4-sandbox-lifecycle)
- [5. Command Execution](#5-command-execution)
- [6. File Operations](#6-file-operations)
- [7. Sandbox Management (Admin)](#7-sandbox-management-admin)
- [8. Networking & Egress](#8-networking--egress)
- [9. Volumes & Storage](#9-volumes--storage)
- [10. System Metrics](#10-system-metrics)
- [11. Code Interpreter SDK](#11-code-interpreter-sdk)
- [12. Error Handling](#12-error-handling)
- [13. API Reference Summary](#13-api-reference-summary)

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
```

Both are pure Python, async-first with sync wrappers available in `opensandbox.sync`.

---

## 2. Quick Start

### Async (recommended)

```python
import asyncio
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig

async def main():
    config = ConnectionConfig(
        domain="localhost:8080",
        api_key="your-api-key",
        use_server_proxy=True,  # Required on macOS / Docker bridge
    )

    # Context manager automatically calls sandbox.close() (local cleanup)
    async with await Sandbox.create("python:3.13-slim", connection_config=config) as sandbox:
        try:
            # File ops
            await sandbox.files.write_file("/workspace/hello.py", "print('Hello Sandbox!')")
            
            # Command execution
            execution = await sandbox.commands.run("python /workspace/hello.py")
            print(execution.logs.stdout[0].text)
        
        finally:
            # You must explicitly kill the remote sandbox container
            await sandbox.kill()

asyncio.run(main())
```

---

## 3. Connection Configuration

### `ConnectionConfig` (async) / `ConnectionConfigSync` (sync)

| Parameter | Type | Default | Env Var | Description |
|---|---|---|---|---|
| `api_key` | `str` | `None` | `OPEN_SANDBOX_API_KEY` | Server authentication key |
| `domain` | `str` | `None` | `OPEN_SANDBOX_DOMAIN` | Server host:port (e.g., `localhost:8080`) |
| `protocol` | `str` | `"http"` | — | `http` or `https` |
| `request_timeout` | `timedelta` | 30s | — | Timeout for API requests |
| `use_server_proxy` | `bool` | `False` | — | Route execd traffic through the server (required on macOS with bridge networking) |

---

## 4. Sandbox Lifecycle

### States (`opensandbox.models.sandboxes.SandboxState`)

Values are Title Case: `"Pending"`, `"Running"`, `"Pausing"`, `"Paused"`, `"Stopping"`, `"Terminated"`, `"Failed"`.

### `Sandbox.create()` 

| Parameter | Type | Default | Description |
|---|---|---|---|
| `image` | `str` \| `SandboxImageSpec` | **required** | Docker image URI (can include private registry auth) |
| `connection_config`| `ConnectionConfig` | **required** | Connection settings |
| `timeout` | `timedelta` \| `None` | 10 minutes | Auto-termination TTL. Pass `None` for manual cleanup. |
| `entrypoint` | `list[str]` | `["tail", "-f", "/dev/null"]`| Container entrypoint command |
| `resource` | `dict[str, str]` | `{"cpu": "1", "memory": "2Gi"}` | CPU/memory limits (K8s notation) |
| `env` | `dict[str, str]` | `{}` | Environment variables |
| `volumes` | `list[Volume]` | `None` | Storage mounts (Host, PVC, or OSSFS) |
| `ready_timeout` | `timedelta` | 30s | Max wait for sandbox health check to pass |

### Lifecycle Operations

```python
from datetime import timedelta

# Get info
info = await sandbox.get_info()
print(f"State: {info.status.state}")  # e.g., "Running"

# Renew (adds duration to current time)
await sandbox.renew(timedelta(minutes=30))

# Pause (suspends processes, state preserved)
await sandbox.pause()

# Resume (Note: this is a classmethod that returns a NEW Sandbox instance)
sandbox = await Sandbox.resume(
    sandbox_id=sandbox.id,
    connection_config=config,
)

# Kill (immediate remote termination)
await sandbox.kill()
```

---

## 5. Command Execution

Access via `sandbox.commands`. 

### Foreground Execution

```python
from opensandbox.models.execd import RunCommandOpts

# Simple run
res = await sandbox.commands.run("echo 'Hello'")
print(res.exit_code) # 0
print(res.text)      # "Hello" (Combined stdout and result text)

# With options (Working Directory, Env, Timeout)
opts = RunCommandOpts(
    working_directory="/workspace",
    timeout=timedelta(seconds=10),
    envs={"CUSTOM_VAR": "123"}
)
res = await sandbox.commands.run("pwd && echo $CUSTOM_VAR", opts=opts)
```

### Background Execution

```python
# Pass background=True via RunCommandOpts
opts = RunCommandOpts(background=True)
res = await sandbox.commands.run("sleep 10 && echo 'Done'", opts=opts)

# res.id contains the execution_id for the background task
execution_id = res.id

# Check status
status = await sandbox.commands.get_command_status(execution_id)
if not status.running:
    print(f"Exit code: {status.exit_code}")

# Get logs (requires a cursor for incremental reads, or None for all)
logs = await sandbox.commands.get_background_command_logs(execution_id)
print(logs.content)
```

### Streaming Handlers (SSE)

```python
from opensandbox.models.execd import ExecutionHandlers

async def on_stdout(msg):
    print(f"STDOUT: {msg.text}")

handlers = ExecutionHandlers(on_stdout=on_stdout)
await sandbox.commands.run("for i in {1..3}; do echo $i; sleep 1; done", handlers=handlers)
```

### Stateful Sessions (Persistent Shell)

```python
session_id = await sandbox.commands.create_session(working_directory="/workspace")

await sandbox.commands.run_in_session(session_id, "export MY_VAR=apple")
res = await sandbox.commands.run_in_session(session_id, "echo $MY_VAR")
print(res.text)  # "apple"

await sandbox.commands.delete_session(session_id)
```

---

## 6. File Operations

Access via `sandbox.files`. 

### Write Files

```python
from opensandbox.models.filesystem import WriteEntry

# Write multiple files (efficient batch upload)
await sandbox.files.write_files([
    WriteEntry(path="/workspace/config.json", data='{"key": "value"}'),
    WriteEntry(path="/workspace/data.bin", data=b'\x00\x01\x02', mode=0o644),
])

# Write single file convenience method
await sandbox.files.write_file("/workspace/hello.txt", "Hello!")
```

### Read Files

```python
# As String
text = await sandbox.files.read_file("/workspace/hello.txt")

# As Bytes
data = await sandbox.files.read_bytes("/workspace/data.bin")

# Stream large files
async for chunk in sandbox.files.read_bytes_stream("/workspace/large.log"):
    process(chunk)
```

### Search & List Files

The SDK does not have a `list_directory` method. Use `search` with glob patterns.

```python
from opensandbox.models.filesystem import SearchEntry

# Find all python files
results = await sandbox.files.search(SearchEntry(path="/workspace", pattern="*.py"))
for info in results:
    print(f"{info.path} - {info.size} bytes")
```

### File Metadata

Retrieve metadata for multiple paths at once.

```python
info_map = await sandbox.files.get_file_info(["/workspace/script.py", "/workspace/data/"])

script_info = info_map.get("/workspace/script.py")
if script_info:
    print(f"Size: {script_info.size}, Mode: {oct(script_info.mode)}")
```

### Directories & Bulk Operations

**Note:** Deletion and creation methods require **lists** of paths/entries.

```python
# Create directories
await sandbox.files.create_directories([
    WriteEntry(path="/workspace/data/raw"),
    WriteEntry(path="/workspace/data/processed")
])

# Move/Rename
from opensandbox.models.filesystem import MoveEntry
await sandbox.files.move_files([
    MoveEntry(source="/workspace/old.txt", destination="/workspace/new.txt")
])

# Delete
await sandbox.files.delete_files(["/workspace/new.txt"])
await sandbox.files.delete_directories(["/workspace/data/raw"])
```

---

## 7. Sandbox Management (Admin)

Use `SandboxManager` for listing/managing multiple sandboxes from the server.

```python
from opensandbox.manager import SandboxManager
from opensandbox.models.sandboxes import SandboxFilter

async with await SandboxManager.create(connection_config=config) as manager:
    # List sandboxes
    page = await manager.list_sandbox_infos(
        SandboxFilter(states=["Running", "Paused"], page_size=50)
    )
    
    for info in page.sandbox_infos:
        print(f"ID: {info.id} | State: {info.status.state}")
        
        # Admin kill
        if info.status.state == "Failed":
            await manager.kill_sandbox(info.id)
```

---

## 8. Networking & Egress

### Network Policies

Restrict outbound access at sandbox creation (requires `network_mode="bridge"` and `[egress]` configured on the server).

```python
from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule

policy = NetworkPolicy(
    defaultAction="deny",
    egress=[
        NetworkRule(action="allow", target="pypi.org"),
        NetworkRule(action="allow", target="github.com"),
    ],
)

sandbox = await Sandbox.create(..., network_policy=policy)
```

### Endpoints (Port Forwarding)

```python
await sandbox.commands.run("python3 -m http.server 8000", opts=RunCommandOpts(background=True))

# Retrieve the external endpoint mapping
endpoint = await sandbox.get_endpoint(8000)
print(f"Access at: http://{endpoint.endpoint}")
```

---

## 9. Volumes & Storage

Mount persistent or host storage into the sandbox at creation.

```python
from opensandbox.models.sandboxes import Volume, Host, PVC, OSSFS

volumes = [
    # Host mount (requires server-side allowlist configuration)
    Volume(
        name="local-data",
        host=Host(path="/data/shared"),
        mount_path="/workspace/data",
        read_only=True
    ),
    
    # Kubernetes PersistentVolumeClaim
    Volume(
        name="k8s-models",
        pvc=PVC(claim_name="model-weights-pvc"),
        mount_path="/models"
    )
]

sandbox = await Sandbox.create(..., volumes=volumes)
```

---

## 10. System Metrics

```python
metrics = await sandbox.get_metrics()
print(f"CPU: {metrics.cpu_used_percentage}%")
print(f"Memory: {metrics.memory_used_in_mib} / {metrics.memory_total_in_mib} MiB")
```

---

## 11. Code Interpreter SDK

*(Requires `opensandbox-code-interpreter` package and `opensandbox/code-interpreter` Docker image)*

```python
from code_interpreter import CodeInterpreter, SupportedLanguage

async with sandbox:
    interpreter = await CodeInterpreter.create(sandbox=sandbox)

    # State persists across runs within a context
    ctx = await interpreter.codes.create_context(SupportedLanguage.PYTHON)
    await interpreter.codes.run("x = 42", context=ctx)
    res = await interpreter.codes.run("print(x * 2)", context=ctx)
    print(res.logs.stdout[0].text)  # "84"
```

---

## 12. Error Handling

### Hierarchy

```python
from opensandbox.exceptions import (
    SandboxException,              # Base
    SandboxApiException,           # HTTP 4xx/5xx from OpenSandbox Server
    SandboxInternalException,      # Network/IO errors, serialization failures
    SandboxReadyTimeoutException,  # Sandbox failed to boot in time
    InvalidArgumentException,      # Bad SDK arguments
)
```

### Catching API Errors

```python
try:
    await sandbox.commands.run("exit 1")
except SandboxApiException as e:
    print(f"HTTP Status: {e.status_code}")
    if e.error:
        print(f"Code: {e.error.code}")
        print(f"Message: {e.error.message}")
```

---

## 13. API Reference Summary

### `Sandbox` Core Methods

| Method | Description |
|---|---|
| `create(...)` | Classmethod (async). Provision a new sandbox. |
| `connect(...)` | Classmethod (async). Connect to an existing sandbox. |
| `resume(...)` | Classmethod (async). Resumes and returns a new Sandbox instance. |
| `get_info()` | Returns `SandboxInfo` (state, image, metadata). |
| `renew(timedelta)` | Extends the sandbox termination TTL. |
| `pause()` | Suspends all processes. |
| `kill()` | Irreversibly terminates the remote sandbox. |

### `Sandbox.commands` (`Commands` Protocol)

| Method | Description |
|---|---|
| `run(cmd, opts, handlers)` | Execute a shell command (fg or bg). |
| `interrupt(exec_id)` | Terminate a running execution. |
| `get_command_status(exec_id)` | Check background command state. |
| `create_session(cwd)` | Open a persistent shell. |
| `run_in_session(id, cmd, ...)` | Run inside persistent shell. |

### `Sandbox.files` (`Filesystem` Protocol)

| Method | Description |
|---|---|
| `read_file(path)` | Returns content as a string. |
| `read_bytes(path)` | Returns content as bytes. |
| `write_files([WriteEntry])` | Bulk file upload (multipart). |
| `create_directories([WriteEntry])` | Make directories (`mkdir -p`). |
| `delete_files([paths])` | Remove files. |
| `delete_directories([paths])` | Remove directories (`rm -rf`). |
| `search(SearchEntry)` | Find files using glob patterns. |
| `get_file_info([paths])` | Returns a dictionary mapping path to `EntryInfo`. |