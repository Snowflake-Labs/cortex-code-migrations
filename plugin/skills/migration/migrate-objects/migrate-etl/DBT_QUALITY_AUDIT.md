# Audit dbt quality (`auditDbtQuality`)

One dbt-quality run over every dbt project of the migration and its converted table DDL, before
deploy. `next_task` offers it once every in-scope ETL unit with a dbt part has reached it; until
then it is blocked on the units still converting or stabilizing.

## Run it

Call the tool once with the batch args `next_task` gave:

```
dbt_quality_audit(where="id IN (...)")
```

Pass nothing else. The tool reads its inputs from the project: every registry dbt target, the
table DDL the registry lists, the `snow:` map of `.scai/bindings/database-bindings.yaml` and
`.dbt-quality.yml`. It then:

1. audits all projects together, so the cross-project rules see the whole estate,
2. reports column findings where model output columns differ from the DDL type and collation. A
   model is checked against the table named by the model or its alias, or the table its post-hook
   `INSERT ... SELECT ... FROM {{ this }}` loads (SnowConvert's SSIS `ole_dst_*` views),
3. writes a Jinja marker (`{# SSC-...DBT... - ... #}`) above each warning, error and deploy-blocking finding
   in the models, keeping markers out of warehouse SQL; the next run removes the markers of fixed
   findings,
4. writes `.scai/dbt-quality/dbt-audit-suggestions.json`, `dbt-audit-report.html`,
   `findings.jsonl` (one finding per line, with its `project` and `scope`: `unit` or `estate`) and
   `changes.diff` (every marker it wrote). The last audit before it stays as `previous-audit.json`
   and `previous-findings.jsonl`,
5. stamps each unit in `where`. Do not stamp `auditDbtQuality` yourself.

A walker runs the step's `run` (`walk_run op=dbt_quality_audit`) in place of the tool: it audits
and stamps its one unit the same way.

An unchanged estate is not audited again (`cached: true`). A change to a model, the DDL, the bindings or `.dbt-quality.yml`, or a registry edit that moves a dbt target to another unit or adds or drops one, runs a new audit.

## Read the answer

| Unit verdict                       | Next                                                                                                                                                                                                                                                                                       |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `completed`                       | If `repairable` is empty, go to `deploy`. Otherwise use the reviewed repair flow below, audit again, then deploy only after the second passing audit. |
| `failed`, error `dbtQuality`       | The fix loop. Error-level findings in the unit's dbt projects, or column-contract findings (`SSC-EWI-DBTCOL0002`–`0006`) on its `table` and `incremental` models or on a table a post-hook loads, would break the deploy or a full refresh.                                                |
| `failed`, error `dbtQualityInputs` | Stop and tell the user. A dbt project the registry names for this unit does not exist, so no model fix helps.                                                                                                                                                                              |

Tell the user:

- every line of `gaps` (a project, table, binding or post-hook the run could not use),
- the `estateAdvisory` count: cross-project findings, such as projects that should be
  consolidated, which do not block deploy. They are the `estate` rows of `findings.jsonl`,
- `delta` after a second audit: the findings resolved and added, and the change in each level
  count. It is `null` on a first audit.

## Repair before deploy

For each issue in a completed unit's nonempty `repairable`, call `dbt_quality_repair` with no issue
to list counts, then preview that issue with `apply: false`. Show the summary, skips, warnings and
`changes.diff`; stop for the user's approval. Apply only with that preview's `plan_id` and unchanged
`project`, `select`, `options`, `allow_dirty` and `verify`. A changed input requires a fresh preview
and approval. Never install dbt, weaken the default parse gate, commit or discard files automatically.

After the approved repairs, call `dbt_quality_audit` again with the same batch `where`; show its
`delta`. Failed gates retain staged edits and rollback evidence and stop deploy. The second passing
audit, not the original completed verdict, is the deploy prerequisite.

`SSC-EWI-DBTINC0010` (a hook writes another table) is a critical warning. Its readers, in
`context.readers`, have no dependency on the writing model. Fix it before projects are
consolidated, as the finding's remediation says.
