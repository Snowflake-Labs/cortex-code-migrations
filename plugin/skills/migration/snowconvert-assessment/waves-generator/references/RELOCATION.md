# Object Relocation Reference

After generating waves, you may need to relocate specific objects to different waves based on business requirements. The `relocate_object.py` script handles this while maintaining dependency integrity.

## Basic Usage

```bash
# Show object info and dependencies
python3 scripts/relocate_object.py info <analysis_dir> --object "dbo.MyTable"

# Relocate to specific wave
python3 scripts/relocate_object.py relocate <analysis_dir> --object "dbo.MyProc" --to-wave 3

# Relocate to beginning (wave 1)
python3 scripts/relocate_object.py relocate <analysis_dir> --object "dbo.MyProc" --to-beginning

# Relocate to end (last wave)
python3 scripts/relocate_object.py relocate <analysis_dir> --object "dbo.MyProc" --to-end

# Preview changes without applying (dry-run)
python3 scripts/relocate_object.py relocate <analysis_dir> --object "dbo.MyProc" --to-wave 2 --dry-run

# Search for objects by name
python3 scripts/relocate_object.py search <analysis_dir> --term "Customer"

# Validate current wave assignments
python3 scripts/relocate_object.py validate <analysis_dir>
```

## Batch Relocation

Relocate multiple objects in a single operation:

```bash
# Inline arguments
python3 scripts/relocate_object.py batch-relocate <analysis_dir> \
  --move "dbo.Proc1" --to-wave 3 \
  --move "dbo.Proc2" --to-wave 5 \
  --move "dbo.Table1" --to-wave 2

# From CSV file (columns: object,target_wave)
python3 scripts/relocate_object.py batch-relocate <analysis_dir> --from-file relocations.csv

# From JSON file
python3 scripts/relocate_object.py batch-relocate <analysis_dir> --from-file relocations.json

# Preview batch changes
python3 scripts/relocate_object.py batch-relocate <analysis_dir> --from-file relocations.csv --dry-run
```

**CSV file format:**
```csv
object,target_wave
dbo.MyProc,3
dbo.MyTable,5
```

**JSON file format:**
```json
[
  {"object": "dbo.MyProc", "target_wave": 3},
  {"object": "dbo.MyTable", "target_wave": 5}
]
```

## How Relocation Works

**Moving to an EARLIER wave:**
1. All transitive dependencies of the object are analyzed
2. Dependencies in later waves are automatically moved to the target wave (cascade)
3. Validation ensures no dependency violations after relocation

**Moving to a LATER wave:**
1. All transitive dependents of the object are analyzed
2. Dependents in earlier waves are automatically moved to the target wave (cascade)
3. Validation ensures no dependency violations after relocation

**Batch Relocation with Conflict Resolution:**
- When multiple objects are relocated, the system consolidates all moves
- If an explicit request conflicts with dependency constraints, the target wave is adjusted
- Warning messages explain adjustments (e.g., "Adjusted: 'ObjectA' requested for wave 2, moved to wave 1 instead (required by 'ObjectB')")
- All wave assignments respect the dependency graph

## Command-Line Arguments

| Argument | Description |
|----------|-------------|
| `--object`, `-o` | Object name to relocate (required for single relocation) |
| `--to-wave`, `-w` | Target wave number |
| `--to-beginning` | Move to wave 1 |
| `--to-end` | Move to last wave |
| `--move`, `-m` | Object name for batch relocation (repeatable) |
| `--from-file`, `-f` | CSV or JSON file with relocations |
| `--dry-run` | Preview changes without applying |
| `--no-cascade` | Fail if dependencies/dependents need to move |
| `--no-backup` | Skip creating backup before changes |
| `--reports-dir`, `-r` | Path to SnowConvert Reports directory (for precise dependency tracking) |

## Examples

### Example 1: Move Critical Table to Wave 1

```bash
python3 scripts/relocate_object.py relocate \
  ./waves/dependency_analysis_20240115_120000 \
  --object "dbo.CustomerMaster" \
  --to-beginning
```

**Output:**
```
RELOCATION PLAN
======================================================================
Target Object: dbo.CustomerMaster
Target Wave: 1
Direction: EARLIER
Valid: YES

Objects to Move (3):
  From Wave 4:
    -> Wave 1: dbo.CustomerMaster (TABLE) [TARGET]
    -> Wave 1: dbo.AddressType (TABLE)
    -> Wave 1: dbo.Region (TABLE)

Affected Waves: [1, 4]
======================================================================
```

### Example 2: Batch Relocate Multiple Objects

```bash
python3 scripts/relocate_object.py batch-relocate \
  ./waves/dependency_analysis_20240115_120000 \
  --move "dbo.sp_ProcessOrders" --to-wave 3 \
  --move "dbo.sp_UpdateInventory" --to-wave 5 \
  --dry-run
```

**Output:**
```
BATCH RELOCATION PLAN
======================================================================
Requested Relocations: 2
  dbo.sp_ProcessOrders: wave 7 -> wave 3
  dbo.sp_UpdateInventory: wave 4 -> wave 5

Total Objects to Move: 5
  - Explicitly requested: 2
  - Cascade (dependencies/dependents): 3

Objects to Move (by original wave):
  From Wave 4:
    -> Wave 5: dbo.sp_UpdateInventory (PROCEDURE) [REQUESTED]
    -> Wave 5: dbo.fn_CalcTotal (FUNCTION) [CASCADE]
  From Wave 7:
    -> Wave 3: dbo.sp_ProcessOrders (PROCEDURE) [REQUESTED]
    -> Wave 3: dbo.vw_OrderSummary (VIEW) [CASCADE]
    -> Wave 3: dbo.OrderDetails (TABLE) [CASCADE]

Affected Waves: [3, 4, 5, 7]
======================================================================
```

### Example 3: Inspect Object Before Relocating

```bash
python3 scripts/relocate_object.py info \
  ./waves/dependency_analysis_20240115_120000 \
  --object "dbo.sp_ProcessOrders"
```

**Output:**
```
OBJECT INFORMATION
======================================================================
Name: dbo.sp_ProcessOrders
Current Wave: 5
Category: PROCEDURE

Dependencies:
  Direct: 3
  Transitive (total): 12

Dependents (objects that depend on this):
  Direct: 2
  Transitive (total): 5

Relocation Constraints:
  Earliest possible wave: 3 (based on dependency in wave 3)
  Latest possible wave: 7 (based on dependent in wave 7)
======================================================================
```

## Backup and Recovery

By default, `relocate_object.py` creates a backup before making changes:
- Backup directory: `<analysis_dir>_backup_<timestamp>`
- Relocation log: `<analysis_dir>/relocation_log_<timestamp>.json` (single relocation)
- Batch relocation log: `<analysis_dir>/batch_relocation_log_<timestamp>.json` (batch relocation)

To skip backup: `--no-backup`

## Validation After Relocation

Always validate after relocation:

```bash
python3 scripts/relocate_object.py validate ./waves/dependency_analysis_*
```
