#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0

"""Bounded validation of the PATH-selected migration MCP server.

Exits 0 for VERIFIED/UNVERIFIED. Exits 1 for INCOMPATIBLE so SessionStart
cannot proceed with a stale PATH scai as the plugin MCP server.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

_TIMEOUT_SECONDS = float(os.environ.get("SCAI_MCP_VALIDATION_TIMEOUT_SECONDS", "3"))
_REQUEST_ID = "session-start-validation"
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?\b")

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_LOG = _PLUGIN_ROOT / "logs" / "mcp-server-validation.log"


def report(kind: str, message: str) -> None:
    line = f"SCAI_MCP_{kind}: {message}"
    _LOG.parent.mkdir(parents=True, exist_ok=True)
    with _LOG.open("a", encoding="utf-8") as log:
        log.write(line + "\n")
    print(line, file=sys.stderr, flush=True)


def application_version(output: str) -> Optional[str]:
    """Extract the reported version from scai's boxed --version table (the
    ``Application`` row) or, absent a table, a plain ``scai 2.39.0`` line."""
    plain_match: Optional[str] = None
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.replace("│", "|").split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2 and cells[0] == "Application":
            match = _VERSION_RE.search(cells[1])
            if match:
                return match.group(0)
        elif "│" not in line and plain_match is None:
            match = _VERSION_RE.search(line)
            if match:
                plain_match = match.group(0)
    return plain_match


def read_stream(stream, output: queue.Queue[Tuple[str, Optional[str]]], kind: str) -> None:
    try:
        for line in iter(stream.readline, ""):
            output.put((kind, line.rstrip("\r\n")))
    finally:
        output.put((f"{kind}-eof", None))


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=0.5)


def drain_stderr(output: queue.Queue[Tuple[str, Optional[str]]]) -> list[str]:
    """Read child stderr the reader thread already has, or will have shortly.

    A stale ``scai mcp run`` can exit before ``initialize`` is flushed. The
    broken-pipe handler must wait for those lines or the CLI diagnostic is lost.
    """
    lines: list[str] = []
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            kind, line = output.get(timeout=min(0.05, max(remaining, 0.0)))
        except queue.Empty:
            continue
        if kind == "stderr" and line:
            lines.append(line)
        elif kind == "stderr-eof":
            break
    return lines


def early_exit_message(
    executable: str,
    version: str,
    returncode: object,
    stderr_lines: list[str],
    fallback: str,
) -> Tuple[str, str]:
    detail = "; ".join(stderr_lines[-3:]) or fallback
    return (
        "INCOMPATIBLE",
        f"'{executable} mcp run' ({version}) exited before initialize "
        f"(status {returncode}); {detail}",
    )


def handshake(executable: str, version: str) -> Tuple[str, str]:
    try:
        process = subprocess.Popen(
            [executable, "mcp", "run"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as error:
        return "INCOMPATIBLE", f"could not launch '{executable} mcp run' ({version}): {error}"

    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    output: queue.Queue[Tuple[str, Optional[str]]] = queue.Queue()
    stderr_lines: list[str] = []
    threading.Thread(
        target=read_stream, args=(process.stdout, output, "stdout"), daemon=True
    ).start()
    threading.Thread(
        target=read_stream, args=(process.stderr, output, "stderr"), daemon=True
    ).start()

    request = {
        "jsonrpc": "2.0",
        "id": _REQUEST_ID,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "migration-plugin-session-start", "version": "1"},
        },
    }
    try:
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError) as error:
        stderr_lines.extend(drain_stderr(output))
        returncode = process.poll()
        if returncode is None:
            returncode = "unknown"
        return early_exit_message(
            executable, version, returncode, stderr_lines, str(error)
        )

    deadline = time.monotonic() + _TIMEOUT_SECONDS
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                detail = "; ".join(stderr_lines[-3:]) or "no diagnostic output"
                return (
                    "UNVERIFIED",
                    f"initialize timed out after {_TIMEOUT_SECONDS:g}s for "
                    f"'{executable} mcp run' ({version}); {detail}",
                )
            try:
                kind, line = output.get(timeout=remaining)
            except queue.Empty:
                continue
            if kind == "stderr" and line:
                stderr_lines.append(line)
                continue
            if kind == "stdout-eof":
                returncode = process.poll()
                if returncode is None:
                    try:
                        returncode = process.wait(timeout=0.1)
                    except subprocess.TimeoutExpired:
                        returncode = "unknown"
                return early_exit_message(
                    executable,
                    version,
                    returncode,
                    stderr_lines,
                    "no diagnostic output",
                )
            if kind != "stdout" or not line:
                continue
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != _REQUEST_ID:
                continue
            if "result" in response:
                return (
                    "VERIFIED",
                    f"executable={executable} version={version} "
                    f"server='{executable} mcp run' initialize=ok",
                )
            return (
                "INCOMPATIBLE",
                f"'{executable} mcp run' ({version}) rejected initialize: "
                f"{response.get('error', response)}",
            )
    finally:
        stop_process(process)


def main() -> int:
    executable = shutil.which("scai")
    if not executable:
        report("INCOMPATIBLE", "executable 'scai' was not found on PATH")
        return 1

    version = "unknown version"
    try:
        version_result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
        )
        parsed = application_version(version_result.stdout + version_result.stderr)
        if parsed:
            version = parsed
    except (OSError, subprocess.TimeoutExpired):
        # Cosmetic only: handshake is the authoritative probe and does not
        # need a version. An unreadable --version must not skip mcp run.
        pass

    kind, message = handshake(executable, version)
    report(kind, message)
    # INCOMPATIBLE must block SessionStart: the same PATH entry would otherwise
    # become the plugin MCP server. VERIFIED/UNVERIFIED stay non-blocking.
    if kind == "INCOMPATIBLE":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
