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

"""Extract data-type usage from captured CREATE TABLE DDL.

A bounded extractor, not a parser. The registry carries no column or type
fields, so the DDL each in-scope table points at is the only in-project carrier
of column types. Anything this cannot resolve -- computed columns, table-valued
or nested types, a file it cannot read -- yields nothing, because the report
names the volume inventory script as authoritative and a wrong type is worse
than an absent one.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# Qualifiers between CREATE and TABLE vary by dialect (MULTISET, SET VOLATILE,
# GLOBAL TEMPORARY, OR REPLACE), so they are counted rather than enumerated.
_CREATE_TABLE = re.compile(r"\bCREATE\s+(?:\w+\s+){0,3}?TABLE\b", re.IGNORECASE)

# A delimited identifier, closed by its delimiter; a doubled closer inside it
# (`]]`, `""`, ``` `` ```) is an escaped delimiter, not the end of the name.
_IDENTIFIER_SPAN = r'\[(?:[^\]]|\]\])*\]|"(?:[^"]|"")*"|`(?:[^`]|``)*`'
# Any quoted span: a delimited identifier or a single-quoted literal (`''`).
_QUOTED_SPAN = re.compile(_IDENTIFIER_SPAN + r"|'(?:[^']|'')*'")

# Stripped before anything else: a comma inside a comment splits the column
# list and shifts every later item, which reports a column *name* as a type.
# Quoted spans are matched first and kept whole, so `[a/*b*/c]` stays a name
# and `DEFAULT '--'` stays a literal.
_COMMENTS_OUTSIDE_QUOTES = re.compile(
    "(" + _QUOTED_SPAN.pattern + r")|--[^\n]*|/\*.*?\*/", re.DOTALL
)


def _strip_comments(ddl: str) -> str:
    """Replace each comment with a space, leaving quoted text untouched."""
    return _COMMENTS_OUTSIDE_QUOTES.sub(lambda m: m.group(1) or " ", ddl)


# An item in the column list that declares something other than a column.
_NOT_A_COLUMN = re.compile(
    r"^(?:CONSTRAINT|PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK|INDEX|KEY|"
    r"PERIOD\s+FOR|EXCLUDE|LIKE)\b",
    re.IGNORECASE,
)

_QUOTED_NAME = re.compile(r"^(?:" + _IDENTIFIER_SPAN + r"|[A-Za-z_][\w$@#]*)")

# A computed column puts an expression where a type belongs. The word boundary
# matters: `ASSET` is a type name, not `AS` followed by an expression.
_COMPUTED = re.compile(r"^AS\b", re.IGNORECASE)

# Types whose name is more than one word. Longest first so a prefix match cannot
# claim a shorter name than the DDL actually spells out.
_MULTI_WORD_TYPES: tuple[str, ...] = tuple(
    sorted(
        (
            "INTERVAL YEAR TO MONTH",
            "INTERVAL DAY TO SECOND",
            "TIMESTAMP WITHOUT TIME ZONE",
            "TIMESTAMP WITH TIME ZONE",
            "TIME WITHOUT TIME ZONE",
            "TIME WITH TIME ZONE",
            "CHARACTER VARYING",
            "BINARY VARYING",
            "DOUBLE PRECISION",
        ),
        key=len,
        reverse=True,
    )
)


@dataclass(frozen=True)
class ScannedColumn:
    """One column with a recognizable type, as declared and as normalized."""

    name: str
    declared_type: str
    type_name: str


@dataclass(frozen=True)
class ScannedTable:
    """The columns the scan read from one table's DDL."""

    name: str
    columns: tuple[ScannedColumn, ...]


@dataclass(frozen=True)
class TableUsage:
    """The columns of one table that use a type, in declared order."""

    table: str
    columns: tuple[ScannedColumn, ...]


@dataclass(frozen=True)
class TypeUsage:
    """How much one normalized type name is used across the scanned tables."""

    type_name: str
    table_count: int
    column_count: int
    tables: tuple[TableUsage, ...] = ()


_QUOTE_OPENERS = frozenset("'\"`[")


def _quoted_span_end(text: str, index: int) -> int:
    """End of the quoted span opening at ``index``; an unclosed one runs to the end."""
    span = _QUOTED_SPAN.match(text, index)
    return span.end() if span else len(text)


def _first_unquoted_paren(ddl: str, offset: int) -> int:
    """Index of the first ``(`` at or after ``offset`` outside a quoted span."""
    index = offset
    while index < len(ddl):
        char = ddl[index]
        if char in _QUOTE_OPENERS:
            index = _quoted_span_end(ddl, index)
            continue
        if char == "(":
            return index
        index += 1
    return -1


def _column_region(ddl: str) -> str:
    """The text between the parentheses of the first ``CREATE TABLE``.

    Walks to the matching close paren so nested type arguments and
    parenthesised CHECK expressions do not end the region early. Literals and
    delimited names are skipped whole, since either may contain a paren.
    """
    match = _CREATE_TABLE.search(ddl)
    if not match:
        return ""
    start = _first_unquoted_paren(ddl, match.end())
    if start < 0:
        return ""

    depth = 0
    index = start
    while index < len(ddl):
        char = ddl[index]
        if char in _QUOTE_OPENERS:
            index = _quoted_span_end(ddl, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return ddl[start + 1 : index]
        index += 1
    return ""


def _split_items(region: str) -> list[str]:
    """Split a column region on its top-level commas."""
    items: list[str] = []
    depth = 0
    item_start = 0
    index = 0
    while index < len(region):
        char = region[index]
        if char in _QUOTE_OPENERS:
            index = _quoted_span_end(region, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(region[item_start:index])
            item_start = index + 1
        index += 1
    items.append(region[item_start:])
    return [item.strip() for item in items if item.strip()]


def _normalize_type(text: str) -> str:
    """Reduce a type region to an uppercase base name ("" if there is none).

    Delimiters go first: a bracketed type (``[int]``) would otherwise be split
    to nothing by the argument split. Length and precision arguments are then
    dropped, so ``DATETIME2(7)`` matches the ``DATETIME2`` coverage row, whose
    note states where the precision caveat applies -- accurate without parsing
    precision.
    """
    undelimited = re.sub(r"[\[\]\"`]", " ", text)
    words = " ".join(re.split(r"\(", undelimited, maxsplit=1)[0].upper().split())
    if not words:
        return ""
    for candidate in _MULTI_WORD_TYPES:
        if words == candidate or words.startswith(candidate + " "):
            return candidate
    return words.split(" ", 1)[0].rsplit(".", 1)[-1]


_DECLARED_TYPE_END = re.compile(
    r"\s+(?:NOT\b|NULL\b|DEFAULT\b|IDENTITY\b|CONSTRAINT\b|PRIMARY\b|UNIQUE\b|"
    r"REFERENCES\b|CHECK\b|COLLATE\b|ENCODE\b|GENERATED\b|SPARSE\b|ROWGUIDCOL\b)",
    re.IGNORECASE,
)


def _declared_type(rest: str) -> str:
    """The type as written, without the column options that follow it."""
    return _DECLARED_TYPE_END.split(rest, maxsplit=1)[0].strip()


_DELIMITER_PAIRS = {"[": "]", '"': '"', "`": "`"}


def _unquote(identifier: str) -> str:
    """Drop the outer delimiter pair and decode each doubled closer inside it."""
    close = _DELIMITER_PAIRS.get(identifier[:1])
    if close and len(identifier) >= 2 and identifier.endswith(close):
        return identifier[1:-1].replace(close * 2, close)
    return identifier


def scan_ddl_columns(ddl: str) -> tuple[ScannedColumn, ...]:
    """Each column of the first ``CREATE TABLE`` that has a recognizable type."""
    columns: list[ScannedColumn] = []
    for item in _split_items(_column_region(_strip_comments(ddl))):
        if _NOT_A_COLUMN.match(item):
            continue
        name = _QUOTED_NAME.match(item)
        if not name:
            continue
        rest = item[name.end() :].strip()
        if not rest or _COMPUTED.match(rest):
            continue
        normalized = _normalize_type(rest)
        if normalized:
            columns.append(
                ScannedColumn(
                    name=_unquote(name.group(0)),
                    declared_type=_declared_type(rest),
                    type_name=normalized,
                )
            )
    return tuple(columns)


def scan_ddl(ddl: str) -> tuple[str, ...]:
    """Normalized type name of each column in the first ``CREATE TABLE``."""
    return tuple(column.type_name for column in scan_ddl_columns(ddl))


def aggregate_usage(tables: Iterable[ScannedTable]) -> tuple[TypeUsage, ...]:
    """Roll per-table columns up into per-type usage, naming each table.

    Ordered by column count descending, then by name, so the findings table is
    stable across runs and leads with the type the project uses most. Tables
    within a type are sorted by name.
    """
    by_type: dict[str, dict[str, list[ScannedColumn]]] = {}
    for table in tables:
        for column in table.columns:
            by_type.setdefault(column.type_name, {}).setdefault(table.name, []).append(column)

    usage = [
        TypeUsage(
            type_name=type_name,
            table_count=len(per_table),
            column_count=sum(len(columns) for columns in per_table.values()),
            tables=tuple(
                TableUsage(table=name, columns=tuple(per_table[name])) for name in sorted(per_table)
            ),
        )
        for type_name, per_table in by_type.items()
    ]
    return tuple(sorted(usage, key=lambda u: (-u.column_count, u.type_name)))
