# SQL Dynamic Analysis (CSV Fallback)

CSV-based workflow for `SSC-EWI-0030` analysis, using:

- `scripts/sql_dynamic_analyzer_helper.py`

Use this path when registry is unavailable or when you need CSV line-level issue details.

## Generate

```bash
python3 scripts/sql_dynamic_analyzer_helper.py generate Issues.csv \
  --top-level-code-units TopLevelCodeUnits.csv \
  --source-dir path/to/source \
  --output sql_dynamic_analysis.json
```

### Inputs

- `Issues.csv` (required positional)
- `--top-level-code-units` (required unless `--registry-dir` is supplied to enrich code units)
- `--source-dir` (required)
- `--code` (optional, default: `SSC-EWI-0030`)
- `--output` (optional, default: `sql_dynamic_analysis.json`)

## Inspect / Review

```bash
python3 scripts/sql_dynamic_analyzer_helper.py show-file sql_dynamic_analysis.json --id 1
python3 scripts/sql_dynamic_analyzer_helper.py show-file sql_dynamic_analysis.json --id 1 --include-code
python3 scripts/sql_dynamic_analyzer_helper.py show sql_dynamic_analysis.json --id 1
python3 scripts/sql_dynamic_analyzer_helper.py show-code-unit sql_dynamic_analysis.json --id 1
```

## Update

```bash
python3 scripts/sql_dynamic_analyzer_helper.py update sql_dynamic_analysis.json \
  --id 1 \
  --status REVIEWED \
  --category "Identifier-Driven" \
  --complexity medium \
  --generated-sql "SELECT * FROM sys.tables WHERE name = @TableName" \
  --sql-classification DQL \
  --notes '{"justification":"...","complexity":"...","migration_considerations":"..."}'
```

## Progress

```bash
python3 scripts/sql_dynamic_analyzer_helper.py stats sql_dynamic_analysis.json
```
