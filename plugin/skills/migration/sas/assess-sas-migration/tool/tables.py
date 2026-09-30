#!/usr/bin/env python3
"""tables.json — the input/output tables a SAS portfolio touches, carried from
assessment through conversion and test. Stdlib only.

Assessment seeds one row per input (shared, read, created nowhere in scope) and
output (shared, created, read nowhere in scope) with ``columns_from: "none"``.
Conversion fills columns / snowflake_fqn / sample_path and regenerates
``source_table_ddl.sql`` from this file (never a side ``*_fix.sql``).

Expected-results CSVs are stamped with the fingerprints they were traced against
(``<csv>.fp.json``); ``check-stale`` reports CSVs whose tables changed since.

  python tables.py update tables.json LIB.T --columns '[{"name":"ID","type":"NUMBER"}]' --from live --by convert
  python tables.py render-ddl tables.json > source_table_ddl.sql
  python tables.py stamp tables.json expected/foo.csv LIB.T LIB.U
  python tables.py check-stale tables.json expected/
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

COLUMNS_FROM = ('live', 'user_file', 'inferred', 'none')
CHANGED_BY = ('assess', 'convert', 'test')


def fingerprint(columns: List[Dict]) -> str:
    key = sorted((c['name'].upper(), str(c.get('type', '')).upper()) for c in columns)
    return hashlib.sha1(json.dumps(key).encode()).hexdigest()


def load(path) -> List[Dict]:
    p = Path(path)
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []


def save(path, rows: List[Dict]) -> None:
    rows = sorted(rows, key=lambda r: (r['role'], r['name']))
    Path(path).write_text(json.dumps(rows, indent=2) + '\n', encoding='utf-8')


def seed(path, inputs: List[str], outputs: List[str]) -> List[Dict]:
    """Write assessment rows, keeping anything a later phase already filled in."""
    existing = {r['name']: r for r in load(path)}
    rows = []
    for role, names in (('input', inputs), ('output', outputs)):
        for name in names:
            rows.append(existing.get(name) or {
                'name': name, 'role': role, 'snowflake_fqn': None, 'columns': [],
                'columns_from': 'none', 'sample_path': None,
                'last_changed_by': 'assess', 'fingerprint': fingerprint([]),
            })
    save(path, rows)
    return rows


def update(path, name: str, by: str, columns: Optional[List[Dict]] = None,
           columns_from: Optional[str] = None, snowflake_fqn: Optional[str] = None,
           sample_path: Optional[str] = None, role: str = 'input') -> Dict:
    rows = load(path)
    row = next((r for r in rows if r['name'].upper() == name.upper()), None)
    if row is None:
        row = {'name': name.upper(), 'role': role, 'snowflake_fqn': None, 'columns': [],
               'columns_from': 'none', 'sample_path': None}
        rows.append(row)
    if columns is not None:
        row['columns'] = columns
    if columns_from is not None:
        row['columns_from'] = columns_from
    if snowflake_fqn is not None:
        row['snowflake_fqn'] = snowflake_fqn
    if sample_path is not None:
        row['sample_path'] = sample_path
    row['last_changed_by'] = by
    row['fingerprint'] = fingerprint(row['columns'])
    save(path, rows)
    return row


def render_ddl(path) -> str:
    out = ['-- Generated from tables.json by tables.py render-ddl. Edit tables.json, not this file.']
    for r in load(path):
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
    s = sub.add_parser('update'); s.add_argument('tables'); s.add_argument('name')
    s.add_argument('--by', choices=CHANGED_BY, required=True)
    s.add_argument('--columns', help='JSON list of {"name","type"}')
    s.add_argument('--from', dest='columns_from', choices=COLUMNS_FROM)
    s.add_argument('--fqn'); s.add_argument('--sample')
    s.add_argument('--role', choices=('input', 'output'), default='input')
    s = sub.add_parser('render-ddl'); s.add_argument('tables')
    s = sub.add_parser('stamp'); s.add_argument('tables'); s.add_argument('csv'); s.add_argument('names', nargs='+')
    s = sub.add_parser('check-stale'); s.add_argument('tables'); s.add_argument('csv_dir')
    a = ap.parse_args(argv)

    if a.cmd == 'load':
        print(json.dumps(load(a.tables), indent=2))
    elif a.cmd == 'update':
        cols = json.loads(a.columns) if a.columns else None
        print(json.dumps(update(a.tables, a.name, a.by, cols, a.columns_from, a.fqn, a.sample, a.role), indent=2))
    elif a.cmd == 'render-ddl':
        sys.stdout.write(render_ddl(a.tables))
    elif a.cmd == 'stamp':
        print(json.dumps(stamp(a.tables, a.csv, a.names), indent=2))
    else:
        stale = check_stale(a.tables, a.csv_dir)
        print(json.dumps(stale, indent=2))
        return 1 if stale else 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
