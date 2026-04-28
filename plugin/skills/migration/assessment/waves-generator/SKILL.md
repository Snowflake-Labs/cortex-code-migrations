---
name: sql-migration-waves-generator
description: Analyze SQL object dependencies and create deployment waves/partitions for database migrations. Use when working with SQL migration planning, SnowConvert outputs, or deployment wave creation.
parent_skill: assessment
license: Proprietary. See License-Skills for complete terms
---

# Migration Waves/Partition Generator

## Overview

This skill analyzes SQL object dependencies from SnowConvert migration outputs and creates deployment waves (partitions) that respect dependency ordering. Ensures all dependencies are met.

**Use this skill when:**
- Planning SQL database and/or ETL migration deployment sequences
- Creating deployment waves that respect object dependencies
- Optimizing migration batch sizes for deployment

## Inputs (auto-detected by parent)

The parent `assessment` skill resolves all input paths from `project_dir`. Do **not** prompt the user for any of these — they are passed in from the parent.

| Input | Source under `project_dir` |
|-------|----------------------------|
| Registry directory (preferred) | `output/registry/` (or wherever the registry is found) |
| `ObjectReferences.*.csv` (CSV fallback) | `reports/SnowConvert/` |
| `TopLevelCodeUnits.*.csv` (CSV fallback) | `reports/SnowConvert/` |
| `ETL.Elements.*.csv` (optional, SSIS) | `reports/SnowConvert/` |

**Mode selection:**
- If a `registry/` directory with JSON entries is present, run `analyze_dependencies_registry.py`.
- Otherwise, run `analyze_dependencies.py` with the CSV inputs.
- The tool automatically searches for `ETL.Elements.NA.csv` or `ETL.Elements.<TIMESTAMP>.csv` in the reports directory. Only Package entries with `.dtsx` extension are included as top-level ETL objects.

## Required User Interactions

**These steps are mandatory. Do not skip them.**

### Before Generating Waves

You MUST confirm the following with the user before running the dependency analysis script for the selected input mode:

1. **Partition size** — The default is 40-80 objects per wave. Ask:
   > "The default wave size is 40-80 objects per wave. Would you like to keep these defaults, or set custom min/max limits?"

2. **Object prioritization** — Some objects may need to be deployed first. Ask:
   > "Would you like to prioritize specific objects to appear in the earliest waves? You can use name patterns, for example `"*Payroll*"` to prioritize all Payroll-related objects, or `"dbo.Customer"` for an exact match."

3. **Wave ordering strategy** — Explain the default and offer the alternative. Ask:
   > "By default, waves are grouped by category: TABLEs are deployed first, then VIEWs, then FUNCTIONs/PROCEDUREs, and ETL packages last. This ensures schema foundations exist before the code that depends on them. Alternatively, you can use a pure dependency-based approach that mixes all object types by dependency level. Would you like to keep the default category-based ordering, or switch to dependency-based?"
   >
   > If user chooses dependency-based, add `--no-category-waves` to the command.

### After Generating Waves

You MUST offer post-generation relocation:

4. **Object relocation** — After the report is generated, ask:
   > "The waves have been generated. Would you like to relocate any objects to different waves? Relocation lets you move specific objects earlier or later in the deployment sequence (for example, to align with a business rollout schedule). Dependencies are automatically cascaded to maintain integrity."
   >
   > If yes, use `relocate_object.py`. See [references/RELOCATION.md](references/RELOCATION.md) for details.

5. **Return to parent workflow** — After relocation (or if the user declined):
   > "Wave generation is complete. Would you like to generate the HTML report now?"
   >
   > If yes, return to the parent skill (`../SKILL.md`) and follow its **Report Generation** section using `generate_multi_report.py` ONLY.
   >
   > If the assessment includes other sub-skills (Object Exclusion, Dynamic SQL, SSIS), continue with the parent workflow sequence.

---

## Quick Start

This skill has two explicit execution modes:

- **Registry mode (preferred):** if a `registry/` directory is available, run `analyze_dependencies_registry.py` and `find_dependencies_by_object_registry.py`. Do **not** run the CSV scripts in this mode.
- **CSV fallback mode:** only when registry is not available, run `analyze_dependencies.py` and `find_dependencies_by_object.py`.

### Basic Usage (CSV fallback)

Use this approach when there is not registry folder.
```bash
python3 scripts/analyze_dependencies.py \
  --references <ObjectReferences.csv> \
  --objects <TopLevelCodeUnits.csv> \
  --output <output_directory>
```

### Basic Usage (Registry preferred - explicit paths)

```bash
# Registry-first mode. --reports-dir is optional here (ETL.Elements CSV supplement).
python3 scripts/analyze_dependencies_registry.py \
  --registry-dir <path/to/output/registry> \
  --reports-dir <path/to/output/reports/SnowConvert> \
  --output <output_directory>
```

> **Explicit paths required**: You must specify the exact path to the registry directory. If registry exists, it is the authoritative input for waves generation and the CSV workflow must not run.

> **Important — reports dir still needed for HTML report**: While `--reports-dir` is optional for the *waves analysis* script itself, the downstream `generate_multi_report.py` always requires `--snowconvert-reports-dir` even in registry mode. The CSV reports contain data the registry does not provide (source dialect, estimation reports, EWI aggregations). Always pass both `--registry-dir` and `--snowconvert-reports-dir` when generating the HTML report.

### With Custom Partition Sizes

Registry mode (preferred):
```bash
python3 scripts/analyze_dependencies_registry.py \
  --registry-dir <path/to/output/registry> \
  --reports-dir <path/to/output/reports/SnowConvert> \
  --output <output_directory> \
  --min-size 15 \
  --max-size 50
```

CSV fallback mode:
```bash
python3 scripts/analyze_dependencies.py \
  --references <ObjectReferences.csv> \
  --objects <TopLevelCodeUnits.csv> \
  --output <output_directory> \
  --min-size 15 \
  --max-size 50
```

### With Object Prioritization

Prioritize specific objects or patterns for earlier deployment in Wave 1:

Registry mode (preferred):
```bash
python3 scripts/analyze_dependencies_registry.py \
  --registry-dir <path/to/output/registry> \
  --reports-dir <path/to/output/reports/SnowConvert> \
  --output <output_directory> \
  --prioritize "*ComputerAsset*" \
  --prioritize "*Worker*"
```

CSV fallback mode:
```bash
python3 scripts/analyze_dependencies.py \
  --references <ObjectReferences.csv> \
  --objects <TopLevelCodeUnits.csv> \
  --output <output_directory> \
  --prioritize "*ComputerAsset*" \
  --prioritize "*Worker*"
```

**Supports wildcards:**
- `--prioritize "PKG_*"` - All objects starting with PKG_
- `--prioritize "*OrthoContract*"` - All objects containing OrthoContract
- `--prioritize "[SCHEMA].[TABLE]"` - Exact object name
- `--prioritize-file priority_list.txt` - Load patterns from file (one per line)

### Category-Based Wave Ordering (Default)

By default, waves are grouped by object category in deployment order: TABLEs first, then VIEWs, then FUNCTIONs, then PROCEDUREs, and finally ETL packages. This ensures schema foundations are deployed before the procedural code and ETL pipelines that depend on them.

To disable this and mix all object types purely by dependency level:

Use these parameters (any mode):
- Input mode (choose one):
  - Registry mode: `python3 scripts/analyze_dependencies_registry.py --registry-dir <path/to/output/registry> [--reports-dir <path/to/output/reports/SnowConvert>]`
  - CSV fallback mode: `--references <ObjectReferences.csv>` and `--objects <TopLevelCodeUnits.csv>`
- Common output parameter: `--output <output_directory>`
- Disable category grouping: `--no-category-waves`

**Default behavior (category waves enabled):**
- TABLEs are deployed first in their own waves, respecting inter-table dependencies
- VIEWs follow in subsequent waves (their TABLE dependencies are already deployed)
- FUNCTIONs come next
- Objects with cross-category dependencies (e.g. a TABLE with a computed column referencing a FUNCTION) are placed immediately after their dependencies via a convergence loop, rather than being deferred to later mixed waves
- PROCEDUREs and ETL packages are placed in later waves with standard size constraints
- No min/max size constraints applied to TABLE/VIEW/FUNCTION category waves

## Output Files

The tool generates a timestamped directory with multiple analysis files:

### object_dependencies.csv
Per-object dependency metrics including direct, transitive, total dependencies and dependents.

### deployment_partitions.txt
Human-readable deployment wave details with:
- Partition size and metadata
- Root nodes (no dependencies) and leaf nodes (no dependents)
- Internal vs external dependencies
- Object types breakdown
- Object listing with ROOT/LEAF markers

### partition_dependency_matrix.txt / .csv
Inter-partition dependency counts showing which partitions depend on which earlier partitions.

### partition_membership.csv
Mapping of each object to its assigned partition with root/leaf flags.

### graph_summary.txt
Overall graph statistics including:
- Total nodes and edges
- Weakly connected components (separate forests)
- Cycle detection
- Component size distribution

### cycles.txt
Details of any circular dependencies detected.

### excluded_edges_analysis.txt
Analysis of edges excluded from partitioning (self-references, undefined objects, temp tables).

### top_dependencies.txt
Objects with the most dependencies and dependents.

### scc_priority_order_summary.txt
Priority tier distribution showing:
- Count of objects in each tier (User-Prioritized, Regular, ETL)
- Top 50 prioritized objects with their metrics
- Useful for validating that prioritization worked as intended

### scc_priority_order.csv
Detailed CSV with all objects and their priority tier assignments for analysis.

## Command-Line Arguments

| Argument | Short | Required | Default | Description |
|----------|-------|----------|---------|-------------|
| `--reports-dir` | - | No | - | Optional SnowConvert reports directory used only as supplement in registry mode (currently ETL.Elements CSV). |
| `--registry-dir` | - | No* | - | Path to registry directory. When provided, use `analyze_dependencies_registry.py` instead of the CSV script. |
| `--references` | `-r` | No* | - | Path to ObjectReferences CSV file for `analyze_dependencies.py` fallback mode only. |
| `--objects` | `-o` | No* | - | Path to TopLevelCodeUnits CSV file for `analyze_dependencies.py` fallback mode only. |
| `--output` | `-d` | Yes | - | Output directory for results |
| `--min-size` | - | No | 40 | Minimum partition size |
| `--max-size` | - | No | 80 | Maximum partition size |
| `--prioritize` | - | No | - | Object name/pattern to prioritize (repeatable) |
| `--prioritize-file` | - | No | - | File with patterns to prioritize (one per line) |
| `--no-category-waves` | - | No | False | Disable category-based wave ordering (TABLE→VIEW→FUNCTION first). Mixes all types by dependency level. |
| `--help` | `-h` | No | - | Show help message |

**\*Note**:
- Registry mode: provide `--registry-dir` to `analyze_dependencies_registry.py`
- CSV fallback mode: provide both `--references` and `--objects` to `analyze_dependencies.py`
- Do not run both analyze workflows for the same assessment input

## Algorithm Details

### Partition Creation Process

1. **Build Dependency Graph**
   - Registry mode: load deployable in-scope objects from registry JSON and build directed graph from `dependencies.dependsOn`
   - CSV mode: load CREATE statements only from TopLevelCodeUnits and build directed graph from ObjectReferences
   - Exclude self-references (object depending on itself)
   - Track undefined nodes separately

2. **Category-Based Wave Ordering (Default)**
   - TABLEs are placed in the earliest waves, then VIEWs, then FUNCTIONs
   - Each category respects inter-object dependencies within it
   - A convergence loop repeats the category pass so cross-category dependencies (e.g. TABLE→FUNCTION) are placed as early as possible
   - Remaining objects (PROCEDURE, ETL) processed in subsequent steps
   - Disable with `--no-category-waves` to mix all types by dependency level

3. **Priority Classification**
   - **Tier 0 (User-Prioritized):** Objects matching `--prioritize` patterns (earliest)
   - **Tier 1 (Regular):** DDL/DML foundations (TABLE, VIEW, PROCEDURE, FUNCTION)
   - **Tier 2 (ETL):** SSIS packages and ETL objects (latest — they consume the foundations)

4. **Initial Partitioning**
   - Process prioritized objects first (Tier 0) with their transitive dependencies
   - Start with root nodes (objects with no dependencies)
   - Iteratively add nodes whose dependencies are all satisfied
   - Use priority tiers for ordering within available objects
   - Create partitions of min_size to max_size objects
   - Handle cycles by selecting minimum unsatisfied dependencies

5. **Partition Merging**
   - Identify partitions smaller than min_size (excluding category waves)
   - Try to merge with adjacent partitions (prefer earlier)
   - Validate all dependencies remain satisfied
   - Ensure merged size doesn't exceed max_size
   - Renumber partitions sequentially

6. **Dependency Validation**
   - Each partition only depends on earlier partitions
   - Topological ordering preserved throughout
   - No forward dependencies allowed

### Filtering Rules

- **Self-references excluded**: Edges where caller equals referenced object
- **CREATE statements only**: Only objects with "CREATE X" pattern in CodeUnit
- **Undefined nodes tracked**: Edges to/from objects not in TopLevelCodeUnits
- **Temp tables excluded**: Dynamic temp tables (e.g., #TTableName) not tracked as formal objects

## Examples

### Example 1: Standard Migration Analysis

Use these parameters:
- Input mode (choose one):
  - Registry mode: `python3 scripts/analyze_dependencies_registry.py --registry-dir /path/to/output/registry --output ./migration-waves`
  - CSV fallback mode: `--references /path/to/ObjectReferences.20251105.102401.csv` and `--objects /path/to/TopLevelCodeUnits.20251105.102401.csv`
- Output: `--output ./migration-waves`

**Output**: Creates deployment waves of 40-80 objects each in `./migration-waves/dependency_analysis_<timestamp>/`

### Example 2: Prioritize Critical ETL Processes

Prioritize specific ETL processes for early deployment:

```bash
python3 scripts/analyze_dependencies.py \
  -r ./refs.csv \
  -o ./objects.csv \
  -d ./waves \
  --prioritize "*ComputerAsset*" \
  --prioritize "*Worker*" \
  --prioritize "PKG_PAYROLL*"
```

**Output**: Places all ComputerAsset, Worker, and Payroll-related objects (with their dependencies) in Wave 1.

### Example 3: Smaller Batch Sizes

For environments with limited deployment windows:

```bash
python3 scripts/analyze_dependencies.py \
  -r ./refs.csv \
  -o ./objects.csv \
  -d ./waves \
  --min-size 10 \
  --max-size 30
```

**Output**: Creates more partitions with 10-30 objects each for incremental deployment.

### Example 4: Validate Partition Dependencies

After generating partitions, verify correctness:

```bash
python3 scripts/validate_partitions.py \
  ./waves/dependency_analysis_*/partition_dependency_matrix.csv
```

**Output**: Confirms all partitions only depend on earlier partitions.

## Supporting Scripts

### find_dependencies_by_object.py (NEW)

Analyzes TopLevelCodeUnits and ObjectReferences.csv to generate a JSON report of missing dependencies per object.

```bash
python3 scripts/find_dependencies_by_object.py \
  -r /path/to/Reports \
  -o missing_dependencies.json
```

**Input Requirements**:
- TopLevelCodeUnits.NA.csv (or TopLevelCodeUnits.<TIMESTAMP>.csv)
- ObjectReferences.*.csv (missing refs are filtered by Referenced_Element_Type='MISSING')

**Output**: JSON file mapping each object to its missing dependencies with details including referenced object name, relation type, line number, and source file.

### find_dependencies_by_object_registry.py

Analyzes registry JSON files to generate the same missing-dependencies JSON contract used by the CSV workflow.

```bash
python3 scripts/find_dependencies_by_object_registry.py \
  --registry-dir /path/to/output/registry \
  --output missing_dependencies.json
```

**Input Requirements**:
- Registry JSON directory from SnowConvert

**Output**: JSON file mapping each object to its missing dependencies with the same schema as `find_dependencies_by_object.py`.

### validate_partitions.py

Validates that all partition dependencies only go to earlier partitions.

```bash
python3 scripts/validate_partitions.py <partition_dependency_matrix.csv>
```

### find_nearest_neighbors.py

Finds objects with similar names using string similarity matching (for duplicate detection).

### show_dependencies.py

Quick lookup tool to show direct dependencies for a specific object (requires editing script to set target object).

### relocate_object.py

Relocates objects between deployment waves while maintaining dependency integrity. Supports both single object and batch relocation operations. See [Object Relocation](references/RELOCATION.md) section for detailed usage.

```bash
# Show object info
python3 scripts/relocate_object.py info <analysis_dir> --object "ObjectName"

# Relocate to specific wave
python3 scripts/relocate_object.py relocate <analysis_dir> --object "ObjectName" --to-wave 3

# Batch relocate multiple objects
python3 scripts/relocate_object.py batch-relocate <analysis_dir> \
  --move "dbo.Proc1" --to-wave 3 \
  --move "dbo.Proc2" --to-wave 5

# Batch relocate from CSV/JSON file
python3 scripts/relocate_object.py batch-relocate <analysis_dir> --from-file relocations.csv

# Validate assignments
python3 scripts/relocate_object.py validate <analysis_dir>
```

**Key Features**:
- Automatic cascade of dependencies when moving to earlier waves
- Automatic cascade of dependents when moving to later waves
- Batch relocation of multiple objects in a single operation
- Conflict resolution with automatic wave adjustment and warning messages
- Dry-run mode for previewing changes
- Automatic backup before applying changes
- Post-relocation validation

## Typical Workflow

1. **Run SnowConvert** to generate either a `registry/` directory or the legacy CSV reports

2. **Generate deployment waves**:
   ```bash
   # Registry mode (preferred, when registry exists)
   python3 scripts/analyze_dependencies_registry.py \
     --registry-dir /path/to/output/registry \
     --output ./waves

   # CSV fallback mode (only when registry does not exist)
   python3 scripts/analyze_dependencies.py \
     -r ObjectReferences.csv \
     -o TopLevelCodeUnits.csv \
     -d ./waves
   ```

3. **Generate missing dependencies report** (optional but recommended):
   ```bash
   # Registry mode
   python3 scripts/find_dependencies_by_object_registry.py \
     --registry-dir /path/to/output/registry \
     --output ./waves/dependency_analysis_*/missing_dependencies.json

   # CSV fallback mode
   python3 scripts/find_dependencies_by_object.py \
     -r /path/to/Reports \
     -o ./waves/dependency_analysis_*/missing_dependencies.json
   ```

4. **Review results**:
   - Check `graph_summary.txt` for overall statistics
   - Review `cycles.txt` for circular dependencies
   - Examine `deployment_partitions.txt` for wave details
   - Look at `excluded_edges_analysis.txt` for temp table references
   - Review `cycles.txt` for circular dependencies
   - Examine `deployment_partitions.txt` for wave details
   - Look at `excluded_edges_analysis.txt` for temp table references

4. **Validate correctness**:
   ```bash
   python3 scripts/validate_partitions.py \
     ./waves/dependency_analysis_*/partition_dependency_matrix.csv
   ```

5. **Relocate objects if needed** (optional):
   ```bash
   # Preview single object relocation
   python3 scripts/relocate_object.py relocate \
     ./waves/dependency_analysis_* \
     --object "dbo.CriticalTable" \
     --to-beginning --dry-run
   
   # Apply single object relocation
   python3 scripts/relocate_object.py relocate \
     ./waves/dependency_analysis_* \
     --object "dbo.CriticalTable" \
     --to-beginning
   
   # Batch relocate multiple objects
   python3 scripts/relocate_object.py batch-relocate \
     ./waves/dependency_analysis_* \
     --move "dbo.Proc1" --to-wave 3 \
     --move "dbo.Proc2" --to-wave 5 \
     --dry-run
   
   # Validate after relocation
   python3 scripts/relocate_object.py validate ./waves/dependency_analysis_*
   ```

6. **Import to deployment tool**:
   - Use `partition_membership.csv` for object-to-wave mapping
   - Use `partition_dependency_matrix.csv` for wave sequencing

## Key Concepts

### Root Nodes
Objects with no dependencies (no incoming edges). Safe to deploy first.

### Leaf Nodes
Objects with no dependents (no outgoing edges). Nothing else depends on them.

### Weakly Connected Components
Separate forests/trees in the dependency graph. Each can be deployed independently.

### Strongly Connected Components (SCCs)
Circular dependencies where objects depend on each other. Requires special handling.

### Progressive Disclosure
Partitions are numbered sequentially. Each partition depends only on partitions with lower numbers.

## Troubleshooting

### Many Single-Object Partitions

**Cause**: Graph has many disconnected components or complex dependency patterns.

**Solution**: Adjust min-size/max-size or accept that some objects are isolated.

### Circular Dependencies Detected

**Cause**: Objects have mutual dependencies (A depends on B, B depends on A).

**Solution**: Review `cycles.txt` to identify problem objects. May require manual intervention or schema refactoring.

### High Excluded Edge Count

**Cause**: Many temp tables or dynamic objects not tracked in TopLevelCodeUnits.

**Solution**: Normal for SQL Server migrations. Review `excluded_edges_analysis.txt` for patterns.

## Object Relocation

After generating waves, you may need to relocate specific objects to different waves based on business requirements. The `relocate_object.py` script handles this while maintaining dependency integrity.

**For detailed relocation instructions, see [references/RELOCATION.md](references/RELOCATION.md).**

Quick reference:
```bash
# Show object info
python3 scripts/relocate_object.py info <analysis_dir> --object "ObjectName"

# Relocate to specific wave
python3 scripts/relocate_object.py relocate <analysis_dir> --object "ObjectName" --to-wave 3

# Batch relocate multiple objects
python3 scripts/relocate_object.py batch-relocate <analysis_dir> \
  --move "dbo.Proc1" --to-wave 3 \
  --move "dbo.Proc2" --to-wave 5

# Validate assignments
python3 scripts/relocate_object.py validate <analysis_dir>
```

## Best Practices

1. **Start with default settings** (40-80 objects) and adjust based on deployment capacity
2. **Review graph structure** first to understand component count and cycles
3. **Validate partitions** before deployment planning
4. **Check excluded edges** to understand temp table usage patterns
5. **Use partition_membership.csv** as the authoritative source for wave assignments
6. **Deploy partitions sequentially** respecting the partition number order
7. **Use prioritization for critical ETL processes** - Prioritize business-critical objects (e.g., `--prioritize "*Payroll*" --prioritize "*Customer*"`) to ensure they deploy first
8. **Review scc_priority_order_summary.txt** after prioritization to verify expected objects are in Tier 0
9. **Combine prioritization with custom sizes** for fine-grained control over wave composition
10. **Use relocation sparingly** - Prefer prioritization during initial wave generation over post-hoc relocation
11. **Always use dry-run first** - Preview relocation changes before applying
12. **Validate after relocation** - Run validation to ensure dependency integrity
13. **Use batch relocation for multiple changes** - More efficient than sequential single relocations
14. **Keep relocation files versioned** - Store CSV/JSON relocation files in version control for audit trail