"""Unit parameters in the shipped models: ${NAME} -> {{ var('NAME', '<default>') }}.

Usage: python3 params_postpass.py <ir.json> <output-root> [--check]

Runs after ai_fill (stage 3b) and the sources declaration (stage 3c), over every dbt project
under <output-root>: models/**/*.sql and models/**/*.yml. Only names the IR's `parameters` and
`variables` blocks carry are rewritten, to their `key` (the CONFIG / --vars key); any other ${X}
(a built-in, or a name nothing sets) is left as is. The var() default is the conversion-time
value, so a run without --vars behaves like the source run with no -p, and the producer's
BuildDbtVarsJsonUDF --vars overrides it per run.

A reference already inside a Jinja expression ({{ ... }} or {% ... %}) becomes a bare var(...),
never nested Jinja: a quoted literal that is exactly the reference is replaced by it, and a
literal with more text around it is concatenated with `~`.

Two checks, both printed and both degrading:
  residual  a ${ left in any model or YAML file after the rewrite;
  missing   a declared parameter the source substitutes (referenced_by[].substituted) that no
            model reads as var('NAME'). That is the shape of ai_fill inlining the default literal
            instead of keeping ${NAME}; `inlined` names the files holding the default literal.

Verdict line, always printed (the driver greps it):
  parameters : declared=<n> rewritten=<n> residual=<n> missing=<n>
Exit 0 always; the driver decides degradation from the verdict.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PRUNE = {"target", "dbt_internal_packages", "dbt_packages", "logs"}
REF = re.compile(r"\$\{([^{}$]+)\}")
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
QUOTED = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
YAML_VALUE = re.compile(r"^(\s*(?:-\s+)?[^\s:#][^:#]*:\s+)(.*)$")


def var_call(key: str, default: str) -> str:
    escaped = default.replace("\\", "\\\\").replace("'", "\\'")
    return "var('%s', '%s')" % (key, escaped)


def var_expr(key: str, default: str) -> str:
    return "{{ %s }}" % var_call(key, default)


def _in_jinja(block: str, defaults: dict[str, tuple[str, str]]) -> tuple[str, int]:
    """Rewrite references inside one Jinja expression without nesting Jinja."""
    count = 0

    def literal(m: re.Match) -> str:
        nonlocal count
        lit = m.group(0)
        quote, body = lit[0], lit[1:-1]
        pieces, last = [], 0
        for r in REF.finditer(body):
            if r.group(1) not in defaults:
                continue
            if r.start() > last:
                pieces.append(quote + body[last:r.start()] + quote)
            pieces.append(var_call(*defaults[r.group(1)]))
            count += 1
            last = r.end()
        if not pieces:
            return lit
        if last < len(body):
            pieces.append(quote + body[last:] + quote)
        return " ~ ".join(pieces)

    def bare(m: re.Match) -> str:
        nonlocal count
        if m.group(1) not in defaults:
            return m.group(0)
        count += 1
        return var_call(*defaults[m.group(1)])

    out, last = [], 0
    for q in QUOTED.finditer(block):
        out.append(REF.sub(bare, block[last:q.start()]))
        out.append(literal(q))
        last = q.end()
    out.append(REF.sub(bare, block[last:]))
    return "".join(out), count


def rewrite_text(text: str, defaults: dict[str, tuple[str, str]]) -> tuple[str, int]:
    count = 0

    def sub(m: re.Match) -> str:
        nonlocal count
        name = m.group(1)
        if name not in defaults:
            return m.group(0)
        count += 1
        return var_expr(*defaults[name])

    out, last = [], 0
    for j in JINJA.finditer(text):
        out.append(REF.sub(sub, text[last:j.start()]))
        block, n = _in_jinja(j.group(0), defaults)
        count += n
        out.append(block)
        last = j.end()
    out.append(REF.sub(sub, text[last:]))
    return "".join(out), count


def rewrite_yaml(text: str, defaults: dict[str, tuple[str, str]]) -> tuple[str, int]:
    """Same rewrite, and a plain scalar that now holds Jinja is double-quoted: an unquoted value
    starting with `{` is a YAML flow mapping, not a string."""
    out, total = [], 0
    for line in text.split("\n"):
        new, n = rewrite_text(line, defaults)
        if n:
            total += n
            m = YAML_VALUE.match(new)
            if m and not m.group(2).startswith(("'", '"')):
                new = m.group(1) + '"' + m.group(2).replace('"', '\\"') + '"'
        out.append(new)
    return "\n".join(out), total


def model_files(out_root: Path) -> list[Path]:
    files = []
    for project in sorted(out_root.rglob("dbt_project.yml")):
        if PRUNE & set(project.relative_to(out_root).parts):
            continue
        models = project.parent / "models"
        if not models.is_dir():
            continue
        for f in sorted(models.rglob("*")):
            if f.suffix in (".sql", ".yml", ".yaml") and not PRUNE & set(f.relative_to(models).parts):
                files.append(f)
    return files


def run(ir: dict, out_root: Path, check_only: bool = False) -> dict:
    params = (ir.get("parameters") or []) + (ir.get("variables") or [])
    defaults = {p["name"]: (p.get("key") or p["name"].replace(" ", "_"), p.get("default") or "")
                for p in params}
    files = model_files(out_root)
    rewritten: list[tuple[str, int]] = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        if check_only or "${" not in text:
            continue
        rewrite = rewrite_yaml if f.suffix in (".yml", ".yaml") else rewrite_text
        new, n = rewrite(text, defaults)
        if n:
            f.write_text(new, encoding="utf-8")
            rewritten.append((str(f.relative_to(out_root)), n))

    residual, reads, inlined = [], {}, {}
    for f in files:
        text = f.read_text(encoding="utf-8")
        rel = str(f.relative_to(out_root))
        for m in REF.finditer(text):
            residual.append((rel, m.group(0)))
        for name, (key, default) in defaults.items():
            if re.search(r"""var\(\s*['"]%s['"]""" % re.escape(key), text):
                reads.setdefault(name, []).append(rel)
            elif default and default in text:
                inlined.setdefault(name, []).append(rel)

    substituted = [p["name"] for p in params
                   if any(r.get("substituted") for r in p.get("referenced_by") or [])]
    missing = [n for n in substituted if n not in reads]
    return {
        "declared": len(params),
        "rewritten": sum(n for _, n in rewritten),
        "rewritten_files": rewritten,
        "residual": residual,
        "missing": missing,
        "inlined": {n: inlined.get(n, []) for n in missing},
        "reads": reads,
    }


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    ir = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    r = run(ir, Path(args[1]), check_only="--check" in argv)
    for rel, n in r["rewritten_files"]:
        print(f"  rewrote   : {rel}  ({n} reference(s))")
    for name, rels in sorted(r["reads"].items()):
        print(f"  var()     : {name} read by {', '.join(rels)}")
    for rel, ref in r["residual"]:
        print(f"  *** RESIDUAL {ref} in {rel} -- not a declared parameter, or not rewritten")
    for name in r["missing"]:
        where = r["inlined"].get(name) or []
        print(f"  *** MISSING var('{name}'): the source substitutes it and no model reads it"
              + (f"; the default literal is in {', '.join(where)} (inlined?)" if where else ""))
    print(f"parameters : declared={r['declared']} rewritten={r['rewritten']} "
          f"residual={len(r['residual'])} missing={len(r['missing'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
