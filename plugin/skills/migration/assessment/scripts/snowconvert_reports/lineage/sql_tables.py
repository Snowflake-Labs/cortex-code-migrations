"""SQL table name extraction with Teradata dialect support.

Uses sqlglot for full AST parsing, falls back to regex when sqlglot fails
(e.g., for Teradata-specific constructs like ZEROIFNULL, QUALIFY, SAMPLE).
"""

from __future__ import annotations

import html
import logging
import re

_log = logging.getLogger(__name__)

# Try to import sqlglot; fall back to regex-only mode if unavailable.
try:
    import sqlglot
    import sqlglot.expressions as exp

    _SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SQLGLOT_AVAILABLE = False


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

# Teradata-specific functions that cause sqlglot parse failures.
_TD_UNSUPPORTED_PATTERN = re.compile(
    r"\b(ZEROIFNULL|NULLIFZERO|QUALIFY|SAMPLE|NORMALIZE\b|EXPAND ON|PERIOD\b)",
    re.IGNORECASE,
)

# Statements that are not DML and contain no FROM clause — skip extraction.
_NON_DML_PATTERN = re.compile(
    r"^\s*(COLLECT\s+STATS?|collect\s+STATISTICS|CALL\s+COLLECT_STATS|"
    r"COLLECT\s+STATISTICS|SET\s+SESSION|LOCK\s+TABLE|HELP\s+TABLE)",
    re.IGNORECASE,
)

# Regex fallback: captures table refs after FROM / JOIN (handles multi-line).
# Matches bare names, db.table, schema.table, db.schema.table, and $$VAR.table.
_FROM_JOIN_RE = re.compile(
    r"""
    \b(?:FROM|JOIN)\s+         # FROM or JOIN keyword
    (                           # capture group: the table reference
        \$\$?[\w]+\.[\w]+       # $$VAR.TABLE or $VAR.TABLE
        |[\w]+\.[\w]+\.[\w]+    # db.schema.table
        |[\w]+\.[\w]+           # db.table or schema.table
        |[\w]+                  # bare table name
    )
    (?:\s+(?:AS\s+)?[\w]+)?    # optional alias
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Pattern to detect Informatica $$variable references.
_DD_VAR_RE = re.compile(r"\$\$[\w]+", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def decode_informatica_sql(raw: str) -> str:
    """Decode HTML entities and Informatica-specific escapes in embedded SQL.

    Handles:
    - Standard HTML entities (``&amp;``, ``&lt;``, etc.)
    - ``&#xD;&#xA;`` → newline
    - ``&apos;`` → single quote
    """
    if not raw:
        return ""
    # xml.etree may have already decoded; html.unescape handles both cases.
    decoded = html.unescape(raw)
    # Additional: explicit CRLF encoding → newline
    decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return decoded


def has_dollar_vars(sql: str) -> bool:
    """Return True if the SQL contains unresolved Informatica $$variable refs."""
    return bool(_DD_VAR_RE.search(sql))


def normalize_table_name(raw_name: str) -> str:
    """Normalize a table name by stripping qualifiers to the bare table name.

    Rules:
    - Strip ``$$DBVAR.`` prefix (Informatica parameter substitution)
    - Strip one-level qualifiers: ``SCHEMA.TABLE`` → ``TABLE``
    - Two-level qualifiers (``DB.SCHEMA.TABLE``) → ``TABLE``
    - Uppercase for case-insensitive comparison
    """
    name = raw_name.strip()
    # Strip $$VAR. prefix (e.g., $$SLSORDVWDB.MY_TABLE → MY_TABLE)
    name = re.sub(r"^\$\$?[\w]+\.", "", name)
    # Remove remaining qualifiers (schema.table or db.schema.table → table)
    parts = name.split(".")
    name = parts[-1]
    return name.upper()


def extract_tables_from_sql(sql: str) -> list[tuple[str, str, bool]]:
    """Extract (raw_name, normalized_name, has_dollar_var) from SQL text.

    First tries sqlglot (Teradata dialect); falls back to regex if:
    - sqlglot is not installed
    - SQL contains Teradata-specific constructs that fail parsing
    - sqlglot raises any error

    Returns a list of ``(raw_name, normalized_name, has_dollar_var)`` tuples
    where ``has_dollar_var`` is True if the name contains a ``$$`` reference.
    """
    decoded = decode_informatica_sql(sql)
    if not decoded.strip():
        return []

    # Skip Teradata non-DML statements (COLLECT STATS, SET SESSION, etc.)
    if _NON_DML_PATTERN.match(decoded):
        return []

    results: list[tuple[str, str, bool]] = []

    use_regex = not _SQLGLOT_AVAILABLE or bool(_TD_UNSUPPORTED_PATTERN.search(decoded))

    if not use_regex:
        try:
            results = _extract_sqlglot(decoded)
        except Exception as exc:  # noqa: BLE001
            _log.debug(f"sqlglot parse failed, falling back to regex: {exc}")
            use_regex = True

    if use_regex:
        results = _extract_regex(decoded)

    return results


def _extract_sqlglot(sql: str) -> list[tuple[str, str, bool]]:
    """Extract tables via sqlglot AST walk (Teradata dialect)."""
    results: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for statement in sqlglot.parse(sql, read="teradata"):
        if statement is None:
            continue
        for table_node in statement.find_all(exp.Table):
            # Skip CTE aliases and subquery aliases.
            raw = table_node.name
            if not raw or not re.match(r"^[\w$]+$", raw):
                continue
            # Build qualified name if db/schema present.
            db = table_node.args.get("db")
            schema = table_node.args.get("schema")
            if db:
                raw_qualified = f"{db.name}.{schema.name}.{raw}" if schema else f"{db.name}.{raw}"
            elif schema:
                raw_qualified = f"{schema.name}.{raw}"
            else:
                raw_qualified = raw

            normalized = normalize_table_name(raw_qualified)
            if normalized in seen or _is_sql_keyword(normalized):
                continue
            seen.add(normalized)
            results.append((raw_qualified, normalized, has_dollar_vars(raw_qualified)))

    return results


def _extract_regex(sql: str) -> list[tuple[str, str, bool]]:
    """Fallback regex-based table extraction."""
    results: list[tuple[str, str, bool]] = []
    seen: set[str] = set()

    for match in _FROM_JOIN_RE.finditer(sql):
        raw = match.group(1).strip()
        if not raw:
            continue
        normalized = normalize_table_name(raw)
        if normalized in seen or _is_sql_keyword(normalized):
            continue
        seen.add(normalized)
        results.append((raw, normalized, has_dollar_vars(raw)))

    return results


# Common SQL keywords that may appear after FROM/JOIN in subqueries or
# set operations — filter these out from table extraction.
_SQL_KEYWORDS = frozenset({
    "SELECT", "WITH", "WHERE", "HAVING", "GROUP", "ORDER", "LIMIT",
    "UNION", "INTERSECT", "EXCEPT", "INSERT", "UPDATE", "DELETE",
    "LATERAL", "UNNEST", "DUAL",
})


def _is_sql_keyword(name: str) -> bool:
    return name.upper() in _SQL_KEYWORDS


def get_dml_write_target(sql: str) -> str | None:
    """Return the normalized name of the primary write-target table for a DML statement.

    For ``UPDATE t SET ...``, ``INSERT INTO t ...``, and ``DELETE FROM t ...`` returns the
    normalized name of *t*.  Returns ``None`` for SELECT statements, non-DML, or when
    sqlglot cannot parse the statement.

    Used by ``_edges_from_session`` to distinguish the actual write target from lookup /
    reference tables that appear in FROM / JOIN / WHERE subqueries of the same SQL —
    those should be classified as reads (SELECT-FROM), not writes.

    sqlglot is preferred for accurate AST parsing, but is optional: when it is
    unavailable or cannot parse the statement, a regex fallback identifies the
    leading DML verb's target so the tool still works without sqlglot installed.
    """
    decoded = decode_informatica_sql(sql)
    if not decoded.strip():
        return None
    if not _SQLGLOT_AVAILABLE:
        return _regex_write_target(decoded)
    try:
        stmt = sqlglot.parse_one(decoded, read="teradata")
    except Exception as exc:  # noqa: BLE001
        _log.debug(f"sqlglot parse failed for write-target detection, falling back to regex: {exc}")
        return _regex_write_target(decoded)
    if stmt is None:
        return _regex_write_target(decoded)

    # sqlglot.parse_one may return a Block for multi-statement SQL (e.g.
    # "DELETE FROM t; INSERT INTO t SELECT ...").  Unwrap to the first DML
    # statement so we can identify the write target of the leading operation.
    if isinstance(stmt, exp.Block):
        for child in stmt.expressions:  # type: ignore[attr-defined]
            if isinstance(child, (exp.Update, exp.Insert, exp.Delete)):
                stmt = child
                break
        else:
            return None

    tbl_node: exp.Table | None = None

    if isinstance(stmt, exp.Update):
        # UPDATE <table> SET ...  — stmt.this is the target Table
        this = stmt.args.get("this")
        if isinstance(this, exp.Table):
            tbl_node = this

    elif isinstance(stmt, exp.Insert):
        # INSERT INTO <table> ...  — stmt.this is the target Table (or a Schema
        # wrapper when the INSERT specifies an explicit column list, e.g.
        # INSERT INTO $$STGDB.T (col1, col2) SELECT ...).
        this = stmt.args.get("this")
        if isinstance(this, exp.Table):
            tbl_node = this
        elif isinstance(this, exp.Schema):
            # Schema(this=Table(...), expressions=[Column, ...]) — unwrap
            inner = this.args.get("this")
            if isinstance(inner, exp.Table):
                tbl_node = inner

    elif isinstance(stmt, exp.Delete):
        # DELETE FROM <table> ...  — stmt.this may be a From wrapper or a Table directly
        this = stmt.args.get("this")
        if isinstance(this, exp.Table):
            tbl_node = this
        elif this is not None:
            # sqlglot wraps it in a From expression in some versions
            tbl_node = this.find(exp.Table)

    if tbl_node is None:
        return None

    raw = tbl_node.name or ""
    if not raw:
        return None
    db = tbl_node.args.get("db")
    schema = tbl_node.args.get("schema")
    if db:
        raw_q = f"{db.name}.{schema.name}.{raw}" if schema else f"{db.name}.{raw}"
    elif schema:
        raw_q = f"{schema.name}.{raw}"
    else:
        raw_q = raw
    return normalize_table_name(raw_q) or None


# Regex fallback for write-target detection when sqlglot is unavailable or fails.
# Captures the table reference immediately after the leading DML verb.
_DML_WRITE_TARGET_RE = re.compile(
    r"^\s*(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO)\s+"
    r"(\$\$?\w+\.\w+\.\w+|\$\$?\w+\.\w+|\w+\.\w+\.\w+|\w+\.\w+|\w+)",
    re.IGNORECASE,
)


def _regex_write_target(sql: str) -> str | None:
    """Regex fallback: normalized target of the leading UPDATE/INSERT/DELETE/MERGE."""
    match = _DML_WRITE_TARGET_RE.match(sql.strip())
    if not match:
        return None
    return normalize_table_name(match.group(1)) or None
