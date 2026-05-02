#!/usr/bin/env python3
"""
OpenSandbox Server Test Script
==============================

Exercises the major features of an OpenSandbox server to verify it is
healthy and that the Python SDK can talk to it.

Usage:
    # Test against localhost:8080 (default)
    python test_opensandbox_server.py

    # Test against a remote server
    python test_opensandbox_server.py --host my-server.internal --port 8080

    # Pass full domain in one shot
    python test_opensandbox_server.py --domain my-server.internal:8080

    # With auth + HTTPS
    python test_opensandbox_server.py \\
        --domain api.example.com:443 \\
        --protocol https \\
        --api-key $OPEN_SANDBOX_API_KEY

    # With Docker bridge networking
    python test_opensandbox_server.py --use-server-proxy

    # Skip slow tests
    python test_opensandbox_server.py --skip background --skip metrics

Exit code is 0 if all selected tests pass, 1 otherwise.
"""

import argparse
import asyncio
import os
import sys
import time
import traceback
from datetime import timedelta
from typing import Awaitable, Callable, List, Tuple

# --- Colored terminal output (no external deps) -----------------------------

class C:
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @staticmethod
    def disable() -> None:
        for attr in ("GREEN", "RED", "YELLOW", "BLUE", "BOLD", "DIM", "RESET"):
            setattr(C, attr, "")


# --- SDK imports (deferred so --help works without the SDK installed) -------

def _import_sdk():
    try:
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.models.filesystem import SearchEntry, WriteEntry
        from opensandbox.exceptions import (
            SandboxApiException,
            SandboxException,
            SandboxReadyTimeoutException,
        )
    except ImportError as e:
        print(
            f"{C.RED}ERROR:{C.RESET} could not import the opensandbox SDK.\n"
            f"  {e}\n\n"
            f"Install it with:\n"
            f"    pip install opensandbox",
            file=sys.stderr,
        )
        sys.exit(2)

    return {
        "Sandbox": Sandbox,
        "ConnectionConfig": ConnectionConfig,
        "RunCommandOpts": RunCommandOpts,
        "SearchEntry": SearchEntry,
        "WriteEntry": WriteEntry,
        "SandboxApiException": SandboxApiException,
        "SandboxException": SandboxException,
        "SandboxReadyTimeoutException": SandboxReadyTimeoutException,
    }


# --- Test runner ------------------------------------------------------------

class TestRunner:
    """
    Tiny async test runner. Keeps state for a single Sandbox so tests
    don't pay the provisioning cost more than once.
    """

    def __init__(self, sandbox, sdk: dict, verbose: bool = False):
        self.sandbox = sandbox
        self.sdk = sdk
        self.verbose = verbose
        self.results: List[Tuple[str, bool, str, float]] = []

    async def run(self, name: str, fn: Callable[[], Awaitable[None]]) -> bool:
        print(f"  {C.BLUE}▶{C.RESET} {name} ... ", end="", flush=True)
        start = time.monotonic()
        try:
            await fn()
            elapsed = time.monotonic() - start
            print(f"{C.GREEN}PASS{C.RESET} {C.DIM}({elapsed:.2f}s){C.RESET}")
            self.results.append((name, True, "", elapsed))
            return True
        except AssertionError as e:
            elapsed = time.monotonic() - start
            msg = str(e) or "assertion failed"
            print(f"{C.RED}FAIL{C.RESET} {C.DIM}({elapsed:.2f}s){C.RESET}")
            print(f"      {C.RED}↳{C.RESET} {msg}")
            self.results.append((name, False, msg, elapsed))
            return False
        except Exception as e:  # noqa: BLE001
            elapsed = time.monotonic() - start
            msg = f"{type(e).__name__}: {e}"
            print(f"{C.RED}ERROR{C.RESET} {C.DIM}({elapsed:.2f}s){C.RESET}")
            print(f"      {C.RED}↳{C.RESET} {msg}")
            if self.verbose:
                print(C.DIM + traceback.format_exc() + C.RESET)
            self.results.append((name, False, msg, elapsed))
            return False

    def summary(self) -> bool:
        passed = sum(1 for _, ok, _, _ in self.results if ok)
        total = len(self.results)
        print()
        print(f"{C.BOLD}━━━ Summary ━━━{C.RESET}")
        for name, ok, msg, elapsed in self.results:
            badge = f"{C.GREEN}✓{C.RESET}" if ok else f"{C.RED}✗{C.RESET}"
            print(f"  {badge} {name} {C.DIM}({elapsed:.2f}s){C.RESET}")
            if not ok and msg:
                print(f"      {C.DIM}{msg}{C.RESET}")
        print()
        if passed == total:
            print(f"{C.GREEN}{C.BOLD}All {total} tests passed.{C.RESET}")
        else:
            print(
                f"{C.RED}{C.BOLD}{total - passed} of {total} tests failed.{C.RESET}"
            )
        return passed == total


# --- Test cases -------------------------------------------------------------

async def test_get_info(sandbox, sdk):
    info = await sandbox.get_info()
    assert info is not None, "get_info() returned None"
    state = info.status.state
    assert state == "Running", f"expected state=Running, got {state!r}"


async def test_simple_command(sandbox, sdk):
    res = await sandbox.commands.run("echo hello-from-sandbox")
    assert res.exit_code == 0, f"non-zero exit code: {res.exit_code}"
    assert "hello-from-sandbox" in res.text, f"unexpected output: {res.text!r}"


async def test_command_with_opts(sandbox, sdk):
    RunCommandOpts = sdk["RunCommandOpts"]
    opts = RunCommandOpts(
        working_directory="/tmp",
        envs={"OS_TEST_VAR": "marker-42"},
        timeout=timedelta(seconds=10),
    )
    res = await sandbox.commands.run("pwd && echo $OS_TEST_VAR", opts=opts)
    assert res.exit_code == 0
    assert "/tmp" in res.text, f"working_directory not honored: {res.text!r}"
    assert "marker-42" in res.text, f"env var not honored: {res.text!r}"


async def test_nonzero_exit(sandbox, sdk):
    res = await sandbox.commands.run("sh -c 'exit 7'")
    assert res.exit_code == 7, f"expected exit_code=7, got {res.exit_code}"


async def test_file_write_read(sandbox, sdk):
    path = "/tmp/os_test_file.txt"
    payload = "the quick brown fox\nover the lazy dog\n"
    await sandbox.files.write_file(path, payload)

    text = await sandbox.files.read_file(path)
    assert text == payload, f"roundtrip mismatch:\n  wrote: {payload!r}\n  read:  {text!r}"


async def test_file_bytes_roundtrip(sandbox, sdk):
    path = "/tmp/os_test_bytes.bin"
    payload = bytes(range(256))
    await sandbox.files.write_file(path, payload)

    data = await sandbox.files.read_bytes(path)
    assert data == payload, "binary roundtrip mismatch"


async def test_bulk_write_and_search(sandbox, sdk):
    WriteEntry = sdk["WriteEntry"]
    SearchEntry = sdk["SearchEntry"]

    await sandbox.files.create_directories(
        [WriteEntry(path="/tmp/os_test_dir")]
    )
    await sandbox.files.write_files(
        [
            WriteEntry(path="/tmp/os_test_dir/a.py", data="print('a')"),
            WriteEntry(path="/tmp/os_test_dir/b.py", data="print('b')"),
            WriteEntry(path="/tmp/os_test_dir/c.txt", data="not python"),
        ]
    )

    results = await sandbox.files.search(
        SearchEntry(path="/tmp/os_test_dir", pattern="*.py")
    )
    found = {r.path for r in results}
    assert any(p.endswith("a.py") for p in found), f"a.py missing from {found}"
    assert any(p.endswith("b.py") for p in found), f"b.py missing from {found}"
    assert not any(p.endswith("c.txt") for p in found), (
        f"c.txt should not match *.py: {found}"
    )


async def test_file_delete(sandbox, sdk):
    path = "/tmp/os_test_to_delete.txt"
    await sandbox.files.write_file(path, "delete me")
    await sandbox.files.delete_files([path])

    res = await sandbox.commands.run(f"test -e {path} && echo EXISTS || echo GONE")
    assert "GONE" in res.text, f"file still exists after delete: {res.text!r}"


async def test_session_state_persists(sandbox, sdk):
    session_id = await sandbox.commands.create_session(working_directory="/tmp")
    try:
        await sandbox.commands.run_in_session(session_id, "export MY_VAR=apple")
        res = await sandbox.commands.run_in_session(session_id, "echo $MY_VAR")
        assert "apple" in res.text, (
            f"session did not preserve env var: {res.text!r}"
        )
    finally:
        await sandbox.commands.delete_session(session_id)


async def test_background_execution(sandbox, sdk):
    RunCommandOpts = sdk["RunCommandOpts"]
    opts = RunCommandOpts(background=True)
    res = await sandbox.commands.run("sleep 2 && echo done", opts=opts)
    exec_id = res.id
    assert exec_id, "background run did not return an execution id"

    # Poll for completion (with a sane upper bound)
    deadline = time.monotonic() + 15
    final = None
    while time.monotonic() < deadline:
        status = await sandbox.commands.get_command_status(exec_id)
        if not status.running:
            final = status
            break
        await asyncio.sleep(0.5)

    assert final is not None, "background task did not finish within 15s"
    assert final.exit_code == 0, f"background exit_code={final.exit_code}"


async def test_metrics(sandbox, sdk):
    metrics = await sandbox.get_metrics()
    assert metrics is not None
    assert metrics.memory_total_in_mib > 0, (
        f"memory_total_in_mib invalid: {metrics.memory_total_in_mib}"
    )
    assert metrics.cpu_used_percentage >= 0, (
        f"cpu_used_percentage invalid: {metrics.cpu_used_percentage}"
    )


async def test_renew(sandbox, sdk):
    # Just verify renew() round-trips without error.
    await sandbox.renew(timedelta(minutes=5))


# Map of test name -> (function, description). Order matters for output.
TESTS: List[Tuple[str, Callable, str]] = [
    ("info",        test_get_info,            "sandbox.get_info()"),
    ("exec",        test_simple_command,      "simple foreground command"),
    ("exec-opts",   test_command_with_opts,   "command with cwd / env / timeout"),
    ("exit-code",   test_nonzero_exit,        "non-zero exit code propagation"),
    ("file-text",   test_file_write_read,     "text file write+read roundtrip"),
    ("file-bytes",  test_file_bytes_roundtrip,"binary file write+read roundtrip"),
    ("file-bulk",   test_bulk_write_and_search,"bulk write + glob search"),
    ("file-delete", test_file_delete,         "file deletion"),
    ("session",     test_session_state_persists,"stateful shell session"),
    ("background",  test_background_execution,"background execution + poll"),
    ("metrics",     test_metrics,             "system metrics"),
    ("renew",       test_renew,               "renew TTL"),
]


# --- CLI / orchestration ----------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test a running OpenSandbox server.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Either --domain (host:port) or --host + --port. --domain wins if both.
    p.add_argument(
        "--domain",
        default=os.environ.get("OPEN_SANDBOX_DOMAIN"),
        help="Server domain as host:port (default: localhost:8080, "
             "or $OPEN_SANDBOX_DOMAIN if set).",
    )
    p.add_argument("--host", default="localhost",
                   help="Server host (default: localhost). Ignored if --domain is given.")
    p.add_argument("--port", type=int, default=8080,
                   help="Server port (default: 8080). Ignored if --domain is given.")

    p.add_argument("--protocol", choices=("http", "https"), default="http",
                   help="Protocol (default: http).")
    p.add_argument(
        "--api-key",
        default=os.environ.get("OPEN_SANDBOX_API_KEY", ""),
        help="API key (default: $OPEN_SANDBOX_API_KEY).",
    )
    p.add_argument(
        "--use-server-proxy",
        action="store_true",
        help="Route execd traffic through the server. Required with Docker bridge networking.",
    )
    p.add_argument(
        "--image",
        default="python:3.13-slim",
        help="Docker image to provision the test sandbox from "
             "(default: python:3.13-slim).",
    )
    p.add_argument(
        "--ready-timeout",
        type=int,
        default=60,
        help="Seconds to wait for the sandbox to become ready (default: 60).",
    )
    p.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="NAME",
        help="Skip a test by name. Repeatable. Names: "
             + ", ".join(name for name, _, _ in TESTS),
    )
    p.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="NAME",
        help="Run only the named test(s). Repeatable. Mutually exclusive with --skip.",
    )
    p.add_argument("-v", "--verbose", action="store_true",
                   help="Print full tracebacks on errors.")
    p.add_argument("--no-color", action="store_true",
                   help="Disable ANSI color output.")

    args = p.parse_args()

    if not args.domain:
        args.domain = f"{args.host}:{args.port}"

    if args.skip and args.only:
        p.error("--skip and --only are mutually exclusive")

    valid = {name for name, _, _ in TESTS}
    for n in args.skip + args.only:
        if n not in valid:
            p.error(f"unknown test name: {n!r}. Valid: {', '.join(sorted(valid))}")

    return args


def select_tests(args: argparse.Namespace):
    if args.only:
        return [(n, f, d) for n, f, d in TESTS if n in args.only]
    if args.skip:
        return [(n, f, d) for n, f, d in TESTS if n not in args.skip]
    return list(TESTS)


async def amain(args: argparse.Namespace) -> int:
    sdk = _import_sdk()
    Sandbox = sdk["Sandbox"]
    ConnectionConfig = sdk["ConnectionConfig"]
    SandboxReadyTimeoutException = sdk["SandboxReadyTimeoutException"]
    SandboxApiException = sdk["SandboxApiException"]

    print(f"{C.BOLD}OpenSandbox Server Test{C.RESET}")
    print(f"  Endpoint:        {C.BLUE}{args.protocol}://{args.domain}{C.RESET}")
    print(f"  API key:         {'<set>' if args.api_key else C.YELLOW + '<empty>' + C.RESET}")
    print(f"  Use server proxy:{' yes' if args.use_server_proxy else ' no'}")
    print(f"  Image:           {args.image}")
    print()

    config = ConnectionConfig(
        domain=args.domain,
        api_key=args.api_key,
        protocol=args.protocol,
        use_server_proxy=args.use_server_proxy,
        request_timeout=timedelta(seconds=30),
    )

    selected = select_tests(args)
    if not selected:
        print(f"{C.YELLOW}No tests selected.{C.RESET}")
        return 0

    # --- Provision a single sandbox for the whole run ---
    print(f"{C.BOLD}Provisioning sandbox...{C.RESET}")
    provision_start = time.monotonic()
    try:
        sandbox = await Sandbox.create(
            args.image,
            connection_config=config,
            timeout=timedelta(minutes=10),
            ready_timeout=timedelta(seconds=args.ready_timeout),
        )
    except SandboxReadyTimeoutException as e:
        print(f"{C.RED}Sandbox failed to become ready within "
              f"{args.ready_timeout}s:{C.RESET} {e}")
        return 1
    except SandboxApiException as e:
        print(f"{C.RED}Server rejected provisioning request "
              f"(HTTP {e.status_code}):{C.RESET} {e}")
        if args.verbose:
            traceback.print_exc()
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"{C.RED}Could not reach server at {args.protocol}://{args.domain}:{C.RESET}"
              f" {type(e).__name__}: {e}")
        if args.verbose:
            traceback.print_exc()
        print()
        print(f"{C.DIM}Hints:{C.RESET}")
        print(f"  • Is the server running and listening on {args.domain}?")
        print(f"  • If using Docker bridge networking, try {C.BOLD}--use-server-proxy{C.RESET}.")
        print(f"  • Check that {C.BOLD}--protocol{C.RESET} matches the server (http vs https).")
        return 1

    provisioned_in = time.monotonic() - provision_start
    print(f"  {C.GREEN}✓{C.RESET} sandbox {C.DIM}{sandbox.id}{C.RESET} ready "
          f"{C.DIM}({provisioned_in:.2f}s){C.RESET}")
    print()

    runner = TestRunner(sandbox, sdk, verbose=args.verbose)

    print(f"{C.BOLD}Running {len(selected)} test(s)...{C.RESET}")
    try:
        for name, fn, desc in selected:
            await runner.run(f"{name:<12} {C.DIM}— {desc}{C.RESET}", lambda fn=fn: fn(sandbox, sdk))
    finally:
        print()
        print(f"{C.BOLD}Tearing down sandbox...{C.RESET}")
        try:
            await sandbox.kill()
            print(f"  {C.GREEN}✓{C.RESET} sandbox terminated")
        except Exception as e:  # noqa: BLE001
            print(f"  {C.RED}✗{C.RESET} kill failed: {type(e).__name__}: {e}")

    ok = runner.summary()
    return 0 if ok else 1


def main() -> int:
    args = parse_args()
    if args.no_color or not sys.stdout.isatty():
        C.disable()
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Interrupted.{C.RESET}", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())