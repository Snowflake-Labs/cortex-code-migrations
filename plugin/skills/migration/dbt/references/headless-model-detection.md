# Detecting headless models

Two checks for the same failure class: a model whose upstream reference or whole `FROM` clause
ended up inside a comment. Step 2.5.2 says when to run them and what must be true to pass;
this file is the scripts and the reasoning behind their exact shape.

## Why not just grep for a commented `ref()`

SnowConvert also emits large *legitimate* commented-out blocks, so a raw grep returns roughly
six times more hits than there are real defects — observed 160 raw hits against 26 real. The
only sound signal is a per-file diff of the **live** set of upstream calls, comments stripped,
against the `source/` original. `source/` is the oracle: any drop is converter-introduced.

Three things the script below gets right, each of which was a real failure when it was not:

**Count `source()` as well as `ref()`, and report them separately.** A staging layer generated
under `models/sources/**` reaches its upstreams only through `{{ source(...) }}` and contains
no `ref()` at all, so a `ref()`-only gate is blind to it and prints a clean `0` while those
models are gutted. Keeping the two numbers apart also matters because a change from `ref` to
`source` at a constant total is itself suspicious.

**Compare the set of targets, not the number of call sites.** A model that calls
`{{ ref('x') }}` twice has one DAG edge, so a raw count falls when a duplicate call site is
removed even though nothing was lost. In one project **898 source model files carried at least
one duplicated `ref()` target**, across 3,562 redundant call sites, so a count comparison is
fragile by construction. Do not "simplify" this back to `len(...)`.

**Check the denominator before you believe the result.** The script pairs each `source/` file
with a same-relative-path file under `DST` and skips any pair it cannot form. If `DST` is wrong,
or the tree you point at uses a different layout, *every* pair is skipped and the gate prints a
flawless `LOST UPSTREAMS: 0` having compared nothing. That is why it reports
`FILES COMPARED: n / m` first: **if `n` is 0 or far below `m`, the gate did not run and its
zero means nothing.** Measured on one project, pointing `DST` at the raw converter output gave
`FILES COMPARED: 0 / 2290` — the converter nests its output as
`<dir>/<name>/deterministic/<timestamp>/<name>.sql`, so no relative path lined up.

**Run it against the repointed tree, never the converter's raw output.** Conversion strips
Jinja and repointing re-injects it in a later phase, so a freshly converted tree can contain
**zero** `{{ ref() }}` — in one project the raw output had 0 against 9,453 in the repointed
tree. `DST` is the repointed project directory for that reason. Note the failure is **silent,
not loud**: an early-phase run does not report catastrophic loss, it reports a clean zero over
an empty comparison. The denominator is the only thing that distinguishes the two.

## Upstream-call diff

```bash
python3 - <<'PY'
import os, re
SRC, DST = 'source', 'snowflake'
CALL = re.compile(r'\{\{\s*(ref|source)\s*\(([^)]*)\)', re.S)

def live_calls(c):
    c = re.sub(r'/\*.*?\*/', '', c, flags=re.S)          # block comments
    c = re.sub(r'^[^\S\n]*--.*$', '', c, flags=re.M)      # line comments
    refs, srcs = set(), set()
    for kind, args in CALL.findall(c):
        key = re.sub(r'\s+', '', args)                    # normalize whitespace
        (refs if kind == 'ref' else srcs).add(key)
    return refs, srcs

lost = []
considered = compared = 0
for root, dirs, files in os.walk(SRC):
    # skip a self-nested migration dir and build output
    dirs[:] = [d for d in dirs if d not in ('migration', 'target', 'dbt_packages', '.git')]
    for f in files:
        if not f.endswith('.sql'):
            continue
        considered += 1
        rel = os.path.relpath(os.path.join(root, f), SRC)
        dst = os.path.join(DST, rel)
        if not os.path.exists(dst):
            continue
        compared += 1
        rd = lambda p: open(p, encoding='utf-8', errors='replace').read()
        sr, ss = live_calls(rd(os.path.join(root, f)))
        dr, ds = live_calls(rd(dst))
        if (sr - dr) or (ss - ds):
            lost.append((rel, sorted(sr - dr), sorted(ss - ds)))

# The denominator comes first: a 0-file comparison also prints 0 lost upstreams.
print(f'FILES COMPARED: {compared} / {considered}')
if compared < considered * 0.9:
    print(f'  GATE DID NOT RUN — {considered - compared} source files had no counterpart '
          f'under DST={DST!r}. Fix the path before reading the result below.')
print('FILES WITH LOST UPSTREAMS:', len(lost),
      '| ref() TARGETS LOST:', sum(len(r) for _, r, _ in lost),
      '| source() TARGETS LOST:', sum(len(s) for _, _, s in lost))
for rel, r, s in sorted(lost, key=lambda x: -(len(x[1]) + len(x[2]))):
    print(f'  {rel}: ref -{r} source -{s}')
PY
```

Passing means **both** lines are right: `FILES COMPARED` at or near the full source count, *and*
`FILES WITH LOST UPSTREAMS: 0`. Quote both when you report it. A zero on the second line with a
zero on the first is the gate telling you it never ran.

A file that drops to `0` is the worst case: dbt treats it as a root node and builds it before
its upstreams, against stale or nonexistent tables.

Every file this reports must be repaired — see Step 2.5.4, most are restorable from source
verbatim. Re-run the script after repairing; it must print `0` before you leave Step 2.5.

## Models with no live `FROM` at all

```bash
for f in $(grep -rl 'SSC-EWI-0001' snowflake/models --include='*.sql'); do
  case "$f" in */macro_tests/*) continue ;; esac
  perl -0pe 's{/\*.*?\*/}{}gs; s{--.*$}{}gm' "$f" \
    | grep -qiE '(^|[[:space:]])FROM[[:space:]]' || echo "HEADLESS: $f"
done
```

**Strip comments before matching, and match `FROM` anywhere on the line.** Both obvious
regexes are wrong against raw text. Anchoring to `^[[:space:]]*FROM` misses every inline
`SELECT a FROM b` and reports those as headless. Matching the raw text un-anchored fails worse
in the other direction: it is satisfied by the converter's own `--    FROM source`, which has
whitespace on both sides of `FROM` and so looks live. Measured across the 77 `SSC-EWI-0001`
files of one raw tree, the un-anchored raw form found **3** of the **74** the `perl` pass
finds — blind to 71 real defects. The `perl` pass deletes `/* */` blocks and everything from
`--` to end of line first, the same normalization `live_calls()` does above.

The `macro_tests/` skip covers macro fixtures, which legitimately have no `FROM` clause and are
not defects. **Many projects have no such directory** — the `case` is a harmless no-op then, so
leave it in rather than reasoning about whether it applies.
