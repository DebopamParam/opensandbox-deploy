"""Quick smoke test — creates a sandbox, runs a command, cleans up."""
import asyncio
import os
from datetime import timedelta
from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig

async def main():
    image = os.environ.get("SANDBOX_IMAGE", "python:3.11-slim")
    port = os.environ.get("SANDBOX_PORT", "8080")
    api_key = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")
    cpu = os.environ.get("SANDBOX_CPU", "1")
    memory = os.environ.get("SANDBOX_MEMORY", "512Mi")
    timeout_s = int(os.environ.get("SANDBOX_TIMEOUT", "1800"))

    config = ConnectionConfig(
        domain=f"localhost:{port}",
        api_key=api_key,
    )

    print(f"Creating sandbox (image={image})...")
    sandbox = await Sandbox.create(
        image,
        connection_config=config,
        entrypoint=["bash"],
        env={"PYTHONUNBUFFERED": "1"},
        timeout=timedelta(seconds=timeout_s),
        resource={"cpu": cpu, "memory": memory},
    )

    async with sandbox:
        print(f"Sandbox ready: {sandbox.sandbox_id}")

        # Basic command
        result = await sandbox.commands.run("echo 'Hello from OpenSandbox!'")
        print(f"stdout: {result.logs.stdout[0].text}")

        # Python check
        result = await sandbox.commands.run("python3 -c 'import sys; print(sys.version)'")
        print(f"Python: {result.logs.stdout[0].text}")

        # Check runtime (gVisor shows "Starting gVisor..." in dmesg)
        result = await sandbox.commands.run("dmesg 2>/dev/null | head -1 || echo 'dmesg not available (runc)'")
        print(f"Runtime: {result.logs.stdout[0].text}")

    await sandbox.kill()
    print("Sandbox killed. All good!")

if __name__ == "__main__":
    asyncio.run(main())
