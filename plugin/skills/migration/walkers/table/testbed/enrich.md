# Enrich

Turn `mine`'s `unsolved` rows into fragments, then drive `testbed(phase="enrich")` to rc 0.
Paths and `objectId` are from [incremental.md](incremental.md). You author every fragment
yourself and pass it inline on `enrich`; never write a fragment file or spawn a subagent.
Follow the prompt text in `mine`'s `prompts`; open
`<prompts>` = `<pluginDir>/skills/migration/migrate-objects/baseline-capture/testbed-generator/prompts`
only for a critic prompt.

## 1. Research

Work every row of `unsolved.by_kind.<kind>.constraints` (the file only when `mine` says
`truncated`); never reopen a constraint it does not list. Get the files in one `query_registry`:
`where="id = '<objectId>' OR source.name IN ('<name>', …)"`, `fields="id,source.name,files"`,
where each `<name>` is a `related_objects` entry without schema or signature
(`defaultdb.dbo.GetX(VARCHAR)` → `GetX`).

The table's own files ground its `check` / `fk` / `enum_domain` rows. A row whose `object` is
a routine came from that routine's predicate or join: find it with `source_evidence` and
`detail`. Never open a routine's testbed artifacts; every data change must affect this table.

## 2. Author fragments

| unsolved `kind` | prompt under `<prompts>/` |
|---|---|
| `fk`, `join_edge` | `structural/fk_chains.md`; peer-attribute joins → `structural/correlated_groups.md` |
| compound `branch_predicate` (cross-table) | **Cross-table rows** below |
| anti-join `branch_predicate` (`NOT EXISTS` / `LEFT JOIN … IS NULL`) | `structural/anti_join_tables.md` |
| date-column pairs | `structural/temporal_alignment.md` |
| `branch_predicate` (value arm) | `value/branch_values.md` |
| `enum_domain` (undeclared) | `value/inferred_enum.md`, covering every value in the row's `mined_values` (what routines write or test); unclassifiable residue → `value/flag_for_llm.md` |
| `check` / lookup floors | `value/must_include.md` |
| column null semantics | `value/null_fraction_override.md` |
| `calendar_column` | `value/derivation.md`, only for a column whose value is a function of the row's run-date column (`columns[0]`) under a convention the workload states; leave every other row unanswered |

**Cross-table rows.** `mine` tags each `branch_predicate` row that names another table with
`cross_table`; follow the tag, never re-derive it from other tables' DDL:

- `handoff`: a later table owns the group and pins its rows to yours. Write no
  `correlated_groups` entry. Put each literal the row tests on this table's columns into
  `branch_values` `must_include` (`EmploymentStatus = 'Active'` → `"Active"`); a column tested
  only through a parameter (`@x IS NULL OR col = @x`) needs nothing.
- `own`: the other tables are already generated. Write `structural/correlated_groups.md`. A
  tuple cell on another table's column must be a literal the row tests; never a key, an FK
  value, or a parameter-tested column.

**Single-row reads.** `mine` lists no row for this, so check the routines' files yourself. A routine
that reads one row per key behind a flag predicate, as a scalar assignment
(`SELECT @x = col FROM <this table> WHERE key = @k AND <flag> = 1`) or a scalar subquery
(`= (SELECT col … WHERE key = … AND <flag> = 1)`) with no `ORDER BY` / `TOP 1`, needs at most one
flagged row per key. Emit `value/unique_where.md` for it (`columns` = the key, `where` = the flag).

One fragment per prompt type, passed inline as `enrich`'s `fragments` map
(`{"<prompt_type>": {…}}`); the tool writes each to `<obj>/fragments/<prompt_type>.json`.
`flag_for_llm` is a router: resolve it into another type; never emit it.

**Table names.** Copy a row's `table` / `right_table` verbatim: the 3-part
`database.schema.table` (`defaultdb.dbo.Tasks`). The prompts' examples show `SCHEMA.TABLE`;
a 2-part name fails `TBD0014` and discards the whole document.

**Order.** Author `fk_chains`, `correlated_groups` and `temporal_alignment` first; every other
type must agree with them (`anti_join_tables` needs an FK the table already has or that
`fk_chains` adds; `branch_values` and `null_fraction_override` must agree with
`correlated_groups` and the FKs).

## 3. Propose

Call `testbed(phase="enrich", objectId=<id>, fragments={…})` with every fragment inline.

- **rc 0:** ready; return `done`.
- **rc 1:** act on the reply's `stop_kind` / `report`, then re-call enrich with the repair
  inline (`fragments` and/or `verdict`) unless the stop is terminal.

| `stop_kind` | Do |
|---|---|
| `critique` | Report `entries` 0, or every `critique-request.json` entry `status: "pass"` → pass `verdict={"verdicts": []}` without opening the critic prompts. Else judge the `flag` entries with `<prompts>/critics/joins_critic.md` (structural) / `spec_critic.md` (value) per `verdict-contract.md`, passed as `verdict`. REJECT only with a verifiable mode-`a` citation; otherwise REVISE (mode `b`). |
| `reject` | Re-run the prompt named by `prompt_type` (`critic` means rewrite the verdict). Re-author that fragment, dropping only the literals the citations name. |
| `iterate` | Issues `blocking` with `remediation.enrichment_fixable: true` → re-run `remediation.enrichment_type` using the `hint`. `reason: critic_revise` → re-author the named fragments from each entry's `feedback`. |
| `documented-stop` | **Terminal.** Return `escalate` with `detail` / `citations`. |
| `budget-exhausted` | **Terminal.** Return `escalate` with the report; a human fixes the fragment and re-runs with `reset_budget=true`. |

Budget: 3 rejections per prompt type and 3 not-ready iterations, unless
`$AIM_TESTBED_MAX_REJECTIONS_PER_TYPE` / `$AIM_TESTBED_MAX_ITERATIONS` say otherwise.
`fk_cycle` and `parent_missing_key` are advisory, never blocking. A not-null FK cycle is a
`documented-stop`.
