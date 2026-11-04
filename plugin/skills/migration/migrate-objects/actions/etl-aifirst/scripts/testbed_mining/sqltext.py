"""Neutral helpers for SQL text an ETL document embeds (a source query, a lookup query).

Adapters share this; it names no platform. It recognises only what it can state with
certainty -- the single FROM table of a query, a trailing WHERE (as text), and
equality JOINs of the form `JOIN t [alias] ON a.col = b.col`. Anything richer is
dropped rather than guessed.
"""

from __future__ import annotations

import re

_IDENT = r"(?:\[[^\]]+\]|`[^`]+`|\"[^\"]+\"|[A-Za-z_#@][\w$#@]*)"
_QUAL = rf"{_IDENT}(?:\s*\.\s*{_IDENT})*"
_FROM = re.compile(
    rf"\bFROM\s+({_QUAL})",
    re.IGNORECASE,
)
_FROM_ALIAS = re.compile(rf"\s+(?:AS\s+)?({_IDENT})\b", re.IGNORECASE)
_WHERE = re.compile(
    r"\bWHERE\b(.+?)(?:\bGROUP\s+BY\b|\bORDER\s+BY\b|\bHAVING\b|\bLIMIT\b|$)",
    re.IGNORECASE | re.DOTALL,
)
_JOIN = re.compile(
    rf"\b((?:INNER|LEFT(?:\s+OUTER)?|RIGHT(?:\s+OUTER)?|FULL(?:\s+OUTER)?)\s+)?"
    rf"JOIN\s+({_QUAL})(?:\s+(?:AS\s+)?({_IDENT}))?\s+ON\s+"
    rf"({_QUAL})\s*=\s*({_QUAL})",
    re.IGNORECASE,
)
_JOIN_WORDS = frozenset(
    {
        "INNER",
        "LEFT",
        "RIGHT",
        "FULL",
        "OUTER",
        "JOIN",
        "WHERE",
        "ON",
        "GROUP",
        "ORDER",
        "HAVING",
        "LIMIT",
        "SELECT",
        "FROM",
        "AND",
        "OR",
    }
)


def _canon(ident: str) -> str:
    return re.sub(r"[\[\]`\"\s]", "", ident or "")


def from_table(sql: str) -> str | None:
    m = _FROM.search(sql or "")
    return re.sub(r"\s+", "", m.group(1)) if m else None


def where_text(sql: str) -> str | None:
    m = _WHERE.search(sql or "")
    text = re.sub(r"\s+", " ", (m.group(1) if m else "").strip())
    return text or None


def _alias_map(sql: str) -> dict[str, str]:
    """identifier (casefold) -> canonical table name, from FROM / JOIN aliases."""
    aliases: dict[str, str] = {}

    def add(table: str, alias: str | None) -> None:
        table = _canon(table)
        if not table:
            return
        aliases[table.casefold()] = table
        aliases[table.split(".")[-1].casefold()] = table
        if alias:
            aliases[_canon(alias).casefold()] = table

    fm = _FROM.search(sql or "")
    if fm:
        rest = (sql or "")[fm.end() :]
        am = _FROM_ALIAS.match(rest)
        alias = am.group(1) if am and am.group(1).upper() not in _JOIN_WORDS else None
        add(fm.group(1), alias)
    for m in _JOIN.finditer(sql or ""):
        add(m.group(2), m.group(3))
    return aliases


def _split_ref(ref: str, aliases: dict[str, str]) -> tuple[str, str] | None:
    parts = _canon(ref).split(".")
    if len(parts) < 2:
        return None
    table, col = parts[-2], parts[-1]
    return aliases.get(table.casefold(), table), col


def equi_joins(sql: str) -> list[tuple[str, str, str, str, str]]:
    """Each equality JOIN: (left_table, left_col, right_table, right_col, join_type)."""
    aliases = _alias_map(sql or "")
    out: list[tuple[str, str, str, str, str]] = []
    for m in _JOIN.finditer(sql or ""):
        kind = (m.group(1) or "inner").strip().lower()
        if kind.startswith("left"):
            join_type = "left"
        elif kind.startswith("right"):
            join_type = "right"
        elif kind.startswith("full"):
            join_type = "full"
        else:
            join_type = "inner"
        left = _split_ref(m.group(4), aliases)
        right = _split_ref(m.group(5), aliases)
        if left and right:
            out.append((left[0], left[1], right[0], right[1], join_type))
    return out
