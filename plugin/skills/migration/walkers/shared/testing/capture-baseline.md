# Capture Baselines

`captureBaseline` for one function or procedure: run the source side of its test YAML and upload the baseline.

Run the step's `run` as given (op `capture`). Never shell `scai test capture`. It binds the step's `sandbox` when
present, else the project common yaml. Success records the task (status source: `VALIDATION.BASELINE_METADATA` has a
row for the object whose `ROW_COUNTS` sum > 0) and replies with the next step.

## Vacuous cases

A case the source rejects for its inputs (an overflow, a value it refuses), or one that returns no rows or only
NULLs, tests nothing: the reply lists it in `vacuous` instead of failing on it, and `runTests` skips the ones that
errored. An error the object raises on purpose (SQL Server error number ≥ 50000, unless it re-raises an engine error) is not vacuous: it is
compared, and the converted object must raise too. A reply with `regenerate` (over a third vacuous) → add rows that cover them once per
[generate-test-cases §7](generate-test-cases.md#7-cover-vacuous-rows-once), then carry on with the step it
returned. An error that names the environment (a missing object, a privilege, the connection) is still a failure.
A vacuous reason starting `source_defect:` (*insert into T omits key column C with no IDENTITY/DEFAULT*) is a source
defect: escalate at once per [general_task §3](../../../../../agents/general_task.md#3-rules) (*Key without
IDENTITY*). No helper, no repair — never inside the procedure.

## If capture fails

Do what `fix` says. Fixing a `failing` case means editing the YAML without losing coverage — never drop or omit a
row, never `ALTER` the source; then re-run `run`. *No case tests anything* →
its `fix`: one error on every case whatever the inputs is the fixture or the source; otherwise §7. Never edit WAVE_SRC or a table unit's CSV. Before spawning
`sandbox_specialist` (`task=captureBaseline`, the reply's `detail`), apply the fixture-rows test in
[general_task §3](../../../../../agents/general_task.md#3-rules): a failure on every legal dataset is a source
defect — escalate, do not spawn. A source error that `files.source` would not raise against its own tables (an
INSERT omitting a key the source table makes `IDENTITY`) is drift, not a defect: same section.
