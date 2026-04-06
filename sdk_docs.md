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

Here is the complete, final architectural pattern in a single Markdown file. It incorporates all of our iterations: Pydantic runtime validation, implicit working directory normalization, stateful shell sessions, and non-blocking background executions. 

---


## 14. Vendor-Agnostic Abstractions (Advanced)

To prevent vendor lock-in and ensure your application can seamlessly switch between OpenSandbox, local Docker, or other remote execution environments, you can use a hardware-agnostic abstraction layer. 

This implementation uses **Pydantic** for strict runtime configuration validation and the **Dependency Inversion Principle** to decouple your business logic from the specific SDK. It provides built-in path normalization, stateful shell sessions, and background task management.

### 1. Core Interfaces (`core.py`)

Defines the universal language for interacting with any sandbox provider.

```python
import abc
import logging
from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)

class CommandResult(BaseModel):
    """Represents the outcome of a command executed inside a sandbox."""
    model_config = ConfigDict(frozen=True)

    exit_code: int = Field(description="The shell exit code (0 usually indicates success).")
    text: str = Field(description="Combined stdout/stderr output.")
    
    @property
    def success(self) -> bool:
        """Syntactic sugar for checking if the command succeeded."""
        return self.exit_code == 0

class ExecutionStatus(BaseModel):
    """Represents the real-time status of a background execution."""
    model_config = ConfigDict(frozen=True)

    execution_id: str = Field(description="The unique identifier for the background task.")
    is_running: bool = Field(description="True if the process is still active.")
    exit_code: Optional[int] = Field(default=None, description="Populated only when the process has finished.")
    
    @property
    def success(self) -> bool:
        """True if the process finished and exited cleanly."""
        return not self.is_running and self.exit_code == 0

class SandboxConfig(BaseModel):
    """Universal configuration for provisioning a sandbox."""
    model_config = ConfigDict(frozen=True)

    image: str = Field(description="Docker image URI (e.g., 'python:3.13-slim').")
    
    env: Dict[str, str] = Field(
        default_factory=dict, 
        description="Environment variables to inject."
    )
    
    timeout_seconds: Optional[int] = Field(
        default=600, 
        ge=1, 
        description="Auto-termination TTL in seconds."
    )
    
    working_dir: str = Field(
        default="/workspace", 
        description="The base directory for all relative file paths and command executions."
    )
    
    provider_kwargs: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Vendor-specific configuration (e.g., domain, api_key)."
    )

class AbstractSession(abc.ABC):
    """An active, stateful shell session inside a sandbox."""
    
    @abc.abstractmethod
    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        pass

    @abc.abstractmethod
    async def close(self) -> None:
        pass

class AbstractSandbox(abc.ABC):
    """Base interface for an active sandbox instance."""

    # -- File & Sync Execution --
    @abc.abstractmethod
    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        pass

    @abc.abstractmethod
    async def write_file(self, path: str, content: Union[str, bytes]) -> None:
        pass

    @abc.abstractmethod
    async def read_file(self, path: str) -> str:
        pass
        
    # -- Background Execution --
    @abc.abstractmethod
    async def start_background(self, cmd: str) -> str:
        pass

    @abc.abstractmethod
    async def get_command_status(self, execution_id: str) -> ExecutionStatus:
        pass

    @abc.abstractmethod
    async def stop_background(self, execution_id: str) -> None:
        pass

    # -- Sessions & Lifecycle --
    @abc.abstractmethod
    async def create_session(self, working_dir: Optional[str] = None) -> AbstractSession:
        pass

    @abc.abstractmethod
    async def kill(self) -> None:
        pass

class AbstractSandboxProvider(abc.ABC):
    """Factory interface for provisioning sandboxes."""

    @abc.abstractmethod
    async def create_sandbox(self, config: SandboxConfig) -> AbstractSandbox:
        pass
```

---

### 2. Async Lifecycle Manager (`context.py`)

A flexible context manager that handles provisioning on entry and mathematically guarantees environment teardown (both sessions and sandboxes) on exit, regardless of exceptions.

```python
from typing import AsyncGenerator, Literal, Tuple, Union, overload
from contextlib import asynccontextmanager
import logging

from .core import AbstractSandbox, AbstractSandboxProvider, SandboxConfig, AbstractSession

logger = logging.getLogger(__name__)

# --- Type Hint Overloads for strict IDE support ---
@overload
def managed_sandbox(
    provider: AbstractSandboxProvider, config: SandboxConfig, with_session: Literal[False] = False
) -> asynccontextmanager[AsyncGenerator[AbstractSandbox, None]]: ...

@overload
def managed_sandbox(
    provider: AbstractSandboxProvider, config: SandboxConfig, with_session: Literal[True]
) -> asynccontextmanager[AsyncGenerator[Tuple[AbstractSandbox, AbstractSession], None]]: ...
# ------------------------------------------------

@asynccontextmanager
async def managed_sandbox(
    provider: AbstractSandboxProvider, 
    config: SandboxConfig,
    with_session: bool = True
) -> AsyncGenerator[Union[AbstractSandbox, Tuple[AbstractSandbox, AbstractSession]], None]:
    """
    Spawns a sandbox and optionally a default stateful session.
    Strictly guarantees termination of all spawned resources on exit.
    """
    sandbox = None
    session = None
    
    try:
        logger.info(f"Provisioning sandbox via {provider.__class__.__name__}...")
        sandbox = await provider.create_sandbox(config)
        logger.info("Sandbox provisioned successfully.")
        
        if with_session:
            logger.info("Starting default stateful session...")
            session = await sandbox.create_session()
            yield sandbox, session
        else:
            yield sandbox
            
    except Exception as e:
        logger.error(f"Error encountered during sandbox execution: {e}")
        raise
    finally:
        # 1. Gracefully close the session first
        if session is not None:
            logger.info("Closing stateful session...")
            try:
                await session.close()
            except Exception as session_err:
                logger.error(f"Failed to cleanly close session: {session_err}")
                
        # 2. Forcefully kill the remote sandbox container
        if sandbox is not None:
            logger.info("Forcefully terminating sandbox...")
            try:
                await sandbox.kill()
                logger.info("Sandbox terminated successfully.")
            except Exception as kill_err:
                logger.critical(f"Failed to cleanly terminate sandbox: {kill_err}")
```

---

### 3. OpenSandbox Adapter (`providers/opensandbox.py`)

The concrete implementation that maps our universal abstractions to the OpenSandbox SDK, handling relative path normalization and implicit directory creation.

```python
import posixpath
from datetime import timedelta
from typing import Union, Optional

from opensandbox import Sandbox as OSSandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts

from ..core import (
    AbstractSandbox, 
    AbstractSandboxProvider, 
    AbstractSession,
    CommandResult, 
    ExecutionStatus,
    SandboxConfig
)

class OpenSandboxSession(AbstractSession):
    def __init__(self, sandbox_instance: OSSandbox, session_id: str):
        self._sandbox = sandbox_instance
        self._session_id = session_id

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        kwargs = {}
        if timeout:
            kwargs["timeout"] = timedelta(seconds=timeout)
            
        result = await self._sandbox.commands.run_in_session(
            self._session_id, 
            cmd, 
            **kwargs
        )
        return CommandResult(exit_code=result.exit_code, text=result.text)

    async def close(self) -> None:
        await self._sandbox.commands.delete_session(self._session_id)


class OpenSandboxAdapter(AbstractSandbox):
    def __init__(self, sandbox_instance: OSSandbox, working_dir: str):
        self._sandbox = sandbox_instance
        self._working_dir = working_dir

    def _normalize_path(self, path: str) -> str:
        """Converts relative paths to absolute paths based on the working directory."""
        if posixpath.isabs(path):
            return path
        return posixpath.join(self._working_dir, path)

    # -- File & Sync Execution --
    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        opts = RunCommandOpts(working_directory=self._working_dir)
        if timeout:
            opts.timeout = timedelta(seconds=timeout)
            
        result = await self._sandbox.commands.run(cmd, opts=opts)
        return CommandResult(exit_code=result.exit_code, text=result.text)

    async def write_file(self, path: str, content: Union[str, bytes]) -> None:
        abs_path = self._normalize_path(path)
        parent_dir = posixpath.dirname(abs_path)
        
        # Implicitly ensure the parent directory exists
        if parent_dir and parent_dir != "/":
            await self._sandbox.commands.run(
                f"mkdir -p {parent_dir}", 
                opts=RunCommandOpts(working_directory="/")
            )
            
        await self._sandbox.files.write_file(abs_path, content)

    async def read_file(self, path: str) -> str:
        abs_path = self._normalize_path(path)
        return await self._sandbox.files.read_file(abs_path)

    # -- Background Execution --
    async def start_background(self, cmd: str) -> str:
        opts = RunCommandOpts(
            working_directory=self._working_dir,
            background=True
        )
        result = await self._sandbox.commands.run(cmd, opts=opts)
        return result.id

    async def get_command_status(self, execution_id: str) -> ExecutionStatus:
        status = await self._sandbox.commands.get_command_status(execution_id)
        return ExecutionStatus(
            execution_id=execution_id,
            is_running=status.running,
            exit_code=status.exit_code if not status.running else None 
        )

    async def stop_background(self, execution_id: str) -> None:
        await self._sandbox.commands.interrupt(execution_id)

    # -- Sessions & Lifecycle --
    async def create_session(self, working_dir: Optional[str] = None) -> AbstractSession:
        target_dir = working_dir if working_dir else self._working_dir
        session_id = await self._sandbox.commands.create_session(
            working_directory=target_dir
        )
        return OpenSandboxSession(self._sandbox, session_id)

    async def kill(self) -> None:
        await self._sandbox.kill()


class OpenSandboxProvider(AbstractSandboxProvider):
    async def create_sandbox(self, config: SandboxConfig) -> AbstractSandbox:
        connection_config = ConnectionConfig(
            domain=config.provider_kwargs.get("domain", "localhost:8080"),
            api_key=config.provider_kwargs.get("api_key", ""),
            use_server_proxy=config.provider_kwargs.get("use_server_proxy", False)
        )
        
        timeout_td = timedelta(seconds=config.timeout_seconds) if config.timeout_seconds else None

        os_sandbox = await OSSandbox.create(
            image=config.image,
            env=config.env,
            timeout=timeout_td,
            connection_config=connection_config
        )

        return OpenSandboxAdapter(os_sandbox, config.working_dir)
```

---

### 4. Comprehensive Usage Example

This demonstrates how client code leverages the abstraction for filesystem operations, stateful executions, and background polling—all without leaking infrastructure details.

```python
import asyncio
from .core import SandboxConfig
from context import managed_sandbox
from .providers.opensandbox import OpenSandboxProvider

async def main():
    # 1. Instantiate the provider
    provider = OpenSandboxProvider()

    # 2. Define the validated configuration
    config = SandboxConfig(
        image="python:3.13-slim",
        working_dir="/app/project", # Implicit target for all paths/commands
        timeout_seconds=300,
        provider_kwargs={
            "domain": "api.sandbox.internal:8080",
            "api_key": "your_api_key",
        }
    )

    # 3. Enter the managed context (spawns sandbox & session automatically)
    async with managed_sandbox(provider, config, with_session=True) as (sandbox, session):
        
        print("--- 1. File System & Sync Execution ---")
        # Automatically runs `mkdir -p /app/project/src` before writing
        await sandbox.write_file("src/hello.py", "import os; print(os.environ.get('MY_VAR', 'None'))")
        
        # Automatically executes inside /app/project
        result = await sandbox.run_command("python src/hello.py")
        print(f"Stateless output: {result.text.strip()}") # Output: None
        
        
        print("\n--- 2. Stateful Session ---")
        # State persists across commands in a session
        await session.run_command("export MY_VAR='Hello from Session'")
        session_result = await session.run_command("python src/hello.py")
        print(f"Stateful output: {session_result.text.strip()}") # Output: Hello from Session
        
        
        print("\n--- 3. Background Execution ---")
        print("Dispatching heavy task...")
        exec_id = await sandbox.start_background("sleep 3 && echo 'Task Complete'")
        
        # Do local work while the remote task processes
        while True:
            status = await sandbox.get_command_status(exec_id)
            if not status.is_running:
                break
            print("Waiting for background task...")
            await asyncio.sleep(1)
            
        print(f"Background task finished! Exit code: {status.exit_code}")

    # Exiting the 'with' block automatically closes the session and kills the sandbox.
    print("\nSandbox teardown complete.")

if __name__ == "__main__":
    asyncio.run(main())
```