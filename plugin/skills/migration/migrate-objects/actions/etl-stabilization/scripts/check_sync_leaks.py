#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Detect test-environment / credential leaks before syncing fixes back.

Usage:
    python check_sync_leaks.py <session_status.json> [--original <path>] <file1> [[--original <path>] <file2> ...]

A `--original <path>` immediately before a file pairs that file with its pre-fix
copy (e.g. under `stabilization/original/`): a match that already exists
anywhere in the original is pre-existing, not a leak introduced by this sync.

Exit 1 if any leak is found; exit 0 with a one-line summary otherwise.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Matches any ad hoc test schema this skill creates, not just the orchestration
# flavor's phase-numbered shape (`ETL_FIX_P1_B2`) -- a unit-prefixed schema with
# no phase number (`ETL_FIX_<unit>`) is just as much a leak signal.
ETL_FIX_RE = re.compile(r"ETL_FIX_\w+")
CREDENTIAL_KEY_RE = re.compile(
    r"^\s*(password|account|authenticator|private_key_path)\s*:\s*(.*?)\s*$"
)
PLACEHOLDER_VALUE_RE = re.compile(r"^(YOUR_|your_)")
ENV_VAR_RE = re.compile(r"\{\{\s*env_var\s*\(")

# SnowConvert's own default output schema (e.g. `PUBLIC.TO_NUMBER_UDF`) -- never a
# leak signal on its own, or every converted file flags as leaking. A real stored
# test schema should never be set to this (the skill no longer recommends it).
DEFAULT_SCHEMA_VALUES = {"public"}


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _is_placeholder_credential(value: str) -> bool:
    stripped = value.strip().strip("\"'")
    if not stripped:
        return True
    if PLACEHOLDER_VALUE_RE.match(stripped):
        return True
    if ENV_VAR_RE.search(stripped):
        return True
    return False


def _is_default_schema(value: str) -> bool:
    return value.strip().strip("\"'").lower() in DEFAULT_SCHEMA_VALUES


def check_file(
    path: Path, database: str, schema: str, original_lines: list[str] | None = None
) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    is_profiles = path.name == "profiles.yml"
    original_text = "\n".join(original_lines) if original_lines else None

    def _pre_existing(token: str) -> bool:
        return original_text is not None and token in original_text

    for i, line in enumerate(text.splitlines(), 1):

        if database and not _is_default_schema(database) and database in line and not _pre_existing(database):
            hits.append((i, database))
        if schema and not _is_default_schema(schema) and schema in line and not _pre_existing(schema):
            hits.append((i, schema))
        etl_match = ETL_FIX_RE.search(line)
        if etl_match and not _pre_existing(etl_match.group(0)):
            hits.append((i, etl_match.group(0)))
        if is_profiles:
            cred = CREDENTIAL_KEY_RE.match(line)
            if cred and not _is_placeholder_credential(cred.group(2)):
                hits.append((i, cred.group(1) + ":"))
    return hits


def _parse_file_args(args: list[str]) -> list[tuple[Path, Path | None]]:
    """Pair each file with an optional preceding `--original <path>`."""
    pairs: list[tuple[Path, Path | None]] = []
    pending_original: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--original":
            if i + 1 >= len(args):
                print("Error: --original requires a path argument", file=sys.stderr)
                sys.exit(1)
            pending_original = Path(args[i + 1])
            i += 2
            continue
        pairs.append((Path(args[i]), pending_original))
        pending_original = None
        i += 1
    return pairs


def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage: python check_sync_leaks.py <session_status.json> [--original <path>] "
            "<file1> [[--original <path>] <file2> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    status_path = Path(sys.argv[1])
    if not status_path.is_file():
        print(f"Error: '{status_path}' not found", file=sys.stderr)
        sys.exit(1)

    session = load_json(status_path)
    test_env = session.get("test_environment") or {}
    database = test_env.get("database") or ""
    schema = test_env.get("schema") or ""

    pairs = _parse_file_args(sys.argv[2:])
    any_hits = False
    for path, original in pairs:
        if not path.is_file():
            print(f"Error: '{path}' not found", file=sys.stderr)
            sys.exit(1)
        original_lines = None
        if original is not None:
            if not original.is_file():
                print(f"Error: original '{original}' not found", file=sys.stderr)
                sys.exit(1)
            original_lines = original.read_text(encoding="utf-8", errors="replace").splitlines()
        for line_no, pattern in check_file(path, database, schema, original_lines):
            print(f"{path}:{line_no}: matched '{pattern}'")
            any_hits = True

    if any_hits:
        sys.exit(1)

    print(f"no leaks found in {len(pairs)} files")


if __name__ == "__main__":
    main()
