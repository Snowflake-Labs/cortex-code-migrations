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

"""Shared utilities for object exclusion analyzers."""

import re
from collections import defaultdict
from typing import Any, Dict, List

INVALID_REFERENCE_VALUES = {"", "N/A", "n/a", "NA", "na", "None", "null", "NULL"}


def pick_primary_entry(entries: List[Dict[str, Any]]) -> tuple:
    """Pick the primary entry when multiple files have the same full_name."""

    def score_entry(entry: Dict[str, Any]) -> tuple:
        name_patterns = entry.get("name_patterns", [])
        deprecated_indicators = ["_bak", "_old", "_backup", "_archive", "_deprecated", "_copy"]
        has_deprecated = any(ind in str(name_patterns).lower() for ind in deprecated_indicators)

        version_num = 0
        file_name = entry.get("file", "").lower()
        version_match = re.search(r"[._]v(\d+)", file_name)
        if version_match:
            version_num = int(version_match.group(1))

        if not name_patterns:
            return (0, -version_num, len(entry.get("file", "")))
        if has_deprecated:
            return (100, -version_num, len(entry.get("file", "")))
        return (50, -version_num, len(entry.get("file", "")))

    sorted_entries = sorted(entries, key=score_entry)
    return sorted_entries[0], sorted_entries[1:]


def analyze_duplicate_objects(
    all_objects: List[Dict[str, Any]],
    dependency_data: Dict | None = None,
    verbose: bool = True,
) -> tuple:
    """Analyze objects for duplicates (same full_name in multiple source files)."""
    objects_by_fullname = defaultdict(list)
    for obj in all_objects:
        full_name = obj.get("full_name", "")
        if full_name:
            objects_by_fullname[full_name].append(obj)

    primary_objects: List[Dict[str, Any]] = []
    duplicate_objects: List[Dict[str, Any]] = []

    for full_name, entries in objects_by_fullname.items():
        if len(entries) == 1:
            entry = entries[0]
            entry["is_duplicate"] = False
            entry["is_primary"] = True
            entry["all_files_for_object"] = [entry.get("file", "")]
            primary_objects.append(entry)
            continue

        primary, others = pick_primary_entry(entries)
        primary["is_duplicate"] = False
        primary["is_primary"] = True
        primary["all_files_for_object"] = [e.get("file", "") for e in entries]
        primary["version_suggestion"] = {
            "recommended_file": primary.get("file", ""),
            "recommended_reason": (
                "No deprecated/backup patterns detected"
                if not primary.get("_has_deprecated_pattern")
                else "Selected as primary (highest version or fewest patterns)"
            ),
            "current_file_status": "primary",
            "alternatives": [
                {
                    "file": other.get("file", ""),
                    "status": "deprecated" if other.get("_has_deprecated_pattern") else "duplicate",
                    "patterns": other.get("name_patterns", []),
                }
                for other in others
            ],
        }
        primary_objects.append(primary)

        for other in others:
            other["is_duplicate"] = True
            other["is_primary"] = False
            other["primary_file"] = primary.get("file", "")
            other["all_files_for_object"] = [e.get("file", "") for e in entries]
            other["version_suggestion"] = {
                "recommended_file": primary.get("file", ""),
                "recommended_reason": (
                    "Primary version without deprecated patterns"
                    if not primary.get("_has_deprecated_pattern")
                    else "Primary version (highest version)"
                ),
                "current_file_status": "deprecated" if other.get("_has_deprecated_pattern") else "duplicate",
                "alternatives": [],
            }
            other["customer_decision"] = "Pending Review"
            duplicate_objects.append(other)

    if dependency_data:
        dependents_graph = dependency_data.get("dependents", {})
        dependencies_graph = dependency_data.get("dependencies", {})

        for dup_obj in duplicate_objects:
            full_name = dup_obj.get("full_name", "")

            if full_name in dependents_graph and dependents_graph[full_name]:
                valid_dependents = [
                    d for d in dependents_graph[full_name] if d and str(d).strip() not in INVALID_REFERENCE_VALUES
                ]
                if valid_dependents:
                    dup_obj["has_dependency_warning"] = True
                    dup_obj["depended_by"] = valid_dependents
                else:
                    dup_obj["has_dependency_warning"] = False
                    dup_obj["depended_by"] = []
            else:
                dup_obj["has_dependency_warning"] = False
                dup_obj["depended_by"] = []

            if full_name in dependencies_graph and dependencies_graph[full_name]:
                valid_dependencies = [
                    d for d in dependencies_graph[full_name] if d and str(d).strip() not in INVALID_REFERENCE_VALUES
                ]
                dup_obj["depends_on"] = valid_dependencies
            else:
                dup_obj["depends_on"] = []

    if verbose:
        print(f"   Found {len(primary_objects)} unique objects")
        if duplicate_objects:
            print(
                f"   Found {len(duplicate_objects)} duplicate objects "
                "(same full_name, different files)"
            )
        print()

    return primary_objects, duplicate_objects


def get_base_object_name(name: str) -> str:
    """Extract base object name by removing version/date/backup/test suffixes."""
    base_name = name.lower()
    patterns_to_strip = [
        r"_bak_\d{6,8}$",
        r"_old_\d{6,8}$",
        r"_backup_\d{6,8}$",
        r"_old_\d{4}$",
        r"_v\d+$",
        r"_v$",
        r"_copy\d+$",
        r"_bak_$",
        r"_old$",
        r"_bak$",
        r"_backup$",
        r"_archive$",
        r"_archived$",
        r"_deprecated$",
        r"_obsolete$",
        r"_copy$",
        r"_test$",
        r"_fake$",
        r"_demo$",
        r"_sample$",
        r"_dummy$",
        r"_mock$",
        r"_test_.*$",
        r"_fake_.*$",
    ]

    if "original" in base_name and "bak" in base_name:
        base_name = re.sub(r"_original.*", "", base_name)
    if "original" in base_name and "slow" in base_name:
        base_name = re.sub(r"_original.*", "", base_name)

    for pattern in patterns_to_strip:
        base_name = re.sub(pattern, "", base_name)

    return base_name


def identify_production_versions(all_objects: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Identify production versions for objects with deprecated/versioned variants."""
    object_groups = defaultdict(list)
    for obj in all_objects:
        base_name = get_base_object_name(obj["name"])
        schema = obj.get("schema", "unknown")
        obj_type = obj.get("type", "unknown")
        key = f"{schema}.{base_name}.{obj_type}"
        object_groups[key].append(obj)

    version_mapping: List[Dict[str, Any]] = []
    production_versions: Dict[str, Dict[str, str]] = {}

    for key, objects in object_groups.items():
        if len(objects) <= 1:
            continue

        def get_priority(obj: Dict[str, Any]) -> float:
            name = obj["name"].lower()
            if name == get_base_object_name(name):
                return 0
            if any(pattern in name for pattern in ["_test", "_fake", "_demo", "_sample", "_dummy", "_mock"]):
                return 1000
            if any(pattern in name for pattern in ["_bak", "_backup", "_archive", "_old", "_copy"]):
                return 900
            version_match = re.search(r"_v(\d+)$", name)
            if version_match:
                version_num = int(version_match.group(1))
                return 100 - version_num
            if name.endswith("_v"):
                return 50
            date_match = re.search(r"_(\d{6,8})$", name)
            if date_match:
                date_str = date_match.group(1)
                return 200 - int(date_str) / 100000000
            return 500

        sorted_objects = sorted(objects, key=get_priority)
        production_obj = sorted_objects[0]
        other_versions = sorted_objects[1:]
        parts = key.split(".")
        mapping_entry = {
            "base_name": parts[1],
            "schema": parts[0],
            "type": parts[2],
            "production_version": production_obj["name"],
            "production_full_name": production_obj["full_name"],
            "production_file": production_obj.get("file", ""),
            "deprecated_versions": [
                {
                    "name": obj["name"],
                    "full_name": obj["full_name"],
                    "file": obj.get("file", ""),
                }
                for obj in other_versions
            ],
            "total_versions": len(objects),
        }
        version_mapping.append(mapping_entry)

        for obj in other_versions:
            production_versions[obj["full_name"]] = {
                "production_version": production_obj["full_name"],
                "production_name": production_obj["name"],
                "production_file": production_obj.get("file", ""),
            }

    return {
        "version_mapping": sorted(version_mapping, key=lambda x: (x["schema"], x["base_name"])),
        "production_versions": production_versions,
    }


class NamingConventionAnalyzer:
    """Shared base analyzer for object exclusion pattern analysis."""

    TEMP_STAGING_PATTERNS = [
        r"^#",
        r"##",
        r"^tmp_",
        r"^temp_",
        r"_tmp$",
        r"_temp$",
        r"^staging_",
        r"^stg_",
        r"_staging$",
        r"_stg$",
        r"^work_",
        r"^wrk_",
        r"_work$",
        r"_wrk$",
        r"^t_",
        r"scratch",
        r"interim",
        r"landing",
        r"\bstg\b",
    ]

    DEPRECATED_LEGACY_PATTERNS = [
        r"_deprecated$",
        r"_obsolete$",
        r"_bak_\d{6,8}$",
        r"_backup_\d{6,8}$",
        r"_old_\d{6,8}$",
        r"_old_\d{4}$",
        r"_bak$",
        r"_backup$",
        r"_old$",
        r"_archive$",
        r"_archived$",
        r"_copy\d+$",
        r"_copy$",
        r"_v\d+$",
        r"_bak_",
        r"original.*bak",
        r"original_slow",
    ]

    DEPRECATED_PREFIX_PATTERNS = [
        r"^deprecated_",
        r"^obsolete_",
        r"^old_",
        r"^bak_",
        r"^backup_",
        r"^archive_",
    ]

    EXCLUSION_PATTERNS = [
        r"^old_to_new",
        r"^old_to_",
        r"^new_to_old",
        r"legacy_.*_nodes",
        r"legacy_.*_mapping",
    ]

    UTILITY_SCHEMAS = ["UTIL", "UTILITY", "HELPER", "COMMON"]
    STAGING_SCHEMAS = ["STAGING", "STG", "TEMP", "TMP", "WORK", "WRK"]

    PATTERN_DISPLAY_NAMES = {
        r"^#": "local temp",
        r"##": "global temp",
        r"^tmp_": "tmp prefix",
        r"^temp_": "temp prefix",
        r"_tmp$": "tmp suffix",
        r"_temp$": "temp suffix",
        r"^staging_": "staging prefix",
        r"^stg_": "stg prefix",
        r"_staging$": "staging suffix",
        r"_stg$": "stg suffix",
        r"^work_": "work prefix",
        r"^wrk_": "wrk prefix",
        r"_work$": "work suffix",
        r"_wrk$": "wrk suffix",
        r"^t_": "t prefix",
        r"scratch": "scratch",
        r"interim": "interim",
        r"landing": "landing",
        r"\bstg\b": "stg",
        r"_deprecated$": "deprecated",
        r"_obsolete$": "obsolete",
        r"_bak_\d{6,8}$": "dated backup",
        r"_backup_\d{6,8}$": "dated backup",
        r"_old_\d{6,8}$": "dated old",
        r"_old_\d{4}$": "year old",
        r"_bak$": "bak suffix",
        r"_backup$": "backup suffix",
        r"_old$": "old suffix",
        r"_archive$": "archive",
        r"_archived$": "archived",
        r"_copy\d+$": "numbered copy",
        r"_copy$": "copy",
        r"_v\d+$": "versioned",
        r"_bak_": "bak infix",
        r"original.*bak": "original backup",
        r"original_slow": "original slow",
        r"^deprecated_": "deprecated prefix",
        r"^obsolete_": "obsolete prefix",
        r"^old_": "old prefix",
        r"^bak_": "bak prefix",
        r"^backup_": "backup prefix",
        r"^archive_": "archive prefix",
        r"_test$": "test",
        r"_test_": "test",
        r"_fake$": "fake",
        r"_fake_": "fake",
        r"^test_": "test",
        r"^fake_": "fake",
        r"_demo$": "demo",
        r"_demo_": "demo",
        r"^demo_": "demo",
        r"_sample$": "sample",
        r"_sample_": "sample",
        r"^sample_": "sample",
        r"_dummy$": "dummy",
        r"_dummy_": "dummy",
        r"^dummy_": "dummy",
        r"_mock$": "mock",
        r"_mock_": "mock",
        r"^mock_": "mock",
    }

    TESTING_PATTERNS = [
        r"_test$",
        r"_test_",
        r"_fake$",
        r"_fake_",
        r"^test_",
        r"^fake_",
        r"_demo$",
        r"_demo_",
        r"^demo_",
        r"_sample$",
        r"_sample_",
        r"^sample_",
        r"_dummy$",
        r"_dummy_",
        r"^dummy_",
        r"_mock$",
        r"_mock_",
        r"^mock_",
    ]

    def __init__(self, report_directory, include_staging_schema: bool = True):
        self.report_directory = report_directory
        self.include_staging_schema = include_staging_schema
        self.object_references = {}

    def _read_object_references(self) -> None:
        raise NotImplementedError

    def _read_snowconvert_report(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def _check_temp_staging_patterns(self, obj_name: str) -> List[str]:
        return [p for p in self.TEMP_STAGING_PATTERNS if re.search(p, obj_name.lower(), re.IGNORECASE)]

    def _check_deprecated_legacy_patterns(self, obj_name: str, schema: str = "", obj_type: str = "") -> List[str]:
        matched: List[str] = []
        obj_lower = obj_name.lower()
        schema_upper = schema.upper() if schema else ""
        for exclusion_pattern in self.EXCLUSION_PATTERNS:
            if re.search(exclusion_pattern, obj_lower, re.IGNORECASE):
                return []
        for pattern in self.DEPRECATED_LEGACY_PATTERNS:
            if re.search(pattern, obj_lower, re.IGNORECASE):
                matched.append(pattern)
        is_utility_schema = schema_upper in self.UTILITY_SCHEMAS
        is_table = obj_type.upper() == "TABLE"
        if not is_utility_schema or is_table:
            for pattern in self.DEPRECATED_PREFIX_PATTERNS:
                if re.search(pattern, obj_lower, re.IGNORECASE) and not re.search(r"^old_to_|^new_to_old", obj_lower, re.IGNORECASE):
                    matched.append(pattern)
        return matched

    def _check_testing_patterns(self, obj_name: str) -> List[str]:
        return [p for p in self.TESTING_PATTERNS if re.search(p, obj_name.lower(), re.IGNORECASE)]

    def _get_base_object_name(self, obj_name: str) -> str:
        return get_base_object_name(obj_name)

    def _identify_production_versions(self, all_objects: List[Dict[str, Any]]) -> Dict[str, Any]:
        return identify_production_versions(all_objects)

    def _get_testing_reason(self, obj_name: str, patterns: List[str]) -> str:
        reasons = []
        if any("test" in p for p in patterns):
            reasons.append("Contains 'test' pattern")
        if any("fake" in p for p in patterns):
            reasons.append("Contains 'fake' pattern")
        if any("demo" in p for p in patterns):
            reasons.append("Contains 'demo' pattern")
        if any("sample" in p for p in patterns):
            reasons.append("Contains 'sample' pattern")
        if any("dummy" in p for p in patterns):
            reasons.append("Contains 'dummy' pattern")
        if any("mock" in p for p in patterns):
            reasons.append("Contains 'mock' pattern")
        return "; ".join(reasons) if reasons else "Matches testing pattern"

    def _analyze_dependency_impact(
        self,
        deprecated_objects: List[Dict[str, Any]],
        temp_staging_objects: List[Dict[str, Any]],
        testing_objects: List[Dict[str, Any]],
        all_objects: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.object_references or not self.object_references.get("dependents"):
            return {"potentially_normal_objects": {}, "has_dependency_data": False}

        dependents_graph = self.object_references["dependents"]
        deprecated_names = {obj["full_name"] for obj in deprecated_objects}
        temp_staging_names = {obj["full_name"] for obj in temp_staging_objects}
        testing_names = {obj["full_name"] for obj in testing_objects}
        problematic_names = deprecated_names | temp_staging_names | testing_names
        potentially_normal_objects = {}
        threshold = 3
        for dep_name in deprecated_names:
            if dep_name in dependents_graph:
                dependent_names = dependents_graph[dep_name]
                normal_dependents = [d for d in dependent_names if d not in problematic_names]
                if len(normal_dependents) >= threshold:
                    potentially_normal_objects[dep_name] = {
                        "normal_dependent_count": len(normal_dependents),
                        "normal_dependents": list(normal_dependents)[:10],
                        "total_dependent_count": len(dependent_names),
                        "validation_message": f"This object is referenced by {len(normal_dependents)} normal objects. Review to confirm it should be deprecated.",
                    }
        print("\n  Dependency Analysis:")
        print(f"     Found {len(potentially_normal_objects)} deprecated objects that may actually be normal")
        return {"potentially_normal_objects": potentially_normal_objects, "has_dependency_data": True}

    def _add_dependency_details_to_objects(
        self,
        all_objects: List[Dict[str, Any]],
        deprecated_objects: List[Dict[str, Any]],
        temp_staging_objects: List[Dict[str, Any]],
        testing_objects: List[Dict[str, Any]],
        dependency_analysis: Dict[str, Any],
    ) -> None:
        if not self.object_references:
            return
        dependents_graph = self.object_references.get("dependents", {})
        dependencies_graph = self.object_references.get("dependencies", {})
        all_objects_map = {obj["full_name"]: obj for obj in all_objects}
        deprecated_names = {obj["full_name"] for obj in deprecated_objects}
        temp_staging_names = {obj["full_name"] for obj in temp_staging_objects}
        testing_names = {obj["full_name"] for obj in testing_objects}

        def get_object_category(full_name: str) -> str:
            if full_name in deprecated_names:
                return "deprecated"
            if full_name in temp_staging_names:
                return "temp_staging"
            if full_name in testing_names:
                return "testing"
            return "normal"

        def build_dependency_detail(full_name: str) -> Dict[str, Any]:
            if full_name in all_objects_map:
                obj = all_objects_map[full_name]
                return {"full_name": full_name, "name": obj.get("name", ""), "schema": obj.get("schema", ""), "type": obj.get("type", ""), "category": get_object_category(full_name)}
            parts = full_name.split(".")
            return {"full_name": full_name, "name": parts[-1] if parts else full_name, "schema": parts[-2] if len(parts) >= 2 else "unknown", "type": "EXTERNAL", "category": "external"}

        for obj in deprecated_objects + temp_staging_objects + testing_objects:
            full_name = obj.get("full_name", "")
            depends_on = [build_dependency_detail(r) for r in dependencies_graph.get(full_name, [])]
            depended_by = [build_dependency_detail(r) for r in dependents_graph.get(full_name, [])]
            obj["dependencies"] = {
                "depends_on": depends_on,
                "depends_on_count": len(depends_on),
                "depended_by": depended_by,
                "depended_by_count": len(depended_by),
            }
            obj["depends_on"] = [d["full_name"] for d in depends_on]
            obj["depended_by"] = [d["full_name"] for d in depended_by]

    def _empty_results(self) -> Dict[str, Any]:
        return {
            "summary": {
                "report_directory": str(self.report_directory.absolute()),
                "total_objects_found": 0,
                "temp_staging_objects_count": 0,
                "deprecated_legacy_objects_count": 0,
                "testing_objects_count": 0,
                "duplicate_objects_count": 0,
                "unique_duplicate_objects_count": 0,
                "objects_by_schema": [],
                "objects_with_multiple_versions": 0,
                "potentially_normal_objects_count": 0,
                "has_dependency_data": False,
            },
            "temporary_staging_objects": [],
            "deprecated_legacy_objects": [],
            "testing_objects": [],
            "duplicate_objects": [],
            "version_analysis": {"objects_with_versions": [], "total_object_groups": 0, "description": "No objects found"},
            "dependency_analysis": {"potentially_normal_objects": {}, "has_dependency_data": False, "description": "No objects found"},
            "naming_pattern_definitions": {
                "temporary_staging_patterns": self.TEMP_STAGING_PATTERNS,
                "deprecated_legacy_patterns": self.DEPRECATED_LEGACY_PATTERNS,
                "testing_patterns": self.TESTING_PATTERNS,
                "exclusion_patterns": self.EXCLUSION_PATTERNS,
                "staging_schemas": self.STAGING_SCHEMAS if self.include_staging_schema else [],
            },
        }

    def analyze(self) -> Dict[str, Any]:
        print(f"Analyzing SnowConvert reports in: {self.report_directory}")
        self._read_object_references()
        all_objects = self._read_snowconvert_report()
        if not all_objects:
            print("No objects found in SnowConvert reports")
            return self._empty_results()

        for obj in all_objects:
            obj_name = obj.get("name", "")
            schema_upper = obj.get("schema", "").upper()
            name_temp = self._check_temp_staging_patterns(obj_name)
            name_deprecated = self._check_deprecated_legacy_patterns(obj_name, obj.get("schema", ""), obj.get("type", ""))
            name_testing = self._check_testing_patterns(obj_name)
            obj["name_patterns"] = name_temp + name_deprecated + name_testing
            obj["_has_temp_pattern"] = bool(name_temp or (self.include_staging_schema and schema_upper in self.STAGING_SCHEMAS))
            obj["_has_deprecated_pattern"] = bool(name_deprecated)
            obj["_has_testing_pattern"] = bool(name_testing)

        dependency_data = self.object_references if self.object_references else None
        primary_objects, duplicate_objects = analyze_duplicate_objects(all_objects, dependency_data=dependency_data, verbose=True)

        temp_staging_objects, deprecated_legacy_objects, testing_objects = [], [], []

        def get_display_names(patterns: List[str]) -> List[str]:
            out = []
            for p in patterns:
                if p.startswith("schema:"):
                    out.append(p.replace("schema:", "schema: ").lower())
                else:
                    out.append(self.PATTERN_DISPLAY_NAMES.get(p, p))
            return out

        for obj in primary_objects:
            obj_name = obj.get("name", "")
            schema_upper = obj.get("schema", "").upper()
            is_staging_schema = self.include_staging_schema and schema_upper in self.STAGING_SCHEMAS
            obj["customer_decision"] = "Pending Review"
            if obj.get("_has_temp_pattern"):
                obj_copy = obj.copy()
                temp_patterns = self._check_temp_staging_patterns(obj_name)
                if is_staging_schema and not temp_patterns:
                    obj_copy["matched_patterns"] = [f"schema: {schema_upper.lower()}"]
                elif temp_patterns:
                    display_patterns = get_display_names(temp_patterns)
                    obj_copy["matched_patterns"] = display_patterns + ([f"schema: {schema_upper.lower()}"] if is_staging_schema else [])
                temp_staging_objects.append(obj_copy)
            if obj.get("_has_deprecated_pattern"):
                obj_copy = obj.copy()
                deprecated_patterns = self._check_deprecated_legacy_patterns(obj_name, obj.get("schema", ""), obj.get("type", ""))
                display_patterns = get_display_names(deprecated_patterns)
                if is_staging_schema and f"schema: {schema_upper.lower()}" not in display_patterns:
                    display_patterns.append(f"schema: {schema_upper.lower()}")
                obj_copy["matched_patterns"] = display_patterns
                deprecated_legacy_objects.append(obj_copy)
            if obj.get("_has_testing_pattern"):
                obj_copy = obj.copy()
                testing_patterns = self._check_testing_patterns(obj_name)
                display_patterns = get_display_names(testing_patterns)
                if is_staging_schema and f"schema: {schema_upper.lower()}" not in display_patterns:
                    display_patterns.append(f"schema: {schema_upper.lower()}")
                obj_copy["matched_patterns"] = display_patterns
                obj_copy["testing_reason"] = self._get_testing_reason(obj_name, testing_patterns)
                testing_objects.append(obj_copy)

        objects_by_schema = defaultdict(int)
        for obj in primary_objects:
            objects_by_schema[obj.get("schema", "unknown")] += 1
        schema_stats = [{"schema": s, "object_count": c} for s, c in sorted(objects_by_schema.items(), key=lambda x: x[1], reverse=True)]
        version_analysis = self._identify_production_versions(primary_objects)
        dependency_analysis = self._analyze_dependency_impact(deprecated_legacy_objects, temp_staging_objects, testing_objects, primary_objects)
        self._add_dependency_details_to_objects(primary_objects, deprecated_legacy_objects, temp_staging_objects, testing_objects, dependency_analysis)

        for obj in deprecated_legacy_objects:
            full_name = obj.get("full_name", "")
            if full_name in version_analysis["production_versions"]:
                obj["production_version"] = version_analysis["production_versions"][full_name]["production_version"]
                obj["production_name"] = version_analysis["production_versions"][full_name]["production_name"]
            if full_name in dependency_analysis["potentially_normal_objects"]:
                obj["dependency_validation"] = dependency_analysis["potentially_normal_objects"][full_name]

        unique_duplicate_objects = len(set(obj.get("full_name", "") for obj in duplicate_objects))
        return {
            "summary": {
                "report_directory": str(self.report_directory.absolute()),
                "total_objects_found": len(primary_objects),
                "temp_staging_objects_count": len(temp_staging_objects),
                "deprecated_legacy_objects_count": len(deprecated_legacy_objects),
                "testing_objects_count": len(testing_objects),
                "duplicate_objects_count": len(duplicate_objects),
                "unique_duplicate_objects_count": unique_duplicate_objects,
                "objects_by_schema": schema_stats,
                "objects_with_multiple_versions": len(version_analysis["version_mapping"]),
                "potentially_normal_objects_count": len(dependency_analysis["potentially_normal_objects"]),
                "has_dependency_data": dependency_analysis["has_dependency_data"],
            },
            "temporary_staging_objects": temp_staging_objects,
            "deprecated_legacy_objects": deprecated_legacy_objects,
            "testing_objects": testing_objects,
            "duplicate_objects": duplicate_objects,
            "version_analysis": {
                "objects_with_versions": version_analysis["version_mapping"],
                "total_object_groups": len(version_analysis["version_mapping"]),
                "description": "Groups of objects with multiple versions (deprecated/versioned/backup variants). The production_version is the object that should be migrated.",
            },
            "dependency_analysis": {
                "potentially_normal_objects": dependency_analysis["potentially_normal_objects"],
                "has_dependency_data": dependency_analysis["has_dependency_data"],
                "description": "Analysis of objects based on their dependency relationships. Dependency details are included in each object.",
            },
            "naming_pattern_definitions": {
                "temporary_staging_patterns": self.TEMP_STAGING_PATTERNS,
                "deprecated_legacy_patterns": self.DEPRECATED_LEGACY_PATTERNS,
                "testing_patterns": self.TESTING_PATTERNS,
                "exclusion_patterns": self.EXCLUSION_PATTERNS,
                "staging_schemas": self.STAGING_SCHEMAS if self.include_staging_schema else [],
            },
        }
