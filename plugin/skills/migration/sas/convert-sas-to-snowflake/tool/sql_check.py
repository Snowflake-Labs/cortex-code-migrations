#!/usr/bin/env python3
"""Zero-credit static gate for converted SAS -> Snowflake SQL. Stdlib only.

  python3 sql_check.py all  --dir <out> [--sas-dir <src>] [--tables tables.json] [--orchestration <out>/orchestration]
  python3 sql_check.py scan|lint|xfile|fidelity --dir <out> ...
  python3 sql_check.py fix  --dir <out> [--dry-run]     # repair stray comment delimiters, differential-checked
  python3 sql_check.py count --file x.sql

Prints only findings (`file:line severity rule message`) and one summary line, and writes the
full report to --report (default <dir>/sql_check.json). Exit 2 when any `error` remains.
Silence one finding with `-- sql_check: allow <rule>` on its line or the line above.

Subcommands
  scan      statements whose first token cannot begin a Snowflake statement (a block comment
            closed early -- Snowflake block comments do not nest -- or SAS left in the code)
  lint      Snowflake constraints verified against a live account, plus type casts that carry
            no `-- TYPE:` reason (see conversion-rules.md, Type Traps)
  xfile     names consumed under one qualifier and produced under another, CALL arity that
            matches no definition, stub procedures shadowing real ones, procedures nothing calls
  fidelity  per `-- SAS: <file>:L<a>-L<b>` anchor, join types, DISTINCT, anti-joins and
            concatenations compared with the SAS lines the block claims to translate;
            warns when a single-key ORDER BY replaces a RETAIN/FIRST./LAST. step (tie order)
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys

# Test scaffolding the skill writes; not conversion output.
GENERATED = {'sql_check.json', 'synthetic_data.sql', 'source_table_ddl.sql'}

# ------------------------------------------------------------------ walker

STARTERS = set("""
select with insert update delete merge create alter drop truncate undrop use call begin
declare set unset grant revoke comment describe desc show list put get copy remove execute
explain return let if else elseif end case when while for repeat loop break continue
exception raise open close fetch analyze rollback commit
""".split())


def _walk(text):
    """Yield (index, char, state) with state in code|blk|ln|str|dol. Models Snowflake:
    non-nesting /* */, -- to end of line, '' escapes, and opaque $$ bodies."""
    i, n, st = 0, len(text), 'code'
    while i < n:
        c = text[i]
        nx = text[i + 1] if i + 1 < n else ''
        if st == 'code':
            if c == '/' and nx == '*':
                yield i, c, 'blk'; yield i + 1, nx, 'blk'; st = 'blk'; i += 2; continue
            if c == '-' and nx == '-':
                yield i, c, 'ln'; yield i + 1, nx, 'ln'; st = 'ln'; i += 2; continue
            if c == "'":
                yield i, c, 'str'; st = 'str'; i += 1; continue
            if c == '$' and nx == '$':
                yield i, c, 'dol'; yield i + 1, nx, 'dol'; st = 'dol'; i += 2; continue
            yield i, c, 'code'; i += 1; continue
        if st == 'blk':
            yield i, c, 'blk'
            if c == '*' and nx == '/':
                yield i + 1, nx, 'blk'; st = 'code'; i += 2; continue
            i += 1; continue
        if st == 'ln':
            yield i, c, 'ln'
            if c == '\n':
                st = 'code'
            i += 1; continue
        if st == 'str':
            yield i, c, 'str'
            if c == "'":
                if nx == "'":
                    yield i + 1, nx, 'str'; i += 2; continue
                st = 'code'
            i += 1; continue
        # dol
        yield i, c, 'dol'
        if c == '$' and nx == '$':
            yield i + 1, nx, 'dol'; st = 'code'; i += 2; continue
        i += 1


def statements(text):
    """Split into (statement, start_line) the way Snowflake does (comments dropped)."""
    out, cur, line, stline = [], [], 1, 1
    for _, c, st in _walk(text):
        if c == '\n':
            line += 1
        if st in ('blk', 'ln'):
            continue
        if st == 'code' and c == ';':
            s = ''.join(cur).strip()
            if s:
                out.append((s, stline))
            cur, stline = [], line
            continue
        if not cur:
            if st == 'code' and c.isspace():
                continue
            stline = line                      # first code character, not a comment above it
        cur.append(c)
    s = ''.join(cur).strip()
    if s:
        out.append((s, stline))
    return out


def masked(text, keep_strings=False, open_dollar=True):
    """Same length as text, newlines kept. Comments blanked; string contents blanked unless
    keep_strings. With open_dollar, $$ bodies are kept as code (their own comments and
    strings are masked by re-walking the body)."""
    buf = list(text)
    bodies, start, prev = [], None, 'code'
    for i, c, st in _walk(text):
        if st in ('blk', 'ln') and c != '\n':
            buf[i] = ' '
        elif st == 'str' and not keep_strings and c not in ("'", '\n'):
            buf[i] = ' '
        if st == 'dol' and prev != 'dol':
            start = i + 2                      # body begins after the opening $$
        elif st != 'dol' and prev == 'dol' and start is not None:
            bodies.append((start, i - 2))      # body ends before the closing $$
            start = None
        prev = st
    if prev == 'dol' and start is not None:
        bodies.append((start, len(text)))
    out = ''.join(buf)
    if open_dollar:
        for a, b in bodies:
            if b > a:
                out = out[:a] + masked(text[a:b], keep_strings, False) + out[b:]
    return out


def comment_lines(text):
    """{line_no: comment text on that line}, including comments inside $$ bodies:
    exactly the characters masking removes when strings are kept."""
    code = masked(text, keep_strings=True)
    res = {}
    for no, (t, c) in enumerate(zip(text.split('\n'), code.split('\n')), 1):
        diff = [k for k, (a, b) in enumerate(zip(t, c)) if a != b]
        if diff:
            res[no] = t[diff[0]:diff[-1] + 1]
    return res


def line_of(text, idx):
    return text.count('\n', 0, idx) + 1


def malformed(text):
    hits = []
    for s, ln in statements(text):
        m = re.match(r'[A-Za-z_$][A-Za-z0-9_$]*', s)
        tok = m.group(0).lower() if m else s[:14]
        if tok not in STARTERS:
            hits.append((ln, tok, re.sub(r'\s+', ' ', s)[:120]))
    return hits


# ------------------------------------------------------------------ findings

class Report:
    def __init__(self):
        self.findings = []
        self.meta = {}

    def add(self, file, line, sev, rule, msg, allowed=None):
        if allowed and rule in allowed.get(line, set()) | allowed.get(line - 1, set()):
            return
        self.findings.append({'file': file, 'line': line, 'severity': sev, 'rule': rule,
                              'message': msg})

    def errors(self):
        return [f for f in self.findings if f['severity'] == 'error']


def allows(text):
    res = {}
    for no, c in comment_lines(text).items():
        for m in re.finditer(r'sql_check:\s*allow\s+([\w,\- ]+)', c):
            res.setdefault(no, set()).update(x.strip() for x in re.split(r'[,\s]+', m.group(1)) if x.strip())
    return res


def sql_files(d):
    return sorted(glob.glob(os.path.join(d, '*.sql')))


def read(p):
    with open(p, encoding='utf-8', errors='replace') as fh:
        return fh.read()


# ------------------------------------------------------------------ scan / fix

def check_scan(files, rep):
    for p in files:
        text, b = read(p), os.path.basename(p)
        al = allows(text)
        for ln, tok, s in malformed(text):
            rep.add(b, ln, 'error', 'malformed_statement',
                    f"statement starts with '{tok}': {s[:80]} (block comment closed early, or SAS left in code; try `fix`)", al)


def _fix_block_line(line):
    out, i, n, inline = [], 0, len(line), 0
    while i < n:
        c, nx = line[i], line[i + 1] if i + 1 < n else ''
        if c == '/' and nx == '*':
            out.append('/ *'); inline += 1; i += 2; continue
        if c == '*' and nx == '/':
            if inline:
                out.append('* /'); inline -= 1; i += 2; continue
            if line[i + 2:].strip() == '':
                out.append(line[i:]); return ''.join(out), True
            out.append('* /'); i += 2; continue
        out.append(c); i += 1
    return ''.join(out), False


def _ends_in_block(line):
    inb, i, n = False, 0, len(line)
    while i < n:
        c, nx = line[i], line[i + 1] if i + 1 < n else ''
        if inb:
            if c == '*' and nx == '/':
                inb = False; i += 2; continue
            i += 1; continue
        if c == "'":
            i += 1
            while i < n:
                if line[i] == "'":
                    if i + 1 < n and line[i + 1] == "'":
                        i += 2; continue
                    i += 1; break
                i += 1
            continue
        if c == '-' and nx == '-':
            return False
        if c == '/' and nx == '*':
            inb = True; i += 2; continue
        i += 1
    return inb


def fix_text(text):
    out, inb, changed = [], False, 0
    for line in text.split('\n'):
        if inb:
            nl, closed = _fix_block_line(line)
            changed += nl != line
            out.append(nl)
            inb = not closed
            continue
        out.append(line)
        inb = _ends_in_block(line)
    return '\n'.join(out), changed


_REAL_SQL = re.compile(r'^(select|with|insert|update|delete|merge|create|alter|drop|truncate|use|'
                       r'grant|revoke|copy|comment|execute|describe|show|call)\b|^set\s+\w+\s*=', re.I)


def cmd_fix(a):
    status = 0
    for p in sql_files(a.dir):
        src = read(p)
        new, changed = fix_text(src)
        if not changed or new == src:
            continue
        norm = lambda t: [re.sub(r'\s+', ' ', s).strip().lower() for s, _ in statements(t)]
        before, after = norm(src), norm(new)
        lost = [s for s in before if s not in after and _REAL_SQL.match(s)]
        b = os.path.basename(p)
        if lost:
            print(f'REFUSED {b}: would drop {len(lost)} real statement(s): {lost[0][:80]}')
            status = 2
            continue
        if not a.dry_run:
            shutil.copyfile(p, p + '.bak_fix')
            with open(p, 'w', encoding='utf-8') as fh:
                fh.write(new)
        print(f'FIXED {b}: {changed} line(s); malformed {len(malformed(src))} -> {len(malformed(new))}'
              + (' (dry run)' if a.dry_run else ''))
    return status


# ------------------------------------------------------------------ lint

_TYPE_CAST = re.compile(
    r'\bTRY_(?:TO_(?:DOUBLE|NUMBER|DECIMAL|NUMERIC)|CAST)\s*\('
    r'|[\w"]+\.[\w"]+\s*::\s*VARCHAR\b[^\n]*?=\s*[\w"]+\.[\w"]+\s*::\s*VARCHAR\b'
    r'|\bTO_DATE\s*\(\s*[A-Za-z_][\w$]*\.[A-Za-z_"][\w$"]*\s*,', re.I)
_KW_CLAUSE = {'SELECT': 'SELECT', 'FROM': 'FROM', 'WHERE': 'WHERE', 'ON': 'ON', 'HAVING': 'HAVING',
              'QUALIFY': 'QUALIFY', 'JOIN': 'FROM', 'GROUP': 'GROUP', 'ORDER': 'ORDER'}


def _star_args_outside_select(code):
    """Positions of f(*) (not COUNT) used outside a SELECT list -- including inside FLATTEN."""
    hits = []
    stack = [{'clause': None, 'flatten': False}]
    toks = re.finditer(r"[A-Za-z_][\w$]*|\(|\)|\*|;", code)
    prev_word = None
    pending = None  # (word, index) of a word directly followed by '('
    seq = list(toks)
    for k, m in enumerate(seq):
        t = m.group(0)
        up = t.upper()
        if t == ';':
            stack = [{'clause': None, 'flatten': False}]
        elif t == '(':
            fn = prev_word if prev_word and seq[k - 1].end() <= m.start() and \
                code[seq[k - 1].end():m.start()].strip() == '' and re.match(r'[A-Za-z_]', seq[k - 1].group(0)) else None
            stack.append({'clause': stack[-1]['clause'], 'flatten': stack[-1]['flatten'] or (fn or '').upper() == 'FLATTEN',
                          'fn': (fn or '').upper()})
            # f ( * )
            if fn and k + 2 < len(seq) and seq[k + 1].group(0) == '*' and seq[k + 2].group(0) == ')' \
                    and fn.upper() not in ('COUNT', 'COUNT_IF'):
                fr = stack[-2]
                if fr['flatten'] or (fr['clause'] and fr['clause'] != 'SELECT'):
                    hits.append((m.start(), fn))
        elif t == ')':
            if len(stack) > 1:
                stack.pop()
        elif up in _KW_CLAUSE:
            stack[-1]['clause'] = _KW_CLAUSE[up]
        prev_word = t if re.match(r'[A-Za-z_]', t) else None
    return hits


def check_lint(files, rep):
    for p in files:
        text, b = read(p), os.path.basename(p)
        al = allows(text)
        code = masked(text)                       # comments + string contents blanked
        code_s = masked(text, keep_strings=True)  # comments blanked, strings kept
        notes = comment_lines(text)

        for m in re.finditer(r'\bEXECUTE\s+IMMEDIATE\b[^;]*?\bINTO\s*:', code, re.I):
            rep.add(b, line_of(text, m.start()), 'error', 'execute_immediate_into',
                    'EXECUTE IMMEDIATE ... INTO is not supported; use SELECT ... INTO :v FROM IDENTIFIER(:t) or a RESULTSET cursor', al)
        for m in re.finditer(r'\bEXCEPTION\s*\(\s*-?\d+\s*,\s*(.*?)\)\s*;', code_s, re.I | re.S):
            if not re.fullmatch(r"\s*'(?:[^']|'')*'\s*", m.group(1)):
                rep.add(b, line_of(text, m.start()), 'error', 'exception_message_not_literal',
                        'EXCEPTION (code, msg): msg must be one string literal', al)
        for m in re.finditer(r'\bFILE_FORMAT\s*=\s*\(([^)]*)\)', code, re.I):
            if re.search(r'\bHEADER\s*=', m.group(1), re.I):
                rep.add(b, line_of(text, m.start()), 'error', 'header_in_file_format',
                        'HEADER is a COPY option; move it outside FILE_FORMAT = (...)', al)
        for pos, fn in _star_args_outside_select(code):
            rep.add(b, line_of(text, pos), 'error', 'star_argument_outside_select',
                    f'{fn}(*) is only allowed in a SELECT list; build the object in a subquery SELECT first', al)
        for s, ln in statements(code_s):
            head = s[:200].upper()
            if re.match(r'CREATE\s+(OR\s+REPLACE\s+)?(SECURE\s+)?PROCEDURE\b', head) and '$$' not in s \
                    and not re.search(r"\bAS\s*'", s, re.I):
                rep.add(b, ln, 'error', 'procedure_body_not_quoted',
                        'procedure body must be $$-quoted, or it is cut at the first ;', al)
            if head.startswith('COPY') and re.search(r'\.xlsx\b|\bxlsx\b', s, re.I):
                rep.add(b, ln, 'error', 'copy_xlsx',
                        'COPY cannot read or write .xlsx; use a Python stored procedure (one call per workbook)', al)
        # static $VAR inside a procedure body is resolved at CREATE time
        for m in re.finditer(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:SECURE\s+)?PROCEDURE\b[\s\S]*?\$\$([\s\S]*?)\$\$', code, re.I):
            for v in sorted(set(re.findall(r'(?<![\w$])\$([A-Za-z_][\w]*)', m.group(1)))):
                rep.add(b, line_of(text, m.start()), 'warn', 'session_var_at_create',
                        f'${v} must be SET before this CREATE PROCEDURE runs (sf_exec orders parameter files first), or use GETVARIABLE', al)
        for m in _TYPE_CAST.finditer(code):
            ln = line_of(text, m.start())
            if not any('TYPE:' in notes.get(x, '') for x in range(ln - 3, ln + 1)):
                rep.add(b, ln, 'warn', 'type_cast_without_reason',
                        f"'{m.group(0)[:40].strip()}' needs a `-- TYPE: <evidence>` comment, or remove it (conversion-rules.md Type Traps)", al)
        # bare temp table created before a USE in the same file
        stmts = statements(code)
        first_use = next((ln for s, ln in stmts if re.match(r'USE\s+(SCHEMA|DATABASE)\b', s, re.I)), None)
        if first_use:
            for s, ln in stmts:
                if ln >= first_use:
                    break
                if re.match(r'CREATE\s+(OR\s+REPLACE\s+)?(LOCAL\s+|GLOBAL\s+)?TEMP(ORARY)?\s+TABLE\s+[\w"]+\s', s + ' ', re.I):
                    rep.add(b, ln, 'error', 'temp_before_use',
                            'bare TEMPORARY table created before USE SCHEMA in this file', al)
                    break


# ------------------------------------------------------------------ xfile

IDENT = r'(?:"[^"]+"|[A-Za-z_][\w$]*)'
QNAME = rf'{IDENT}(?:\s*\.\s*{IDENT}){{0,2}}'
_SKIP_NAMES = {'TABLE', 'LATERAL', 'VALUES', 'SELECT', 'IDENTIFIER', 'DUAL', 'WITH'}


def norm_name(n):
    return '.'.join(x.strip().strip('"').upper() for x in n.split('.'))


def _cte_names(stmt):
    return {m.group(1).upper() for m in re.finditer(rf'(?:\bWITH\s+(?:RECURSIVE\s+)?|,\s*)({IDENT})\s+AS\s*\(', stmt, re.I)}


def _in_function_call(code, pos):
    """True when pos sits inside f(...) rather than a subquery or the top level."""
    depth, i = 0, pos - 1
    while i >= 0:
        c = code[i]
        if c == ')':
            depth += 1
        elif c == '(':
            if depth == 0:
                after = code[i + 1:i + 40].lstrip().upper()
                return not (after.startswith('SELECT') or after.startswith('WITH'))
            depth -= 1
        elif c == ';' and depth == 0:
            return False
        i -= 1
    return False


def _args(s, open_idx):
    """Arg count for the parenthesised list starting at s[open_idx] == '('."""
    depth, j, commas, content = 0, open_idx, 0, False
    while j < len(s):
        c = s[j]
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1
            if depth == 0:
                break
        elif c == ',' and depth == 1:
            commas += 1
        elif depth >= 1 and not c.isspace():
            content = True
        j += 1
    return (commas + 1 if content else 0), j


def parse_objects(text):
    code = masked(text)
    prod, cons, procs, calls = [], [], [], []
    for m in re.finditer(rf'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:LOCAL|GLOBAL)\s+)?(TEMP|TEMPORARY|TRANSIENT|VOLATILE|DYNAMIC)?\s*(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?({QNAME})', code, re.I):
        if norm_name(m.group(2)) in _SKIP_NAMES:      # CREATE TABLE IDENTIFIER(:v): name known only at run time
            continue
        prod.append({'name': norm_name(m.group(2)), 'temp': (m.group(1) or '').upper() in ('TEMP', 'TEMPORARY', 'VOLATILE'),
                     'line': line_of(text, m.start())})
    for s, ln0 in [(code, 1)]:
        ctes = set()
        for st, _ in statements(code):
            ctes |= _cte_names(st)
        for m in re.finditer(rf'\b(FROM|JOIN|INSERT\s+(?:OVERWRITE\s+)?INTO|TRUNCATE\s+(?:TABLE\s+)?(?:IF\s+EXISTS\s+)?|MERGE\s+INTO|DELETE\s+FROM|UPDATE|USING)\s+({QNAME})(\s*\()?', s, re.I):
            name = norm_name(m.group(2))
            if m.group(3) or name.split('.')[0] in _SKIP_NAMES or name in ctes or name.startswith('INFORMATION_SCHEMA') \
                    or name.split('.')[-1] in ('INFORMATION_SCHEMA',) or _in_function_call(code, m.start()):
                continue
            cons.append({'name': name, 'line': line_of(text, m.start())})
    for m in re.finditer(rf'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:SECURE\s+)?PROCEDURE\s+({QNAME})\s*\(', code, re.I):
        n_args, end = _args(code, m.end() - 1)
        body = re.search(r'\$\$([\s\S]*?)\$\$', code[end:])
        btxt = body.group(1) if body else ''
        decl = text[m.start(): end + (body.end() if body else 0)]
        marked = bool(re.search(r'MANUAL_REVIEW_REQUIRED|\bSTUB\b', decl, re.I))
        stub = (not re.search(r'\b(INSERT|UPDATE|DELETE|MERGE|CREATE|TRUNCATE|COPY|CALL)\b', btxt, re.I)) or \
            (marked and len(btxt.split()) < 120)
        procs.append({'name': norm_name(m.group(1)), 'args': n_args, 'stub': stub, 'line': line_of(text, m.start())})
    code_s = masked(text, keep_strings=True)
    for m in re.finditer(rf'\bCALL\s+({QNAME})\s*\(', code, re.I):
        n_args, close = _args(code, m.end() - 1)
        lits = re.findall(r"'((?:[^']|'')*)'", code_s[m.end() - 1:close])
        calls.append({'name': norm_name(m.group(1)), 'args': n_args, 'line': line_of(text, m.start()),
                      'literals': sorted({_key(t) for lit in lits for t in re.findall(r'[A-Za-z_][\w]*', lit)})})
    return {'produces': prod, 'consumes': cons, 'procedures': procs, 'calls': calls}


def _key(name):
    """Comparable form of a routine name: last part, upper, SP_/USP_ prefix and non-alnum dropped."""
    n = _last(norm_name(name)) if '.' in name else name.upper()
    return re.sub(r'[^A-Z0-9]', '', re.sub(r'^(SP|USP|PROC|P)_', '', n))


def _last(n):
    return n.split('.')[-1]


def check_xfile(files, rep, tables_path=None, orch_dir=None):
    objs = {os.path.basename(p): parse_objects(read(p)) for p in files}
    orch = {}
    if orch_dir and os.path.isdir(orch_dir):
        orch = {'orchestration/' + os.path.basename(p): read(p) for p in sql_files(orch_dir)}
    known_inputs = set()
    if tables_path and os.path.exists(tables_path):
        for r in json.load(open(tables_path, encoding='utf-8')):
            for k in ('name', 'snowflake_fqn'):
                if r.get(k) and r.get('role') == 'input':
                    known_inputs.add(norm_name(r[k]))
    produced = {}
    for f, o in objs.items():
        for pr in o['produces']:
            produced.setdefault(pr['name'], []).append(f)
    by_last = {}
    for n in produced:
        by_last.setdefault(_last(n), set()).add(n)

    never = set()
    for f, o in objs.items():
        al = allows(read(os.path.join(os.path.dirname(files[0]), f)))
        for c in o['consumes']:
            n = c['name']
            if n in produced or n in known_inputs or _last(n) in {_last(k) for k in known_inputs if '.' not in n}:
                continue
            same_last = by_last.get(_last(n), set())
            if '.' not in n and same_last:
                continue                          # unqualified read of a produced table
            if '.' in n and same_last:
                rep.add(f, c['line'], 'error', 'qualifier_mismatch',
                        f"reads {n} but it is produced as {sorted(same_last)[0]}", al)
                continue
            # affix-only pair with a produced name (one extra leading/trailing token)
            ln_ = _last(n)
            pair = next((p for p in produced if re.fullmatch(rf'(?:[A-Z0-9]+_)?{re.escape(_last(p))}(?:_[A-Z0-9]+)?', ln_)
                         and ln_ != _last(p) and n not in known_inputs), None) if known_inputs else None
            if pair:
                rep.add(f, c['line'], 'warn', 'affix_pair',
                        f"reads {n}, never produced; {pair} differs only by an affix -- same table under two names?", al)
            never.add(n)
    rep.meta['consumed_never_produced'] = sorted(never)

    defs = {}
    for f, o in objs.items():
        for d in o['procedures']:
            defs.setdefault(d['name'], []).append(dict(d, file=f))
    for name, ds in defs.items():
        if len({d['args'] for d in ds}) > 1:
            rep.add(ds[0]['file'], ds[0]['line'], 'warn', 'procedure_overload',
                    f"{name} defined with {sorted({d['args'] for d in ds})} args in {sorted({d['file'] for d in ds})}")
        stubs = [d for d in ds if d['stub']]
        real = [d for d in ds if not d['stub']]
        for s in stubs if real else []:
            rep.add(s['file'], s['line'], 'error', 'stub_shadows_real',
                    f"stub {name}({s['args']}) coexists with a real implementation in {real[0]['file']} -- route calls to the real one and delete the stub")
    real_keys = {_key(n): (n, d[0]['file']) for n, d in defs.items() if any(not x['stub'] for x in d)}
    stub_names = {n for n, d in defs.items() if all(x['stub'] for x in d)}
    for f, o in objs.items():
        flagged = set()
        for c in o['calls']:
            if c['name'] not in stub_names and _last(c['name']) not in {_last(s) for s in stub_names}:
                continue
            hit = next((real_keys[k] for k in c['literals'] if k in real_keys), None)
            if hit and (c['name'], hit[0]) not in flagged:
                flagged.add((c['name'], hit[0]))
                rep.add(f, c['line'], 'error', 'stub_shadows_real',
                        f"CALL {c['name']} (a stub) names {hit[0]}, which is implemented in {hit[1]} -- call the real procedure")
    called = set()
    for src, text in list(orch.items()) + [(f, read(os.path.join(os.path.dirname(files[0]), f))) for f in objs]:
        o = parse_objects(text)
        for c in o['calls']:
            called.add(c['name'])
            ds = defs.get(c['name']) or [d for k, v in defs.items() if _last(k) == _last(c['name']) for d in v]
            if ds and c['args'] not in {d['args'] for d in ds}:
                rep.add(src, c['line'], 'error', 'call_arity_mismatch',
                        f"CALL {c['name']} with {c['args']} args; defined with {sorted({d['args'] for d in ds})}")
    if orch:
        orch_text = '\n'.join(orch.values()).upper()
        for f, o in objs.items():
            names = [d['name'] for d in o['procedures']]
            if names and not any(n in called or _last(n) in {_last(c) for c in called} for n in names) \
                    and os.path.splitext(f)[0].upper() not in orch_text:
                rep.add(f, o['procedures'][0]['line'], 'warn', 'not_invoked',
                        f"no file or orchestration script calls {names[0]} -- a sub-flow its parent should CALL?")


# ------------------------------------------------------------------ fidelity

_ANCHOR = re.compile(r'--\s*SAS:\s*([^\s:]+):L?(\d+)\s*-\s*L?(\d+)', re.I)


def _sas_strip(src):
    src = re.sub(r'/\*[\s\S]*?\*/', lambda m: re.sub(r'[^\n]', ' ', m.group(0)), src)
    src = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", lambda m: "''", src)
    return re.sub(r'(?m)^\s*\*[^;]*;', ' ', src)


_VALUE_LIST_SUBQ = re.compile(r'\bnot\s+in\s*\(\s*select\b[^;]{0,200}?\bfrom\s+table\s*\(\s*(?:split_to_table|flatten)\b')


def shape(code):
    c = code.lower()
    left = len(re.findall(r'\bleft\s+(?:outer\s+)?join\b', c))
    right = len(re.findall(r'\bright\s+(?:outer\s+)?join\b', c))
    full = len(re.findall(r'\bfull\s+(?:outer\s+)?join\b', c))
    cross = len(re.findall(r'\bcross\s+join\b', c)) + len(re.findall(r'\bnatural\s+join\b', c))
    total = len(re.findall(r'\bjoin\b', c))
    return {'inner': total - left - right - full - cross, 'left': left, 'right': right, 'full': full,
            'distinct': len(re.findall(r'\bdistinct\b', c)) - len(re.findall(r'\bis\s+(?:not\s+)?distinct\b', c)),
            'dedup': len(re.findall(r'\bnodup(?:key|recs)?\b', c)) + len(re.findall(r'\bqualify\b', c)),
            # NOT IN over a value list (literals, or a split/flattened macro list) is a filter, not an anti-join
            'anti': len(re.findall(r'\bnot\s+in\s*\(\s*select\b', c)) - len(_VALUE_LIST_SUBQ.findall(c))
            + len(re.findall(r'\bnot\s+exists\b', c)) + len(re.findall(r'\bexcept\b', c))}


def _sas_unions(sas):
    """Concatenations: PROC SQL [OUTER] UNION, or one SET statement naming 2+ datasets."""
    n = len(re.findall(r'\bunion\b', sas, re.I))
    for m in re.finditer(r'(?:^|;)\s*set\s+([^;]*);', sas, re.I):
        args = m.group(1)
        while re.search(r'\([^()]*\)', args):
            args = re.sub(r'\([^()]*\)', ' ', args)          # dataset options
        n += len([t for t in args.split() if '=' not in t and not t.startswith('&')]) >= 2
    return n


def _single_key_order(sql):
    """First ORDER BY with one key (window or statement), or None."""
    for m in re.finditer(r'\border\s+by\s+(.*?)(?=\)|;|\bqualify\b|\brows\b|\blimit\b|$)', sql, re.I | re.S):
        if m.group(1).strip() and ',' not in m.group(1):
            return m.group(1).strip()
    return None


def _multiple(sas, sql, keys):
    vs = [k for k in keys if sas[k]]
    if not vs:
        return all(sql[k] == 0 for k in keys)
    k0 = sql[vs[0]] / sas[vs[0]]
    return k0 >= 1 and k0 == int(k0) and all(sql[k] == sas[k] * k0 for k in keys)


def check_fidelity(files, rep, sas_dir):
    sas_index = {}
    if sas_dir:
        for p in glob.glob(os.path.join(sas_dir, '**', '*.sas'), recursive=True):
            sas_index.setdefault(os.path.basename(p).lower(), p)
    for p in files:
        text, b = read(p), os.path.basename(p)
        al = allows(text)
        lines = text.split('\n')
        anchors = [(no, m) for no, ln in enumerate(lines, 1) for m in [_ANCHOR.search(ln)] if m]
        code_lines = masked(text).split('\n')
        writes = [no for no, ln in enumerate(code_lines, 1)
                  if re.search(r'\b(CREATE\s+(OR\s+REPLACE\s+)?(TEMP\w*\s+)?TABLE|INSERT\s+INTO|MERGE\s+INTO)\b', ln, re.I)]
        if not anchors:
            if writes and b.lower() not in GENERATED:
                rep.add(b, writes[0], 'warn', 'no_sas_anchors', f'{len(writes)} table write(s) and no `-- SAS: file:La-Lb` anchors', al)
            continue
        unanchored = [w for w in writes if w < anchors[0][0]]
        if unanchored:
            rep.add(b, unanchored[0], 'warn', 'unanchored_block', f'{len(unanchored)} table write(s) before the first SAS anchor', al)
        if not sas_dir:
            continue
        for k, (no, m) in enumerate(anchors):
            end = anchors[k + 1][0] - 1 if k + 1 < len(anchors) else len(lines)
            sp = sas_index.get(os.path.basename(m.group(1)).lower())
            if not sp:
                rep.add(b, no, 'warn', 'anchor_unresolved', f'SAS file {m.group(1)} not found under --sas-dir', al)
                continue
            a, z = int(m.group(2)), int(m.group(3))
            with open(sp, encoding='utf-8', errors='replace', newline='') as fh:   # same line numbers as the assessment
                sas_lines = re.sub(r'\r*\n|\r', '\n', fh.read()).split('\n')
            sas_src = '\n'.join(sas_lines[a - 1:z])
            s_shape, q_shape = shape(_sas_strip(sas_src)), shape('\n'.join(code_lines[no - 1:end]))
            # the step just above the range is a PROC SORT NODUP* feeding this block
            above = [x for x in re.split(r'\b(?:run|quit)\s*;', _sas_strip('\n'.join(sas_lines[max(0, a - 16):a - 1])), flags=re.I) if x.strip()]
            if above and re.search(r'\bproc\s+sort\b[^;]*\bnodup', above[-1], re.I):
                s_shape['dedup'] += 1
            joins = ('inner', 'left', 'right', 'full')
            if sum(s_shape[j] for j in joins) and not _multiple(s_shape, q_shape, joins):
                rep.add(b, no, 'error', 'join_type_mismatch',
                        'SAS ' + ' '.join(f'{j}={s_shape[j]}' for j in joins) + ' vs SQL ' + ' '.join(f'{j}={q_shape[j]}' for j in joins), al)
            sd, qd = s_shape['distinct'], q_shape['distinct']
            if qd > sd and not (sd and qd % sd == 0) and not (s_shape['dedup'] and not sd):
                rep.add(b, no, 'error', 'distinct_added', f"SQL DISTINCT={q_shape['distinct']}, SAS DISTINCT={s_shape['distinct']}", al)
            sas_code, sql_code = _sas_strip(sas_src), '\n'.join(code_lines[no - 1:end])
            su, qu = _sas_unions(sas_code), len(re.findall(r'\bunion\b', sql_code, re.I))
            if qu < su:
                rep.add(b, no, 'error', 'union_dropped', f'SAS concatenates {su} time(s) (multi-dataset SET / UNION), SQL has {qu} UNION', al)
            key = _single_key_order(sql_code)
            if key and re.search(r'\bretain\b|\b(?:first|last)\.\w', sas_code, re.I) and not re.search(r'TIEBREAK|_SRC_ROW', '\n'.join(lines[no - 1:end]), re.I):
                rep.add(b, no, 'warn', 'order_tie_unresolved',
                        f'ORDER BY {key[:40]} replaces a RETAIN/FIRST./LAST. step; SAS keeps input order on ties -- add _SRC_ROW or `-- TIEBREAK:`', al)
            if q_shape['anti'] > s_shape['anti'] and not (s_shape['anti'] and q_shape['anti'] % s_shape['anti'] == 0):
                rep.add(b, no, 'error', 'anti_join_introduced',
                        f"SQL has {q_shape['anti']} NOT IN/NOT EXISTS/EXCEPT, SAS has {s_shape['anti']}", al)


# ------------------------------------------------------------------ driver

def emit(rep, report_path, label):
    """Errors one per line (max 40); warnings grouped per (file, rule) with first line + count."""
    errs = rep.errors()
    for f in sorted(errs, key=lambda f: (f['file'], f['line']))[:40]:
        print(f"{f['file']}:{f['line']} error {f['rule']} {f['message']}")
    if len(errs) > 40:
        print(f'... {len(errs) - 40} more errors in {report_path}')
    groups = {}
    for f in rep.findings:
        if f['severity'] != 'error':
            groups.setdefault((f['file'], f['rule']), []).append(f)
    for (file, rule), fs in sorted(groups.items()):
        more = f' (+{len(fs) - 1} more)' if len(fs) > 1 else ''
        print(f"{file}:{fs[0]['line']} warn {rule}{more} {fs[0]['message'][:110]}")
    warns = len(rep.findings) - len(errs)
    if report_path:
        with open(report_path, 'w', encoding='utf-8') as fh:
            json.dump({'findings': rep.findings, **rep.meta}, fh, indent=1)
    extra = f", consumed_never_produced={len(rep.meta['consumed_never_produced'])}" if 'consumed_never_produced' in rep.meta else ''
    print(f'sql_check {label}: errors={len(errs)} warnings={warns}{extra}')
    return 2 if errs else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('all', 'scan', 'lint', 'xfile', 'fidelity'):
        s = sub.add_parser(name)
        s.add_argument('--dir', required=True)
        s.add_argument('--sas-dir')
        s.add_argument('--tables')
        s.add_argument('--orchestration')
        s.add_argument('--report')
    s = sub.add_parser('fix'); s.add_argument('--dir', required=True); s.add_argument('--dry-run', action='store_true')
    s = sub.add_parser('count'); s.add_argument('--file', required=True)
    a = ap.parse_args(argv)

    if a.cmd == 'fix':
        return cmd_fix(a)
    if a.cmd == 'count':
        t = read(a.file)
        print(f'{os.path.basename(a.file)}: {len(statements(t))} statement(s), {len(malformed(t))} malformed')
        return 0
    files = sql_files(a.dir)
    if not files:
        print(f'no .sql files in {a.dir}', file=sys.stderr)
        return 2
    rep = Report()
    orch = a.orchestration or (os.path.join(a.dir, 'orchestration') if os.path.isdir(os.path.join(a.dir, 'orchestration')) else None)
    if a.cmd in ('all', 'scan'):
        check_scan(files, rep)
    if a.cmd in ('all', 'lint'):
        check_lint(files, rep)
    if a.cmd in ('all', 'xfile'):
        check_xfile(files, rep, a.tables, orch)
    if a.cmd in ('all', 'fidelity'):
        check_fidelity(files, rep, a.sas_dir)
    rep.meta['statements'] = sum(len(statements(read(p))) for p in files)
    report = a.report or (os.path.join(a.dir, 'sql_check.json') if a.cmd == 'all' else None)
    return emit(rep, report, a.cmd)


if __name__ == '__main__':
    sys.exit(main())
