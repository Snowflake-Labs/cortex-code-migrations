"""Declare the sink columns the shipped models fill from the clock or at random (clock_columns.json).

Usage: python3 clock_postpass.py <output-root> [--table <platform-table.json> --doc <source document>]

Runs after the models are final (stage 3c1b). For every unit under <output-root>/ETL/<unit>/ that
carries sink_writes.json, each written table's model (the one whose dbt alias, else file stem, is the
table) is traced column by column back through the models it refs. A column whose value is a bare
clock call (CURRENT_TIMESTAMP(), SYSDATE(), GETDATE(), LOCALTIMESTAMP, NOW(), CURRENT_DATE, possibly
cast) in the model that computes it is a clock column: the original pipeline and the converted one
run at different times, so the test seed excludes it from the comparison. The producer already
declares the stateful sinks' clock columns (SCD2 validity and audit dates); they are kept and merged.

A column whose value is a bare random generator (UUID_STRING(), RANDOM(), UNIFORM(...), RANDSTR(...))
differs between any two runs the same way, but a conversion could also invent one where the source
computed a value. So it is declared only when the source document confirms it: the model that
computes it stands for a source element whose kind the platform table lists under
`runtime.nondeterministic_transforms` (Hop: RandomValue). Without --table / --doc, or with no such
element, the column stays compared.

Read on the emitted Snowflake SQL, so every AI-First platform gets the clock half; the random half
needs only the platform table's runtime list. Tracing is by column name through `<expr> AS <name>`
and bare `[alias.]<name>` projections; a column computed by anything else (CASE, arithmetic, a
function of the clock) is not declared. Each declared column is recorded with its reason under
`reasons` (`clock` or `nondeterministic: <element>`); the seed reads only `columns`.

Verdict line, always printed: `clock columns : <n> in <m> table(s)`. Exit 0 always.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PRUNE = {"target", "dbt_internal_packages", "dbt_packages", "logs"}
_CLOCK = r"(?:CURRENT_TIMESTAMP|LOCALTIMESTAMP|SYSTIMESTAMP|SYSDATE|GETDATE|NOW|CURRENT_DATE)"
_TYPE = r"[A-Za-z_][\w]*(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?"
CLOCK_EXPR = re.compile(
    rf"^\(?\s*(?:{_CLOCK}\s*(?:\(\s*\))?(?:\s*::\s*{_TYPE})?"
    rf"|CAST\s*\(\s*{_CLOCK}\s*(?:\(\s*\))?\s+AS\s+{_TYPE}\s*\)"
    rf"|(?:TO_TIMESTAMP_NTZ|TO_TIMESTAMP|TO_DATE)\s*\(\s*{_CLOCK}\s*(?:\(\s*\))?\s*\))\s*\)?$",
    re.IGNORECASE,
)
_RANDOM = r"(?:UUID_STRING|RANDOM|UNIFORM|RANDSTR|NORMAL|ZIPF)"
RANDOM_EXPR = re.compile(
    rf"^\(?\s*(?:{_RANDOM}\s*\([^()]*(?:\([^()]*\)[^()]*)*\)(?:\s*::\s*{_TYPE})?"
    rf"|CAST\s*\(\s*{_RANDOM}\s*\([^()]*(?:\([^()]*\)[^()]*)*\)\s+AS\s+{_TYPE}\s*\))\s*\)?$",
    re.IGNORECASE,
)
REF = re.compile(r"\{\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}")
ALIAS = re.compile(r"alias\s*=\s*['\"]([^'\"]+)['\"]")
COMMENT = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
SELECT_LIST = re.compile(r"\bSELECT\b(.*?)\bFROM\b", re.IGNORECASE | re.DOTALL)
IDENT = r"\"?[A-Za-z_][\w$]*\"?"
AS_ITEM = re.compile(rf"^(.*?)\s+AS\s+({IDENT})$", re.IGNORECASE | re.DOTALL)
BARE_ITEM = re.compile(rf"^(?:{IDENT}\.)?({IDENT})$")


def _name(identifier: str) -> str:
    return identifier.strip().strip('"').lower()


def _split_items(select_list: str) -> list[str]:
    """Split a SELECT list on top-level commas."""
    items, depth, current = [], 0, []
    for ch in select_list:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(ch)
    if "".join(current).strip():
        items.append("".join(current).strip())
    return items


def model_columns(sql: str) -> dict[str, tuple[str, str]]:
    """Per output column name (lower): ('clock', ''), ('random', ''), ('pass', <source column name>)
    or ('other', '').

    Every SELECT list in the file is read (CTEs and the final one); a later list overrides an
    earlier one for the same name, so the final projection wins.
    """
    body = JINJA.sub(" ", COMMENT.sub(" ", sql))
    columns: dict[str, tuple[str, str]] = {}
    for match in SELECT_LIST.finditer(body):
        for item in _split_items(match.group(1)):
            item = " ".join(item.split())
            if as_match := AS_ITEM.match(item):
                expr, name = as_match.group(1).strip(), _name(as_match.group(2))
                if CLOCK_EXPR.match(expr):
                    columns[name] = ("clock", "")
                elif RANDOM_EXPR.match(expr):
                    columns[name] = ("random", "")
                elif bare := BARE_ITEM.match(expr):
                    columns[name] = ("pass", _name(bare.group(1)))
                else:
                    columns[name] = ("other", "")
            elif bare := BARE_ITEM.match(item):
                name = _name(bare.group(1))
                columns.setdefault(name, ("pass", name))
    return columns


def clock_columns_for(project: Path, table: str) -> list[str]:
    """The columns of *table*'s model in dbt *project* that come from a bare clock call."""
    return [name for name, why in traced_columns_for(project, table) if why == "clock"]


def traced_columns_for(project: Path, table: str) -> list[tuple[str, str]]:
    """(column, reason) for each column of *table*'s model in dbt *project* that comes from a bare clock
    call (reason `clock`) or a bare random generator (reason `random:<model stem that computes it>`)."""
    models: dict[str, Path] = {}
    for path in sorted((project / "models").rglob("*.sql")):
        if not PRUNE.intersection(path.parts):
            models[path.stem.lower()] = path
    texts = {stem: path.read_text(encoding="utf-8", errors="replace") for stem, path in models.items()}
    sink = None
    for stem, text in texts.items():
        alias = ALIAS.search(text)
        if (alias and alias.group(1).lower() == table.lower()) or (not alias and stem == table.lower()):
            sink = stem
            break
    if sink is None:
        return []
    cache: dict[str, dict[str, tuple[str, str]]] = {}

    def trace(stem: str, column: str, seen: frozenset[tuple[str, str]]) -> str | None:
        if (stem, column) in seen or stem not in texts:
            return None
        cols = cache.setdefault(stem, model_columns(texts[stem]))
        kind, source = cols.get(column, ("pass", column))
        if kind == "clock":
            return "clock"
        if kind == "random":
            return f"random:{stem}"
        if kind != "pass":
            return None
        refs = [r.lower() for r in REF.findall(texts[stem])]
        for ref in refs:
            if why := trace(ref, source, seen | {(stem, column)}):
                return why
        return None

    out: list[tuple[str, str]] = []
    body = JINJA.sub(" ", COMMENT.sub(" ", texts[sink]))
    finals = list(SELECT_LIST.finditer(body))
    if not finals:
        return []
    for item in _split_items(finals[-1].group(1)):
        item = " ".join(item.split())
        as_match = AS_ITEM.match(item)
        bare = BARE_ITEM.match(item)
        display = (as_match.group(2) if as_match else bare.group(1) if bare else "").strip('"')
        if display and (why := trace(sink, display.lower(), frozenset())):
            out.append((display, why))
    return out


def nondeterministic_models(table: dict, document: str, unit_dir: Path) -> dict[str, str]:
    """Model stem -> source element, for each model of *unit_dir* that stands for an element whose kind
    the platform table lists under runtime.nondeterministic_transforms. Empty when the table lists none
    or the document names no such element."""
    kinds = {k for k in ((table.get("runtime") or {}).get("nondeterministic_transforms") or {})
             if not k.startswith("_")}
    if not kinds:
        return {}
    import element_map  # noqa: PLC0415 - pulls the emitter's naming only when a random column needs it

    built = element_map.build(table, document, str(unit_dir))
    kind_of = {e["element_id"]: e.get("kind", "") for e in built.get("elements", [])}
    return {m["model"].lower(): m["source_element"] for m in built.get("models", [])
            if m.get("source_element") and kind_of.get(m["source_element"]) in kinds}


def run(output_root: Path, table: dict | None = None, document: str | None = None) -> tuple[int, int]:
    total_columns = total_tables = 0
    for sink_file in sorted(output_root.rglob("sink_writes.json")):
        unit_dir = sink_file.parent
        if PRUNE.intersection(unit_dir.parts):
            continue
        projects = [p.parent for p in unit_dir.rglob("dbt_project.yml") if not PRUNE.intersection(p.parts)]
        sinks = json.loads(sink_file.read_text(encoding="utf-8")).get("tables", [])
        manifest_path = unit_dir / "clock_columns.json"
        manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                    if manifest_path.is_file() else {"tables": []})
        entries = {str(t.get("table", "")).lower(): t for t in manifest.get("tables", [])}
        changed = False
        confirmed: dict[str, str] | None = None
        for sink in sinks:
            sink_table = str(sink.get("table", ""))
            found: list[tuple[str, str]] = []
            for project in projects:
                for column, why in traced_columns_for(project, sink_table):
                    if why.startswith("random:"):
                        if confirmed is None:
                            confirmed = (nondeterministic_models(table, document, unit_dir)
                                         if table and document else {})
                        element = confirmed.get(why.split(":", 1)[1])
                        if element is None:
                            continue
                        why = f"nondeterministic: {element}"
                    found.append((column, why))
            if not found:
                continue
            entry = entries.get(sink_table.lower())
            if entry is None:
                entry = {"table": sink_table, "transform": sink.get("transform", ""), "columns": []}
                manifest["tables"].append(entry)
                entries[sink_table.lower()] = entry
            for column, why in found:
                if column.lower() not in {c.lower() for c in entry["columns"]}:
                    entry["columns"].append(column)
                    entry.setdefault("reasons", {})[column] = why
                    changed = True
            total_tables += 1
            total_columns += len(entry["columns"])
            print(f"   {unit_dir.name}: {sink_table}: {', '.join(entry['columns'])}")
        if changed:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return total_columns, total_tables


def main(argv: list[str]) -> int:
    args = argv[1:]
    options = {}
    while len(args) >= 3 and args[-2] in ("--table", "--doc"):
        options[args[-2]] = args[-1]
        args = args[:-2]
    if len(args) != 1:
        print(__doc__.splitlines()[2])
        return 0
    table = None
    if options.get("--table"):
        try:
            table = json.loads(Path(options["--table"]).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"   platform table not readable ({exc}); random columns stay compared")
    columns, tables = run(Path(args[0]), table, options.get("--doc"))
    print(f"clock columns : {columns} in {tables} table(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
