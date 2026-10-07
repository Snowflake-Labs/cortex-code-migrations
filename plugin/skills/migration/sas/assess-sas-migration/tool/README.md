# SAS Migration Assessment Tool

Standalone CLI for assessing SAS-to-Snowflake migration complexity and volume.

## Usage

```bash
cd assess-sas-migration/tool

# Analyze a directory of .sas files
python assess_sas.py /path/to/sas/files --output ./results

# Analyze a single file
python assess_sas.py /path/to/script.sas --output ./results

# Use custom thresholds
python assess_sas.py /path/to/sas/ --config custom_config.json

# JSON only
python assess_sas.py /path/to/sas/ --format json --output ./results

# HTML report only
python assess_sas.py /path/to/sas/ --format html --output ./results

# SAS Enterprise Guide projects (alone, in a directory, or mixed with .sas)
python assess_sas.py /path/to/project.egp --output ./results

# Only unpack .egp files (no assessment)
python assess_sas.py /path/to/egps/ --output ./results --egp-extract-only
```

## Outputs

| File | Description |
|------|-------------|
| `assessment.json` | Machine-readable per-file metrics, portfolio summary, dependency graph |
| `assessment_report.md` | Human-readable report with tables and distribution analysis |
| `assessment_report.html` | Self-contained, SCAI-themed HTML report (KPIs, tier mix, complexity/volume charts, dependency DAG, per-file detail). Open in a browser. |
| `dependency_dag.mmd` | Mermaid diagram showing cross-file data flow dependencies |
| `tables.json` | Input/output tables (shared librefs only) for conversion to fill with columns; managed by `tables.py` |
| `egp_extracted/<project>/` | Only for `.egp` input: one `.sas` per code task (`<project>__<flow><position>_<TaskID>.sas`, in run order), `egp_manifest.json`, `egp_flow.mmd` |

`--format` accepts `json`, `md`, `html`, or `all` (default). The HTML report renders fully offline except the dependency diagram, which uses the Mermaid CDN when opened in a browser (an edges table is the offline fallback).

## Enterprise Guide (`.egp`) extraction

`sas_analyzer/egp_extractor.py` unpacks each `.egp` (a ZIP) and reads its `project.xml`. It
uses structural rules rather than a list of task types, so it works across EG versions:

- **Code:** any block with `TaskCode`, attached to its task via the sibling `Parent`;
  user-written `BeginUserCode` / `EndUserCode` are kept, EG's `*AppCode` wrappers dropped.
  `code.sas` entries in the ZIP are only a fallback for live tasks without `TaskCode`; entries
  for tasks no longer in `project.xml` are reported as stale and never assessed.
- **Flows:** every item with a `<PFD>` child (any `Type`), edges from
  `Process/Dependencies/DepID` plus `LinkFrom`/`LinkTo` items; ordered topologically (XML
  order breaks ties; cycles fall back to XML order with a warning).
- **Nodes:** data/file shortcuts resolved via `DataList` / `ExternalFileList`; tasks without
  code (exports, wizards) kept as manual-review nodes with any output-path fields.
- **Graph:** all files from one project share one `WORK` session; flow edges are merged into
  the dependency graph as `via: egp_flow`, and `assessment.json` → `egp_projects.flow_vs_inferred`
  compares them with dataset-inferred edges.
- **Safety:** DOCTYPE/ENTITY rejected, archive size capped, output names sanitised; one bad
  `.egp` is reported without stopping the run.
- **Other outputs:** librefs the EGP's datasets use are labelled *Defined on SAS server
  (Enterprise Guide)* in the source inventory; the provenance header is not counted in `lines`.

Across all input: SAS name literals (`lib.'my table'n`) are tracked as datasets
(canonical form `LIB.'MY TABLE'N`); every `%include` is listed in
`portfolio_summary.external_includes` with `in_scope`; output folders of earlier runs
inside the source tree are never re-read as source.

Tests use synthetic archives only: `python3 -m unittest tests.test_egp_extractor`.

## Threshold Tuning

Edit `config.json` to adjust classification boundaries:

```json
{
  "complexity_thresholds": {
    "low_max": 50,
    "medium_max": 150
  },
  "volume_thresholds": {
    "low_max": 250,
    "medium_max": 1000
  }
}
```

**Target distribution** (empirically validated against 1400+ real SAS files):
- ~50% LOW, ~35% MEDIUM, ~15% HIGH

## Dependencies

Python 3.8+ with standard library only. No pip install required.

## How It Works

1. **Parser** — Extracts typed blocks (DATA steps, PROC SQL, macros, etc.) from SAS source
2. **Scorer** — 3-component complexity score: base (block weights) + feature (tier-specific patterns) + structure (macros/nesting). Produces the **complexity** axis (LOW/MEDIUM/HIGH), used for sizing — independent of the translation tier.
3. **Classifier** — SQL-first **translation tier** assignment aligned with the conversion skill (Tier 1 SQL → Tier 2 SP → Tier 3 PySpark). A file's tier follows the strict "any-block" rule: any Tier-3 block → Tier 3, else any Tier-2 block → Tier 2, else Tier 1. No proportion thresholds.
4. **Dependency Tracker** — Builds cross-file DAG from dataset CREATES/READS (plus EG process-flow edges for `.egp` input)
5. **Reporter** — Generates JSON, Markdown, and Mermaid outputs

**Block counting & tiering are governed by the shared canonical spec**
`../references/block-tiering-spec.md`: macros are flattened (each inner DATA/PROC step counts as
a block), DI Studio / DataFlow boilerplate is excluded from counts and tiering, and all reported
counts (portfolio total, per-file, per-tier) are computed over the same block set so they
reconcile. This is the same logic the `convert-sas-to-snowflake` skill applies, so assessment and
conversion agree on block counts and tiers.
