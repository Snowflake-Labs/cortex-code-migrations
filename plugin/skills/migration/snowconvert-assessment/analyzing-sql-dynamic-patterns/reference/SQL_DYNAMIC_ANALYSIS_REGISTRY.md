# SQL Dynamic Analysis (Registry-Only)

Registry-first workflow for `SSC-EWI-0030` analysis, using:

- `scripts/sql_dynamic_analyzer_registry_helper.py`

Use this path when SnowConvert output includes `registry/*.json`.

## Generate

```bash
python3 scripts/sql_dynamic_analyzer_registry_helper.py generate \
  --registry-dir path/to/output/registry \
  --output sql_dynamic_analysis.json
```

### Inputs

- `--registry-dir` (required): Directory containing SnowConvert registry JSON files
- `--code` (optional): Issue code filter (default: `SSC-EWI-0030`)
- `--output` (optional): Output JSON path (default: `sql_dynamic_analysis.json`)

### What It Reads From Registry

- `source.objectType == "procedure"` (current scope)
- `issues[].code == SSC-EWI-0030` with `count > 0`
- `files.source.path` to read procedure source text

### Known Differences vs CSV Mode

- Line numbers for individual occurrences are not available from registry issue counts; generated records use `line = 0`.
- Occurrence cardinality comes from registry issue `count`.
- After analyzing each occurrence, set the correct line explicitly with `update --line <LINE_NUMBER>`.

## Inspect / Review

```bash
python3 scripts/sql_dynamic_analyzer_registry_helper.py show-file sql_dynamic_analysis.json --id 1
python3 scripts/sql_dynamic_analyzer_registry_helper.py show-file sql_dynamic_analysis.json --id 1 --include-code
python3 scripts/sql_dynamic_analyzer_registry_helper.py show sql_dynamic_analysis.json --id 1
python3 scripts/sql_dynamic_analyzer_registry_helper.py show-code-unit sql_dynamic_analysis.json --id 1
```

## Update

```bash
python3 scripts/sql_dynamic_analyzer_registry_helper.py update sql_dynamic_analysis.json \
  --id 1 \
  --line 128 \
  --status REVIEWED \
  --category "Identifier-Driven" \
  --complexity medium \
  --generated-sql "SELECT * FROM sys.tables WHERE name = @TableName" \
  --sql-classification DQL \
  --notes '{"justification":"...","complexity":"...","migration_considerations":"..."}'
```

### Line Update Requirement (Registry Mode)

- Use `show-code-unit` or `show-file --include-code` to inspect numbered procedure text.
- For each reviewed occurrence, set `--line` to the best matching line number from that code.
- Do not leave reviewed records with `line = 0` unless the source text is unavailable.

## Progress

```bash
python3 scripts/sql_dynamic_analyzer_registry_helper.py stats sql_dynamic_analysis.json
```
