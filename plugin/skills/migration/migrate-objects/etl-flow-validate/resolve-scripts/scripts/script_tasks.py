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

"""Inventory, resolve and check SSC-EWI-SSIS0004 blocks in converted SSIS orchestration SQL.

Usage:
    script_tasks.py inventory --project-dir P --unit-id ID
    script_tasks.py apply     --project-dir P --unit-id ID --plan plan.json
    script_tasks.py check     --project-dir P --unit-id ID

Exit codes: 0 ok, 2 usage or input error, 3 check failed, 4 plan refused.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

ISSUE_CODE = "SSC-EWI-SSIS0004"
SCRIPT_TASK = "Microsoft.ScriptTask"
RESOLVED_TAG = f"{ISSUE_CODE} resolved:"
NEEDS_USER_TAG = f"{ISSUE_CODE} needs manual migration:"

EXIT_OK, EXIT_USAGE, EXIT_CHECK_FAILED, EXIT_PLAN_REFUSED = 0, 2, 3, 4

RE_MARKER = re.compile(
    r"^(?P<indent>[ \t]*)!!!RESOLVE EWI!!!\s*/\*\*\*\s*SSC-EWI-SSIS0004\s*-\s*"
    r"SSIS CONTROL FLOW ELEMENT (?P<type>.+?) CANNOT BE CONVERTED.*?\*\*\*/!!!\s*$"
)
RE_TAG = re.compile(r"^\s*----\s+(?:Start|End)(?:\s+block)?\s+'([^']+)'")
RE_START_TAG = re.compile(r"^\s*----\s+Start(?:\s+block)?\s+'([^']+)'")
RE_TERMINATOR = re.compile(r"^\s*(NULL)?\s*;\s*$")
RE_CREATE = re.compile(r"^\s*CREATE\s", re.IGNORECASE)
RE_EXECUTABLE = re.compile(r"<Executable\b[^>]*>")
RE_ATTR = re.compile(r'\b(?:DTS:)?(\w+)="([^"]*)"')
RE_SCRIPTMAIN = re.compile(
    r'<ProjectItem\s+Name="ScriptMain\.(?:cs|vb)"[^>]*>(.*?)</ProjectItem>', re.S
)
RE_MAIN = re.compile(r"\b(?:public\s+void|Public\s+Sub)\s+Main\s*\(\s*\)", re.S)
RE_SCOPE = re.compile(
    r"\bLET\s+scope\s+VARCHAR\s*:=\s*'([^']+)'"
    r"|(?:UpdateControlVariable|GetControlVariableUDF)\('[^']+',\s*'([^']+)'",
    re.IGNORECASE,
)
RE_EXECUTABLE_SQL = re.compile(r"^(?!\s*(--|NULL\s*;|$)).+", re.M)

# A script's purpose is read from the APIs its Main() touches: any external effect makes the
# whole task external, because a partial SQL conversion would silently drop that effect.
EXTERNAL_SIGNALS = {
    "http": r"HttpClient|WebRequest|WebClient|HttpWebRequest|RestClient|\.GetAsync\(|\.PostAsync\(",
    "file_io": r"\bFile\.|\bDirectory\.|StreamWriter|StreamReader|FileStream|FileInfo|DirectoryInfo",
    "sql_connection": r"SqlConnection|OleDbConnection|OdbcConnection|SqlCommand|AcquireConnection",
    "excel": r"Microsoft\.Office|Excel\.|Workbook",
    "process": r"Process\.Start",
    "registry": r"Microsoft\.Win32\.Registry|Registry\.(?:GetValue|SetValue|LocalMachine|CurrentUser)",
}
NOTIFICATION_SIGNALS = {
    "smtp": r"SmtpClient|MailMessage|System\.Net\.Mail",
    "logging": r"FireInformation|FireWarning|Dts\.Log\(|Console\.Write|Trace\.Write|EventLog",
}
VARIABLE_SIGNALS = {
    "variable_write": r"Variables\[[^\]]+\]\.Value\s*=(?!=)|LockOneForWrite",
    "variable_read": r"Variables\[[^\]]+\]\.Value(?!\s*=[^=])",
}

ALLOWED_ACTIONS = {
    "disabled": {"remove", "raise"},
    "variables_only": {"replace", "raise"},
    "notification": {"eliminate", "raise"},
    "external": {"raise"},
}


@dataclass
class Block:
    block_id: str
    file: str
    start_line: int
    end_line: int
    indent: str
    executable_type: str
    ref_id: str
    language: str
    disabled: bool
    read_only_variables: list[str]
    read_write_variables: list[str]
    signals: list[str]
    classification: str
    scope: str | None
    main_body: str
    part_name: str | None = None


@dataclass
class Inventory:
    unit_id: str
    blocks: list[Block] = field(default_factory=list)
    inactive_parts: list[dict] = field(default_factory=list)
    unlocated_parts: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(b.classification for b in self.blocks))


class InputError(Exception):
    pass


def load_unit(project_dir: Path, unit_id: str) -> dict:
    path = project_dir / "registry" / f"{unit_id}.json"
    if not path.is_file():
        raise InputError(f"registry entry not found: {path}")
    unit = json.loads(path.read_text(encoding="utf-8"))
    if unit.get("kind") != "etl":
        raise InputError(f"unit {unit_id} is not an ETL code unit")
    return unit


def _has_issue(part: dict) -> bool:
    return any(issue.get("code") == ISSUE_CODE for issue in part.get("issues") or [])


def sql_targets(unit: dict) -> list[str]:
    paths = {
        part["target"]["path"]
        for part in unit.get("parts") or []
        if (part.get("target") or {}).get("format") == "snowflakeSQL" and part["target"].get("path")
    }
    if not paths:
        converted = ((unit.get("files") or {}).get("converted") or {}).get("path")
        if converted and converted.endswith(".sql"):
            paths.add(converted)
    return sorted(paths)


def _strip_csharp_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"(?m)//.*$|^\s*'.*$", "", code)


def _extract_main(xml: str) -> str:
    project_item = RE_SCRIPTMAIN.search(xml)
    if not project_item:
        return ""
    source = project_item.group(1).replace("<![CDATA[", "").replace("]]>", "")
    match = RE_MAIN.search(source)
    if not match:
        return ""
    body = source[match.end():]
    # The ScriptResults enum and the closing region follow Main() in every VSTA template.
    end = re.search(r"\n\s*(?:#region ScriptResults|#Region|enum ScriptResults|Enum ScriptResults)", body)
    return (body[: end.start()] if end else body).strip()


def _signals(main_body: str) -> list[str]:
    code = _strip_csharp_comments(main_body)
    found = []
    for table in (EXTERNAL_SIGNALS, NOTIFICATION_SIGNALS, VARIABLE_SIGNALS):
        found.extend(name for name, pattern in table.items() if re.search(pattern, code))
    return found


def classify(executable_type: str, disabled: bool, main_body: str, signals: list[str]) -> str:
    if disabled:
        return "disabled"
    if executable_type != SCRIPT_TASK or not main_body:
        return "external"
    if any(signal in EXTERNAL_SIGNALS for signal in signals):
        return "external"
    if any(signal in NOTIFICATION_SIGNALS for signal in signals):
        return "notification"
    return "variables_only"


def _split_vars(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _owning_tag(lines: list[str], index: int) -> str | None:
    for i in range(index - 1, -1, -1):
        match = RE_START_TAG.match(lines[i])
        if match:
            return match.group(1)
    return None


def scan_file(project_dir: Path, rel_path: str) -> list[Block]:
    lines = (project_dir / rel_path).read_text(encoding="utf-8").splitlines()
    found = RE_SCOPE.findall("\n".join(lines))
    scope_hits = Counter(let for let, _ in found if let) or Counter(call for _, call in found if call)
    scope = scope_hits.most_common(1)[0][0] if scope_hits else None
    blocks: list[Block] = []
    seen: Counter[str] = Counter()
    for index, line in enumerate(lines):
        marker = RE_MARKER.match(line)
        if not marker:
            continue
        end = index + 1
        while end < len(lines) and not RE_TERMINATOR.match(lines[end]):
            if not lines[end].lstrip().startswith("--") or RE_TAG.match(lines[end]):
                end = -1
                break
            end += 1
        if end < 0 or end >= len(lines):
            continue
        xml = html.unescape("\n".join(re.sub(r"^\s*--", "", l, count=1) for l in lines[index + 1 : end]))
        executable = RE_EXECUTABLE.search(xml)
        attrs = dict(RE_ATTR.findall(executable.group(0))) if executable else {}
        project = re.search(r"<ScriptProject\b[^>]*>", xml)
        project_attrs = dict(RE_ATTR.findall(project.group(0))) if project else {}
        ref_id = attrs.get("refId") or _owning_tag(lines, index) or f"line {index + 1}"
        disabled = attrs.get("Disabled", "").lower() == "true"
        main_body = _extract_main(xml)
        signals = _signals(main_body)
        executable_type = attrs.get("ExecutableType") or attrs.get("CreationName") or marker.group("type")
        seen[ref_id] += 1
        block_id = ref_id if seen[ref_id] == 1 else f"{ref_id}#{seen[ref_id]}"
        blocks.append(
            Block(
                block_id=block_id,
                file=rel_path,
                start_line=index + 1,
                end_line=end + 1,
                indent=marker.group("indent"),
                executable_type=executable_type,
                ref_id=ref_id,
                language=project_attrs.get("Language", ""),
                disabled=disabled,
                read_only_variables=_split_vars(project_attrs.get("ReadOnlyVariables", "")),
                read_write_variables=_split_vars(project_attrs.get("ReadWriteVariables", "")),
                signals=signals,
                classification=classify(executable_type, disabled, main_body, signals),
                scope=scope,
                main_body=main_body,
            )
        )
    return blocks


def build_inventory(project_dir: Path, unit: dict) -> Inventory:
    inventory = Inventory(unit_id=unit["id"])
    for rel_path in sql_targets(unit):
        if (project_dir / rel_path).is_file():
            inventory.blocks.extend(scan_file(project_dir, rel_path))
    by_ref = {(b.file, b.ref_id): b for b in inventory.blocks}
    for part in unit.get("parts") or []:
        if not _has_issue(part):
            continue
        target = (part.get("target") or {}).get("path")
        block = by_ref.get((target, part.get("name")))
        entry = {"name": part.get("name"), "target": target}
        if block:
            block.part_name = part.get("name")
        elif _commented_out(project_dir, target, part.get("name")):
            inventory.inactive_parts.append(entry)
        elif not _already_resolved(project_dir, target, part.get("name")):
            inventory.unlocated_parts.append(entry)
    return inventory


def _read(project_dir: Path, rel_path: str | None) -> str:
    if not rel_path or not (project_dir / rel_path).is_file():
        return ""
    return (project_dir / rel_path).read_text(encoding="utf-8")


def _already_resolved(project_dir: Path, rel_path: str | None, name: str | None) -> bool:
    text = _read(project_dir, rel_path)
    return bool(name) and any(f"{tag} {name} (" in text for tag in (RESOLVED_TAG, NEEDS_USER_TAG))


def _commented_out(project_dir: Path, rel_path: str | None, name: str | None) -> bool:
    """SnowConvert comments out a disabled container whole, markers included; those never run."""
    lines = _read(project_dir, rel_path).splitlines()
    return bool(name) and any(
        re.match(r"^\s*--+\s*!!!RESOLVE EWI!!!.*SSC-EWI-SSIS0004", line)
        and i + 1 < len(lines)
        and f'refId="{name}"' in html.unescape(lines[i + 1])
        for i, line in enumerate(lines)
    )


def _sql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")


def _comment(text: str) -> str:
    return "-- " + text.replace("$$", "$ $").rstrip() if text.strip() else "--"


def render(block: Block, decision: dict) -> list[str]:
    action = decision["action"]
    label = f"{block.ref_id} ({block.executable_type})"
    if action == "remove":
        body = [_comment(f"{RESOLVED_TAG} {label} is disabled in SSIS and never runs."), "NULL;"]
    elif action == "eliminate":
        body = [
            _comment(f"{RESOLVED_TAG} {label} only sent a notification or wrote a log, so it is eliminated."),
            _comment("To keep it, call SYSTEM$SEND_EMAIL through a notification integration or use a Snowflake Alert."),
        ]
        if block.read_only_variables:
            body.append(_comment(f"Inputs it read: {', '.join(block.read_only_variables)}"))
        body.append("NULL;")
    elif action == "raise":
        signals = ", ".join(s for s in block.signals if s in EXTERNAL_SIGNALS) or "logic the conversion could not read"
        message = _sql_string(f"{ISSUE_CODE}: {block.ref_id} ({block.executable_type}) needs manual migration")
        body = [_comment(f"{NEEDS_USER_TAG} {label} uses {signals}.")]
        if block.main_body:
            body.append(_comment("Original Main() kept for reference:"))
            body.extend(_comment(line) for line in block.main_body.splitlines())
        body += [
            "DECLARE",
            f"  ssis0004_not_migrated EXCEPTION (-20004, '{message[:500]}');",
            "BEGIN",
            "  RAISE ssis0004_not_migrated;",
            "END;",
        ]
    else:
        summary = decision["summary"].strip()
        body = [_comment(f"{RESOLVED_TAG} {label} converted from the C# Script Task: {summary}")]
        body.extend(line.rstrip() for line in decision["sql"].strip().splitlines())
    return [block.indent + line if line else line for line in body]


def _validate_decision(block: Block, decision: dict) -> str | None:
    action = decision.get("action")
    if action not in ALLOWED_ACTIONS[block.classification]:
        return (
            f"{block.block_id}: action '{action}' is not allowed for class '{block.classification}' "
            f"(allowed: {sorted(ALLOWED_ACTIONS[block.classification])})"
        )
    if action != "replace":
        return None
    sql = (decision.get("sql") or "").strip()
    if not decision.get("summary", "").strip():
        return f"{block.block_id}: a replace decision needs a one-line summary"
    if "!!!RESOLVE EWI!!!" in sql:
        return f"{block.block_id}: replacement SQL still carries an EWI marker"
    if not RE_EXECUTABLE_SQL.search(sql) and "variable_write" in block.signals:
        return f"{block.block_id}: the script writes variables, so a no-op replacement would drop them"
    return None


def _structure(lines: list[str]) -> tuple[list[str], int]:
    return [l.strip() for l in lines if RE_TAG.match(l)], sum(1 for l in lines if RE_CREATE.match(l))


def apply_plan(project_dir: Path, unit: dict, plan: dict) -> tuple[list[dict], list[str]]:
    inventory = build_inventory(project_dir, unit)
    decisions = {d.get("block"): d for d in plan.get("decisions") or []}
    errors = [f"part {p['name']} has {ISSUE_CODE} but no block was found in {p['target']}" for p in inventory.unlocated_parts]
    for block in inventory.blocks:
        decision = decisions.pop(block.block_id, None)
        if decision is None:
            errors.append(f"{block.block_id}: no decision in the plan")
            continue
        problem = _validate_decision(block, decision)
        if problem:
            errors.append(problem)
    errors.extend(f"{block_id}: not an open {ISSUE_CODE} block in this unit" for block_id in decisions)
    if errors:
        return [], errors

    plan_by_id = {d["block"]: d for d in plan["decisions"]}
    results: list[dict] = []
    for rel_path in sorted({b.file for b in inventory.blocks}):
        original = (project_dir / rel_path).read_text(encoding="utf-8")
        newline = "\r\n" if "\r\n" in original else "\n"
        lines = original.splitlines()
        before = _structure(lines)
        for block in sorted((b for b in inventory.blocks if b.file == rel_path), key=lambda b: -b.start_line):
            decision = plan_by_id[block.block_id]
            lines[block.start_line - 1 : block.end_line] = render(block, decision)
            results.append({"block": block.block_id, "file": rel_path, "class": block.classification, "action": decision["action"]})
        if _structure(lines) != before:
            return [], [f"{rel_path}: the edit would change task tags or CREATE statements; nothing written"]
        trailing = newline if original.endswith(("\n", "\r\n")) else ""
        (project_dir / rel_path).write_text(newline.join(lines) + trailing, encoding="utf-8", newline="")
    return sorted(results, key=lambda r: (r["file"], r["block"])), []


def check(project_dir: Path, unit: dict) -> list[str]:
    inventory = build_inventory(project_dir, unit)
    problems = [f"{b.file}:{b.start_line}: {b.block_id} still carries an active {ISSUE_CODE} marker" for b in inventory.blocks]
    problems += [f"part {p['name']} has {ISSUE_CODE} but nothing in {p['target']} resolves it" for p in inventory.unlocated_parts]
    return problems


def _artifacts_dir(project_dir: Path, unit: dict) -> Path:
    path = ((unit.get("files") or {}).get("artifacts") or {}).get("path")
    return project_dir / (path or f"artifacts/{unit['id']}") / "script-tasks"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["inventory", "apply", "check"])
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--unit-id", required=True)
    parser.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    try:
        unit = load_unit(args.project_dir, args.unit_id)
        if args.command == "inventory":
            inventory = build_inventory(args.project_dir, unit)
            print(json.dumps({**asdict(inventory), "counts": inventory.counts()}, indent=2))
            return EXIT_OK
        if args.command == "check":
            problems = check(args.project_dir, unit)
            print(json.dumps({"ok": not problems, "problems": problems}, indent=2))
            return EXIT_CHECK_FAILED if problems else EXIT_OK
        if not args.plan or not args.plan.is_file():
            raise InputError("apply needs --plan pointing at an existing plan JSON")
        results, errors = apply_plan(args.project_dir, unit, json.loads(args.plan.read_text(encoding="utf-8")))
        if errors:
            print(json.dumps({"applied": False, "errors": errors}, indent=2))
            return EXIT_PLAN_REFUSED
        out_dir = _artifacts_dir(args.project_dir, unit)
        out_dir.mkdir(parents=True, exist_ok=True)
        report = {"unit_id": unit["id"], "resolutions": results, "counts": dict(Counter(r["action"] for r in results))}
        (out_dir / "resolution.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"applied": True, **report}, indent=2))
        return EXIT_OK
    except (InputError, json.JSONDecodeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
