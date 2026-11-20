"""Synthetic Testbed mining for AI-First ETL documents.

WHY THIS EXISTS. SnowConvert's native SSIS path mines testbed signals (branch
predicates, join edges, derived-column markers, source schemas) into per-object
`<artifacts-dir>/testbed/*.testbed.json` files that `scai testbed init` consumes. An
ETL document forced through AI-First produced NONE of them, so a migration that went
the AI-First way silently had no synthetic-data inputs at all.

LAYERING, so a second unsupported platform does not have to re-derive the contract:

    adapter  (platform-specific)  document [+ optional AI-First IR] -> MiningResult
    model    (neutral)            MiningResult / MinedPackage / MinedTable / ...
    artifacts(neutral)            MiningResult -> snake_case JSON + on-disk placement,
                                  with the SQL-DDL de-duplication seam

Only an adapter may know what a platform's document looks like. `model`,
`predicate`, `types` and `artifacts` must never name a platform.
"""
