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

"""AnalysisService — exports workflow analysis to JSON."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from ..models import WorkflowAnalysis


class AnalysisService:
    """Handles JSON export of workflow analysis results."""

    @staticmethod
    def export_to_json(
        workflows: Dict[str, WorkflowAnalysis],
        output_path: str,
        conversion_mode: str = "dbt",
    ) -> None:
        """Export all workflow analyses to a single JSON file.

        Output structure:
        {
            "summary": {...},
            "workflows": [...]
        }
        """
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        # Build summary
        # Counted the way the code unit registry counts them: workflows and
        # mappings apart, not one "workflow" per XML file analyzed.
        total_files = len(workflows)
        total_workflows = sum(1 for w in workflows.values() if w.kind == "workflow")
        # A dropped mapping is attached to every workflow that runs it. Count that
        # mapping, its transforms, and its issues once. Each workflow's own tasks
        # are still counted.
        seen_mapping_paths: set[str] = set()
        total_components = 0
        total_ewis = 0
        total_fdms = 0
        total_prfs = 0
        status_totals: Dict[str, int] = {}
        subtype_totals: Dict[str, int] = {}

        def add_count(bucket: Dict[str, int], key: str) -> None:
            if key and key.upper() != "N/A":
                bucket[key] = bucket.get(key, 0) + 1

        def add_issues(component) -> None:
            nonlocal total_ewis, total_fdms, total_prfs
            total_ewis += component.ewi_count
            total_fdms += component.fdm_count
            total_prfs += component.prf_count

        for workflow in workflows.values():
            total_components += len(workflow.workflow_tasks)
            for component in workflow.workflow_tasks:
                add_count(status_totals, component.status)
                add_count(subtype_totals, component.subtype)
                add_issues(component)
            for component in workflow.source_definitions:
                add_issues(component)
            for component in workflow.target_definitions:
                add_issues(component)
            for mapping in workflow.mappings.values():
                if mapping.full_path in seen_mapping_paths:
                    continue
                seen_mapping_paths.add(mapping.full_path)
                total_components += len(mapping.components)
                for component in mapping.components:
                    add_count(status_totals, component.status)
                    add_count(subtype_totals, component.subtype)
                    add_issues(component)

        total_mappings = len(seen_mapping_paths)

        data = {
            "summary": {
                "generated_at": datetime.now().isoformat(),
                "technology": "InformaticaPowerCenter",
                "conversion_mode": conversion_mode,
                "total_files": total_files,
                "total_workflows": total_workflows,
                "total_mappings": total_mappings,
                "total_components": total_components,
                "total_ewis": total_ewis,
                "total_fdms": total_fdms,
                "total_prfs": total_prfs,
                "status_totals": status_totals,
                "subtype_totals": subtype_totals,
            },
            "workflows": [w.to_dict() for w in sorted(workflows.values(), key=lambda x: x.path)],
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"Exported analysis to: {output_file}")
