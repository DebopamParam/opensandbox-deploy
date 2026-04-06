import abc
import asyncio
import logging
import os
import posixpath
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, AsyncGenerator, Dict, Literal, Optional, Tuple, Union, overload

from pydantic import BaseModel, ConfigDict, Field

# --- OpenSandbox SDK Imports ---
from opensandbox import Sandbox as OSSandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.execd import RunCommandOpts

# Set up basic logging for the abstraction layer
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("sandbox_abstraction")

# ==========================================
# 1. CORE ABSTRACTIONS (Models & Interfaces)
# ==========================================

class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    exit_code: int = Field(description="The shell exit code.")
    text: str = Field(description="Combined stdout/stderr output.")
    
    @property
    def success(self) -> bool:
        return self.exit_code == 0

class ExecutionStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    execution_id: str
    is_running: bool
    exit_code: Optional[int] = None
    
    @property
    def success(self) -> bool:
        return not self.is_running and self.exit_code == 0

class SandboxConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    image: str = Field(...)
    env: Dict[str, str] = Field(default_factory=dict)
    timeout_seconds: Optional[int] = Field(default=600, ge=1)
    working_dir: str = Field(default="/workspace")
    provider_kwargs: Dict[str, Any] = Field(default_factory=dict)

class AbstractSession(abc.ABC):
    @abc.abstractmethod
    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult: pass

    @abc.abstractmethod
    async def close(self) -> None: pass

class AbstractSandbox(abc.ABC):
    @abc.abstractmethod
    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult: pass

    @abc.abstractmethod
    async def write_file(self, path: str, content: Union[str, bytes]) -> None: pass

    @abc.abstractmethod
    async def read_file(self, path: str) -> str: pass
        
    @abc.abstractmethod
    async def start_background(self, cmd: str) -> str: pass

    @abc.abstractmethod
    async def get_command_status(self, execution_id: str) -> ExecutionStatus: pass

    @abc.abstractmethod
    async def stop_background(self, execution_id: str) -> None: pass

    @abc.abstractmethod
    async def create_session(self, working_dir: Optional[str] = None) -> AbstractSession: pass

    @abc.abstractmethod
    async def kill(self) -> None: pass

class AbstractSandboxProvider(abc.ABC):
    @abc.abstractmethod
    async def create_sandbox(self, config: SandboxConfig) -> AbstractSandbox: pass


# ==========================================
# 2. CONTEXT MANAGER
# ==========================================

# --- Type Hint Overloads for strict IDE support ---
@overload
def managed_sandbox(
    provider: AbstractSandboxProvider, config: SandboxConfig, with_session: Literal[False] = False
) -> AsyncGenerator[AbstractSandbox, None]: ...

@overload
def managed_sandbox(
    provider: AbstractSandboxProvider, config: SandboxConfig, with_session: Literal[True]
) -> AsyncGenerator[Tuple[AbstractSandbox, AbstractSession], None]: ...
# ------------------------------------------------

@asynccontextmanager
async def managed_sandbox(
    provider: AbstractSandboxProvider, 
    config: SandboxConfig,
    with_session: bool = False
) -> AsyncGenerator[Union[AbstractSandbox, Tuple[AbstractSandbox, AbstractSession]], None]:
    sandbox = None
    session = None
    
    try:
        logger.info(f"Provisioning sandbox via {provider.__class__.__name__}...")
        sandbox = await provider.create_sandbox(config)
        
        if with_session:
            session = await sandbox.create_session()
            yield sandbox, session
        else:
            yield sandbox
            
    finally:
        if session is not None:
            logger.info("Closing stateful session...")
            await session.close()
                
        if sandbox is not None:
            logger.info("Forcefully terminating sandbox...")
            await sandbox.kill()


# ==========================================
# 3. OPENSANDBOX ADAPTER IMPLEMENTATION
# ==========================================

class OpenSandboxSession(AbstractSession):
    def __init__(self, sandbox_instance: OSSandbox, session_id: str):
        self._sandbox = sandbox_instance
        self._session_id = session_id

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        kwargs = {}
        if timeout: kwargs["timeout"] = timedelta(seconds=timeout)
        result = await self._sandbox.commands.run_in_session(self._session_id, cmd, **kwargs)
        return CommandResult(exit_code=result.exit_code, text=result.text)

    async def close(self) -> None:
        await self._sandbox.commands.delete_session(self._session_id)

class OpenSandboxAdapter(AbstractSandbox):
    def __init__(self, sandbox_instance: OSSandbox, working_dir: str):
        self._sandbox = sandbox_instance
        self._working_dir = working_dir

    def _normalize_path(self, path: str) -> str:
        if posixpath.isabs(path): return path
        return posixpath.join(self._working_dir, path)

    async def run_command(self, cmd: str, timeout: Optional[int] = None) -> CommandResult:
        opts = RunCommandOpts(working_directory=self._working_dir)
        if timeout: opts.timeout = timedelta(seconds=timeout)
        result = await self._sandbox.commands.run(cmd, opts=opts)
        return CommandResult(exit_code=result.exit_code, text=result.text)

    async def write_file(self, path: str, content: Union[str, bytes]) -> None:
        abs_path = self._normalize_path(path)
        parent_dir = posixpath.dirname(abs_path)
        if parent_dir and parent_dir != "/":
            await self._sandbox.commands.run(f"mkdir -p {parent_dir}", opts=RunCommandOpts(working_directory="/"))
        await self._sandbox.files.write_file(abs_path, content)

    async def read_file(self, path: str) -> str:
        abs_path = self._normalize_path(path)
        return await self._sandbox.files.read_file(abs_path)

    async def start_background(self, cmd: str) -> str:
        opts = RunCommandOpts(working_directory=self._working_dir, background=True)
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

    async def create_session(self, working_dir: Optional[str] = None) -> AbstractSession:
        target_dir = working_dir if working_dir else self._working_dir
        session_id = await self._sandbox.commands.create_session(working_directory=target_dir)
        return OpenSandboxSession(self._sandbox, session_id)

    async def kill(self) -> None:
        await self._sandbox.kill()

class OpenSandboxProvider(AbstractSandboxProvider):
    async def create_sandbox(self, config: SandboxConfig) -> AbstractSandbox:
        conn_config = ConnectionConfig(
            domain=config.provider_kwargs.get("domain", "localhost:8080"),
            api_key=config.provider_kwargs.get("api_key", ""),
            use_server_proxy=config.provider_kwargs.get("use_server_proxy", False)
        )
        
        timeout_td = timedelta(seconds=config.timeout_seconds) if config.timeout_seconds else None
        
        # Adding entrypoint to keep container alive like in your WeasyPrint example
        entrypoint = config.provider_kwargs.get("entrypoint", ["sleep", "infinity"])

        os_sandbox = await OSSandbox.create(
            image=config.image,
            env=config.env,
            timeout=timeout_td,
            connection_config=conn_config,
            entrypoint=entrypoint
        )
        return OpenSandboxAdapter(os_sandbox, config.working_dir)


# ==========================================
# 4. COMPREHENSIVE TEST RUNNER
# ==========================================

async def run_tests():
    print("\n🚀 Initializing Abstraction Test Suite...\n")
    
    # Mirroring your environment setup
    IMAGE = os.environ.get("SANDBOX_IMAGE", "opensandbox-base:latest")
    PORT = os.environ.get("SANDBOX_PORT", "8080")
    API_KEY = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")

    provider = OpenSandboxProvider()
    config = SandboxConfig(
        image=IMAGE,
        working_dir="/workspace/test_project",
        provider_kwargs={
            "domain": f"localhost:{PORT}",
            "api_key": API_KEY,
            "use_server_proxy": True,
        }
    )

    async with managed_sandbox(provider, config, with_session=True) as (sandbox, session):
        
        print("\n--- Test 1: File Operations & Implicit Paths ---")
        try:
            # Should automatically create /workspace/test_project/src/
            await sandbox.write_file("src/hello.txt", "Hello from Abstraction!")
            content = await sandbox.read_file("src/hello.txt")
            if content == "Hello from Abstraction!":
                print("✅ File write/read with implicit directory creation successful.")
            else:
                print("❌ File read mismatch.")
        except Exception as e:
            print(f"❌ File Ops failed: {e}")


        print("\n--- Test 2: Synchronous Command Execution ---")
        try:
            # Runs automatically in /workspace/test_project
            res = await sandbox.run_command("cat src/hello.txt")
            if res.success and res.text.strip() == "Hello from Abstraction!":
                print("✅ Sync command execution successful.")
            else:
                print(f"❌ Sync command failed. Exit code: {res.exit_code}, Output: {res.text}")
        except Exception as e:
             print(f"❌ Sync Execution failed: {e}")


        print("\n--- Test 3: Stateful Sessions ---")
        try:
            await session.run_command("export TEST_VAR='State Persisted'")
            session_res = await session.run_command("echo $TEST_VAR")
            
            if session_res.success and session_res.text.strip() == "State Persisted":
                print("✅ Stateful environment variables persisted across commands.")
            else:
                print(f"❌ Session state failed to persist. Output: {session_res.text}")
        except Exception as e:
             print(f"❌ Session Execution failed: {e}")


        print("\n--- Test 4: Background Executions & Polling ---")
        try:
            print("Dispatching 3-second background sleep task...")
            exec_id = await sandbox.start_background("sleep 3 && echo 'Background Job Done' > bg_output.txt")
            print(f"Got Execution ID: {exec_id}")
            
            attempts = 0
            while True:
                status = await sandbox.get_command_status(exec_id)
                if not status.is_running:
                    break
                attempts += 1
                print(f"Polling... (Attempt {attempts})")
                await asyncio.sleep(1)
                
            if status.success:
                bg_content = await sandbox.read_file("bg_output.txt")
                if bg_content.strip() == "Background Job Done":
                    print("✅ Background task executed, polled, and validated successfully.")
                else:
                    print("❌ Background task finished but output was wrong.")
            else:
                print(f"❌ Background task failed with exit code: {status.exit_code}")
        except Exception as e:
             print(f"❌ Background Execution failed: {e}")

    print("\n🎉 Test suite complete. Context manager is tearing down resources.")

if __name__ == "__main__":
    asyncio.run(run_tests())