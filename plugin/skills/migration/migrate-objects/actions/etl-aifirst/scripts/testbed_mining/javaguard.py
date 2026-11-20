"""Prove what a Java row computes into a flag column, as guards over its INPUT columns.

A Talend validation tJavaRow typically does

    output_row.flag = "0";
    if (input_row.A == null || "".equals(input_row.A)) { output_row.flag = "-1"; }
    else if (input_row.A.length() > 40) { output_row.flag = "-1"; }

and a downstream filter tests `flag`. `flag` is not a source column, so a branch atom on it
binds to nothing. This module proves, from the code alone, the shape

    flag == D  exactly when no guard fires        (D = the last unconditional literal)
    flag == R  exactly when some guard fires      (R = the single literal every guard assigns)

and returns the guard as a `Cond` tree over `input_row` columns, so the filter can be restated
on source columns. Anything the proof does not cover returns a `Refusal` with the reason.

A guard leaf is turned into an atom only when its Java meaning is exactly a column-vs-literal
SQL test:  `X == null` / `X != null` (IS [NOT] NULL), `"v".equals(X)` / `X.equals("v")` /
`X.isEmpty()` (= 'v' / = ''), and `X <op> <number>` on a numeric column (Java `==` on a String
is reference identity, so it is never an atom). Every other leaf, `X.length() > 40` included,
is kept as an `opaque` leaf carrying its source text. It is never guessed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_STRING = r'"(?:[^"\\]|\\.)*"'
_NUMBER = r"-?\d+(?:\.\d+)?"
_NEGATE = {
    "IS NULL": "IS NOT NULL",
    "IS NOT NULL": "IS NULL",
    "=": "<>",
    "<>": "=",
    "<": ">=",
    ">=": "<",
    ">": "<=",
    "<=": ">",
}
_FLIP = {"<": ">", ">": "<", "<=": ">=", ">=": "<=", "==": "==", "!=": "!="}
_JAVA_CMP = {"==": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


@dataclass
class Cond:
    """atom (column op values) | and | or | opaque (an unprovable leaf, kept as text)."""

    kind: str
    column: str | None = None
    operator: str | None = None
    values: list[str] = field(default_factory=list)
    children: list[Cond] = field(default_factory=list)
    text: str = ""

    def negated(self) -> Cond:
        if self.kind == "atom":
            return Cond("atom", self.column, _NEGATE[self.operator], list(self.values))
        if self.kind in ("and", "or"):
            return Cond(
                "or" if self.kind == "and" else "and",
                children=[c.negated() for c in self.children],
            )
        t = self.text
        if t.startswith("!(") and _balanced(t, 1, "(", ")") == len(t):
            return Cond("opaque", text=t[2:-1])
        return Cond("opaque", text=f"!({t})")

    def opaque_leaves(self) -> list[str]:
        if self.kind == "opaque":
            return [self.text]
        return [t for c in self.children for t in c.opaque_leaves()]

    def columns(self) -> list[str]:
        own = [self.column] if self.kind == "atom" and self.column else []
        return own + [c for ch in self.children for c in ch.columns()]


def any_of(conds: list[Cond]) -> Cond:
    flat: list[Cond] = []
    for c in conds:
        flat += c.children if c.kind == "or" else [c]
    return flat[0] if len(flat) == 1 else Cond("or", children=flat)


def all_of(conds: list[Cond]) -> Cond:
    flat: list[Cond] = []
    for c in conds:
        flat += c.children if c.kind == "and" else [c]
    return flat[0] if len(flat) == 1 else Cond("and", children=flat)


def exact(c: Cond) -> Cond | None:
    """The tree itself, or None if any leaf is opaque."""
    return None if c.opaque_leaves() else c


def sufficient(c: Cond) -> Cond | None:
    """The strongest opaque-free tree that IMPLIES `c`: an OR drops opaque disjuncts (it only
    gets stricter); an AND with any opaque conjunct has no such sub-tree. None = nothing left."""
    if c.kind == "atom":
        return c
    if c.kind == "opaque":
        return None
    kept = [sufficient(ch) for ch in c.children]
    if c.kind == "and":
        return None if any(k is None for k in kept) else all_of(kept)
    kept = [k for k in kept if k is not None]
    return any_of(kept) if kept else None


@dataclass
class Refusal:
    reason: str


@dataclass
class FlagProof:
    default: str  # D: the value when no guard fires
    guard_value: str  # R: the value when any guard fires
    guard: Cond  # over input column names
    guard_texts: list[str]  # the Java conditions, in source order


# ---- statement splitting ----------------------------------------------------------------------


@dataclass
class _Stmt:
    kind: str  # simple | if | opaque
    text: str = ""
    # if: [(condition text or None for the final else, body statements)]
    arms: list[tuple[str | None, list[_Stmt]]] = field(default_factory=list)


def _skip_string(code: str, i: int) -> int:
    q, j, n = code[i], i + 1, len(code)
    while j < n and code[j] != q:
        j += 2 if code[j] == "\\" else 1
    return j + 1


def _balanced(code: str, i: int, open_: str, close: str) -> int:
    """Index just past the bracket matching code[i] == open_, or -1."""
    depth, j, n = 0, i, len(code)
    while j < n:
        ch = code[j]
        if ch in "\"'":
            j = _skip_string(code, j)
            continue
        if ch == open_:
            depth += 1
        elif ch == close:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return -1


def _statement_end(code: str, i: int) -> int:
    depth, j, n = 0, i, len(code)
    while j < n:
        ch = code[j]
        if ch in "\"'":
            j = _skip_string(code, j)
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth <= 0:
            return j + 1
        j += 1
    return n


def _body(code: str, i: int) -> tuple[list[_Stmt], int] | None:
    while i < len(code) and code[i].isspace():
        i += 1
    if i < len(code) and code[i] == "{":
        end = _balanced(code, i, "{", "}")
        if end < 0:
            return None
        inner = split_statements(code[i + 1 : end - 1])
        return (inner, end) if inner is not None else None
    end = _statement_end(code, i)
    inner = split_statements(code[i:end])
    return (inner, end) if inner is not None else None


_KEYWORD = re.compile(
    r"(if|else|for|while|do|switch|try|catch|finally|return|break|continue|throw)\b"
)


def split_statements(code: str) -> list[_Stmt] | None:
    """Comment-free Java -> top-level statements; `if`/`else if`/`else` chains are structured.
    None when the brackets don't balance."""
    out: list[_Stmt] = []
    i, n = 0, len(code)
    while i < n:
        if code[i].isspace() or code[i] == ";":
            i += 1
            continue
        m = _KEYWORD.match(code, i)
        if m and m.group(1) == "if":
            arms: list[tuple[str | None, list[_Stmt]]] = []
            while True:
                j = code.index("if", i) + 2
                while j < n and code[j].isspace():
                    j += 1
                if j >= n or code[j] != "(":
                    return None
                end = _balanced(code, j, "(", ")")
                if end < 0:
                    return None
                body = _body(code, end)
                if body is None:
                    return None
                arms.append((code[j + 1 : end - 1].strip(), body[0]))
                i = body[1]
                rest = re.match(r"\s*else\b", code[i:])
                if not rest:
                    break
                i += rest.end()
                if re.match(r"\s*if\b", code[i:]):
                    continue
                body = _body(code, i)
                if body is None:
                    return None
                arms.append((None, body[0]))
                i = body[1]
                break
            out.append(_Stmt("if", arms=arms))
            continue
        if m:  # loops, switch, try/catch, early exits: kept whole, never modelled
            brace, semi = code.find("{", i), _statement_end(code, i)
            end = _balanced(code, brace, "{", "}") if 0 <= brace < semi else semi
            end = n if end < 0 else end
            out.append(_Stmt("opaque", text=code[i:end].strip()))
            i = end
            continue
        if code[i] == "{":
            body = _body(code, i)
            if body is None:
                return None
            out.append(_Stmt("opaque", text=code[i : body[1]].strip()))
            i = body[1]
            continue
        end = _statement_end(code, i)
        out.append(_Stmt("simple", text=code[i:end].strip()))
        i = end
    return out


# ---- guard conditions -------------------------------------------------------------------------


class _Parser:
    """Java boolean over `<alias>.<column>` refs -> Cond. Unknown leaves become opaque."""

    def __init__(self, text: str, ins: set[str], is_numeric: Callable[[str], bool]):
        self.s, self.i = text, 0
        alias = "|".join(re.escape(a) for a in sorted(ins, key=len, reverse=True))
        self.ref = rf"(?:{alias})\.([A-Za-z_]\w*)"
        self.is_numeric = is_numeric

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def eat(self, tok: str) -> bool:
        self.ws()
        if self.s.startswith(tok, self.i):
            self.i += len(tok)
            return True
        return False

    def parse(self) -> Cond:
        c = self.disj()
        self.ws()
        if self.i != len(self.s):
            return Cond("opaque", text=self.s.strip())
        return c

    def disj(self) -> Cond:
        parts = [self.conj()]
        while self.eat("||"):
            parts.append(self.conj())
        return any_of(parts)

    def conj(self) -> Cond:
        parts = [self.unary()]
        while self.eat("&&"):
            parts.append(self.unary())
        return all_of(parts)

    def unary(self) -> Cond:
        self.ws()
        if self.s.startswith("!", self.i) and not self.s.startswith("!=", self.i):
            self.i += 1
            return self.unary().negated()
        if self.eat("("):
            c = self.disj()
            if not self.eat(")"):
                return Cond("opaque", text=self.s.strip())
            return c
        return self.leaf()

    def _leaf_end(self) -> int:
        depth, j, n = 0, self.i, len(self.s)
        while j < n:
            ch = self.s[j]
            if ch in "\"'":
                j = _skip_string(self.s, j)
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                if depth == 0:
                    return j
                depth -= 1
            elif depth == 0 and self.s.startswith(("&&", "||"), j):
                return j
            j += 1
        return n

    def leaf(self) -> Cond:
        self.ws()
        end = self._leaf_end()
        text = self.s[self.i : end].strip()
        self.i = end
        return self.atom(text) or Cond("opaque", text=text)

    def atom(self, t: str) -> Cond | None:
        ref, lit = self.ref, _STRING
        if m := re.fullmatch(rf"{ref}\s*(==|!=)\s*null|null\s*(==|!=)\s*{ref}", t):
            col, op = (
                (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
            )
            return Cond("atom", col, "IS NULL" if op == "==" else "IS NOT NULL")
        if m := re.fullmatch(rf"({lit})\.equals\(\s*{ref}\s*\)", t):
            return Cond("atom", m.group(2), "=", [_unescape(m.group(1))])
        if m := re.fullmatch(rf"{ref}\.equals\(\s*({lit})\s*\)", t):
            return Cond("atom", m.group(1), "=", [_unescape(m.group(2))])
        if m := re.fullmatch(rf"{ref}\.isEmpty\(\s*\)", t):
            return Cond("atom", m.group(1), "=", [""])
        cmp = r"(==|!=|<=|>=|<|>)"
        if m := re.fullmatch(rf"{ref}\s*{cmp}\s*({_NUMBER})", t):
            col, op, v = m.groups()
        elif m := re.fullmatch(rf"({_NUMBER})\s*{cmp}\s*{ref}", t):
            v, op, col = m.groups()
            op = _FLIP[op]
        else:
            return None
        return Cond("atom", col, _JAVA_CMP[op], [v]) if self.is_numeric(col) else None


def _unescape(lit: str) -> str:
    return re.sub(
        r"\\(.)",
        lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)),
        lit[1:-1],
    )


# ---- the flag proof ---------------------------------------------------------------------------


def prove_flag(
    code: str,
    column: str,
    outs: set[str],
    ins: set[str],
    is_numeric: Callable[[str], bool],
) -> FlagProof | Refusal:
    """`code` must already be comment-stripped. `outs`/`ins` are the output/input row aliases."""
    stmts = split_statements(code)
    if stmts is None:
        return Refusal("code brackets do not balance")
    out_alt = "|".join(re.escape(a) for a in sorted(outs, key=len, reverse=True))
    assign = re.compile(
        rf"^(?:{out_alt})\.{re.escape(column)}\s*=(?!=)\s*(.*?);?$", re.DOTALL
    )
    mentions = re.compile(rf"(?<![\w.])(?:{out_alt})\.{re.escape(column)}\b")
    reads_output = re.compile(rf"(?<![\w.])(?:{out_alt})\.")

    def literal(stmt: _Stmt) -> str | None | bool:
        """The literal a simple `X = "lit";` assigns; False if it is not an X assignment."""
        m = assign.match(stmt.text) if stmt.kind == "simple" else None
        if not m:
            return False
        lit = m.group(1).strip()
        if re.fullmatch(_STRING, lit):
            return _unescape(lit)
        return lit if re.fullmatch(_NUMBER, lit) else None

    def touches(st: _Stmt) -> bool:
        return bool(mentions.search(st.text)) or any(
            (c and mentions.search(c)) or any(touches(b) for b in body)
            for c, body in st.arms
        )

    default: str | None = None
    guards: list[Cond] = []
    texts: list[str] = []
    values: set[str] = set()
    for st in stmts:
        if not touches(st):
            continue
        if st.kind == "simple":
            v = literal(st)
            if v is False:
                return Refusal(
                    f"{st.text[:60]!r} uses {column!r} other than as an assignment"
                )
            if v is None:
                return Refusal(f"{st.text!r} does not assign a literal")
            # An unconditional literal resets the column: earlier guards no longer matter.
            default, guards, texts, values = v, [], [], set()
            continue
        if st.kind == "opaque":
            return Refusal(
                f"touches {column!r} inside an unmodelled statement {st.text[:60]!r}"
            )
        if default is None:
            return Refusal("a guard assigns the flag before any unconditional default")
        # Arm k fires only when no earlier arm of its chain did. Earlier arms that assign the same
        # literal are already in the union, so only the NON-assigning ones must be negated.
        blockers: list[Cond] = []
        for cond, body in st.arms:
            if cond is None:
                return Refusal("an unconditional else touches the flag")
            if mentions.search(cond) or reads_output.search(cond):
                return Refusal(
                    f"guard {cond!r} reads an output column, which the code may have changed"
                )
            c = _Parser(cond, ins, is_numeric).parse()
            hits = [b for b in body if touches(b)]
            if not hits:
                blockers.append(c)
                continue
            v = literal(hits[0]) if len(hits) == 1 else None
            if v is None or v is False:
                return Refusal(
                    "a guarded block does more than one plain literal assignment of the flag"
                )
            guards.append(all_of([c] + [b.negated() for b in blockers]))
            texts.append(cond)
            values.add(v)
    if default is None:
        return Refusal(f"{column!r} is never assigned an unconditional literal")
    if not guards:
        return Refusal(f"{column!r} is a constant {default!r}; no guard changes it")
    if default in values:
        return Refusal(f"a guard re-assigns the default {default!r}")
    if len(values) != 1:
        return Refusal(f"guards assign several values {sorted(values)}")
    return FlagProof(default, values.pop(), any_of(guards), texts)
