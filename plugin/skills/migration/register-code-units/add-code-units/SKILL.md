---
name: add-code-units
description: Add local source code files to a migration project using scai code add. Use when source SQL files are already available on disk instead of extracting from a live database. Triggers: add code, import files, local files, add source, scai code add.
parent_skill: register-code-units
license: Proprietary. See License-Skills for complete terms
---

# Add Local Source Code

## On Entry

Tell the user:
> **Importing local SQL files.**
>
> I'll handle this for you — importing your local SQL files and organizing them by type into `source/`, ready for conversion. It's a single automated step; you won't need to copy, arrange, or move anything yourself.

## Prerequisites

- Migration project initialized (`scai init`)
- Local directory containing SQL source files

## Workflow

### Step 1: Get Source Path

If the session's `workload` is `dbt`, load `dbt.md` instead of Steps 1–4, then rejoin at Step 5.

Otherwise, ask the user for the path to their source SQL files:

> "Where are your SQL source files located? Please provide the full path to the directory."

### Step 2: Annotate Multi-Object Files with sc-tags

`scai code add` uses the arrange engine to split files into one object per code unit. For non-T-SQL dialects the engine splits on `/* <sc-...> */` boundary tags. Before importing, call the `split_code` MCP tool to detect files that need tags (at least one top-level object and no SC tag yet) and inject those tags automatically. Files that already carry SC tags, such as Teradata extraction-script output, are copied unchanged.

```
split_code(input_path="<INPUT_PATH>")
```

- If no file needs tags, the tool says so and you can skip ahead to Step 3 using `<INPUT_PATH>` directly.
- Otherwise the tool copies all files to `artifacts/source_split/` (leaving out macOS `__MACOSX/` / `._*` metadata), injects the sc-tags, verifies the result, and tells you to use `artifacts/source_split` as the input for Step 3.
- If it lists files that still have no SC tag, apply the fix it gives for each before Step 3 — do not fall back to `--code-already-split`.

The tool handles the full detect → inject → verify cycle in one call. It is OS-agnostic and does not require Python.

**Example** — what the tool injects before each object in a multi-object file:

```sql
/* <sc-table>sales.public.customers</sc-table> */
CREATE TABLE sales.public.customers (
  id INT,
  name VARCHAR(100)
);

/* <sc-view>sales.public.v_active_customers</sc-view> */
CREATE VIEW sales.public.v_active_customers AS
SELECT * FROM sales.public.customers WHERE active = 1;
```

> **T-SQL note:** T-SQL files do not need this step — the engine has a native T-SQL splitter. Skip Step 2 for T-SQL source files.

### Step 2b: Give SQL Server files their database

**SQL Server only; skip for every other dialect and for dbt.** An object belongs to the database
named by the `USE` in effect where it is defined. A file with no `USE` puts its objects in
`defaultdb`, where same-named objects from different databases collide and cross-database
references (`SALES.dbo.ORDERS`) find no unit. Give `code add` each file's database instead:
`--database <NAME>` for the whole input, or `--database-map <FILE>` per path. It writes the
`USE` into the engine's copy only (the user's files and `artifacts/source_raw/` stay as they were)
and records the assignment under `.scai/code-add/`.

1. Count the files that already name their database:
   `grep -rliE '^[[:space:]]*USE[[:space:]]' <INPUT_PATH> | wc -l` against the `.sql` count (UTF-16
   files do not match `grep`; check those by opening them). If every file has one, skip to Step 3. A file's own `USE` always wins over an assignment.
2. Collect the evidence for the rest, never guessing a name:
   - **Layout:** top-level folders or file-name prefixes per database (`<DB>/…`, `<DB>_db__…`), or a
     `.sqlproj` (the engine binds those itself; leave them unassigned).
   - **References:** the first part of three-part names in the code
     (`grep -rhoiE '\[?[A-Za-z_][A-Za-z0-9_]*\]?\.\[?[A-Za-z_][A-Za-z0-9_]*\]?\.\[?[A-Za-z_][A-Za-z0-9_]*' <INPUT_PATH> | cut -d. -f1 | sort | uniq -c`),
     SSIS connection `Initial Catalog` values, deploy scripts, and the source connection's databases
     when one is configured.
3. Classify the input and act:
   - **S1, layout names the databases:** each folder or prefix matches a database the references or
     the source name. Write the map (one rule per folder or prefix, first match wins) to
     `.scai/config/database-map.json` (not under `artifacts/`, which a failed add only cleans when it
     was empty), e.g. `{"databases": [{"path": "**/SALES_ARCHIVE_db__*", "database":
     "SALES_ARCHIVE"}, {"path": "SALES", "database": "SALES"}]}`. Put the narrower
     rules first. Show the user the folder → database table and ask with `ask_user_question` to
     confirm or correct it.
   - **One database, flat dump:** ask for the database's name and pass `--database <NAME>`. The
     answer is a name: when the evidence suggests names (a three-part-name prefix, the source
     connection's databases), offer them as `ask_user_question` options; when it suggests none,
     ask in a plain message and wait for the typed name, as Step 1 asks for the path. Leaving the
     files without a database is never the only option offered: it puts them in `defaultdb`.
   - **S2, several databases, no layout:** propose what the references support, file by file, and
     ask. Never assign a database the evidence does not name.
   - **S6, a deployment merged or renamed databases** (folders say `STAGE` but file prefixes say
     `STAGE` and `STAGE_JL`): ask which model is migrated, the original databases (prefix
     rules) or the deployed ones (folder rules). Code that references the deployed names binds
     only under the deployed model; copies that collide inside a merged database are then S4.
   - **S5, environment copies** (`SALES_DEV`, `SALES_QA`, `SALES_PROD`): ask whether to migrate one
     environment (map only its folder and leave the others out of the input) or all of them as
     separate databases.
4. Check the plan without changing anything:
   `scai code add -i <INPUT_PATH> --database-map .scai/config/database-map.json --dry-run --json`.
   `result.databaseAssignments` lists each file's `database` and `source` (`map`, `option`, or
   `file` for its own `USE`; `assignedDatabase` then names the assignment it overrode). `ADD0026`
   means a rule matched no file, `ADD0033` that an earlier rule takes every file it matches: fix
   the pattern or move the narrower rule first, never drop the rule silently. Then run Step 3 with
   the same option.

### Step 3: Add Code to Project

Use the path returned by `split_code` (or `<INPUT_PATH>` directly if no file needed tags).

Launch this call as the next section says: `run_in_background=true`, or set the bash tool `timeout` to at least `900000` (15 minutes), then poll until the command finishes. The default 120 second timeout kills the process during the conversion engine's silent pause and a relaunch starts it over.

```bash
scai code add -i <INPUT_PATH> --json
```

With Step 2b's assignment, add the same `--database <NAME>` or `--database-map <FILE>`.

**dbt projects use this form instead** — always, with no exceptions:

```bash
scai code add -i <DBT_PROJECT_PATH> --code-already-split --json
```

Step 2 is skipped for dbt, so the files have no SC tags; `--code-already-split` tells the arrange
engine the input is already one object per file. Without it the command fails with `ADD0010`.

This will:
- Copy all files from the input path to `artifacts/source_raw/`
- Arrange and process the source code
- Merge processed output into `source/`

**If files already exist** and you need to overwrite:
```bash
scai code add -i <INPUT_PATH> --overwrite --json
```

#### If the import times out or runs in the background

This section covers every `scai code add` the register and conversion skills run: the SQL
add here, ETL, dbt, Power BI and `code-conversion-only`.

Launch the command with `run_in_background=true`, or set the bash tool `timeout` to at least `900000` (15 minutes), then poll until it finishes. The default 120 second timeout kills the process during the conversion engine's silent pause and a relaunch starts it over. `--help` and `--list-settings` can stay on the short timeout.

A large source can keep `scai code add` running longer than one `bash` call allows. When
the call times out, or returns `Command running in background with ID: <id>` or
`Process moved to background with ID: <id>`, the import has not finished and you have no
envelope yet. A timeout is neither a failure nor a success.

- **With an id, wait for the real end, in this turn.** Call
  `bash_output(bash_id=<id>, wait=true)`, and call it again while it reports running, until
  it shows `<status>completed</status>`. Then take its `<exit_code>` and the `--json`
  envelope in its `<stdout>`; those are the import's result. Do not end the turn to say it
  is still importing: this app does not show the turn cortex starts when the job ends, so
  the user would be left with an idle screen. A short line before each wait is fine. Until
  you have the result, say only that it is still running,
  never that it finished or that nothing is wrong.
- **With no id, the run you started has ended or is ending; do not start another.** First
  check whether scai is still running with `pgrep -fl '[s]cai code add'` on macOS/Linux, or
  `Get-CimInstance Win32_Process -Filter "Name LIKE 'scai%' AND CommandLine LIKE '%code add%'"`
  on Windows. Output lists a running import;
  exit code 1 with no output means no import is running, not that the check failed.
  Keep the brackets in `[s]cai`: without them `pgrep -f` matches the shell running the
  check and reports an import that has stopped. Run the check as its own command,
  never chained with the import, whose text the shell's command line would hold. Repeat it until nothing is running, then treat that run as finished: read any
  envelope left in the timed-out output, else run `scai logs --last 5` and read the newest
  `scai_error<YYYYMMDD>.log` as below. A logged error is a failure to report.
  Start another `scai code add` only when the logs show the first one never ran or was cut
  off before it wrote anything, say so to the user first, and launch it with
  `run_in_background=true` so you have an id to wait on as above. Two imports writing
  `source/` at once corrupt it, and one rerun after a crash only repeats the crash.

**If the import failed** — a non-zero `<exit_code>`, an envelope with `"success": false`,
or a job that ended with no envelope at all — find out why before you say anything else:

1. An envelope with `"success": false` names the cause in `error.code`, `error.message`
   and `error.suggestion`. Use those.
2. With no envelope, run `scai logs --last 5`. It prints the log directory (honouring
   `SCAI_LOGS_DIR`) and the newest log files on every OS. Read the end of the newest
   `scai_error<YYYYMMDD>.log` there for the error code and its message.
3. Tell the user, with the code and message you found (e.g. `CVT0008` or `CRG1001`):
   > **The import failed.** `<code>`: `<message>`. `<what you propose next>`.

   Rerunning the same command gives the same failure, so propose a change (the suggestion,
   a fix to the files it names) rather than a retry. Do not continue to the next step, and
   do not treat the import as done.

**If the failure is `ADD0029` or `CVT0008` with a `Duplicate groups` entry in `error.details`**,
the input defines the same object in more than one file and nothing was added. Go to
[Duplicated objects](#duplicated-objects). Never add `--keep` or `--dedup keep-first` to get past it
on your own.

**If the failure is `ADD0007` after an earlier `scai code add` in this project failed**, and
`migration_status` reports no registered code units, the files it lists are most likely what
that failed run left in `source/`: a failed add rolls back, but it cannot always remove every
file. Keep them. Rerun the same command with `--overwrite` added, which replaces them with this
run's output, and tell the user in one line that you are doing so. Never delete files from
`source/` or `artifacts/` yourself to clear the way. When the project already has registered
units, the files may be code the user added before: ask before you add `--overwrite`.

### Duplicated objects

`ADD0029` and `CVT0008` carry `error.details["Duplicate groups"]`: per object, its `id`, `database`,
`databaseStatus` (`unknown` when the copies collide only because no file named a database) and
`copies`, each with `path` (in `source/`), `origin` (`input` or `project`), `inputs` (input file,
`database`, `databaseSource`), `contentHash`, `lines` and `differingLines` against the first copy.
Classify every group from that evidence and the input layout, then propose one action per group:

| Situation | Evidence | Action |
|---|---|---|
| S1/S2 different databases | `databaseStatus: unknown`; the copies' input paths sit in different database folders or prefixes, or references name different databases | **Assign databases** (Step 2b) and rerun. Every copy becomes its own unit. |
| S3 byte-identical copies | equal `contentHash` | Same database: `code add` already keeps one. Different databases: assign databases; both stay. |
| S4 versions of one object in one database | known `database`, or a user-confirmed single database; old script, `_v2`, backup, ALTER script | **Keep one**, chosen by the user: the version deployed on the source when there is a connection (`query_source`), else the user's pick. |
| S5 environment copies | database names with environment suffixes, near-identical content | Ask: migrate one environment, or all as separate databases. |
| S6 merged or renamed databases | folder and file-prefix databases disagree | Ask which database model is migrated; inside a merged database, S4 applies. |
| S8 a later add brings a copy of an object already in the project | `ADD0007` on the registered file, or a copy with `origin: project` | Different database: assign it; it becomes a new unit. Same database: S4. A new copy arranged onto the registered file stops with `ADD0007`: replace it only with the user's consent (`--overwrite`), as the `ADD0007` rule says. A copy under another name keeps the registered one with `--keep source/<path>`. |

1. Show the user each group in a short table: object, database, each copy's input file, database
   and `differingLines`, and your classification.
2. Ask with `ask_user_question`. The options must include **"These are different databases (assign
   databases)"** and **"These are environments of one system"**; offer **"Keep one copy"** only for
   groups classified S4, naming the copy for each.
3. Apply the answer and rerun the same command:
   - assign databases → Step 2b's `--database-map`;
   - keep one → `--keep <INPUT_PATH>` per object (the copy's `inputs[].path`, relative to the input
     root; `source/<path>` for a copy already in the project). Use `--dedup keep-first` only when
     the user explicitly chooses "keep the first file of every object".
4. Report each file in `result.duplicatesSkipped` (`path`, `inputPaths`, `keptPath`,
   `keptInputPath`, `policy`) as left out, and `result.decisionRecord`, where the choice is kept.

`ADD0030` means a `--keep` named no copy, two different copies, or would drop a copy the project
already registered: show the reason and ask again. A `--keep not applied` entry in `error.details`
names a `--keep` that matched no copy while other objects stayed undecided. `ADD0019` / `ADD0021` with `--dedup keep-first`
mean no copy can be chosen from the input: tell the user which files to remove.

**When nobody can answer** (an autonomous or headless run, a walker or Hail Mary agent, or no
`ask_user_question`): apply only S1 database assignments whose evidence is unambiguous (every
folder or prefix matches a database the references or the source name) and S3 identical-copy
handling. Never pass `--keep` or `--dedup keep-first`, and never treat an automated reply as the
user's choice of a copy. Stop and report the groups still blocked, with their evidence.

### Step 4: Import ETL

**Skip this entire step for a dbt project.** If Step 1 found `dbt_project.yml`, do **not** ask the
ETL question — a dbt workload has no SSIS or Informatica packages, and asking it is a defect. Go
straight to Step 5 without calling `ask_user_question`.

ETL belongs in the project from register onward. Read `has_etl_code` from `configure()` (set by
`chooseMigrationExtras` or by the parent register skill's extras card). Never ask a standalone ETL
yes/no — that question lives only on the extras multi-select.

- If `has_etl_code` is **`false`** (explicitly): the user already said no ETL — proceed to Step 5 without asking.
- If `has_etl_code` is **not set**: return to the parent register skill and collect the extras card there, then re-read `has_etl_code`. Do not invent a yes/no.
- If `has_etl_code` is **`true`** (explicitly): open [etl.md](etl.md) and follow it. That file holds the ETL import
  steps: which directory each platform uses, and how each unit is registered as `kind: etl`. Come
  back here at Step 5 when it finishes. Do not register ETL as `customKind`.

### Step 5: Import Power BI templates

Power BI template (`.pbit`) files are inventory only: `code add` copies them to
`source/BI/PowerBI/` and `artifacts/BI/PowerBI/` and never sends them to the conversion engine.
Read `has_power_bi` from `configure()`:

- If `has_power_bi` is **`false`**, proceed to Step 6 without asking.
- If `has_power_bi` is not set, return to the parent register skill and collect
  the extras card, then re-read it.
- If `has_power_bi` is **`true`**, first check whether Step 3 already imported
  `.pbit` files. If it did, proceed to Step 6. Otherwise ask only for the folder
  path and compare it to `<INPUT_PATH>`:
  - If it is **the same as, or inside, `<INPUT_PATH>`**, Step 3 already imported it — `code add` claims `.pbit` files anywhere under the input path. Proceed to Step 6 without running a second `code add`.
  - Otherwise (a genuinely separate folder) run:

```bash
scai code add -i <POWER_BI_PATH> --json
```

Do **not** pass `--overwrite` here — existing SQL/ETL in `source/` would be wiped. If it
times out, runs in the background or fails, handle it as
[Step 3](#if-the-import-times-out-or-runs-in-the-background) says.

Confirm files landed in both `source/BI/PowerBI/` and `artifacts/BI/PowerBI/` before continuing.

### Step 6: Verify Files Were Added

Check that `source/` contains the expected `.sql` files and report a count. Use whichever portable form fits the host:

```bash
# macOS / Linux
find source/ -name "*.sql" | head -20
find source/ -name "*.sql" | wc -l
```

```powershell
# Windows PowerShell
Get-ChildItem -Recurse -Filter *.sql source/ | Select-Object -First 20
(Get-ChildItem -Recurse -Filter *.sql source/).Count
```

## Output Structure

```
artifacts/source_raw/    Original files copied from input path
artifacts/source_split/  sc-tag annotated copies (only created when some file needed tags)
source/                  Arranged source files ready for conversion
source/_etl/             ETL packages (when present)
source/BI/PowerBI/       Power BI `.pbit` templates (inventory only, not converted)
artifacts/BI/PowerBI/    Same relative layout as `source/BI/PowerBI/`
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "conflicting files" error | Use `--overwrite` flag to replace existing files |
| `ADD0029` database unknown | The copies collide in `defaultdb`: give the files their databases (Step 2b), see [Duplicated objects](#duplicated-objects) |
| `ADD0026` database map rule matches no file | Fix the rule's pattern (relative to the input root) |
| `ADD0033` database map rule is shadowed | An earlier rule takes all its files: put the narrower rule first |
| `ADD0010: Source files must contain SC tags` | The arrange engine found no `/* <sc-...> */` boundary tags. For a **dbt project**, re-run with `--code-already-split` (required on every dbt add). For a non-dbt source, run Step 2 (`split_code`) first and pass the returned `artifacts/source_split/` path. |
| No `.sql` files found after add | Verify input path contains valid SQL files |
| Unexpected file arrangement | Check `artifacts/source_raw/` for the original copies |
| `split_code` reports verification errors | Manually inspect flagged files; the tool lists each with its boundary and tag counts |

## CHECKPOINT

Check these yourself against the `--json` envelope. Do **not** turn them into a
question — the envelope already says what was imported, and the user cannot
verify a count you just computed for them:

- [ ] Every `scai code add` finished with exit code 0 and an envelope with `"success": true`
      — a timeout or a background launch is neither; wait for the job as Step 3 says
- [ ] `filesCopied` matches the SQL files in the input path
- [ ] `.sql` files are present under `source/`
- [ ] SQL Server: every file without its own `USE` got a database (Step 2b), or the user chose to
      leave the input in one unnamed database
- [ ] If Power BI was imported: files exist in both `source/BI/PowerBI/` and `artifacts/BI/PowerBI/`

Stop and ask only when a check fails: say which one, and what you propose to do
about it.

## On Completion

### Break down `Other` from the registry

`byType` counts units by `objectType`. `Other` is the registry's catch-all, not a type: every
type it knows (`trigger`, `index`, `joinIndex`, …) has its own row, so never say a type you
expected "lands in" `Other`. Most of its units are missing references — objects the imported
code uses but no imported file defines, registered with `isMissing = true`. They count in
`codeUnitsAdded`, which is why the total can exceed the objects in the source files.

When `byType` has an `Other` row, look up what is in it before you report, never guess:

```
query_registry(where="source.objectType = 'other' AND isMissing = true", fields="id,source.name,source.schema", limit=5)
query_registry(where="source.objectType = 'other' AND NOT isMissing = true", fields="id,source.name,files.source.path", limit=5)
```

Each response's `total` is that group's count; its `results` give a few names to quote. If the
two totals do not add up to the `Other` count, give the counts you have and say the rest are
unexplained.

### Report

After the CHECKPOINT passes, tell the user — a statement, not a question. Fill placeholders from the JSON envelope returned by `scai code add --json`.
Never report the import as complete, or as fine, without that envelope in hand: on a failure,
report it as Step 3 says instead.

> **Import complete.** `<filesCopied>` files imported as `<codeUnitsAdded>` code units, broken down by type (filled from `byType`). Files in `source/`.
> *If `byType` has `Other`:* `<missing total>` are missing references: objects your code uses that the imported files do not define (e.g. `<names>`); add their DDL if they belong in the migration. *If the second total is not 0:* `<other total>` more are defined in your files with no type the registry knows (e.g. `<names>`).
> *If `etlFilesAdded > 0`:* ETL: `<etlFilesAdded>` files added.
> *If `etlFilesSkippedInvalidSchema > 0`:* `<etlFilesSkippedInvalidSchema>` ETL files skipped due to invalid schema.
> *If Power BI files were added:* Power BI templates copied to `source/BI/PowerBI/` and `artifacts/BI/PowerBI/` (not converted).
> Next, we'll convert these to Snowflake SQL.

Then return to the calling skill **in this same turn**. That last line announces
the next step; it is not a stopping point. Under setup, call `progress_setup()`
now and start the step it names. Ending the turn on it leaves the user watching
an idle screen with nothing to click until they type "continue".
