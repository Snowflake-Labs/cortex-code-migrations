---
name: tableau-repointing
description: Repoint Oracle or SQL Server Tableau workbooks (`.twb` / `.tds`) to Snowflake. Triggers: tableau, tableau migration, tableau repointing, migrate tableau, repoint tableau, twb, tds. Load from skill-match on those phrases, or from `convert` when the project is Oracle or SqlServer and the user confirms they have Tableau files.
parent_skill: migration
license: Proprietary. See License-Skills for complete terms
---

# Tableau Repointing (Oracle and SQL Server)

Tableau repointing supports **Oracle** and **SQL Server** (`SqlServer`) projects. Do not check licenses — if the CLI is unlicensed it will fail on its own.

Supported files: `.twb` and `.tds`. `.twbx` is not supported.

Treat `source_language` case-insensitively. `SqlServer` is the plugin/CLI language; do not require the string `Transact`.

## Load modes

**Direct (skill-match).** The user asked for Tableau (e.g. "tableau", "migrate tableau", "repoint tableau"). You own init + convert. Empty `source/` is allowed.

**Path-only (from `convert`).** The convert skill already confirmed Oracle or SqlServer and a yes. Collect `TABLEAU_PATH` and return. Do not run convert yourself.

## Shared: collect the workbook folder

Do the following in order:

1. Say to the user (verbatim): *"Repointing rewrites each Tableau workbook connection to Snowflake and translates embedded Oracle SQL or T-SQL to Snowflake syntax. Only `.twb` and `.tds` are supported — `.twbx` is not."*
2. Ask the user (verbatim): *"Please provide the folder path containing your Tableau `.twb` or `.tds` files."*
3. Store the user's answer internally as `TABLEAU_PATH`.

## Direct mode

Do the following in order:

1. Call `configure` with `project_dir = "<current directory>"` if this session has not already.

2. If `project_exists` is true and `source_language` is **neither** Oracle **nor** SqlServer (compare case-insensitively), stop. Tell the user (verbatim): *"Tableau repointing currently supports Oracle and SQL Server workbooks only. This project is neither. Start an Oracle or SQL Server project, or convert this project as-is without Tableau."*

3. If `project_exists` is false, there is no `source_language` to check, so confirm the source before creating a project. Ask the user (verbatim): *"Tableau repointing currently supports Oracle and SQL Server. Are your workbooks connected to Oracle or SQL Server?"*

   - On **neither** (or any other source), stop. Tell the user (verbatim): *"Tableau repointing currently supports Oracle and SQL Server only. Support for other sources is not available yet."* Do not create a project.
   - On **Oracle**, initialize Oracle in the current directory (name defaults to the folder name):

```bash
scai init -l Oracle --json
```

Then `configure(project_dir="<current directory>", source_language="Oracle")`.

   - On **SQL Server**, initialize SQL Server in the current directory (name defaults to the folder name):

```bash
scai init -l SqlServer --json
```

Then `configure(project_dir="<current directory>", source_language="SqlServer")`.

4. Collect `TABLEAU_PATH` (Shared steps above).

5. Run conversion. `--json` is required. Empty `source/` is fine — do not import SQL first unless the user asked to convert SQL as well.

```bash
scai code convert --tableauRepointing <TABLEAU_PATH> --json
```

If `source/` already has SQL, the same command converts that SQL and repoints Tableau. Substitute the stored path. Do not emit the literal `<TABLEAU_PATH>` token.

6. Show the JSON envelope as-is. Read `result.tableauRepointing` from the envelope:
   - Success has `processedFiles` and `outputPath`.
   - `{"message":"None found"}` means Tableau was not requested or no Tableau output was processed.
   Name the durable output location only from `result.tableauRepointing.outputPath`. Then stop unless the user asks to continue the rest of migration.

## Path-only mode

Collect `TABLEAU_PATH` (Shared steps). Return to `convert`. When it runs `scai code convert`, it appends `--tableauRepointing <TABLEAU_PATH>`.

## Convert Output for Tableau

When `--tableauRepointing` is used, `scai code convert` writes:

- Repointed `.twb` / `.tds` → `artifacts/repointing_output/tableauResults/`
- Per-query / connection summary → `reports/SnowConvert/ETLAndBiRepointing.*.csv`

The JSON result envelope contains:

```json
{
  "result": {
    "tableauRepointing": {
      "processedFiles": 1,
      "outputPath": "<absolute-project-path>/artifacts/repointing_output/tableauResults"
    }
  }
}
```

Do not report `.scai/.snowconvert/tableauResults`; it is temporary engine output and is deleted after promotion.

## Option Reference

| Option | Description |
|--------|-------------|
| `--tableauRepointing <PATH>` | Path to a folder of Tableau `.twb` / `.tds` files to repoint to Snowflake (rewrites connections and embedded Oracle SQL or T-SQL). `.twbx` is not supported. |

## CHECKPOINT Addendum

After conversion, also confirm:

- [ ] Convert exited successfully and the envelope reports no conversion errors
- [ ] `result.tableauRepointing.processedFiles` is greater than zero and `outputPath` is present
- [ ] Per-query summary appears in `reports/SnowConvert/ETLAndBiRepointing.*.csv` when the engine emitted one
