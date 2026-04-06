import asyncio
import os
import traceback
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from opensandbox.models.filesystem import WriteEntry, SearchEntry
from opensandbox.models.execd import ExecutionHandlers, RunCommandOpts
from opensandbox.manager import SandboxManager
from opensandbox.models.sandboxes import SandboxFilter

# --- Configuration ---
IMAGE = os.environ.get("SANDBOX_IMAGE", "opensandbox-base:latest")
PORT = os.environ.get("SANDBOX_PORT", "8080")
API_KEY = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")

CONFIG = ConnectionConfig(
    domain=f"localhost:{PORT}",
    api_key=API_KEY,
    use_server_proxy=True,
)

# --- Test Harness ---
class TestTracker:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures = []

    def log_pass(self, name: str):
        print(f"✅ PASS : {name}")
        self.passed += 1

    def log_fail(self, name: str, error: Exception):
        print(f"❌ FAIL : {name} -> {type(error).__name__}: {str(error)}")
        self.failed += 1
        self.failures.append((name, error))

tracker = TestTracker()

async def safe_test(name: str, coro):
    """Runs a coroutine and tracks success/failure."""
    try:
        await coro
        tracker.log_pass(name)
    except Exception as e:
        tracker.log_fail(name, e)

# --- Test Suites ---

async def test_commands_api(sandbox: Sandbox):
    print("\n--- Testing Commands API ---")
    
    async def foreground():
        res = await sandbox.commands.run("echo 'sync test'")
        assert res.exit_code == 0
        assert "sync test" in res.text
    await safe_test("commands.run (Foreground)", foreground())

    async def background():
        opts = RunCommandOpts(background=True)
        res = await sandbox.commands.run("sleep 2 && echo 'async test'", opts=opts)
        execution_id = res.id
        assert execution_id is not None
        
        # Wait for completion
        for _ in range(5):
            status = await sandbox.commands.get_command_status(execution_id)
            if not status.running:
                break
            await asyncio.sleep(1)
        
        logs = await sandbox.commands.get_background_command_logs(execution_id)
        assert logs.content is not None
    await safe_test("commands.run (Background & Status)", background())

    async def streaming():
        output_captured = []
        async def on_stdout(msg):
            output_captured.append(msg.text)
            
        handlers = ExecutionHandlers(on_stdout=on_stdout)
        await sandbox.commands.run("echo 'stream 1' && echo 'stream 2'", handlers=handlers)
        assert len(output_captured) > 0
    await safe_test("commands.run (Streaming Handlers)", streaming())


async def test_files_api(sandbox: Sandbox):
    print("\n--- Testing Files API ---")
    test_file = "/workspace/api_test.txt"
    test_dir = "/workspace/api_test_dir"

    async def write():
        await sandbox.files.write_files([
            WriteEntry(path=test_file, data="hello world", mode=0o644)
        ])
    await safe_test("files.write_files", write())

    async def read():
        content = await sandbox.files.read_file(test_file)
        assert "hello world" in content
    await safe_test("files.read_file", read())

    async def meta_info():
        info_map = await sandbox.files.get_file_info([test_file])
        info = info_map.get(test_file)
        assert info is not None
        assert info.size > 0
    await safe_test("files.get_file_info", meta_info())

    async def search():
        results = await sandbox.files.search(SearchEntry(path="/workspace", pattern="*.txt"))
        paths = [info.path for info in results]
        assert len(results) > 0
        assert any("api_test.txt" in p for p in paths)
    await safe_test("files.search (Replaces list_directory)", search())

    async def directories():
        await sandbox.files.create_directories([WriteEntry(path=test_dir)])
        info_map = await sandbox.files.get_file_info([test_dir])
        info = info_map.get(test_dir)
        
        # Note: Depending on SDK implementation, you might need to check mode or a specific attribute
        assert info is not None
        await sandbox.files.delete_directories([test_dir])
    await safe_test("files.create/delete_directories", directories())

    async def delete():
        await sandbox.files.delete_files([test_file])
    await safe_test("files.delete_files", delete())


async def test_sandbox_lifecycle_and_metrics(sandbox: Sandbox):
    print("\n--- Testing Sandbox Core APIs ---")
    
    async def get_info():
        info = await sandbox.get_info()
        assert info.status.state == "Running"
    await safe_test("sandbox.get_info", get_info())

    async def get_metrics():
        metrics = await sandbox.get_metrics()
        assert metrics.memory_total_in_mib > 0
    await safe_test("sandbox.get_metrics", get_metrics())

    async def networking():
        # Start a dummy server
        opts = RunCommandOpts(background=True)
        await sandbox.commands.run("python3 -m http.server 8081", opts=opts)
        await asyncio.sleep(1) # wait for boot
        endpoint = await sandbox.get_endpoint(8081)
        assert endpoint.endpoint is not None
    await safe_test("sandbox.get_endpoint", networking())

    async def renew():
        await sandbox.renew(timedelta(minutes=45))
    await safe_test("sandbox.renew", renew())

    async def pause_resume():
        await sandbox.pause()
        info = await sandbox.get_info()
        assert info.status.state in ["Pausing", "Paused"]
        
        # Resume requires class method
        resumed_sbx = await Sandbox.resume(sandbox.id, connection_config=CONFIG)
        info = await resumed_sbx.get_info()
        assert info.status.state == "Running"
    await safe_test("sandbox.pause & Sandbox.resume", pause_resume())


async def test_manager_api():
    print("\n--- Testing Manager API ---")
    
    async def list_sandboxes():
        async with await SandboxManager.create(connection_config=CONFIG) as manager:
            result = await manager.list_sandbox_infos(SandboxFilter(states=["Running", "Paused"]))
            assert len(result.sandbox_infos) > 0
    await safe_test("SandboxManager.list_sandbox_infos", list_sandboxes())


# --- Main Execution ---
async def main():
    print(f"🚀 Initializing exhaustive API test with image: {IMAGE}\n")
    
    sandbox = None
    try:
        print("Creating Sandbox...")
        sandbox = await Sandbox.create(
            IMAGE,
            connection_config=CONFIG,
            entrypoint=["sleep", "infinity"],
            timeout=timedelta(minutes=10)
        )
        print(f"Sandbox created: {sandbox.id}")

        await test_commands_api(sandbox)
        await test_files_api(sandbox)
        await test_sandbox_lifecycle_and_metrics(sandbox)
        await test_manager_api()

    except Exception as e:
        print(f"\n💥 FATAL SETUP ERROR: {e}")
        traceback.print_exc()
    finally:
        if sandbox:
            print("\nCleaning up sandbox...")
            await sandbox.kill()

    print("\n" + "="*40)
    print("🎯 TEST RUN COMPLETE")
    print("="*40)
    print(f"Passed: {tracker.passed}")
    print(f"Failed: {tracker.failed}")
    
    if tracker.failed > 0:
        print("\nFailures needing SDK/Doc inspection:")
        for name, err in tracker.failures:
            print(f" - {name}: {type(err).__name__}: {err}")

if __name__ == "__main__":
    asyncio.run(main())