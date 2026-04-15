# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared data models for SQL dynamic analysis helpers."""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class DynamicSQLOccurrence:
    """Represents a SQL Dynamic occurrence to be analyzed."""

    id: int
    line: int
    status: str = "PENDING"
    category: List[str] = None
    complexity: str = ""
    notes: str = ""
    generated_sql: str = ""
    sql_classification: str = ""

    def __post_init__(self) -> None:
        if self.category is None:
            self.category = []

    @staticmethod
    def from_dict(data: Dict) -> "DynamicSQLOccurrence":
        """Create DynamicSQLOccurrence from dictionary."""
        category_data = data.get("category", [])
        if isinstance(category_data, str):
            category = [c.strip() for c in category_data.split("|") if c.strip()] if category_data else []
        else:
            category = category_data if category_data else []

        return DynamicSQLOccurrence(
            id=data.get("id", 0),
            line=data.get("line", 0),
            status=data.get("status", "PENDING"),
            category=category,
            complexity=data.get("complexity", ""),
            notes=data.get("notes", ""),
            generated_sql=data.get("generated_sql", ""),
            sql_classification=data.get("sql_classification", ""),
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON writing."""
        return {
            "id": self.id,
            "line": self.line,
            "status": self.status,
            "category": self.category,
            "complexity": self.complexity,
            "notes": self.notes,
            "generated_sql": self.generated_sql,
            "sql_classification": self.sql_classification,
        }


@dataclass
class CodeUnitData:
    """Represents a code unit with its metadata and occurrences."""

    code_unit_id: str
    procedure_name: str
    filename: str
    code_unit_start_line: int
    lines_of_code: int
    occurrences: List[DynamicSQLOccurrence]
    procedure: str = ""

    @staticmethod
    def from_dict(code_unit_id: str, data: Dict) -> "CodeUnitData":
        """Create CodeUnitData from dictionary."""
        metadata = data.get("metadata", {})
        occurrences_data = data.get("occurrences", [])

        return CodeUnitData(
            code_unit_id=code_unit_id,
            procedure_name=metadata.get("procedure_name", ""),
            filename=metadata.get("filename", ""),
            code_unit_start_line=metadata.get("code_unit_start_line", 0),
            lines_of_code=metadata.get("lines_of_code", 0),
            occurrences=[DynamicSQLOccurrence.from_dict(occ) for occ in occurrences_data],
            procedure=metadata.get("procedure", ""),
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON writing."""
        return {
            "metadata": {
                "procedure_name": self.procedure_name,
                "filename": self.filename,
                "code_unit_start_line": self.code_unit_start_line,
                "lines_of_code": self.lines_of_code,
                "procedure": self.procedure,
            },
            "occurrences": [occ.to_dict() for occ in self.occurrences],
        }


class AnalysisJSONManager:
    """Manager for updating analysis JSON records."""

    def __init__(self, json_file: str):
        self.json_file = Path(json_file)
        self.data: Dict = {}
        self.code_units: Dict[str, CodeUnitData] = {}

    def load(self) -> None:
        """Load existing analysis JSON."""
        if not self.json_file.exists():
            raise FileNotFoundError(f"Analysis JSON not found: {self.json_file}")

        with open(self.json_file, "r", encoding="utf-8") as f:
            self.data = json.load(f)

        code_units_data = self.data.get("code_units", {})
        for code_unit_id, cu_data in code_units_data.items():
            self.code_units[code_unit_id] = CodeUnitData.from_dict(code_unit_id, cu_data)

        total_occurrences = sum(len(cu.occurrences) for cu in self.code_units.values())
        print(f"Loaded {total_occurrences} records from {self.json_file}")
        print(f"Total code units: {len(self.code_units)}")

    def save(self) -> None:
        """Save analysis JSON."""
        code_units_data = {}
        for code_unit_id, cu in self.code_units.items():
            code_units_data[code_unit_id] = cu.to_dict()

        total_occurrences = sum(len(cu.occurrences) for cu in self.code_units.values())
        self.data["metadata"]["total_occurrences"] = total_occurrences
        self.data["metadata"]["total_code_units"] = len(self.code_units)
        self.data["code_units"] = code_units_data

        with open(self.json_file, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

        print(f"Saved {total_occurrences} records to {self.json_file}")

    def update_record(
        self,
        record_id: int,
        line: Optional[int] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        complexity: Optional[str] = None,
        notes: Optional[str] = None,
        generated_sql: Optional[str] = None,
        sql_classification: Optional[str] = None,
    ) -> bool:
        """Update a record by ID. Returns True if record was found and updated."""
        for cu in self.code_units.values():
            for occ in cu.occurrences:
                if occ.id == record_id:
                    if line is not None:
                        occ.line = line
                    if status is not None:
                        occ.status = status
                    if category is not None:
                        occ.category = [c.strip() for c in category.split("|") if c.strip()] if category else []
                    if complexity is not None:
                        occ.complexity = complexity
                    if notes is not None:
                        occ.notes = notes
                    if generated_sql is not None:
                        occ.generated_sql = generated_sql
                    if sql_classification is not None:
                        occ.sql_classification = sql_classification
                    return True
        return False

    def get_record(self, record_id: int) -> Optional[tuple[DynamicSQLOccurrence, CodeUnitData]]:
        """Get a record by ID. Returns (occurrence, code_unit) tuple."""
        for cu in self.code_units.values():
            for occ in cu.occurrences:
                if occ.id == record_id:
                    return (occ, cu)
        return None

    def print_record(self, record_id: int) -> None:
        """Print details of a specific record."""
        result = self.get_record(record_id)
        if result:
            occ, cu = result
            print(f"\nRecord ID: {occ.id}")
            print(f"  File: {cu.filename}")
            print(f"  Line: {occ.line}")
            print(f"  Procedure: {cu.procedure_name}")
            print(f"  Code Unit ID: {cu.code_unit_id}")
            print(f"  Code Unit Start Line: {cu.code_unit_start_line}")
            print(f"  Lines of Code: {cu.lines_of_code}")
            print(f"  Status: {occ.status}")
            print(f"  Category: {' | '.join(occ.category) if occ.category else ''}")
            print(f"  Complexity: {occ.complexity}")
            print(f"  SQL Classification: {occ.sql_classification}")
            print(f"  Generated SQL: {occ.generated_sql}")
            print(f"  Notes: {occ.notes}")
        else:
            print(f"Record ID {record_id} not found")

    def get_code_unit_by_id(self, code_unit_id: str) -> Optional[CodeUnitData]:
        """Get code unit by its ID."""
        return self.code_units.get(code_unit_id)

    def get_code_unit_by_filename(self, filename: str) -> List[CodeUnitData]:
        """Get all code units for a specific filename."""
        return [cu for cu in self.code_units.values() if cu.filename == filename]

    def print_code_unit(self, code_unit_id: str, include_code: bool = False) -> None:
        """Print all records for a specific code unit. Optionally include the stored procedure code."""
        cu = self.get_code_unit_by_id(code_unit_id)

        if not cu:
            print(f"\nNo code unit found with ID: {code_unit_id}")
            return

        print(f"\n{'='*80}")
        print(f"Code Unit: {cu.procedure_name}")
        print(f"{'='*80}")
        print(f"File: {cu.filename}")
        print(f"Code Unit Start Line: {cu.code_unit_start_line}")
        print(f"Lines of Code: {cu.lines_of_code}")
        print(f"Total occurrences in this code unit: {len(cu.occurrences)}\n")

        for occ in sorted(cu.occurrences, key=lambda x: x.line):
            print(f"Record ID: {occ.id}")
            print(f"  Line: {occ.line}")
            print(f"  Status: {occ.status}")
            print(f"  Category: {' | '.join(occ.category) if occ.category else ''}")
            print(f"  Complexity: {occ.complexity}")
            print(f"  Notes: {occ.notes}")
            print()

        if include_code:
            print(f"{'─'*80}")
            print("Procedure Code (from JSON metadata):")
            if cu.procedure:
                print(cu.procedure)
            else:
                print("(No procedure code stored. Re-run `generate` with a valid --source-dir.)")
            print()

    def print_all_code_units_in_file(self, filename: str, include_code: bool = False) -> None:
        """Print all code units in a file with their occurrences grouped. Optionally include procedure code."""
        code_units = self.get_code_unit_by_filename(filename)

        if not code_units:
            print(f"\nNo code units found for filename: {filename}")
            return

        total_occurrences = sum(len(cu.occurrences) for cu in code_units)

        print(f"\n{'='*80}")
        print(f"File: {filename}")
        print(f"{'='*80}")
        print(f"Total code units: {len(code_units)}")
        print(f"Total occurrences: {total_occurrences}\n")

        for cu in sorted(code_units, key=lambda x: x.code_unit_start_line):
            print(f"{'─'*80}")
            print(f"Code Unit: {cu.procedure_name}")
            print(f"  Code Unit ID: {cu.code_unit_id}")
            print(f"  Start Line: {cu.code_unit_start_line}")
            print(f"  Lines of Code: {cu.lines_of_code}")
            print(f"  Occurrences: {len(cu.occurrences)}")
            print()

            for occ in sorted(cu.occurrences, key=lambda x: x.line):
                print(f"  Record ID: {occ.id}")
                print(f"    Line: {occ.line}")
                print(f"    Status: {occ.status}")
                if occ.category:
                    print(f"    Category: {' | '.join(occ.category)}")
                if occ.complexity:
                    print(f"    Complexity: {occ.complexity}")
                print()

            if include_code:
                print(f"{'─'*80}")
                print("Procedure Code (from JSON metadata):")
                if cu.procedure:
                    print(cu.procedure)
                else:
                    print("(No procedure code stored. Re-run `generate` with a valid --source-dir.)")
                print()

        print(f"{'='*80}")

    def get_code_unit_id_from_record_id(self, record_id: int) -> Optional[str]:
        """Get code unit ID for a specific record ID."""
        result = self.get_record(record_id)
        return result[1].code_unit_id if result else None

    def get_filename_from_record_id(self, record_id: int) -> Optional[str]:
        """Get filename for a specific record ID."""
        result = self.get_record(record_id)
        return result[1].filename if result else None

    def get_stats(self) -> Dict:
        """Get statistics about the analysis."""
        status_counts = defaultdict(int)
        category_counts = defaultdict(int)
        total = 0

        for cu in self.code_units.values():
            for occ in cu.occurrences:
                total += 1
                status_counts[occ.status] += 1
                if occ.category:
                    for cat in occ.category:
                        category_counts[cat] += 1

        return {
            "total": total,
            "status_counts": dict(status_counts),
            "category_counts": dict(category_counts),
        }

    def print_stats(self) -> None:
        """Print statistics about the analysis."""
        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("ANALYSIS STATISTICS")
        print("=" * 60)
        print(f"\nTotal Records: {stats['total']}")

        print("\nStatus Distribution:")
        for status, count in sorted(stats["status_counts"].items()):
            percentage = (count / stats["total"]) * 100
            print(f"  {status}: {count} ({percentage:.1f}%)")

        if stats["category_counts"]:
            print("\nCategory Distribution:")
            for category, count in sorted(stats["category_counts"].items(), key=lambda x: x[1], reverse=True):
                percentage = (count / stats["total"]) * 100
                print(f"  {category}: {count} ({percentage:.1f}%)")
