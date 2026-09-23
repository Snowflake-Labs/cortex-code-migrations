# Assessment Routing and Report Reference

Read this file when the user requests one specific analysis, asks for a
nonstandard report input, or needs command invocation details. The ordinary
end-to-end path is fully defined in `SKILL.md`.

## Contents

- Analysis routing
- Script invocation
- Report command
- Readiness-only topics

## Intent Detection & Routing

| Intent | Skill or source |
|---|---|
| Deployment waves, dependency order | `waves-generator/SKILL.md` |
| Temporary/staging/deprecated exclusions | `object_exclusion_detection/SKILL.md` |
| Migration effort/hours | `effort-estimate/SKILL.md` |
| SQL Server migration risks/anti-patterns | `anti-patterns/SKILL.md` |
| Dynamic SQL patterns | `analyzing-sql-dynamic-patterns/SKILL.md` |
| SQL Server Extended Events or Teradata DBQL discovery | Parent input collection, then `workload-insights/SKILL.md` |
| SSIS packages | `etl-assessment/SKILL.md` |
| Informatica PowerCenter | `informatica-assessment/SKILL.md` |
| Source → pipeline → target → report lineage | Parent input collection, then `data-lineage/SKILL.md` |

Discovery triggers include `discovery`, `workload insights`, `query logs`,
`extended events`, `xel`, `dbql`, and `querylogs`. It accepts SQL Server `.xel`
captures or Teradata DBQL metrics `.csv`; statement text is never a Teradata
input. With no files, route through the parent input collection so it offers
skip / existing files / later and shows the dialect-specific collection SQL.

Power BI templates are optional Data Lineage input. Do not confuse assessment
lineage with `../powerbi-repointing/SKILL.md`, which rewrites templates after
migration.

**Data Lineage** always runs `scai assessment data-lineage`; Power BI is
optional reporting-layer input that enriches the graph.

For any requested assessment, still generate the consolidated report with
`scai assessment report`. Never hand-author `multi_report.html` or run an
individual HTML generator as the deliverable.

## Running Scripts

- Run `scai assessment waves` from the SCAI project directory.
- Run `scai assessment report` through the CLI.
- Run every Python script with:

```bash
uv run --project "<directory containing the applicable SKILL.md>" \
  python "<absolute path to script>" ...
```

For `data-lineage/scripts/query_cur_catalog.py`, that `--project` directory is
`assessment_skill_dir` from the 6.7 context block — never `project_dir`. The
helper is not a carve-out: it uses the same `uv run --project` form as staging.

Do not create custom scripts or bash loops. Follow the selected sub-skill's
commands exactly.

## Report command

The common path is:

```bash
scai assessment report \
  --project-dir "<project_dir>" \
  --output "<project_dir>/assessment/multi_report.html" \
  [--ssis-json "<path>" when SSIS succeeded] \
  [--informatica-json "<path>" when Informatica succeeded]
```

Always pass `--project-dir`; its registry is required to enrich UUID-based
waves with names, categories, paths, statuses, and dependencies. The command
auto-discovers:

- `registry/`
- SnowConvert CSVs under `reports/`
- newest waves, exclusion, anti-pattern, effort, and workload-insights
  artifacts
- `assessment/json/sql_dynamic_analysis.json`
- stable `artifacts/assessment/data-lineage.json`

Only use explicit source flags to select nonstandard locations:

```bash
scai assessment report \
  --project-dir "<project_dir>" \
  --waves-json "<path>" \
  --exclusion-json "<path>" \
  --dynamic-sql-json "<path>" \
  --workload-insights-json "<path>" \
  --snowconvert-reports-dir "<path>" \
  --ssis-json "<path>" \
  --informatica-json "<path>" \
  --output "<path>/multi_report.html"
```

An explicitly supplied source overrides discovery. A partial assessment passes
only available sources, but still passes `--project-dir`.

The workload-insights artifact may come from SQL Server Extended Events or a
Teradata DBQL metrics export. Statement text is never a Teradata input.

## Readiness-only topics

Data Migration & Validation and Testing have no sub-skill or separate
assessment command. Their report/dashboard sections derive from the Code Unit
Registry:

- Data migration readiness:
  `scripts/snowconvert_reports/data_migration_readiness.py`,
  `data_types_scan.py`, and `type_coverage.py`.
- Testing readiness: `scripts/snowconvert_reports/testing_readiness.py`.

Reviewed inventory SQL exists only for SQL Server and Redshift. Other dialects
receive a gather checklist; do not invent queries. ETL testing readiness ends
at stabilization; other code units end at testing.
