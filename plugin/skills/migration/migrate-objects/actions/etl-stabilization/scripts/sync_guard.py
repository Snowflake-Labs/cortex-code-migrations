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

"""Guard a shared mapping-procedure / dbt-project sync-back -- SNOW-4221309, SNOW-4221304.

A dbt project or mapping procedure referenced by more than one sibling unit is
staged into each unit's own folder (see SKILL.md "When the converted-output
folder is not isolated"). Between staging and this unit's fix landing, another
unit's session may have already synced its own fix back to the same canonical
file, or may be sitting on its own different staged fix of the same file.
Overwriting canonical unconditionally would silently discard that other work.

Before authorizing a write, this guard compares up to four copies of the same
shared file:
  - `--backup`    this unit's pre-fix snapshot (taken at staging time)
  - `--current`   this unit's fixed, staged copy -- the bytes that would land
                   on canonical (required to use `--apply`, or to detect
                   sibling drift)
  - `--canonical` the shared file other units read and write today
  - `--sibling`   another staged unit's current copy of the same shared file
                   (repeatable)

Usage:
    python sync_guard.py --canonical <path> --backup <path> --fix-log <path> \
        --element <name> [--current <path>] [--sibling <path> ...] [--apply]

Exit 0 ("ok to sync") when:
  - there is no canonical file yet (first write, not a conflict), or
  - canonical bytes still match the pre-fix backup AND no supplied sibling's
    bytes differ from `--current`, or
  - canonical already holds exactly this unit's `--current` bytes (a prior
    sync already landed; retrying is a no-op), or
  - a drift was found, but fix-log.md already records a
    `<!-- sync-winner: element=<name> winner=this-unit ... -->` marker for
    <element>. A `winner=other-unit` marker is a real, logged decision -- it
    just never authorizes *this* unit to overwrite canonical.

Exit 1 ("do not sync") otherwise, with the fix-log line to add before
retrying. On exit 1 canonical is never touched: the drift/winner checks run
to completion strictly before any write, and `--apply` only performs that
write once every check has already passed in the same process -- so there is
no separate copy step that could run after a failed guard call.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_SYNC_WINNER_RE = re.compile(r"<!--\s*sync-winner:\s*(.*?)\s*-->")
_FIELD_RE = re.compile(r'(\w+)=("[^"]*"|\S+)')


def _parse_sync_winners(text: str) -> list[dict]:
    winners: list[dict] = []
    for m in _SYNC_WINNER_RE.finditer(text):
        fields: dict = {}
        for fm in _FIELD_RE.finditer(m.group(1)):
            fields[fm.group(1)] = fm.group(2).strip('"')
        winners.append(fields)
    return winners


def get_sync_winner(fix_log_text: str, element: str) -> dict | None:
    """Return the most recent sync-winner record for `element`, or None.

    fix-log.md is append-only (see reference/templates/fix-log-format.md), so
    the last matching record is the current decision.
    """
    matches = [w for w in _parse_sync_winners(fix_log_text) if w.get("element") == element]
    return matches[-1] if matches else None


def has_sync_winner(fix_log_text: str, element: str) -> bool:
    """True iff a decision exists AND it authorizes overwriting with *this* unit's bytes.

    `winner=other-unit` is a deliberate decision too -- it must never be read
    as permission for this unit to overwrite canonical.
    """
    winner = get_sync_winner(fix_log_text, element)
    return winner is not None and winner.get("winner") == "this-unit"


def _read_fix_log(fix_log: Path) -> str:
    return fix_log.read_text(encoding="utf-8", errors="replace") if fix_log.is_file() else ""


def _winner_marker_hint(element: str, fix_log: Path) -> str:
    return (
        f"Add a '<!-- sync-winner: element={element} winner=<this-unit|other-unit> "
        f"reason=<why> -->' record to {fix_log} before overwriting."
    )



def discover_siblings(staged_root: Path, current: Path) -> list[Path]:
    """Other unit directories under staged_root that hold the same relative file."""
    if not staged_root.is_dir():
        raise ValueError(f"staged root '{staged_root}' is not a directory")
    try:
        rel = current.resolve().relative_to(staged_root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"current '{current}' is not under staged root '{staged_root}'"
        ) from exc
    if len(rel.parts) < 2:
        raise ValueError(
            f"current '{current}' is not inside a unit directory under '{staged_root}'"
        )
    rest = Path(*rel.parts[1:])
    unit = rel.parts[0]
    found: list[Path] = []
    for child in sorted(staged_root.iterdir()):
        if not child.is_dir() or child.name == unit or child.name.startswith("."):
            continue
        candidate = child / rest
        if candidate.is_file():
            found.append(candidate)
    return found


def check_sync(
    canonical: Path,
    backup: Path,
    fix_log: Path,
    element: str,
    *,
    current: Path | None = None,
    siblings: tuple[Path, ...] = (),
) -> str | None:
    """Return None if sync-back may proceed, else a human-readable error.

    A missing canonical file is a first write, not a conflict with canonical.
    Sibling copies are still compared, so a different staged copy blocks the
    write even when canonical does not exist yet.
    """
    if current is not None and not current.is_file():
        return f"current '{current}' not found -- cannot verify drift for '{element}'"

    current_bytes = current.read_bytes() if current is not None else None

    if canonical.is_file():
        if not backup.is_file():
            return f"backup '{backup}' not found -- cannot verify canonical drift for '{element}'"

        canonical_bytes = canonical.read_bytes()

        if canonical_bytes != backup.read_bytes():
            already_synced = current_bytes is not None and canonical_bytes == current_bytes
            if not already_synced:
                fix_log_text = _read_fix_log(fix_log)
                winner = get_sync_winner(fix_log_text, element)
                if winner is None:
                    return (
                        f"canonical '{canonical}' differs from the pre-fix backup '{backup}' for "
                        f"'{element}' -- another writer touched it since staging. "
                        f"{_winner_marker_hint(element, fix_log)}"
                    )
                if winner.get("winner") != "this-unit":
                    return (
                        f"canonical '{canonical}' differs from the pre-fix backup '{backup}' for "
                        f"'{element}', and {fix_log} already records winner="
                        f"'{winner.get('winner')}' for it -- that decision does not authorize "
                        f"overwriting canonical with this unit's version."
                    )


    for sibling in siblings:
        if not sibling.is_file():
            continue
        if current_bytes is None:
            return (
                f"sibling staged copy '{sibling}' was supplied for '{element}' but --current "
                f"was not -- cannot verify sibling drift without this unit's staged file"
            )
        if sibling.read_bytes() == current_bytes:
            continue
        fix_log_text = _read_fix_log(fix_log)
        winner = get_sync_winner(fix_log_text, element)
        if winner is None:
            return (
                f"sibling staged copy '{sibling}' differs from this unit's current version of "
                f"'{element}' -- another unit staged a different fix. "
                f"{_winner_marker_hint(element, fix_log)}"
            )
        if winner.get("winner") != "this-unit":
            return (
                f"sibling staged copy '{sibling}' differs from this unit's current version of "
                f"'{element}', and {fix_log} already records winner="
                f"'{winner.get('winner')}' for it -- that decision does not authorize "
                f"overwriting canonical with this unit's version."
            )

    return None


def apply_sync(canonical: Path, current: Path) -> None:
    """Atomically write `current`'s bytes onto `canonical`.

    Only call after check_sync() has returned None. Writes to a sibling temp
    file first and renames over canonical, so a crash mid-write cannot leave
    canonical half-written.
    """
    current_bytes = current.read_bytes()
    if canonical.is_file() and canonical.read_bytes() == current_bytes:
        return  # already in sync
    tmp = canonical.with_name(canonical.name + ".sync-tmp")
    tmp.write_bytes(current_bytes)
    tmp.replace(canonical)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canonical", required=True, type=Path)
    ap.add_argument("--backup", required=True, type=Path)
    ap.add_argument(
        "--current",
        type=Path,
        default=None,
        help="this unit's staged fix -- the bytes that would be written to canonical",
    )
    ap.add_argument("--fix-log", required=True, type=Path)
    ap.add_argument("--element", required=True)
    ap.add_argument(
        "--staged-root",
        type=Path,
        default=None,
        help=(
            "Output/ETL directory. Other unit folders that contain the same relative "
            "path as --current are compared as siblings, including when canonical is missing"
        ),
    )
    ap.add_argument(
        "--sibling",
        action="append",
        default=[],
        type=Path,
        dest="siblings",
        help="another staged unit's current copy of the same shared file; repeatable",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help=(
            "atomically copy --current onto --canonical once every check passes; "
            "requires --current; never runs when a check fails"
        ),
    )
    args = ap.parse_args()

    if args.apply and args.current is None:
        print("Error: --apply requires --current", file=sys.stderr)
        sys.exit(1)

    siblings = list(args.siblings)
    if args.staged_root is not None:
        if args.current is None:
            print("Error: --staged-root requires --current", file=sys.stderr)
            sys.exit(1)
        try:
            siblings.extend(discover_siblings(args.staged_root, args.current))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    error = check_sync(
        args.canonical,
        args.backup,
        args.fix_log,
        args.element,
        current=args.current,
        siblings=tuple(siblings),
    )
    if error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)

    if args.apply:
        apply_sync(args.canonical, args.current)
        print(f"synced '{args.element}' to {args.canonical}")
    else:
        print(f"ok to sync '{args.element}'")


if __name__ == "__main__":
    main()
