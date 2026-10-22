#!/usr/bin/env python3
"""Deterministic execution planner and recorder for Snowflake validation runs. Stdlib only.

The agent runs SQL through its one Snowflake session (temp tables and session variables must
persist across files, and CLI logins are often unavailable; PUT through that session works). This tool owns
everything around that: a $$-aware split, the order, the compile-vs-execute decision per
statement, first-blocker bookkeeping, failure classes, and false-green detection.

  python3 sf_exec.py plan   --dir <out> [--tables tables.json] [--files a.sql,b.sql] [--mode compile|run]
  python3 sf_exec.py next   --plan <out>/exec_plan.json          # prints ONE statement + how to run it
  plan --stage @DB.SCH.STG/run                                    # next prints PUT + EXECUTE IMMEDIATE FROM
  python3 sf_exec.py record --plan P --id N (--ok | --error "<first 300 chars>")
  python3 sf_exec.py status --plan P                              # per-file result; exit 2 if any blocker
  python3 sf_exec.py counts-sql --plan P                          # one query: row count of every output
  python3 sf_exec.py ingest-counts --plan P <result.json>         # flags EMPTY outputs (false-green suspects)
  python3 sf_exec.py compare-sql --plan P --tests <out>/tests      # one query: every expected CSV vs its table

Order: files holding only SET/USE (parameters) first -- a static $VAR must exist when its
procedure is created -- then producers before consumers, then statement order within a file.
After a statement fails, the rest of that file is skipped (its first blocker is what to fix);
files that read a skipped/failed file's outputs are marked UPSTREAM_CASCADE, not failed.

Mode `compile` (T1): DDL that needs no warehouse is executed (CREATE PROCEDURE/FUNCTION,
plain CREATE TABLE, SET/USE); every other statement is sent with only_compile. A statement
that only fails because an object an earlier step creates does not exist yet is DEFERRED to
T2, not counted as a failure. Mode `run` (T2/T3): every statement executes.

With --stage, `next` writes the run of consecutive execute steps of one file to
<dir>/_steps/<id>.sql and prints a PUT + EXECUTE IMMEDIATE FROM pair, so the agent never re-types
SQL that is already on disk; `record --error` maps the reported "on line N" back to its step.
"""

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sql_check as sc  # noqa: E402

CLASSES = ('OWN_DEFECT', 'UPSTREAM_CASCADE', 'TEST_DATA_GAP', 'ORDER', 'ENV', 'DEFERRED')


def _kind(stmt):
    s = re.sub(r'\s+', ' ', stmt.strip()).upper()
    if re.match(r'(SET|UNSET|USE|ALTER SESSION)\b', s):
        return 'param'
    if re.match(r'CREATE (OR REPLACE )?(SECURE )?(PROCEDURE|FUNCTION)\b', s):
        return 'routine'
    if re.match(r'CREATE (OR REPLACE )?((LOCAL |GLOBAL )?(TEMP|TEMPORARY|TRANSIENT) )?TABLE\b', s) and not re.search(r'\bAS\s*(\(\s*)?(SELECT|WITH)\b', s):
        return 'ddl'
    if re.match(r'CREATE\b|DROP\b|ALTER\b', s):
        return 'ddl_query' if re.search(r'\bAS\s*(\(\s*)?(SELECT|WITH)\b', s) else 'ddl'
    if s.startswith('CALL'):
        return 'call'
    return 'query'


def _order(files):
    """Parameter-only files, then a stable topological order over producer->consumer edges."""
    objs = {f: sc.parse_objects(sc.read(f)) for f in files}
    stmts = {f: sc.statements(sc.read(f)) for f in files}
    params = [f for f in files if stmts[f] and all(_kind(s) == 'param' for s, _ in stmts[f])]
    produced_by = {}
    for f in files:
        for p in objs[f]['produces']:
            produced_by.setdefault(sc._last(p['name']), f)
        for d in objs[f]['procedures']:
            produced_by.setdefault(sc._last(d['name']), f)
    deps = {f: set() for f in files}
    for f in files:
        for c in objs[f]['consumes'] + objs[f]['calls']:
            src = produced_by.get(sc._last(c['name']))
            if src and src != f:
                deps[f].add(src)
    out, done = list(params), set(params)
    rest = [f for f in files if f not in done]
    while rest:
        ready = [f for f in rest if deps[f] <= done] or [rest[0]]     # cycle: keep input order
        for f in ready:
            out.append(f)
            done.add(f)
        rest = [f for f in rest if f not in done]
    return out, deps, objs


def _surviving(path):
    """Tables still present after the file runs: not temporary and not dropped later in the file."""
    objs = sc.parse_objects(sc.read(path))
    dropped = {sc._last(sc.norm_name(n)) for n in
               re.findall(rf'\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?({sc.QNAME})', sc.masked(sc.read(path)), re.I)}
    return sorted({p['name'] for p in objs['produces'] if not p['temp'] and sc._last(p['name']) not in dropped})


def cmd_plan(a):
    files = [os.path.join(a.dir, f) for f in a.files.split(',')] if a.files else sc.sql_files(a.dir)
    files = [f for f in files if os.path.basename(f).lower() not in sc.GENERATED]
    ordered, deps, objs = _order(files)
    steps, n = [], 0
    for f in ordered:
        for s, ln in sc.statements(sc.read(f)):
            n += 1
            step = {'id': n, 'file': os.path.basename(f), 'line': ln, 'kind': _kind(s), 'status': None}
            if a.mode == 'compile' and step['kind'] == 'call':    # a CALL only resolves at run time (T2)
                step.update(status='deferred', **{'class': 'DEFERRED'})
            steps.append(step)
    plan = {'mode': a.mode, 'dir': os.path.abspath(a.dir), 'tables': a.tables, 'stage': a.stage,
            'order': [os.path.basename(f) for f in ordered],
            'deps': {os.path.basename(k): sorted(os.path.basename(x) for x in v) for k, v in deps.items()},
            'outputs': {os.path.basename(f): sorted({p['name'] for p in objs[f]['produces']}) for f in ordered},
            'steps': steps}
    path = a.out or os.path.join(a.dir, f'exec_plan_{a.mode}.json')
    _save(path, plan)
    print(f'{len(ordered)} files, {len(steps)} statements, mode={a.mode} -> {path}')
    print('order: ' + ' > '.join(plan['order']))
    return 0


def _load(p):
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def _save(p, plan):
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(plan, fh, indent=1)


def _statement(plan, step):
    stmts = sc.statements(sc.read(os.path.join(plan['dir'], step['file'])))
    i = [s for s in plan['steps'] if s['file'] == step['file']].index(step)
    return stmts[i][0]


def _blocked_files(plan):
    bad = {s['file'] for s in plan['steps'] if s['status'] in ('error', 'skipped')}
    # cascade: anything depending on a blocked file
    changed = True
    while changed:
        changed = False
        for f, ds in plan['deps'].items():
            if f not in bad and bad & set(ds):
                bad.add(f)
                changed = True
    return bad


def cmd_next(a):
    plan = _load(a.plan)
    blocked = _blocked_files(plan)
    for s in plan['steps']:
        if s['status'] is not None:
            continue
        if s['file'] in blocked:
            s['status'] = 'skipped'
            s['class'] = 'UPSTREAM_CASCADE' if any(st['status'] == 'error' for st in plan['steps']
                                                   if st['file'] != s['file'] and st['file'] in plan['deps'].get(s['file'], [])) \
                else 'AFTER_BLOCKER'
            continue
        how = 'only_compile=true' if _compile_only(plan, s) else 'execute'
        if plan.get('stage') and how == 'execute':
            return _next_staged(a, plan, s, blocked)
        _save(a.plan, plan)
        print(f"#{s['id']} {s['file']}:{s['line']} kind={s['kind']} run_with={how}")
        print(_statement(plan, s) + ';')
        return 0
    _save(a.plan, plan)
    print('DONE -- run `sf_exec.py status`')
    return 0


def _compile_only(plan, s):
    return plan['mode'] == 'compile' and s['kind'] in ('query', 'ddl_query', 'call')


def _next_staged(a, plan, first, blocked):
    group = []
    for s in plan['steps'][plan['steps'].index(first):]:
        if s['file'] != first['file'] or s['status'] is not None or _compile_only(plan, s):
            break
        group.append(s)
    os.makedirs(os.path.join(plan['dir'], '_steps'), exist_ok=True)
    path = os.path.join(plan['dir'], '_steps', f"{first['id']}.sql")
    body, starts = '', []
    for s in group:
        starts.append(body.count('\n') + 1)
        body += _statement(plan, s).strip() + ';\n'
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)
    plan['group'] = {'ids': [s['id'] for s in group], 'starts': starts}
    _save(a.plan, plan)
    stage = plan['stage'].rstrip('/')
    print(f"#{first['id']}-{group[-1]['id']} {first['file']} ({len(group)} statements) run_with=execute")
    print(f"PUT '{_file_url(path)}' {stage}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;")
    print(f"EXECUTE IMMEDIATE FROM {stage}/{first['id']}.sql;")
    print(f"-- then: record --id {first['id']} --ok  (or --error \"<message>\")")
    return 0


def _file_url(path):
    return 'file://' + os.path.abspath(path).replace('\\', '/').replace("'", "\\'")


def classify(plan, step, msg):
    m = msg.lower()
    tables = _load(plan['tables']) if plan.get('tables') and os.path.exists(plan['tables']) else []
    obj = re.search(r"(?:object|table|view|procedure|function|schema)\s+'?\"?([\w.$\"]+)\"?'?\s+does not exist", msg, re.I)
    if re.search(r'session variable .* does not exist', m):
        var = re.search(r"\$(\w+)", msg)
        sets = var and any(re.search(rf'\bSET\s+{var.group(1)}\b', sc.read(os.path.join(plan['dir'], f)), re.I)
                           for f in plan['order'])
        return ('ORDER', 'SET is in the plan but ran later -- re-plan; parameter files run first') if sets \
            else ('OWN_DEFECT', 'no SET for this variable anywhere -- add it or use GETVARIABLE')
    if obj:
        name = sc._last(sc.norm_name(obj.group(1)))
        earlier = [s for s in plan['steps'] if s['id'] < step['id']]
        producers = {f for f, outs in plan['outputs'].items() if name in {sc._last(o) for o in outs}}
        if producers & {s['file'] for s in earlier if s['status'] in ('error', 'skipped')}:
            return 'UPSTREAM_CASCADE', 'its producer failed earlier -- fix that file first'
        if plan['mode'] == 'compile' and producers:
            return 'DEFERRED', 'created by an earlier statement; only_compile cannot see it -- checked in T2'
        if producers - {s['file'] for s in earlier}:
            return 'ORDER', f'produced later by {sorted(producers)[0]} -- dependency order is wrong'
        row = next((r for r in tables if name in {sc._last(sc.norm_name(r['name'])), sc._last(sc.norm_name(r.get('snowflake_fqn') or ''))}), None)
        if row and row.get('location_status') in ('not_found', 'unchecked'):
            return 'TEST_DATA_GAP', f"{row['name']} is {row.get('location_status')} in tables.json -- create it from render-ddl"
        return 'OWN_DEFECT', 'unresolved name -- compare with tables.json / xfile findings'
    if 'invalid identifier' in m:
        return 'OWN_DEFECT', 'check `tables.py gap <table> <column>` first: exit 3 means TEST_DATA_GAP'
    if re.search(r'insufficient privileges|not authorized|warehouse|timeout|quota|network', m):
        return 'ENV', 'environment / permission problem, not the conversion'
    return 'OWN_DEFECT', 'compiler rejected the statement -- fix the SQL, then re-run this file and its dependents'


def _resolve_group(plan, a):
    """A staged group is one call: --ok covers all of it; an error names the statement by its line."""
    g = plan.pop('group', None)
    if not g or a.id != g['ids'][0]:
        return a.id
    hit = len(g['ids']) - 1
    if a.error:
        m = re.search(r'\bon line (\d+)', a.error)
        hit = sum(1 for st in g['starts'] if m and st <= int(m.group(1))) - 1 if m else 0
    for sid in g['ids'][:max(hit, 0) if a.error else len(g['ids'])]:
        step = next(s for s in plan['steps'] if s['id'] == sid)
        step['status'] = 'ok'
    return g['ids'][max(hit, 0)]


def cmd_record(a):
    plan = _load(a.plan)
    sid = _resolve_group(plan, a)
    if a.ok and sid != a.id:
        _save(a.plan, plan)
        print(f"#{a.id}-{sid} ok")
        return 0
    step = next(s for s in plan['steps'] if s['id'] == sid)
    if a.ok:
        step.pop('error', None)
        step.pop('class', None)
        step['status'] = 'ok'
        print(f"#{a.id} ok")
    else:
        cls, hint = classify(plan, step, a.error)
        step.update(status='deferred' if cls == 'DEFERRED' else 'error', error=a.error[:300], **{'class': cls})
        print(f"#{sid} {step['file']}:{step['line']} {cls}: {hint}")
    _save(a.plan, plan)
    return 0


def cmd_reset(a):
    """After a fix: clear results for these files and everything downstream of them."""
    plan = _load(a.plan)
    targets = set(a.files.split(','))
    changed = True
    while changed:
        changed = False
        for f, ds in plan['deps'].items():
            if f not in targets and targets & set(ds):
                targets.add(f)
                changed = True
    for s in plan['steps']:
        if s['file'] in targets:
            s['status'] = None
            for k in ('error', 'class'):
                s.pop(k, None)
            if plan['mode'] == 'compile' and s['kind'] == 'call':    # same rule as `plan`: CALLs resolve in T2
                s.update(status='deferred', **{'class': 'DEFERRED'})
    _save(a.plan, plan)
    print('reset: ' + ', '.join(sorted(targets)))
    return 0


def cmd_status(a):
    plan = _load(a.plan)
    rows, failed = [], 0
    for f in plan['order']:
        st = [s for s in plan['steps'] if s['file'] == f]
        err = next((s for s in st if s['status'] == 'error'), None)
        casc = next((s for s in st if s.get('class') == 'UPSTREAM_CASCADE'), None)
        if err:
            failed += 1
            rows.append(f"{f}: BLOCKED {err['class']} at line {err['line']}: {err['error'][:120]}")
        elif casc:
            rows.append(f'{f}: NOT RUN (UPSTREAM_CASCADE)')
        elif any(s['status'] is None for s in st):
            rows.append(f'{f}: pending {sum(s["status"] is None for s in st)}/{len(st)}')
        else:
            d = sum(s['status'] == 'deferred' for s in st)
            rows.append(f'{f}: ok {len(st) - d}/{len(st)}' + (f' ({d} deferred to T2)' if d else ''))
    empty = plan.get('empty_outputs', [])
    print('\n'.join(rows))
    if empty:
        print('EMPTY outputs (false-green suspects): ' + ', '.join(empty[:20]))
    print(f'sf_exec status mode={plan["mode"]}: files={len(plan["order"])} blocked={failed} empty_outputs={len(empty)}')
    return 2 if failed else 0


def cmd_counts_sql(a):
    plan = _load(a.plan)
    names = sorted({o for f in plan['outputs'] for o in _surviving(os.path.join(plan['dir'], f))})
    if not names:
        print('-- no output tables in plan')
        return 0
    parts = [f"SELECT '{n}' AS t, COUNT(*) AS n FROM {n}" for n in names]
    print('SELECT TO_JSON(OBJECT_AGG(t, n)) AS counts FROM (\n' + '\nUNION ALL\n'.join(parts) + '\n);')
    return 0


def cmd_ingest_counts(a):
    plan = _load(a.plan)
    raw = open(a.result, encoding='utf-8').read().strip()
    counts = json.loads(raw)
    plan['row_counts'] = counts
    plan['empty_outputs'] = sorted(k for k, v in counts.items() if not v)
    _save(a.plan, plan)
    print(f"{len(counts)} outputs counted, {len(plan['empty_outputs'])} empty"
          + (': ' + ', '.join(plan['empty_outputs'][:20]) if plan['empty_outputs'] else ''))
    return 0


def _ident(c):
    # always quote: CSV headers can be reserved words (DEFAULT); plain names resolve as stored (upper)
    c = c.upper() if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', c) else c
    return '"' + c.replace('"', '""') + '"'


def _col_type(vals):
    vals = [v.strip() for v in vals if v.strip() != '']
    is_day = lambda v: re.fullmatch(r'\d{4}-\d{2}-\d{2}', v)
    if vals and all(re.fullmatch(r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d*)?)?', v) for v in vals):
        return 'ts'
    # dates mixed with whole numbers: the numbers are SAS day counts (e.g. `if d = 0 then x = 0`)
    if any(is_day(v) for v in vals) and all(is_day(v) or re.fullmatch(r'-?\d+', v) for v in vals):
        return 'date'
    try:
        if vals:
            [float(v) for v in vals]
            return 'num'
    except ValueError:
        pass
    return 'str'


def _norm(expr, kind, digits):
    # comparison-rules.md: NULL == '' and trailing blanks ignored for text; dates by day; numbers rounded;
    # a SAS date number (days since 1960-01-01) equals the calendar DATE on either side
    v = f'TO_VARCHAR({expr})'
    sas_day = f"DATEADD('day', TRY_TO_NUMBER({v}), '1960-01-01'::DATE)"
    if kind == 'num':
        day = f"DATEDIFF('day', '1960-01-01'::DATE, TRY_TO_DATE(LEFT({v}, 10)))"
        return f"ROUND(IFF(REGEXP_LIKE({v}, '\\\\d{{4}}-\\\\d{{2}}-\\\\d{{2}}.*'), {day}, TRY_TO_DOUBLE({v})), {digits})"
    if kind == 'date':
        return f"IFF(REGEXP_LIKE({v}, '-?\\\\d+'), {sas_day}, TRY_TO_DATE(LEFT({v}, 10)))"
    if kind == 'ts':                                   # '08:00:00' == '08:00:00.000' (to the second)
        return f"DATE_TRUNC('second', TRY_TO_TIMESTAMP_NTZ({v}))"
    return f"NULLIF(RTRIM({v}), '')"


def compare_query(table, header, rows, digits=6):
    kinds = [_col_type([r[i] if i < len(r) else '' for r in rows]) for i in range(len(header))]
    alias = [f'C{i}' for i in range(len(header))]
    lit = lambda v: 'NULL' if v == '' else "'" + v.replace("'", "''") + "'"
    if rows:
        vals = ',\n    '.join('(' + ', '.join(lit(r[i] if i < len(r) else '') for i in range(len(header))) + ')' for r in rows)
        src = f"(VALUES\n    {vals}) AS v({', '.join(alias)})"
    else:
        src = f"(SELECT {', '.join('NULL::VARCHAR AS ' + a for a in alias)} WHERE FALSE)"
    e_cols = ', '.join(f'{_norm(a, k, digits)} AS {a}' for a, k in zip(alias, kinds))
    a_cols = ', '.join(f'{_norm(_ident(h), k, digits)} AS {a}' for h, a, k in zip(header, alias, kinds))
    dup = f"ROW_NUMBER() OVER (PARTITION BY {', '.join(alias)} ORDER BY 1) AS DUP_N"     # multiset, not set, EXCEPT
    cols = ', '.join(alias)
    names = ', '.join(f"'{h}', {a}" for h, a in zip(header, alias))
    return (f"WITH e AS (SELECT {cols}, {dup} FROM (SELECT {e_cols} FROM {src})),\n"
            f"a AS (SELECT {cols}, {dup} FROM (SELECT {a_cols} FROM {table})),\n"
            f"m AS (SELECT * FROM e EXCEPT SELECT * FROM a), x AS (SELECT * FROM a EXCEPT SELECT * FROM e)\n"
            f"SELECT '{table}' AS T, (SELECT COUNT(*) FROM e) AS EXPECTED_ROWS, (SELECT COUNT(*) FROM a) AS ACTUAL_ROWS,\n"
            f"  (SELECT COUNT(*) FROM m) AS MISSING, (SELECT COUNT(*) FROM x) AS EXTRA,\n"
            f"  (SELECT TO_JSON(ARRAY_AGG(r)) FROM (SELECT OBJECT_CONSTRUCT_KEEP_NULL('side', s, {names}) r FROM\n"
            f"    (SELECT 'missing' s, * FROM m UNION ALL SELECT 'extra', * FROM x) LIMIT 10)) AS DIFF_ROWS")


def _dropped_at_end(plan):
    """Tables whose last statement in the plan's SQL is a DROP (a drop-then-recreate still survives)."""
    out = set()
    for f in plan['order']:
        txt = sc.masked(sc.read(os.path.join(plan['dir'], f)))
        last = {}
        for m in re.finditer(rf'\b(DROP|CREATE)\b[^;]*?\bTABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?({sc.QNAME})', txt, re.I):
            last[sc._last(sc.norm_name(m.group(2)))] = m.group(1).upper()
        out |= {n for n, k in last.items() if k == 'DROP'}
    return out


def cmd_compare_sql(a):
    import csv
    plan = _load(a.plan)
    files = sorted(glob.glob(os.path.join(a.tests, '**', 'expected_*.csv'), recursive=True))
    if not files:
        print(f'-- no expected_<TABLE>.csv under {a.tests}')
        return 1
    parts, skipped = [], []
    gone = _dropped_at_end(plan)
    for f in files:
        with open(f, newline='', encoding='utf-8') as fh:
            data = list(csv.reader(fh))
        table = os.path.basename(f)[len('expected_'):-len('.csv')]
        if sc._last(sc.norm_name(table)) in gone:
            skipped.append(table)
            continue
        if a.schema:
            table = f'{a.schema}.{table}'
        parts.append('(' + compare_query(table, data[0], data[1:], a.digits) + ')')
    if skipped:
        print('NOT_COMPARABLE (the program drops them): ' + ', '.join(skipped))
    if not parts:
        return 1
    # one statement, so EXECUTE IMMEDIATE FROM returns its rows
    sql = 'SELECT * FROM (\n' + '\nUNION ALL\n'.join(parts) + '\n) ORDER BY T;\n'
    os.makedirs(os.path.join(plan['dir'], '_steps'), exist_ok=True)
    path = os.path.join(plan['dir'], '_steps', 'compare.sql')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(sql)
    print(f'{len(parts)} outputs -> {path} (PASS when MISSING = EXTRA = 0)')
    if plan.get('stage'):
        stage = plan['stage'].rstrip('/')
        print(f"PUT '{_file_url(path)}' {stage}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE;")
        print(f'EXECUTE IMMEDIATE FROM {stage}/compare.sql;')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('plan'); s.add_argument('--dir', required=True); s.add_argument('--tables')
    s.add_argument('--files'); s.add_argument('--mode', choices=('compile', 'run'), default='run'); s.add_argument('--out')
    s.add_argument('--stage', help='@DB.SCHEMA.STAGE/path: run steps from staged files instead of pasting SQL')
    s = sub.add_parser('next'); s.add_argument('--plan', required=True)
    s = sub.add_parser('record'); s.add_argument('--plan', required=True); s.add_argument('--id', type=int, required=True)
    g = s.add_mutually_exclusive_group(required=True); g.add_argument('--ok', action='store_true'); g.add_argument('--error')
    s = sub.add_parser('reset'); s.add_argument('--plan', required=True); s.add_argument('--files', required=True)
    s = sub.add_parser('status'); s.add_argument('--plan', required=True)
    s = sub.add_parser('counts-sql'); s.add_argument('--plan', required=True)
    s = sub.add_parser('ingest-counts'); s.add_argument('--plan', required=True); s.add_argument('result')
    s = sub.add_parser('compare-sql'); s.add_argument('--plan', required=True); s.add_argument('--tests', required=True)
    s.add_argument('--schema'); s.add_argument('--digits', type=int, default=6)
    a = ap.parse_args(argv)
    return {'plan': cmd_plan, 'next': cmd_next, 'record': cmd_record, 'reset': cmd_reset, 'status': cmd_status,
            'counts-sql': cmd_counts_sql, 'ingest-counts': cmd_ingest_counts, 'compare-sql': cmd_compare_sql}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
