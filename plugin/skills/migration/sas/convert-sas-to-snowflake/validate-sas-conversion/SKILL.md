---
name: validate-sas-conversion
parent_skill: sas
description: |
  Preview. Validate a completed SAS to Snowflake conversion: compile it, unit test it on test
  data against SAS outputs (or an LLM trace of the SAS), and run it end to end on full data,
  with a repair loop that feeds every failure back into the converted code.
  Triggers: validate conversion, verify sas migration, test conversion, compare sas output.
license: Proprietary. See License-Skills for complete terms
---

# Validate SAS to Snowflake Conversion

Entry point for validating converted SQL that already exists (a finished conversion, or SQL
from another session). The workflow is the conversion skill's own validation pipeline -- there
is one, so a stand-alone validation and an in-conversion validation behave identically.

## Inputs

| Input | Required | Notes |
|---|---|---|
| Converted `.sql` directory (`<out>`) | yes | the files are never edited except by the repair loop |
| Original SAS source (`<src>`) | yes | needed for SAS anchors, the fidelity check and any trace |
| `tables.json` | no | from `/assess-sas-migration`; if absent, run the assessment on `<src>` first -- it seeds the registry |
| Answers to the Step 1 validation questions | yes | depth (T1/T2/T3), table locations, DDL, test data, SAS outputs, full data |

## Workflow

1. Ask the Step 1 validation questions (`../workflows/validation-pipeline.md` §Step 1 inputs) in
   one prompt, plus target and validation schema.
2. Run `../workflows/validation-pipeline.md` from Gate 0 to the deepest approved tier.
3. Generate the report per `../workflows/step-10-report.md` (Section 3 and the artifact list are
   what a stand-alone validation adds to an existing conversion report).

## Rules

- The SAS is the specification. A mismatch is fixed in the SQL (`OWN_DEFECT`), the test data
  (`TEST_DATA_GAP`) or the baseline (`BASELINE_CORRECTED`) -- each by its own route, recorded in
  `validation_results.json`; never by editing two of them in one attempt.
- Nothing outside the validation and target schemas is created, changed or dropped.
