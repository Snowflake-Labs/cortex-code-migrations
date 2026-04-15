# `snowconvert_reports` — Architecture

> Shared data access layer for SnowConvert assessment reports.
> All sub-skills import from here instead of re-implementing CSV/JSON parsing.

---

## Package Structure

```
scripts/snowconvert_reports/
├── __init__.py                      # Public API re-exports
├── models/
│   ├── issue.py                     # IssueRecord        ← Issues.csv
│   ├── element.py                   # Element            ← Elements.csv
│   ├── code_unit.py                 # TopLevelCodeUnit   ← TopLevelCodeUnits.csv
│   ├── object_reference.py          # ObjectReference    ← ObjectReferences.*.csv
│   ├── partition_member.py          # PartitionMember    ← PartitionMembership.csv
│   └── estimation.py                # IssueEstimationEntry, SeverityBaseline, ObjectEstimation
├── loaders/
│   ├── csv_reader.py                # read_csv_rows(), load_csv_as()
│   ├── elements_loader.py           # load_elements()
│   ├── issues_loader.py             # load_issues(filter_code=)
│   ├── code_units_loader.py         # load_code_units()
│   ├── object_references_loader.py  # load_object_references(), load_missing_references()
│   ├── partition_loader.py          # load_partition_membership()
│   ├── estimation_loader.py         # load_issues_estimation_json(), load_object_estimations()
│   └── graph_loader.py              # parse_graph_summary(), parse_cycles(), parse_excluded_edges()
├── services/
│   ├── issue_effort_service.py      # IssueEffortService (unified effort/severity lookup)
│   └── report_finder.py             # ReportFinder (glob-based file discovery)
└── data/
    └── issues_ref.json              # Bundled issue reference (for offline/ETL use)
```

---

## Layered Architecture

```
 ╔═══════════════════════════════════════════════════════════════════╗
 ║                    SnowConvert Assessment Reports                ║
 ║                    (CSV / JSON / TXT files on disk)              ║
 ╚════════════════════════════════╤══════════════════════════════════╝
                                  │
                                  ▼
 ┌────────────────────────────────────────────────────────────────────┐
 │                                                                    │
 │                    snowconvert_reports (shared lib)                 │
 │                                                                    │
 │   ┌──────────┐      ┌──────────┐      ┌──────────────────────┐   │
 │   │  models/  │◄─────│ loaders/ │      │      services/       │   │
 │   │          │      │          │      │                      │   │
 │   │ frozen   │      │ csv_     │      │ IssueEffortService   │   │
 │   │ data-    │      │  reader  │      │   .from_json_file()  │   │
 │   │ classes  │      │   ▲      │      │   .from_bundled()    │   │
 │   │          │      │   │      │      │   .get_effort_hours()│   │
 │   │ 1 model  │      │ typed    │      │                      │   │
 │   │ per CSV  │      │ loaders  │      │ ReportFinder         │   │
 │   │ file     │      │ (1 per   │      │   .find(base_name)   │   │
 │   │ type     │      │  report) │      │   .find_issues()     │   │
 │   └──────────┘      └──────────┘      └──────────────────────┘   │
 │                                                                    │
 └─────────────────────────────┬──────────────────────────────────────┘
                               │
          ┌────────────────────┼────────────────────┬─────────────────┐
          │                    │                    │                 │
          ▼                    ▼                    ▼                 ▼
 ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐
 │     ETL     │   │    Waves     │   │  SQL Dynamic │   │  Exclusion   │
 │  Assessment │   │  Generator   │   │   Analyzer   │   │  Detection   │
 │             │   │              │   │              │   │              │
 │ SSIS/DTSX   │   │ Dependency   │   │ SSC-EWI-0030 │   │ Naming       │
 │ package     │   │ graph,       │   │ pattern      │   │ patterns,    │
 │ analysis    │   │ wave algo,   │   │ detection &  │   │ duplicate    │
 │             │   │ HTML reports │   │ tracking     │   │ detection    │
 └─────────────┘   └──────────────┘   └──────────────┘   └──────────────┘
```

---

## Import Dependency Graph

Shows exactly what each sub-skill imports from the shared library.

```
snowconvert_reports
│
├──► etl-assessment
│    ├── ElementRepository      → load_elements, Element
│    ├── IssueRepository        → read_csv_rows
│    ├── IssueLookupService     → IssueEffortService
│    └── IssueLoader            → IssueEffortService
│
├──► waves-generator
│    └── load_data_html_report  → load_issues_estimation_json
│                                  load_code_units
│                                  load_partition_membership
│                                  load_object_estimations
│                                  load_object_references
│                                  parse_graph_summary
│                                  parse_cycles
│                                  parse_excluded_edges
│                                  ReportFinder
│
├──► analyzing-sql-dynamic-patterns
│    └── sql_dynamic_analyzer   → IssueRecord
│                                  TopLevelCodeUnit
│                                  load_issues
│                                  load_code_units
│
└──► object_exclusion_detection
     └── analyze_naming_conv.   → ReportFinder
                                   load_object_references
                                   read_csv_rows
```

---

## Data Flow: From Raw Reports to Sub-Skill Domain Models

```
                         ┌───────────────────────┐
                         │  SnowConvert Reports   │
                         │  ─────────────────     │
                         │  Elements.csv          │
                         │  Issues.csv            │
                         │  TopLevelCodeUnits.csv │
                         │  ObjectReferences.csv  │
                         │  PartitionMembership   │
                         │  IssuesEstimation.json │
                         │  graph_summary.txt     │
                         │  cycles.txt            │
                         └───────────┬───────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   csv_reader.py      │
                          │   ───────────────    │
                          │   read_csv_rows()    │
                          │   • utf-8-sig → utf-8│
                          │     → latin-1        │
                          │   • strips all values│
                          │   • yields dict rows │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   Typed Loaders      │
                          │   ─────────────      │
                          │   load_csv_as(       │
                          │     path, factory)   │
                          │                      │
                          │   factory = Model    │
                          │     .from_csv_row    │
                          └──────────┬───────────┘
                                     │
                          ┌──────────▼──────────┐
                          │   Frozen Dataclasses │
                          │   ─────────────────  │
                          │   list[Element]      │
                          │   list[IssueRecord]  │
                          │   list[TopLevel...]  │
                          │   list[ObjectRef]    │
                          └──────────┬───────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
            ▼                        ▼                        ▼
  ┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
  │   ETL Domain    │    │  Waves Adapter  │    │ SQL-Dynamic /    │
  │   ───────────   │    │  ────────────   │    │ Exclusion        │
  │                 │    │                 │    │ ─────────        │
  │ Element         │    │ dataclass → dict│    │                  │
  │   ↓ map         │    │ (preserves old  │    │ Use IssueRecord  │
  │ Component       │    │  return types)  │    │ and TopLevel     │
  │   + issues[]    │    │                 │    │ CodeUnit directly │
  │   + sql_tasks   │    │ ▼               │    │                  │
  │                 │    │ analyze_deps.py │    │ Feed into domain │
  │ PackageAnalysis │    │ (untouched      │    │ analysis logic   │
  │ DataFlow        │    │  algorithms)    │    │ (untouched)      │
  └─────────────────┘    └─────────────────┘    └──────────────────┘
```

---

## Adapter Pattern in Waves Generator

The waves generator was the largest consumer. Its internal callers expect `dict[str, dict]`, not dataclasses. The adapter layer in `load_data_html_report.py` bridges this:

```
    Shared Library                    Adapter (load_data_html_report.py)           Consumers
    ──────────────                    ──────────────────────────────────           ─────────

    load_code_units(csv)              load_toplevel_code_units(csv)
    → list[TopLevelCodeUnit]    ──►   → dict[code_unit_id, {                ──►  analyze_deps.py
                                          'category': ...,                       generate_html.py
                                          'ewi_count': ...,
                                        }]

    load_partition_membership(csv)    load_partition_membership(csv)
    → list[PartitionMember]     ──►   → dict[object_name, {                ──►  generate_html.py
                                          'partition': int,
                                          'is_root': bool,
                                        }]

    load_issues_estimation_json(json) load_issues_estimation(json)
    → (dict[str, Entry],        ──►   → (dict[str, {                       ──►  generate_html.py
       dict[str, Baseline])              'severity': ...,                        estimate_hours()
                                          'manual_effort': ...,
                                        }],
                                        dict[str, float])
```

---

## IssueEffortService: Two Initialization Paths

```
                    ┌─────────────────────────────────┐
                    │       IssueEffortService          │
                    │                                   │
                    │  .get_effort_hours(code) → float  │
                    │  .get_severity(code)     → str    │
                    │  .get_effort_and_severity(code)   │
                    │                                   │
                    │  EWI codes: minutes / 60 → hours  │
                    │  Other codes: effort as-is        │
                    │  Negative: clamp to 0.0           │
                    └──────────┬──────────┬─────────────┘
                               │          │
              ┌────────────────┘          └────────────────┐
              ▼                                            ▼
   .from_bundled_reference()                   .from_json_file(path)
   ┌────────────────────────┐                  ┌────────────────────────┐
   │ Loads issues_ref.json  │                  │ Loads runtime          │
   │ shipped with library   │                  │ IssuesEstimation.json  │
   │                        │                  │ from reports directory  │
   │ Used by:               │                  │                        │
   │   • ETL Assessment     │                  │ Used by:               │
   │     (no reports dir    │                  │   • Waves Generator    │
   │      at analysis time) │                  │     (has reports dir)  │
   └────────────────────────┘                  └────────────────────────┘
```

---

## Composition in ETL: Element → Component

ETL doesn't subclass `Element`. It composes a richer domain model:

```
    Shared: Element (frozen)              ETL: Component (mutable)
    ────────────────────────              ────────────────────────

    full_name          ─────────────►     full_name
    file_name          ─────────────►     file_name
    technology         ─────────────►     technology
    category           ─────────────►     category
    subtype            ─────────────►     subtype
    status             ─────────────►     status
    entry_kind         ─────────────►     entry_kind
    additional_info    ─────────────►     additional_info
                                          issues: list[Issue]        ← domain
                                          sql_task_details: dict     ← domain
                                          ewi_count (property)       ← derived
                                          unique_ewis (property)     ← derived
                                          to_dict()                  ← serialization
```

---

## What Lives Where

| Concern | Location | Rationale |
|---|---|---|
| CSV parsing, encoding | `snowconvert_reports/loaders/csv_reader.py` | Single implementation for all sub-skills |
| Report file discovery | `snowconvert_reports/services/report_finder.py` | Consistent glob patterns |
| Data models (raw rows) | `snowconvert_reports/models/` | One frozen dataclass per CSV file type |
| Effort calculation | `snowconvert_reports/services/issue_effort_service.py` | Unified EWI/non-EWI logic |
| SSIS package analysis | `etl-assessment/` | Domain-specific (DTSX parsing, DAGs) |
| Wave generation algo | `waves-generator/analyze_dependencies.py` | Domain-specific (topo sort, SCC, partitioning) |
| Dynamic SQL detection | `analyzing-sql-dynamic-patterns/` | Domain-specific (pattern matching, tracking) |
| Naming pattern rules | `object_exclusion_detection/` | Domain-specific (regex patterns, scoring) |
| HTML report rendering | `scripts/generate_multi_report.py` | Presentation layer (Vue.js, Chart.js) |

---

## Test Coverage

```
tests/assessment/snowconvert_reports/
├── conftest.py                  # fixtures_dir, sys.path setup
├── fixtures/                    # Minimal CSV/JSON/TXT fixtures
│   ├── Elements.NA.csv
│   ├── Issues.NA.csv
│   ├── TopLevelCodeUnits.NA.csv
│   ├── ObjectReferences.NA.csv
│   ├── PartitionMembership.NA.csv
│   ├── IssuesEstimation.NA.json
│   ├── TopLevelObjectsEstimation.NA.csv
│   ├── graph_summary.txt
│   └── cycles.txt
├── test_models.py               # 17 tests — all dataclass parsing
├── test_loaders.py              # 14 tests — all loaders + csv_reader
└── test_services.py             # 10 tests — effort service + finder
                                   ──────
                                   45 tests total (0.08s)
```
