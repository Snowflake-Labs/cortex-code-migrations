"""SqlStatementSource extraction and ObjectReferences rows for table-refused SQL.

Measured on ssis-execsql (convert-ctrl 2026-09-02, HEAD 07b5c542cd): five
Microsoft.ExecuteSQLTask nodes are absent from kind_dispatch, so they stay
UnsupportedTransformation. C# lineage only reads SourceQualifier.TableName and
ref()/source() inside SSC-AI-AUTHORED models. Authored bodies used a bare FROM /
the sproc sidecar abstained because ModelSql had to contain SELECT, and
ObjectReferences stayed the one-line placeholder.

The document already stated the SQL in SqlStatementSource on the Executable
fragment that `_unsupported_body` / source_text carry. This module reads that
statement (and filled ModelSql) and writes SELECT - FROM / EXECUTE rows so the
report is populated without widening the frozen platform table.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

MODELSQL_VERB = re.compile(r"\b(SELECT|WITH)\b", re.I)
# One identifier part: bracketed/quoted (may hold spaces or a literal dot) or a
# bare word. `FROM`/`EXEC`/`DELETE FROM` all key off this so `[My Table]` and
# `"Order Detail"` are captured whole instead of being split on an inner dot.
_IDENT_PART = r'(?:\[[^\]]+\]|"[^"]+"|[A-Za-z_][\w$]*)'
_QUALIFIED_IDENT = rf"{_IDENT_PART}(?:\.{_IDENT_PART}){{0,2}}"
FROM_REL = re.compile(rf"\b(?:FROM|JOIN)\s+({_QUALIFIED_IDENT})", re.I)
EXEC_REL = re.compile(rf"\b(?:EXEC(?:UTE)?|CALL)\s+({_QUALIFIED_IDENT})", re.I)
# The specific `DELETE FROM <target>` shape: that FROM names what the statement
# deletes, not something it reads, unlike every other FROM/JOIN this module sees.
DELETE_FROM_REL = re.compile(rf"\bDELETE\s+FROM\s+({_QUALIFIED_IDENT})", re.I)
# `WITH cte AS (` / `, cte2 AS (` -- names a CTE defines for itself, not a table
# reference, so a later `FROM cte` must not be reported as a relation.
CTE_DEF = re.compile(rf"(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)({_IDENT_PART})\s+AS\s*\(", re.I)
_JINJA = re.compile(r"\{\{.*?\}\}", re.S)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
SQL_STATEMENT_ATTR = re.compile(
    r"""SqlStatementSource\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.I,
)
SQL_STATEMENT_SOURCE_TYPE_ATTR = re.compile(
    r"""SqlStatementSourceType\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.I,
)
# SSIS ExecuteSQLTask source types whose SqlStatementSource attribute names a
# variable or connection manager, not literal SQL.
UNRESOLVABLE_SOURCE_TYPES = {"VARIABLE", "FILECONNECTION"}

OBJECTREF_FIELDS = [
    "PartitionKey",
    "FileName",
    "Caller_CodeUnit",
    "Caller_CodeUnit_Database",
    "Caller_CodeUnit_Schema",
    "Caller_CodeUnit_Name",
    "Caller_CodeUnit_FullName",
    "Referenced_Element_Type",
    "Referenced_Element_Database",
    "Referenced_Element_Schema",
    "Referenced_Element_Name",
    "Referenced_Element_FullName",
    "Line",
    "Relation_Type",
]
PLACEHOLDER_PROSE = "No object references found"
PARTITION_KEY = "Development Session"
NA = "N/A"


def _strip_noise(sql: str) -> str:
    """Drop Jinja, `--`/`/* */` comments, and string literals.

    Without this, a verb or a relation name spelled inside a comment or a quoted
    string (`-- SELECT omitted`, `WHERE note = 'from dbo.Ghost'`) reads as real SQL.
    """
    cleaned = _JINJA.sub(" ", sql)
    cleaned = _BLOCK_COMMENT.sub(" ", cleaned)
    cleaned = _LINE_COMMENT.sub(" ", cleaned)
    cleaned = _STRING_LITERAL.sub(" ", cleaned)
    return cleaned


_SELECT_HEAD = re.compile(r"(?is)select\s+(?:distinct\s+|top\s+\d+\s+)?(.*)")
_TOP_LEVEL_FROM = re.compile(r"(?i)from(?![\w$#])")
_DOTTED_IDENT = re.compile(rf"(?s){_IDENT_PART}(?:\.{_IDENT_PART})*")
_ALIAS_AS = re.compile(rf"(?is)(.*?)\s+as\s+({_IDENT_PART})")
_ALIAS_BARE = re.compile(rf"(?s)(.*?)\s+({_IDENT_PART})")
_LAST_DOT = re.compile(r"\.(?=(?:[^\"\[\]]|\"[^\"]*\"|\[[^\]]*\])*$)")
_LITERAL = re.compile(r"(?s)'(?:[^']|'')*'|-?\d+(?:\.\d+)?")


def _top_level(body: str):
    """Yield (index, char) for the characters of `body` outside quotes and parentheses."""
    depth, quote = 0, None
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"[":
            quote = "]" if ch == "[" else ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0:
            yield i, ch


def _named(operand: str) -> bool:
    """True when `operand` is complete on its own, so a trailing identifier after it is an alias:
    a dotted identifier, a literal, or something ending in a closing parenthesis."""
    operand = operand.strip()
    return bool(_DOTTED_IDENT.fullmatch(operand) or _LITERAL.fullmatch(operand)
                or (operand.endswith(")") and not operand.lower().startswith("case")))


def select_list_names(sql: str) -> tuple[list[str], str]:
    """Column names of a plain SELECT list, or ([], reason). Conservative on purpose: one
    top-level SELECT ... FROM, every item either an identifier (the last dotted part is the
    name), `<expression> AS x`, or `<operand> x` where the operand is complete on its own.
    `*` or an unnamed expression (`a + b`, `CASE ... END`, `x COLLATE c`) refuses the whole
    list rather than guessing."""
    text = _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql or "")).strip()
    m = _SELECT_HEAD.match(text)
    if not m:
        return [], "no SELECT"
    body = m.group(1)
    cut = next((i for i, _ in _top_level(body)
                if _TOP_LEVEL_FROM.match(body, i) and (i == 0 or not re.match(r"[\w$#.@]", body[i - 1]))),
               None)
    if cut is None:
        return [], "no top-level FROM"
    body = body[:cut]
    commas = [i for i, ch in _top_level(body) if ch == ","]
    items = [body[a + 1:b] for a, b in zip([-1, *commas], [*commas, len(body)])]
    names = []
    for it in (x.strip() for x in items):
        if not it or it.endswith("*"):
            return [], f"item {it!r} names no column"
        if _DOTTED_IDENT.fullmatch(it):
            nm = _LAST_DOT.split(it)[-1]
        elif (a := _ALIAS_AS.fullmatch(it)) and a.group(1).strip():
            nm = a.group(2)
        elif (a := _ALIAS_BARE.fullmatch(it)) and _named(a.group(1)):
            nm = a.group(2)
        else:
            return [], f"item {it!r} has no alias"
        names.append(nm.strip('"[]'))
    if len({n.lower() for n in names}) != len(names):
        return [], "duplicate column names"
    return names, ""


def modelsql_has_verb(sql: str | None) -> bool:
    """True when ModelSql is a SELECT/WITH dbt can compile as a model body.

    A body whose only verb is EXEC/EXECUTE/CALL/INSERT/UPDATE/DELETE/MERGE is not an
    authored dbt model -- dbt materializes a model from a query, not a procedure call or a
    bare mutation -- so it is refused here rather than written into a `.sql` file dbt
    cannot compile. That case is expected to abstain and keep its placeholder instead.
    """
    return bool(sql and MODELSQL_VERB.search(_strip_noise(sql)))


def _sql_statement_source_type(text: str) -> str:
    m = SQL_STATEMENT_SOURCE_TYPE_ATTR.search(text)
    if m:
        return _unescape(m.group(1) or m.group(2) or "")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ""
    for el in root.iter():
        for key, value in el.attrib.items():
            if key == "SqlStatementSourceType" or key.endswith("}SqlStatementSourceType"):
                return (value or "").strip()
    return ""


def _raw_sql_statement_source(text: str) -> str:
    m = SQL_STATEMENT_ATTR.search(text)
    if m:
        return _unescape(m.group(1) or m.group(2) or "")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ""
    for el in root.iter():
        for key, value in el.attrib.items():
            if key == "SqlStatementSource" or key.endswith("}SqlStatementSource"):
                return (value or "").strip()
    return ""


def extract_sql_statement_source(text: str | None) -> str:
    """SqlStatementSource from an SSIS Executable fragment, or ''.

    A Variable/FileConnection SqlStatementSourceType means the attribute names a
    variable or connection-manager, not literal SQL -- returns '' rather than
    feeding that name to `relations_from_sql` as if it were a statement.
    """
    if not text or not str(text).strip():
        return ""
    if _sql_statement_source_type(text).upper() in UNRESOLVABLE_SOURCE_TYPES:
        return ""
    return _raw_sql_statement_source(text)


def unresolved_sql_source(text: str | None) -> str:
    """'<Type>:<name>' when SqlStatementSource names a Variable/FileConnection, else ''.

    Gives the Variable/FileConnection case a signal instead of the silent zero
    rows `extract_sql_statement_source("")` would otherwise produce.
    """
    if not text or not str(text).strip():
        return ""
    source_type = _sql_statement_source_type(text)
    if source_type.upper() not in UNRESOLVABLE_SOURCE_TYPES:
        return ""
    ref = _raw_sql_statement_source(text)
    return f"{source_type}:{ref}" if ref else source_type


def _unescape(value: str) -> str:
    return (value.replace("&quot;", '"').replace("&apos;", "'")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
            .strip())


def _norm_ident(name: str) -> str:
    parts = [p.strip().strip("[]").strip('"') for p in (name or "").split(".")]
    return ".".join(p for p in parts if p)


def _cte_names(cleaned: str) -> set[str]:
    return {_norm_ident(m.group(1)).upper() for m in CTE_DEF.finditer(cleaned)}


def relations_from_sql(sql: str | None) -> list[tuple[str, str]]:
    """(relation_name, relation_type) from FROM/JOIN and EXEC/CALL."""
    if not sql:
        return []
    cleaned = _strip_noise(sql)
    cte_names = _cte_names(cleaned)
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in EXEC_REL.finditer(cleaned):
        name = _norm_ident(match.group(1))
        if name and name.upper() not in {"SELECT"} and (name, "EXECUTE") not in seen:
            seen.add((name, "EXECUTE"))
            found.append((name, "EXECUTE"))
    # `DELETE FROM x` names what the statement deletes, not something it reads --
    # matched separately and excluded from the generic FROM/JOIN sweep below so the
    # same clause is not also reported as a "SELECT - FROM" read.
    delete_match = DELETE_FROM_REL.search(cleaned)
    delete_span = delete_match.span(1) if delete_match else None
    if delete_match:
        name = _norm_ident(delete_match.group(1))
        if name and (name, "DELETE") not in seen:
            seen.add((name, "DELETE"))
            found.append((name, "DELETE"))
    for match in FROM_REL.finditer(cleaned):
        if delete_span and match.span(1) == delete_span:
            continue
        name = _norm_ident(match.group(1))
        if not name or name.upper() in {"SELECT", "VALUES"} or name.upper() in cte_names:
            continue
        key = (name, "SELECT - FROM")
        if key not in seen:
            seen.add(key)
            found.append(key)
    return found


def attach_source_sql(element: dict, body: str | None) -> str:
    """Set element['source_sql'] from SqlStatementSource in body. Return it."""
    stmt = extract_sql_statement_source(body)
    if stmt:
        element["source_sql"] = stmt
    else:
        unresolved = unresolved_sql_source(body)
        if unresolved:
            element["source_sql_unresolved"] = unresolved
    return stmt


def _caller_for_node(node: dict, out_root: Path) -> str:
    model_name = str(node.get("modelName") or "")
    element = node.get("element") or {}
    aliases = [model_name, f"int_{model_name}", f"stg_raw__{model_name}",
               str(element.get("Name") or "")]
    etl = out_root / "Output" / "ETL"
    if model_name and etl.is_dir():
        for path in etl.rglob("*.sql"):
            if "/target/" in str(path) or "/dbt_internal_packages/" in str(path):
                continue
            if path.stem in aliases or path.stem.endswith(f"__{model_name}"):
                return path.stem
    return f"int_{model_name}" if model_name else str(node.get("id") or "unknown")


def _row(file_name: str, caller: str, referenced: str, relation: str,
         caller_unit: str = "ETL PROCESS", line: str = "-1") -> dict:
    return {
        "PartitionKey": PARTITION_KEY,
        "FileName": file_name,
        "Caller_CodeUnit": caller_unit,
        "Caller_CodeUnit_Database": NA,
        "Caller_CodeUnit_Schema": NA,
        "Caller_CodeUnit_Name": caller,
        "Caller_CodeUnit_FullName": caller,
        "Referenced_Element_Type": "MISSING",
        "Referenced_Element_Database": NA,
        "Referenced_Element_Schema": NA,
        "Referenced_Element_Name": referenced,
        "Referenced_Element_FullName": referenced,
        "Line": line,
        "Relation_Type": relation,
    }


def _objectref_path(reports_dir: Path) -> Path | None:
    hits = sorted(reports_dir.glob("ObjectReferences.*.csv"))
    return hits[0] if hits else None


def _read_existing(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    if len(lines) == 1 and "," not in lines[0]:
        return []
    return list(csv.DictReader(lines))


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(PLACEHOLDER_PROSE + "\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=OBJECTREF_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in OBJECTREF_FIELDS})


def _dedup_key(row: dict) -> tuple[str, str, str]:
    return (
        str(row.get("Caller_CodeUnit_FullName") or ""),
        str(row.get("Referenced_Element_FullName") or ""),
        str(row.get("Relation_Type") or ""),
    )


def rows_from_ir(ir: dict, out_root: Path, source_document: str) -> list[dict]:
    rows = []
    nodes = (ir.get("pipeline") or ir).get("nodes") or []
    for node in nodes:
        element = node.get("element") or {}
        body = element.get("_unsupported_body")
        stmt = element.get("source_sql") or extract_sql_statement_source(body)
        caller = _caller_for_node(node, out_root)
        relations = relations_from_sql(stmt)
        for name, relation in relations:
            rows.append(_row(source_document, caller, name, relation))
        if not relations:
            # Variable/FileConnection statement sources leave no SQL to parse. A row
            # naming the unresolved source beats the original bug this module exists
            # to close: an empty result with no signal the statement was unresolvable.
            unresolved = element.get("source_sql_unresolved") or unresolved_sql_source(body)
            if unresolved:
                rows.append(_row(source_document, caller, unresolved, "UNRESOLVED - SOURCE"))
    return rows


def rows_from_authored_sql(out_root: Path, source_document: str) -> list[dict]:
    rows = []
    etl = out_root / "Output" / "ETL"
    if not etl.is_dir():
        return rows
    for path in etl.rglob("*.sql"):
        rel = str(path.relative_to(etl)).replace("\\", "/")
        if "/target/" in f"/{rel}/" or "/dbt_internal_packages/" in f"/{rel}/":
            continue
        if "/models/" not in f"/{rel}":
            continue
        text = path.read_text(encoding="utf-8")
        if "SSC-AI-AUTHORED" not in text:
            continue
        caller = path.stem
        for name, relation in relations_from_sql(text):
            rows.append(_row(
                source_document, caller, name,
                f"{relation} (MODEL-AUTHORED)",
                caller_unit="ETL PROCESS (MODEL-AUTHORED)",
            ))
    return rows


def merge_object_references(ir: dict, out_root: Path,
                            source_document: str) -> tuple[int, int]:
    """Merge source_sql / authored-SQL rows into ObjectReferences. Return (total, added)."""
    reports = out_root / "Reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = _objectref_path(reports) or (reports / "ObjectReferences.NA.csv")
    existing = _read_existing(path) if path.is_file() else []
    offered = rows_from_ir(ir, out_root, source_document)
    offered += rows_from_authored_sql(out_root, source_document)
    seen = {_dedup_key(r) for r in existing}
    added = []
    for row in offered:
        key = _dedup_key(row)
        if key in seen:
            continue
        seen.add(key)
        added.append(row)
    merged = existing + added
    _write_rows(path, merged)
    return len(merged), len(added)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: source_sql.py <producer-ir.json> <output-root> [source-document]",
              file=sys.stderr)
        return 2
    ir_path, out_root = Path(argv[1]), Path(argv[2])
    source_document = Path(argv[3]).name if len(argv) > 3 else "unknown"
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    total, added = merge_object_references(ir, out_root, source_document)
    print(f"source-sql lineage : rows={total} added={added}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
