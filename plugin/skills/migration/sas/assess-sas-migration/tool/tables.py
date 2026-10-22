#!/usr/bin/env python3
"""tables.json — every table a SAS portfolio touches, carried from assessment through
conversion and test: where it lives in Snowflake, its columns, and how we know. Stdlib only.

Assessment seeds one row per input (read, created nowhere in scope) and output (created, read
nowhere in scope). Conversion adds intermediates, records where each table was found (or that
it was not), its columns, and regenerates ``source_table_ddl.sql`` from this file -- never a
side ``*_fix.sql``. Read it through these commands; do not load the JSON into context.

  python tables.py summary tables.json                         # counts + not-found names
  python tables.py probe tables.json --schemas DB.SCH[,DB2.S2]  # prints ONE SQL query
  python tables.py ingest tables.json probe_result.json        # the query's single JSON cell
  python tables.py import-ddl tables.json user_ddl.sql|.csv    # CREATE TABLEs, or table,column,type
  python tables.py get tables.json LIB.T                       # one row, compact
  python tables.py gap tables.json LIB.T COL                   # exit 3 = TEST_DATA_GAP
  python tables.py seed-targets tables.json                    # tables that get test rows
  python tables.py update tables.json LIB.T --columns '[{"name":"ID","type":"NUMBER"}]' --from live --by convert
  python tables.py update tables.json --batch rows.jsonl --by convert
  python tables.py render-ddl tables.json [--roles input,intermediate] > source_table_ddl.sql
  python tables.py stamp tables.json expected/foo.csv LIB.T LIB.U
  python tables.py check-stale tables.json expected/

Expected-results CSVs are stamped with the fingerprints they were traced against
(``<csv>.fp.json``); ``check-stale`` reports CSVs whose tables changed since.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

COLUMNS_FROM = ('live', 'user_file', 'inferred', 'none')
CHANGED_BY = ('assess', 'convert', 'test')
ROLES = ('input', 'intermediate', 'output')
LOCATION_STATUS = ('unchecked', 'found', 'not_found', 'user_supplied')
# SAS metadata views have Snowflake equivalents (INFORMATION_SCHEMA); they are never data tables.
SYSTEM_LIBREFS = ('DICTIONARY', 'SASHELP')
OPTIONAL = ('full_data_fqn', 'sas_output_fqn')
GAP_EXIT = 3


def fingerprint(columns: List[Dict]) -> str:
    key = sorted((c['name'].upper(), str(c.get('type', '')).upper()) for c in columns)
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()


def load(path) -> List[Dict]:
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []


def save(path, rows: List[Dict]) -> None:
    rows = sorted(rows, key=lambda r: (ROLES.index(r['role']) if r['role'] in ROLES else 9, r['name']))
    Path(path).write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


def is_system(name: str) -> bool:
    return name.split('.')[0].upper() in SYSTEM_LIBREFS


def _new_row(name: str, role: str, by: str) -> Dict:
    return {'name': name, 'role': role, 'snowflake_fqn': None, 'columns': [],
            'columns_from': 'none', 'location_status': 'unchecked', 'sample_path': None,
            'last_changed_by': by, 'fingerprint': fingerprint([])}


def seed(path, inputs: List[str], outputs: List[str]) -> List[Dict]:
    """Write assessment rows, keeping anything a later phase already filled in."""
    existing = {r['name']: r for r in load(path)}
    rows = []
    for role, names in (('input', inputs), ('output', outputs)):
        for name in names:
            if is_system(name) or name in {r['name'] for r in rows}:
                continue
            row = existing.get(name) or _new_row(name, role, 'assess')
            if '&' in name or '%' in name:
                row['macro_name'] = True     # a name pattern: conversion binds the resolved table name
            rows.append(row)
    seeded = {r['name'] for r in rows}
    rows += [r for n, r in existing.items() if n not in seeded and r['role'] == 'intermediate']
    save(path, rows)
    return rows


def _find(rows: List[Dict], name: str) -> Optional[Dict]:
    n = name.upper()
    return next((r for r in rows if r['name'].upper() == n or (r.get('snowflake_fqn') or '').upper() == n), None)


def _apply(row: Dict, by: str, columns=None, columns_from=None, snowflake_fqn=None, sample_path=None,
           location_status=None, **extra) -> Dict:
    if columns is not None:
        row['columns'] = columns
    if columns_from is not None:
        row['columns_from'] = columns_from
    if snowflake_fqn is not None:
        row['snowflake_fqn'] = snowflake_fqn
    if sample_path is not None:
        row['sample_path'] = sample_path
    if location_status is not None:
        row['location_status'] = location_status
    for k in OPTIONAL:
        if extra.get(k) is not None:
            row[k] = extra[k]
    row.setdefault('location_status', 'unchecked')
    row['last_changed_by'] = by
    row['fingerprint'] = fingerprint(row['columns'])
    return row


def update(path, name: str, by: str, columns: Optional[List[Dict]] = None,
           columns_from: Optional[str] = None, snowflake_fqn: Optional[str] = None,
           sample_path: Optional[str] = None, role: str = 'input', **extra) -> Dict:
    rows = load(path)
    row = _find(rows, name)
    if row is None:
        row = _new_row(name.upper(), role, by)
        rows.append(row)
    _apply(row, by, columns, columns_from, snowflake_fqn, sample_path, **extra)
    save(path, rows)
    return row


def update_batch(path, entries: List[Dict], by: str) -> int:
    """One write for many rows. Each entry: {name, role?, columns?, from?, fqn?, sample?,
    location_status?, full_data_fqn?, sas_output_fqn?}."""
    rows = load(path)
    for e in entries:
        row = _find(rows, e['name'])
        if row is None:
            row = _new_row(e['name'].upper(), e.get('role', 'intermediate'), by)
            rows.append(row)
        elif e.get('role'):
            row['role'] = e['role']
        _apply(row, by, e.get('columns'), e.get('from'), e.get('fqn'), e.get('sample'),
               e.get('location_status'), **{k: e.get(k) for k in OPTIONAL})
    save(path, rows)
    return len(entries)


# ------------------------------------------------------------------ live location

def _candidates(row: Dict) -> List[str]:
    """Snowflake table names this SAS dataset may have landed as."""
    if row.get('snowflake_fqn'):
        return [row['snowflake_fqn'].split('.')[-1].strip('"').upper()]
    lib, _, ds = row['name'].rpartition('.')
    ds = re.sub(r"^'(.*)'N$", r'\1', ds, flags=re.I).upper()
    return ([f'{lib.upper()}_{ds}'] if lib else []) + [ds]   # most specific first


def probe_sql(path, schemas: List[str], roles=('input', 'intermediate')) -> str:
    """One query, one JSON cell: [{fqn, cols:'NAME TYPE|NAME TYPE'}] for every candidate found."""
    rows = [r for r in load(path) if r['role'] in roles and r.get('columns_from') not in ('live', 'user_file')]
    names = sorted({c for r in rows for c in _candidates(r)})
    if not names:
        return '-- nothing to probe: every table already has live or user-supplied columns'
    lit = ', '.join("'" + n.replace("'", "''") + "'" for n in names)
    parts = []
    for s in schemas:
        db, sch = s.split('.', 1)
        parts.append(
            f"SELECT table_catalog || '.' || table_schema || '.' || table_name AS fqn,\n"
            f"       LISTAGG(column_name || ' ' || data_type ||\n"
            f"         CASE WHEN character_maximum_length IS NOT NULL THEN '(' || character_maximum_length || ')'\n"
            f"              WHEN data_type = 'NUMBER' THEN '(' || numeric_precision || ',' || numeric_scale || ')' ELSE '' END,\n"
            f"         '|') WITHIN GROUP (ORDER BY ordinal_position) AS cols\n"
            f"FROM {db}.INFORMATION_SCHEMA.COLUMNS\n"
            f"WHERE table_schema = '{sch.upper()}' AND table_name IN ({lit})\nGROUP BY 1")
    return ('SELECT TO_JSON(ARRAY_AGG(OBJECT_CONSTRUCT(\'fqn\', fqn, \'cols\', cols))) AS found FROM (\n'
            + '\nUNION ALL\n'.join(parts) + '\n);')


def _parse_cols(spec: str) -> List[Dict]:
    out = []
    for c in spec.replace('\\|', '|').split('|'):
        c = c.strip()
        if c:
            name, _, typ = c.partition(' ')
            typ = re.sub(r'^TEXT\b', 'VARCHAR', typ.strip().upper()) or 'VARCHAR'  # INFORMATION_SCHEMA says TEXT
            out.append({'name': name, 'type': typ})
    return out


def ingest(path, result_file, schemas: Optional[List[str]] = None, by='convert') -> Dict:
    """Record probe results. Rows probed but absent become not_found."""
    raw = Path(result_file).read_text(encoding='utf-8').strip().replace('\\|', '|')
    found = json.loads(raw) if raw.startswith('[') else [
        {'fqn': r['fqn'], 'cols': r['cols']} for r in csv.DictReader(raw.splitlines())]
    order = [s.upper() for s in (schemas or [])]
    by_table = {}
    for f in found:
        fqn = f['fqn'].upper()
        by_table.setdefault(fqn.split('.')[-1], []).append(f)
    rows = load(path)
    shared = {}
    for r in rows:
        for c in _candidates(r)[1:]:
            shared[c] = shared.get(c, 0) + 1
    stats = {'found': 0, 'not_found': 0, 'ambiguous': []}
    for r in rows:
        if r['role'] not in ('input', 'intermediate') or r.get('columns_from') in ('live', 'user_file'):
            continue
        cands = _candidates(r)
        hits = [h for c in cands[:1] for h in by_table.get(c, [])]
        if not hits and len(cands) > 1:
            bare = [h for h in by_table.get(cands[-1], [])]
            if bare and shared.get(cands[-1], 0) > 1:
                stats['ambiguous'].append(r['name'])   # two SAS datasets share this bare name
                continue
            hits = bare
        if not hits:
            if r['role'] == 'input':
                r['location_status'] = 'not_found'
                r['last_changed_by'] = by
                stats['not_found'] += 1
            continue
        hits.sort(key=lambda h: next((i for i, s in enumerate(order) if h['fqn'].upper().startswith(s + '.')), 99))
        if len({h['fqn'] for h in hits}) > 1:
            stats['ambiguous'].append(r['name'])
        _apply(r, by, _parse_cols(hits[0]['cols']), 'live', hits[0]['fqn'], location_status='found')
        stats['found'] += 1
    save(path, rows)
    return stats


def import_ddl(path, ddl_file, by='convert') -> Dict:
    """CREATE TABLE statements (.sql) or table,column,type[,nullable] rows (.csv)."""
    text = Path(ddl_file).read_text(encoding='utf-8')
    tables: Dict[str, List[Dict]] = {}
    if str(ddl_file).lower().endswith('.csv'):
        for r in csv.DictReader(text.splitlines()):
            tables.setdefault(r['table'].strip().upper(), []).append(
                {'name': r['column'].strip(), 'type': (r.get('type') or 'VARCHAR').strip()})
    else:
        body = re.sub(r'--[^\n]*|/\*[\s\S]*?\*/', '', text)
        for m in re.finditer(r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:\w+\s+)*?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w."$]+)\s*\(', body, re.I):
            depth, j, start = 1, m.end(), m.end()
            while j < len(body) and depth:
                depth += {'(': 1, ')': -1}.get(body[j], 0)
                j += 1
            cols, depth, cur = [], 0, ''
            for ch in body[start:j - 1] + ',':
                if ch == ',' and depth == 0:
                    if cur.strip() and not re.match(r'\s*(CONSTRAINT|PRIMARY|UNIQUE|FOREIGN)\b', cur, re.I):
                        name, _, typ = cur.strip().partition(' ')
                        cols.append({'name': name.strip('"'), 'type': typ.split(' NOT ')[0].split(' DEFAULT ')[0].strip() or 'VARCHAR'})
                    cur = ''
                    continue
                depth += {'(': 1, ')': -1}.get(ch, 0)
                cur += ch
            tables[m.group(1).replace('"', '').upper()] = cols
    rows = load(path)
    matched, added = 0, 0
    for tname, cols in tables.items():
        row = _find(rows, tname) or next((r for r in rows if tname.split('.')[-1] in _candidates(r)), None)
        if row is None:
            row = _new_row(tname, 'input', by)
            rows.append(row)
            added += 1
        else:
            matched += 1
        _apply(row, by, cols, 'user_file', location_status='user_supplied')
    save(path, rows)
    return {'matched': matched, 'added_not_in_sas': added}


# ------------------------------------------------------------------ read views

def summary(path) -> Dict:
    rows = load(path)
    counts: Dict[str, Dict[str, int]] = {}
    for r in rows:
        key = f"{r['role']}"
        counts.setdefault(key, {})
        for k in (f"loc:{r.get('location_status', 'unchecked')}", f"cols:{r['columns_from']}"):
            counts[key][k] = counts[key].get(k, 0) + 1
    nf = [r['name'] for r in rows if r.get('location_status') == 'not_found']
    return {'total': len(rows), 'by_role': counts, 'not_found': nf[:20], 'not_found_total': len(nf),
            'inferred': [r['name'] for r in rows if r['columns_from'] == 'inferred'][:20]}


def get(path, name) -> Optional[Dict]:
    row = _find(load(path), name) or next((r for r in load(path) if name.upper().split('.')[-1] in _candidates(r)), None)
    if row is None:
        return None
    out = {k: row.get(k) for k in ('name', 'role', 'snowflake_fqn', 'columns_from', 'location_status') + OPTIONAL if row.get(k)}
    out['columns'] = ', '.join(f"{c['name']} {c.get('type', '')}".strip() for c in row['columns'])
    return out


def gap(path, name, column) -> (int, str):
    row = get(path, name)
    if row is None:
        return 4, f'{name}: not in tables.json -- unresolved name (fix the name, or add the row)'
    cols = {c.split(' ')[0].upper() for c in row['columns'].split(', ') if c}
    if column.upper() not in cols:
        return GAP_EXIT, f"TEST_DATA_GAP: {name} has no column {column} (columns_from={row['columns_from']}) -- add it, render-ddl, reload"
    if row['columns_from'] in ('inferred', 'none'):
        return GAP_EXIT, f"TEST_DATA_GAP?: {name}.{column} type is inferred -- check the type before blaming the SQL"
    return 0, f"{name}.{column} recorded ({row['columns_from']})"


def seed_targets(path) -> List[str]:
    return [r.get('snowflake_fqn') or r['name'] for r in load(path) if r['role'] == 'input' and not is_system(r['name'])]


def render_ddl(path, roles=ROLES) -> str:
    out = ['-- Generated from tables.json by tables.py render-ddl. Edit tables.json, not this file.']
    for r in load(path):
        if r['role'] not in roles:
            continue
        target = r.get('snowflake_fqn') or r['name']
        if not r['columns']:
            out.append(f'-- {target}: no columns recorded (columns_from={r["columns_from"]})')
            continue
        cols = ',\n'.join(f'    {c["name"]} {c.get("type") or "VARCHAR"}' for c in r['columns'])
        out.append(f'-- {r["role"]}, columns_from={r["columns_from"]}\n'
                   f'CREATE TABLE IF NOT EXISTS {target} (\n{cols}\n);')
    return '\n'.join(out) + '\n'


def stamp(path, csv_path, names: List[str]) -> Dict[str, str]:
    by_name = {r['name'].upper(): r['fingerprint'] for r in load(path)}
    fps = {n.upper(): by_name.get(n.upper()) for n in names}
    Path(str(csv_path) + '.fp.json').write_text(json.dumps(fps, indent=2) + '\n', encoding='utf-8')
    return fps


def check_stale(path, csv_dir) -> List[Dict]:
    """CSVs whose recorded fingerprints no longer match tables.json."""
    current = {r['name'].upper(): r['fingerprint'] for r in load(path)}
    stale = []
    for fp_file in sorted(Path(csv_dir).rglob('*.csv.fp.json')):
        recorded = json.loads(fp_file.read_text(encoding='utf-8'))
        changed = sorted(n for n, fp in recorded.items() if current.get(n) != fp)
        if changed:
            stale.append({'csv': str(fp_file)[:-len('.fp.json')], 'changed_tables': changed})
    return stale


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('load'); s.add_argument('tables')
    s = sub.add_parser('summary'); s.add_argument('tables')
    s = sub.add_parser('get'); s.add_argument('tables'); s.add_argument('name')
    s = sub.add_parser('gap'); s.add_argument('tables'); s.add_argument('name'); s.add_argument('column')
    s = sub.add_parser('seed-targets'); s.add_argument('tables')
    s = sub.add_parser('probe'); s.add_argument('tables'); s.add_argument('--schemas', required=True)
    s = sub.add_parser('ingest'); s.add_argument('tables'); s.add_argument('result'); s.add_argument('--schemas', default='')
    s = sub.add_parser('import-ddl'); s.add_argument('tables'); s.add_argument('ddl')
    s = sub.add_parser('update'); s.add_argument('tables'); s.add_argument('name', nargs='?')
    s.add_argument('--by', choices=CHANGED_BY, required=True)
    s.add_argument('--batch', help='JSON-lines file of row updates (one write)')
    s.add_argument('--columns', help='JSON list of {"name","type"}')
    s.add_argument('--from', dest='columns_from', choices=COLUMNS_FROM)
    s.add_argument('--fqn'); s.add_argument('--sample')
    s.add_argument('--role', choices=ROLES, default='input')
    s.add_argument('--location', choices=LOCATION_STATUS)
    s.add_argument('--full-data-fqn'); s.add_argument('--sas-output-fqn')
    s = sub.add_parser('render-ddl'); s.add_argument('tables'); s.add_argument('--roles', default=','.join(ROLES))
    s = sub.add_parser('stamp'); s.add_argument('tables'); s.add_argument('csv'); s.add_argument('names', nargs='+')
    s = sub.add_parser('check-stale'); s.add_argument('tables'); s.add_argument('csv_dir')
    a = ap.parse_args(argv)

    if a.cmd == 'load':
        print(json.dumps(load(a.tables), indent=2))
    elif a.cmd == 'summary':
        print(json.dumps(summary(a.tables)))
    elif a.cmd == 'get':
        row = get(a.tables, a.name)
        print(json.dumps(row) if row else f'{a.name}: not in tables.json')
        return 0 if row else 4
    elif a.cmd == 'gap':
        code, msg = gap(a.tables, a.name, a.column)
        print(msg)
        return code
    elif a.cmd == 'seed-targets':
        print('\n'.join(seed_targets(a.tables)))
    elif a.cmd == 'probe':
        print(probe_sql(a.tables, [s.strip() for s in a.schemas.split(',') if s.strip()]))
    elif a.cmd == 'ingest':
        print(json.dumps(ingest(a.tables, a.result, [s.strip() for s in a.schemas.split(',') if s.strip()])))
    elif a.cmd == 'import-ddl':
        print(json.dumps(import_ddl(a.tables, a.ddl)))
    elif a.cmd == 'update':
        if a.batch:
            entries = [json.loads(l) for l in Path(a.batch).read_text(encoding='utf-8').splitlines() if l.strip()]
            print(f'updated {update_batch(a.tables, entries, a.by)} row(s)')
        elif not a.name:
            ap.error('update needs NAME or --batch')
        else:
            cols = json.loads(a.columns) if a.columns else None
            row = update(a.tables, a.name, a.by, cols, a.columns_from, a.fqn, a.sample, a.role,
                         location_status=a.location, full_data_fqn=a.full_data_fqn, sas_output_fqn=a.sas_output_fqn)
            print(json.dumps(get(a.tables, row['name'])))
    elif a.cmd == 'render-ddl':
        sys.stdout.write(render_ddl(a.tables, tuple(r.strip() for r in a.roles.split(','))))
    elif a.cmd == 'stamp':
        print(json.dumps(stamp(a.tables, a.csv, a.names), indent=2))
    else:
        stale = check_stale(a.tables, a.csv_dir)
        print(json.dumps(stale, indent=2))
        return 1 if stale else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
