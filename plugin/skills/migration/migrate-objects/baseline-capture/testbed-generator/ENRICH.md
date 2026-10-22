# Enrich

Turn unsolved constraints into enrichment JSON. Use the unsolved view, readiness
view, fragments directory, critic directory, enrich report, enrich view, and
`testbed(phase="enrich", ...)` arguments already in play.

## 1. Write fragments

Walk every listed constraint **one by one** (`by_kind.<kind>.constraints` for
each kind whose `count` is not 0). Do not reopen a constraint that is not listed.

For each listed row, inspect the affected and affecting code, then write the
enrichment that row requires:

- **Affected (the constraint's table).** Read that table's source SQL and
  converted SQL (`files.source.path`, `files.converted.path` from the registry).
  Use them for that table's own `check` / `fk` / `enum_domain` rows, and for any
  column the row names on it.
- **Affecting (related routines).** `related_objects` — and the row's `object`
  when it is not the constraint's table — names the routines whose
  `branch_predicate` / `join_edge` rows landed here. Look each name up with
  `query_registry` and read that unit's `files.source.path` and
  `files.converted.path`. Use `source_evidence` and `detail` to find the
  corresponding predicate or join in that SQL.

That inspection is research, not ownership: never inspect those routines' raw
testbed artifacts. Enrichment fragments may cite a related routine as evidence;
every proposed data change must still affect the constraint's table.

Then, for each unsolved `kind` with a non-zero count, follow the matching prompt
under `prompts/{structural,value}/` and write **one file per prompt type** to
the fragments directory as `<prompt_type>.json`. Overwrite in place — never add
a sibling.

| unsolved `kind` | prompt |
|---|---|
| `fk`, `join_edge` | `structural/fk_chains.md`; peer-attribute joins → `structural/correlated_groups.md` |
| compound `branch_predicate` (cross-table) | `structural/correlated_groups.md` |
| anti-join `branch_predicate` (`NOT EXISTS` / `LEFT JOIN … IS NULL`) | `structural/anti_join_tables.md` |
| date-column pairs | `structural/temporal_alignment.md` |
| `branch_predicate` (value arm) | `value/branch_values.md` |
| `enum_domain` (undeclared) | `value/inferred_enum.md`; unclassifiable residue → `value/flag_for_llm.md` |
| `check` / lookup floors | `value/must_include.md` |
| column null semantics | `value/null_fraction_override.md` |

Write **structural first** (`fk_chains` → `correlated_groups` →
`temporal_alignment` → `anti_join_tables`), then **value** (`branch_values`,
`inferred_enum`, `must_include`, `null_fraction_override`, `predicate_fills`).
`flag_for_llm` is a router: resolve it into one of the other types; never emit
it.

If the unsolved view `total` is 0, write no fragments. Otherwise every required
`<prompt_type>.json` must already be on disk in the fragments directory. Do not call `testbed(phase="enrich")` until this section is finished.

## 2. Propose

Call `testbed(phase="enrich")` with the same object arguments already in use.

- **rc 0:** done. Proceed to compile.
- **rc 1:** read the enrichment report and act on `stop_kind`, then re-call
  enrich unless the stop is terminal.

| `stop_kind` | What you do |
|---|---|
| `critique` | Run `prompts/critics/joins_critic.md` (structural) and `prompts/critics/spec_critic.md` (value) against `critique-request.json`. Write `verdict.json` per `prompts/critics/verdict-contract.md`. REJECT only with a verifiable mode-`a` citation; otherwise REVISE (mode `b`). |
| `reject` | Re-run the prompt named by `prompt_type` (`critic` means rewrite the verdict). Overwrite that fragment. |
| `iterate` | If issues are `blocking` with `remediation.enrichment_fixable: true`, re-run `remediation.enrichment_type` using the `hint`. If `reason: critic_revise`, re-author the named fragments from each entry's `feedback`. |
| `documented-stop` | **Terminal.** Surface `detail` / `citations` and stop. A human resolves it. |
| `budget-exhausted` | **Terminal.** Surface the report and stop. A human fixes the fragment and re-runs with `reset_budget=true`. |

The enrich budget is 3 rejections per prompt type and 3 not-ready iterations unless overridden. An explicit `max_rejections_per_type` / `max_iterations` on the tool call wins (including `0`, which stops on the first reject). Otherwise `$AIM_TESTBED_MAX_REJECTIONS_PER_TYPE` and `$AIM_TESTBED_MAX_ITERATIONS`. Otherwise 3.

Do not compile or generate until enrich returns rc 0.

`fk_cycle` and `parent_missing_key` are advisory (never blocking). A not-null FK
cycle is a `documented-stop`.
