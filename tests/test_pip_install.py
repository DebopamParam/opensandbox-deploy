#!/usr/bin/env python3
"""
Pip Install Test
================

Verifies that sandbox containers can install Python packages at runtime using
both pip and uv.

Usage:
    python tests/test_pip_install.py

    # Against a remote server
    python tests/test_pip_install.py --domain 35.207.234.60:8080 --api-key <key>

    # With Docker bridge networking
    python tests/test_pip_install.py --use-server-proxy

Exit code is 0 if all tests pass, 1 otherwise.
"""

import argparse
import asyncio
import os
import sys
import time
import traceback
from datetime import timedelta
from typing import Awaitable, Callable, List, Tuple


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


def _import_sdk():
    try:
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
        from opensandbox.models.execd import RunCommandOpts
        from opensandbox.exceptions import SandboxApiException, SandboxReadyTimeoutException
    except ImportError as e:
        print(
            f"{C.RED}ERROR:{C.RESET} could not import opensandbox SDK.\n"
            f"  {e}\n\nInstall with: pip install opensandbox",
            file=sys.stderr,
        )
        sys.exit(2)
    return {
        "Sandbox": Sandbox,
        "ConnectionConfig": ConnectionConfig,
        "RunCommandOpts": RunCommandOpts,
        "SandboxApiException": SandboxApiException,
        "SandboxReadyTimeoutException": SandboxReadyTimeoutException,
    }


class TestRunner:
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
            print(f"{C.RED}{C.BOLD}{total - passed} of {total} tests failed.{C.RESET}")
        return passed == total


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

async def test_pip_available(sandbox, sdk):
    res = await sandbox.commands.run("pip --version")
    assert res.exit_code == 0, f"pip not found: {res.text}"
    assert "pip" in res.text.lower(), f"unexpected output: {res.text!r}"


async def test_uv_available(sandbox, sdk):
    res = await sandbox.commands.run("uv --version")
    assert res.exit_code == 0, f"uv not found: {res.text}"
    assert "uv" in res.text.lower(), f"unexpected output: {res.text!r}"


async def test_pip_install(sandbox, sdk):
    # cowsay: tiny pure-Python package with no transitive deps
    res = await sandbox.commands.run("pip install cowsay")
    assert res.exit_code == 0, f"pip install failed (exit {res.exit_code}):\n{res.text}"
    assert "successfully installed" in res.text.lower() or "already satisfied" in res.text.lower(), (
        f"unexpected pip output:\n{res.text}"
    )


async def test_pip_installed_package_works(sandbox, sdk):
    res = await sandbox.commands.run("python -c \"import cowsay; cowsay.cow('hello')\"")
    assert res.exit_code == 0, f"imported package failed (exit {res.exit_code}):\n{res.text}"
    assert "hello" in res.text, f"cowsay output missing: {res.text!r}"


async def test_uv_pip_install(sandbox, sdk):
    res = await sandbox.commands.run("uv pip install --system pytz")
    assert res.exit_code == 0, f"uv pip install failed (exit {res.exit_code}):\n{res.text}"


async def test_uv_installed_package_works(sandbox, sdk):
    res = await sandbox.commands.run(
        "python -c \"import pytz; tz = pytz.timezone('UTC'); print(tz)\""
    )
    assert res.exit_code == 0, f"pytz import failed (exit {res.exit_code}):\n{res.text}"
    assert "UTC" in res.text, f"unexpected output: {res.text!r}"


async def test_pip_install_with_version_pin(sandbox, sdk):
    res = await sandbox.commands.run("pip install 'six>=1.16'")
    assert res.exit_code == 0, f"pip install (pinned) failed (exit {res.exit_code}):\n{res.text}"


async def test_pip_install_no_break_system_flag_needed(sandbox, sdk):
    # Ensure PIP_BREAK_SYSTEM_PACKAGES=1 means we never need --break-system-packages
    res = await sandbox.commands.run(
        "env -u PIP_BREAK_SYSTEM_PACKAGES pip install --dry-run cowsay 2>&1 || true"
    )
    # If the env var is inherited the install proceeds; if stripped we might see the
    # externally-managed error. We assert it does NOT appear.
    assert "externally-managed-environment" not in res.text, (
        f"PIP_BREAK_SYSTEM_PACKAGES not set — got externally-managed error:\n{res.text}"
    )


async def test_pip_install_multiple_packages(sandbox, sdk):
    res = await sandbox.commands.run("pip install tomli python-dateutil")
    assert res.exit_code == 0, f"multi-package install failed (exit {res.exit_code}):\n{res.text}"


async def test_installed_packages_persist_in_session(sandbox, sdk):
    session_id = await sandbox.commands.create_session()
    try:
        r1 = await sandbox.commands.run_in_session(session_id, "pip install colorama -q")
        assert r1.exit_code == 0, f"install in session failed:\n{r1.text}"

        r2 = await sandbox.commands.run_in_session(
            session_id, "python -c \"import colorama; print('ok')\""
        )
        assert r2.exit_code == 0 and "ok" in r2.text, (
            f"package installed in session not importable: {r2.text!r}"
        )
    finally:
        await sandbox.commands.delete_session(session_id)


TESTS: List[Tuple[str, Callable, str]] = [
    ("pip-avail",       test_pip_available,                         "pip is on PATH"),
    ("uv-avail",        test_uv_available,                          "uv is on PATH"),
    ("pip-install",     test_pip_install,                           "pip install cowsay"),
    ("pip-import",      test_pip_installed_package_works,           "cowsay import + run"),
    ("uv-install",      test_uv_pip_install,                        "uv pip install pytz"),
    ("uv-import",       test_uv_installed_package_works,            "pytz import + use"),
    ("pip-pin",         test_pip_install_with_version_pin,          "pip install with version pin"),
    ("no-break-flag",   test_pip_install_no_break_system_flag_needed,"no --break-system-packages needed"),
    ("pip-multi",       test_pip_install_multiple_packages,         "pip install multiple packages"),
    ("session-persist", test_installed_packages_persist_in_session, "install persists within session"),
]


# ---------------------------------------------------------------------------
# CLI / orchestration
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Test pip/uv package installation inside OpenSandbox sandboxes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--domain", default=os.environ.get("OPEN_SANDBOX_DOMAIN"),
                   help="Server domain as host:port (default: localhost:8080 or $OPEN_SANDBOX_DOMAIN).")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--protocol", choices=("http", "https"), default="http")
    p.add_argument("--api-key", default=os.environ.get("OPEN_SANDBOX_API_KEY", ""))
    p.add_argument("--use-server-proxy", action="store_true",
                   help="Route execd traffic through the server (required with Docker bridge networking).")
    p.add_argument("--image", default=os.environ.get("SANDBOX_IMAGE", "opensandbox-base:latest"),
                   help="Sandbox image to use (default: opensandbox-base:latest).")
    p.add_argument("--ready-timeout", type=int, default=120,
                   help="Seconds to wait for sandbox to become ready (default: 120).")
    p.add_argument("--skip", action="append", default=[], metavar="NAME")
    p.add_argument("--only", action="append", default=[], metavar="NAME")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--no-color", action="store_true")
    args = p.parse_args()
    if not args.domain:
        args.domain = f"{args.host}:{args.port}"
    if args.skip and args.only:
        p.error("--skip and --only are mutually exclusive")
    valid = {name for name, _, _ in TESTS}
    for n in args.skip + args.only:
        if n not in valid:
            p.error(f"unknown test: {n!r}. Valid: {', '.join(sorted(valid))}")
    return args


def select_tests(args):
    if args.only:
        return [(n, f, d) for n, f, d in TESTS if n in args.only]
    if args.skip:
        return [(n, f, d) for n, f, d in TESTS if n not in args.skip]
    return list(TESTS)


async def amain(args) -> int:
    sdk = _import_sdk()
    Sandbox = sdk["Sandbox"]
    ConnectionConfig = sdk["ConnectionConfig"]
    SandboxReadyTimeoutException = sdk["SandboxReadyTimeoutException"]
    SandboxApiException = sdk["SandboxApiException"]

    print(f"{C.BOLD}OpenSandbox Pip Install Test{C.RESET}")
    print(f"  Endpoint: {C.BLUE}{args.protocol}://{args.domain}{C.RESET}")
    print(f"  Image:    {args.image}")
    print()

    config = ConnectionConfig(
        domain=args.domain,
        api_key=args.api_key,
        protocol=args.protocol,
        use_server_proxy=args.use_server_proxy,
        request_timeout=timedelta(seconds=60),
    )

    selected = select_tests(args)
    if not selected:
        print(f"{C.YELLOW}No tests selected.{C.RESET}")
        return 0

    print(f"{C.BOLD}Provisioning sandbox ({args.image})...{C.RESET}")
    t0 = time.monotonic()
    try:
        sandbox = await Sandbox.create(
            args.image,
            connection_config=config,
            timeout=timedelta(minutes=15),
            ready_timeout=timedelta(seconds=args.ready_timeout),
        )
    except SandboxReadyTimeoutException as e:
        print(f"{C.RED}Sandbox not ready within {args.ready_timeout}s:{C.RESET} {e}")
        return 1
    except SandboxApiException as e:
        print(f"{C.RED}Server rejected request (HTTP {e.status_code}):{C.RESET} {e}")
        if args.verbose:
            traceback.print_exc()
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"{C.RED}Could not reach {args.protocol}://{args.domain}:{C.RESET} {type(e).__name__}: {e}")
        if args.verbose:
            traceback.print_exc()
        print(f"\n{C.DIM}Hints:{C.RESET}")
        print(f"  • Is the server running on {args.domain}?")
        print(f"  • If using Docker bridge networking, try {C.BOLD}--use-server-proxy{C.RESET}.")
        return 1

    print(f"  {C.GREEN}✓{C.RESET} sandbox {C.DIM}{sandbox.id}{C.RESET} ready "
          f"{C.DIM}({time.monotonic() - t0:.2f}s){C.RESET}")
    print()

    runner = TestRunner(sandbox, sdk, verbose=args.verbose)
    print(f"{C.BOLD}Running {len(selected)} test(s)...{C.RESET}")
    try:
        for name, fn, desc in selected:
            await runner.run(
                f"{name:<14} {C.DIM}— {desc}{C.RESET}",
                lambda fn=fn: fn(sandbox, sdk),
            )
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
