"""Spawn 5 sandboxes concurrently and run a small workload in each."""
import asyncio
import os
import time
from contextlib import asynccontextmanager
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig


# ── config ────────────────────────────────────────────────────────────────────

IMAGE     = os.environ.get("SANDBOX_IMAGE",   "python:3.11-slim")
PORT      = os.environ.get("SANDBOX_PORT",    "8080")
API_KEY   = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")
TIMEOUT_S = int(os.environ.get("SANDBOX_TIMEOUT", "120"))

N_SANDBOXES = 5

CONFIG = ConnectionConfig(
    domain=f"localhost:{PORT}",
    api_key=API_KEY,
    use_server_proxy=True,
)


# ── per-sandbox workload ──────────────────────────────────────────────────────

async def run_worker(worker_id: int) -> dict:
    """Create one sandbox, run a few commands, return a result summary."""
    errors = []

    # ── spawn ─────────────────────────────────────────────────────────────────
    t_spawn = time.perf_counter()
    sandbox = await Sandbox.create(
        IMAGE,
        connection_config=CONFIG,
        entrypoint=["sleep", "infinity"],
        env={"PYTHONUNBUFFERED": "1"},
        timeout=timedelta(seconds=TIMEOUT_S),
        resource={"cpu": "0.25", "memory": "128Mi"},
    )
    spawn_s = time.perf_counter() - t_spawn

    # ── workload ──────────────────────────────────────────────────────────────
    t_work = time.perf_counter()
    try:
        checks = {
            "echo":   "echo hello-from-worker",
            "python": "python3 -c 'print(2 ** 10)'",
            "uptime": "cat /proc/uptime",
        }
        outputs = {}
        for name, cmd in checks.items():
            try:
                res = await sandbox.commands.run(cmd)
                outputs[name] = res.logs.stdout[0].text.strip() if res.logs.stdout else ""
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    finally:
        await sandbox.kill()

    work_s = time.perf_counter() - t_work

    return {
        "worker_id": worker_id,
        "spawn_s":   round(spawn_s, 2),
        "work_s":    round(work_s, 2),
        "total_s":   round(spawn_s + work_s, 2),
        "outputs":   outputs,
        "errors":    errors,
        "ok":        len(errors) == 0,
    }


# ── test runner ───────────────────────────────────────────────────────────────

async def main():
    print(f"Launching {N_SANDBOXES} sandboxes in parallel...\n")
    wall_t0 = time.perf_counter()

    results = await asyncio.gather(
        *[run_worker(i) for i in range(N_SANDBOXES)],
        return_exceptions=True,   # don't let one failure cancel the rest
    )

    wall_elapsed = time.perf_counter() - wall_t0

    # ── report ────────────────────────────────────────────────────────────────
    passed = failed = 0
    for r in results:
        if isinstance(r, BaseException):
            failed += 1
            print(f"[worker ?] EXCEPTION → {r}")
            continue

        status = "✓ PASS" if r["ok"] else "✗ FAIL"
        if r["ok"]:
            passed += 1
        else:
            failed += 1

        print(f"[worker {r['worker_id']}] {status}  spawn={r['spawn_s']}s  work={r['work_s']}s  total={r['total_s']}s")
        for k, v in r["outputs"].items():
            print(f"    {k:8s} → {v}")
        for e in r["errors"]:
            print(f"    ERROR: {e}")

    print(f"\n{'─'*50}")
    print(f"Results  : {passed} passed / {failed} failed / {N_SANDBOXES} total")
    print(f"Wall time: {wall_elapsed:.2f}s")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())