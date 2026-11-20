#!/usr/bin/env python3
"""Check, before a local worker starts on macOS, that the SQL Server driver can load OpenSSL.

Microsoft's SQL Server driver on macOS (``msodbcsql18``, and the copy that
``mssql-python`` bundles) loads OpenSSL when it connects, accepts only OpenSSL
1.0, 1.1 or 3.x, and looks for it in one place: Homebrew's ``openssl`` alias,
``<brew prefix>/opt/openssl``. Installing ``msodbcsql18`` can pull in
``openssl@4`` and move that alias to it; every connection then fails with
"OpenSSL library could not be loaded", and installing ``openssl@3`` alone does
not move the alias back.

This script only reads: it never changes Homebrew. On a problem it prints a
``FAILED:`` line with the command the user can run (no ``sudo``) and exits 1;
otherwise it prints ``OK:`` and exits 0. ``--driver`` also checks that an ODBC
Driver for SQL Server is registered (``odbcinst -q -d``), for hosts that
connect through ``pyodbc``. Stdlib only, Python 3.9+ (macOS ships 3.9).
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

# libssl names the driver accepts, newest first (OpenSSL 3.x, 1.1, 1.0).
_ACCEPTED_LIBSSL = ("libssl.3.dylib", "libssl.1.1.dylib", "libssl.1.0.0.dylib")


def brew_prefix(run: Runner = subprocess.run, machine: str | None = None) -> Path:
    """Homebrew's prefix from ``brew --prefix``, else its default for this CPU."""
    if shutil.which("brew"):
        proc = run(["brew", "--prefix"], capture_output=True, text=True, check=False)
        if proc.returncode == 0 and proc.stdout.strip():
            return Path(proc.stdout.strip())
    arch = (machine or platform.machine()).lower()
    return Path("/opt/homebrew") if arch in ("arm64", "aarch64") else Path("/usr/local")


def openssl_version(target: Path) -> str | None:
    """The OpenSSL version a resolved alias points at, from its Cellar directory name."""
    match = re.match(r"^(\d+(?:\.\d+)*)", target.name)
    return match.group(1) if match else None


def accepted(version: str) -> bool:
    """Whether the driver loads this OpenSSL version: 1.0, 1.1 or 3.x."""
    parts = version.split(".")
    if parts[0] == "3":
        return True
    return parts[0] == "1" and len(parts) > 1 and parts[1] in ("0", "1")


def _q(path: Path) -> str:
    return shlex.quote(str(path))


def repoint_hint(prefix: Path, current: str) -> str:
    """The user-run, no-sudo repair: point the alias at openssl@3, installing it first if needed."""
    alias = prefix / "opt" / "openssl"
    openssl3 = prefix / "opt" / "openssl@3"
    steps = []
    if not (openssl3 / "lib" / "libssl.3.dylib").exists():
        steps.append("brew install openssl@3")
    steps.append(f"ln -sfn {_q(openssl3)} {_q(alias)}")
    undo = f" To undo: ln -sfn {shlex.quote(current)} {_q(alias)}." if current else ""
    return (
        "Ask the user to run (no sudo needed): "
        + " && ".join(steps)
        + f".{undo} A later brew upgrade may move the alias again; re-run this check after one."
    )


def check_openssl(prefix: Path) -> list[str]:
    """Problems with Homebrew's openssl alias under ``prefix``; empty when the driver can load it."""
    alias = prefix / "opt" / "openssl"
    if not alias.exists():
        return [
            f"{alias} does not exist, so the SQL Server driver finds no OpenSSL. "
            + repoint_hint(prefix, "")
        ]
    current = os.readlink(alias) if alias.is_symlink() else ""
    target = alias.resolve()
    version = openssl_version(target)
    if version is not None and not accepted(version):
        return [
            f"{alias} points at OpenSSL {version} ({target}); the SQL Server driver loads only "
            "OpenSSL 1.0, 1.1 or 3.x, so every connection fails with "
            '"OpenSSL library could not be loaded". ' + repoint_hint(prefix, current)
        ]
    if not any((alias / "lib" / name).exists() for name in _ACCEPTED_LIBSSL):
        return [
            f"{alias}/lib holds none of {', '.join(_ACCEPTED_LIBSSL)} ({target}). "
            + repoint_hint(prefix, current)
        ]
    return []


def check_driver(run: Runner = subprocess.run) -> list[str]:
    """Problems finding a registered ODBC Driver for SQL Server."""
    if shutil.which("odbcinst") is None:
        return ["odbcinst is not on PATH: unixODBC and msodbcsql18 are not installed."]
    proc = run(["odbcinst", "-q", "-d"], capture_output=True, text=True, check=False)
    if not re.search(r"ODBC Driver \d+ for SQL Server", proc.stdout or ""):
        return [
            "No ODBC Driver for SQL Server is registered (odbcinst -q -d lists none)."
        ]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--driver",
        action="store_true",
        help="also check that an ODBC Driver for SQL Server is registered",
    )
    parser.add_argument(
        "--brew-prefix",
        type=Path,
        help="Homebrew's prefix (default: brew --prefix)",
    )
    return parser


def main(argv: Sequence[str] | None = None, run: Runner = subprocess.run) -> int:
    args = build_parser().parse_args(argv)
    if sys.platform != "darwin" and args.brew_prefix is None:
        print("OK: not macOS; nothing to check.")
        return 0
    prefix = args.brew_prefix or brew_prefix(run)
    problems = check_openssl(prefix)
    if args.driver:
        problems += check_driver(run)
    for problem in problems:
        print(f"FAILED: {problem}")
    if problems:
        return 1
    target = (prefix / "opt" / "openssl").resolve()
    print(f"OK: the SQL Server driver can load OpenSSL from {target}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
