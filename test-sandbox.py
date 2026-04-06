"""Spawn N sandboxes concurrently and run a small workload in each,
with per-command timing and inter-command delay tracking."""
import asyncio
import os
import time
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig


# ── config ────────────────────────────────────────────────────────────────────

IMAGE       = os.environ.get("SANDBOX_IMAGE",   "python:3.13-slim")
PORT        = os.environ.get("SANDBOX_PORT",    "8080")
API_KEY     = os.environ.get("SANDBOX_API_KEY", "change-me-to-something-secret")
TIMEOUT_S   = int(os.environ.get("SANDBOX_TIMEOUT", "120"))

N_SANDBOXES = 3

CONFIG = ConnectionConfig(
    domain=f"localhost:{PORT}",
    api_key=API_KEY,
    use_server_proxy=True,
)

CHECKS = {
    "echo":   "echo hello-from-worker",
    "python": "python3 -c 'print(2 ** 10)'",
    "uptime": "cat /proc/uptime",
    "primes":   "python3 -c 'print(sum(1 for n in range(2,100000) if all(n%i for i in range(2,n))))'",
    # "fib":      "python3 -c 'f=lambda n:n if n<2 else f(n-1)+f(n-2); print(f(35))'",
    # "matrix":   "python3 -c 'import math; print(sum(math.sqrt(i)*math.log(i+1) for i in range(1,500000)))'",
}


# ── timing helpers ────────────────────────────────────────────────────────────

class CommandTimer:
    """Tracks absolute start, duration, and gap from the previous command."""

    def __init__(self, epoch: float):
        self._epoch   = epoch
        self._prev_end: float | None = None
        self.records: list[dict] = []

    async def run(self, sandbox, name: str, cmd: str) -> tuple[str, Exception | None]:
        t0  = time.perf_counter()
        gap = round(t0 - self._prev_end, 4) if self._prev_end is not None else None
        err = None
        output = ""
        try:
            res = await sandbox.commands.run(cmd)
            output = res.logs.stdout[0].text.strip() if res.logs.stdout else ""
        except Exception as exc:
            err = exc
        finally:
            t1 = time.perf_counter()
            self._prev_end = t1
            self.records.append({
                "name":       name,
                "cmd":        cmd,
                "start_rel":  round(t0 - self._epoch, 4),
                "duration_s": round(t1 - t0, 4),
                "gap_s":      gap,
                "output":     output,
                "error":      str(err) if err else None,
            })
        return output, err


# ── per-sandbox workload ──────────────────────────────────────────────────────

async def run_worker(worker_id: int, epoch: float) -> dict:
    errors = []

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

    timer  = CommandTimer(epoch)
    t_work = time.perf_counter()
    try:
        for name, cmd in CHECKS.items():
            _, err = await timer.run(sandbox, name, cmd)
            if err:
                errors.append(f"{name}: {err}")
    finally:
        await sandbox.kill()

    work_s = time.perf_counter() - t_work

    return {
        "worker_id": worker_id,
        "spawn_s":   round(spawn_s, 4),
        "work_s":    round(work_s, 4),
        "total_s":   round(spawn_s + work_s, 4),
        "commands":  timer.records,
        "errors":    errors,
        "ok":        len(errors) == 0,
    }


# ── reporting ─────────────────────────────────────────────────────────────────

def _gap_str(gap_s: float | None) -> str:
    return f"+{gap_s:.4f}s gap" if gap_s is not None else "first command"

def print_results(results: list, wall_elapsed: float) -> None:
    passed = failed = 0

    for r in results:
        if isinstance(r, BaseException):
            failed += 1
            print(f"[worker ?] EXCEPTION → {r}")
            continue

        passed += r["ok"]
        failed += not r["ok"]
        status  = "✓ PASS" if r["ok"] else "✗ FAIL"

        print(
            f"\n[worker {r['worker_id']}] {status}  "
            f"spawn={r['spawn_s']}s  work={r['work_s']}s  total={r['total_s']}s"
        )
        print(f"  {'CMD':<10} {'START':>11}  {'DUR':>10}  {'GAP / NOTE'}")
        print(f"  {'─'*10} {'─'*11}  {'─'*10}  {'─'*20}")

        for rec in r["commands"]:
            start = f"t+{rec['start_rel']:.4f}s"
            dur   = f"{rec['duration_s']:.4f}s"
            note  = _gap_str(rec["gap_s"])
            mark  = "✗" if rec["error"] else " "
            print(f"  {mark}{rec['name']:<9} {start:>11}  {dur:>10}  {note}")
            if rec["output"]:
                print(f"           → {rec['output']}")
            if rec["error"]:
                print(f"           ✗ {rec['error']}")

    print(f"\n{'─'*55}")
    print(f"Results  : {passed} passed / {failed} failed / {N_SANDBOXES} total")
    print(f"Wall time: {wall_elapsed:.4f}s")

    if failed:
        raise SystemExit(1)


# ── test runner ───────────────────────────────────────────────────────────────

async def main():
    print(f"Launching {N_SANDBOXES} sandbox(es) in parallel...\n")
    epoch = time.perf_counter()

    results = await asyncio.gather(
        *[run_worker(i, epoch) for i in range(N_SANDBOXES)],
        return_exceptions=True,
    )

    print_results(results, time.perf_counter() - epoch)


if __name__ == "__main__":
    asyncio.run(main())