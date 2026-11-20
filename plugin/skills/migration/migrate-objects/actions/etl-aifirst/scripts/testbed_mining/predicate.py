"""Neutral infix boolean-predicate decomposer -> PredicateNode trees.

Dialect-specific spelling (`==` vs `=`, `&&` vs `AND`, `[col]` vs `"col"`) is
supplied by a `Dialect` the adapter passes in; the grammar itself is shared:

    expr   := and ( OR and )*
    and    := atom ( AND atom )*
    atom   := '(' expr ')' | operand CMP operand

Only shapes the Testbed boundary calculator can sample become nodes: one column
compared with literals. Anything else (functions, column-vs-column, arithmetic,
casts) makes the WHOLE predicate undecomposable -> None, and the branch keeps only
its predicate text. A half-decomposed tree would silently drop a conjunct's
constraint, which is worse than none.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from testbed_mining.model import PredicateNode

# Consumer-side operator vocabulary (BranchBoundaryCalculator); flipped when the literal is on the left.
_FLIP = {"=": "=", "<>": "<>", "<": ">", ">": "<", "<=": ">=", ">=": "<="}


@dataclass(frozen=True)
class Dialect:
    # Source spelling -> consumer comparison operator.
    comparisons: dict[str, str]
    and_tokens: frozenset[str]
    or_tokens: frozenset[str]
    # (open, close) quote pairs that delimit an identifier, e.g. ("[", "]").
    identifier_quotes: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    string_quotes: tuple[str, ...] = ('"', "'")


@dataclass(frozen=True)
class _Tok:
    kind: str  # ident | number | string | op | lparen | rparen | other
    text: str


def _tokenize(text: str, dialect: Dialect) -> list[_Tok] | None:
    ops = sorted(
        set(dialect.comparisons)
        | {t for t in dialect.and_tokens | dialect.or_tokens if not t.isalpha()},
        key=len,
        reverse=True,
    )
    words = {t.upper() for t in dialect.and_tokens | dialect.or_tokens if t.isalpha()}
    toks: list[_Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "(":
            toks.append(_Tok("lparen", c))
            i += 1
            continue
        if c == ")":
            toks.append(_Tok("rparen", c))
            i += 1
            continue
        quote = next(
            ((o, cl) for o, cl in dialect.identifier_quotes if text.startswith(o, i)),
            None,
        )
        if quote:
            end = text.find(quote[1], i + len(quote[0]))
            if end < 0:
                return None
            toks.append(_Tok("ident", text[i + len(quote[0]) : end]))
            i = end + len(quote[1])
            continue
        if c in dialect.string_quotes:
            end = text.find(c, i + 1)
            if end < 0:
                return None
            toks.append(_Tok("string", text[i + 1 : end]))
            i = end + 1
            continue
        op = next((o for o in ops if text.startswith(o, i)), None)
        if op:
            toks.append(_Tok("op", op))
            i += len(op)
            continue
        m = re.match(r"-?\d+(\.\d+)?", text[i:])
        if m and (c != "-" or not toks or toks[-1].kind in ("op", "lparen")):
            toks.append(_Tok("number", m.group(0)))
            i += len(m.group(0))
            continue
        m = re.match(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*", text[i:])
        if m:
            word = m.group(0)
            toks.append(
                _Tok(
                    "op" if word.upper() in words else "ident",
                    word.upper() if word.upper() in words else word,
                )
            )
            i += len(word)
            continue
        toks.append(_Tok("other", c))
        i += 1
    return toks


class _Undecomposable(Exception):
    pass


def decompose(
    text: str,
    dialect: Dialect,
    qualify: Callable[[str], str | None],
) -> PredicateNode | None:
    """Parse `text`; `qualify(column)` returns `TABLE.COLUMN` or None to keep the operand bare.

    The consumer keys branch column types by `TABLE.COLUMN`, so a resolved atom must carry
    that spelling; an unresolved operand stays bare (it still samples, just untyped).
    """
    toks = _tokenize(text, dialect)
    if not toks:
        return None
    and_ops = {t.upper() if t.isalpha() else t for t in dialect.and_tokens}
    or_ops = {t.upper() if t.isalpha() else t for t in dialect.or_tokens}
    pos = 0

    def peek() -> _Tok | None:
        return toks[pos] if pos < len(toks) else None

    def take() -> _Tok:
        nonlocal pos
        if pos >= len(toks):
            raise _Undecomposable
        pos += 1
        return toks[pos - 1]

    def connective(
        sub: Callable[[], PredicateNode], ops: set[str], kind: str
    ) -> PredicateNode:
        children = [sub()]
        while (t := peek()) is not None and t.kind == "op" and t.text in ops:
            take()
            children.append(sub())
        return (
            children[0]
            if len(children) == 1
            else PredicateNode(kind=kind, children=children)
        )

    def expr() -> PredicateNode:
        return connective(conj, or_ops, "or")

    def conj() -> PredicateNode:
        return connective(atom, and_ops, "and")

    def atom() -> PredicateNode:
        t = peek()
        if t is not None and t.kind == "lparen":
            take()
            node = expr()
            if take().kind != "rparen":
                raise _Undecomposable
            return node
        left, op, right = take(), take(), take()
        if op.kind != "op" or op.text not in dialect.comparisons:
            raise _Undecomposable
        operator = dialect.comparisons[op.text]
        if left.kind == "ident" and right.kind in ("number", "string"):
            column, value = left.text, right.text
        elif right.kind == "ident" and left.kind in ("number", "string"):
            column, value, operator = right.text, left.text, _FLIP[operator]
        else:
            raise _Undecomposable
        return PredicateNode(
            kind="atom",
            columns=[qualify(column) or column],
            operator=operator,
            values=[value],
        )

    try:
        node = expr()
    except _Undecomposable:
        return None
    return node if pos == len(toks) else None


def operand_columns(text: str, dialect: Dialect) -> list[str]:
    """Every identifier the predicate text references, in first-seen order."""
    toks = _tokenize(text, dialect) or []
    seen: list[str] = []
    for i, t in enumerate(toks):
        is_call = i + 1 < len(toks) and toks[i + 1].kind == "lparen"
        if t.kind == "ident" and not is_call and t.text not in seen:
            seen.append(t.text)
    return seen
