#!/usr/bin/env python3
import csv
import sys

def validate_partitions(matrix_csv):
    errors = []
    with open(matrix_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            source = int(row['source_partition'])
            target = int(row['target_partition'])
            edge_count = int(row['dependency_count'])
            
            if target >= source:
                errors.append(f"ERROR: Partition {source} depends on later/same partition {target} ({edge_count} edges)")
    
    if errors:
        print(f"Found {len(errors)} validation errors:")
        for err in errors[:20]:
            print(f"  {err}")
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors")
        return False
    else:
        print("✓ All partitions only depend on earlier partitions")
        return True

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: validate_partitions.py <partition_dependency_matrix.csv>", file=sys.stderr)
        sys.exit(2)

    success = validate_partitions(sys.argv[1])
    sys.exit(0 if success else 1)