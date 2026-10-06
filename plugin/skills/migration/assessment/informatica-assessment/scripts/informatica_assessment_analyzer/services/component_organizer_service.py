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

"""ComponentOrganizerService — routes components into WorkflowAnalysis structures."""

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from ..models import Component, Mapping, WorkflowAnalysis

_MAPPINGNAME = re.compile(r'\bMAPPINGNAME\s*=\s*"([^"]+)"')


class ComponentOrganizerService:
    """Routes components into WorkflowAnalysis by file_name, category, and entry_kind."""

    def organize_by_workflows(
        self,
        components_by_key: Dict[Tuple[str, str], Component],
        source_dir: Optional[str] = None,
    ) -> Dict[str, WorkflowAnalysis]:
        """Organize components into workflow analysis structures.

        Routing rules:
        - Category='Folder', Subtype='Source Definition' → source_definitions
        - Category='Folder', Subtype='Target Definition' → target_definitions
        - Category='Folder', Subtype='Workflow'/'Session' → sets has_workflow_declaration
        - Category='Folder', other subtypes → metadata (Mapping declarations)
        - Category='Workflow' → workflow_tasks
        - Category='Mapping', EntryKind='Instance' → mapping components
        - Category='Mapping', EntryKind='Declaration' → mapping component declarations

        Post-processing (two-tier filter):
        - Files with workflow_tasks or has_workflow_declaration are always included.
        - Files with only source/target defs are included ONLY if no file in the
          dataset has primary workflow signals (i.e. pre-Arrange legacy export).

        With source_dir, mappings from dropped files (after Arrange, each mapping
        is its own file) join the workflows whose XML names them in MAPPINGNAME.
        """
        all_entries: Dict[str, WorkflowAnalysis] = {}

        for component in components_by_key.values():
            workflow = self._get_or_create_workflow(all_entries, component)
            self._add_component_to_workflow(workflow, component)

        dataset_has_workflow_signals = any(
            wa.workflow_tasks or wa.has_workflow_declaration
            for wa in all_entries.values()
        )

        workflows = {
            path: wa
            for path, wa in all_entries.items()
            if self._is_workflow_file(wa, dataset_has_workflow_signals)
        }

        if source_dir:
            self._attach_split_mappings(workflows, all_entries, Path(source_dir))

        return workflows

    @staticmethod
    def _attach_split_mappings(
        workflows: Dict[str, WorkflowAnalysis],
        all_entries: Dict[str, WorkflowAnalysis],
        source_dir: Path,
    ) -> None:
        """Move each dropped file's mappings into the workflows that run them.

        A workflow's XML names the mappings its sessions run in MAPPINGNAME;
        mappings are matched by name, so the mapping file's own name does not matter.
        """
        dropped_by_name: Dict[str, Dict[str, Mapping]] = {}
        for path, entry in all_entries.items():
            if path in workflows:
                continue
            for mapping_path, mapping in entry.mappings.items():
                dropped_by_name.setdefault(mapping.name, {})[mapping_path] = mapping

        for path, workflow in workflows.items():
            xml = ComponentOrganizerService._find_xml(source_dir, path)
            if xml is None:
                continue
            text = xml.read_text(encoding="utf-8", errors="ignore")
            for name in sorted(set(_MAPPINGNAME.findall(text))):
                workflow.mappings.update(dropped_by_name.get(name, {}))

    @staticmethod
    def _find_xml(source_dir: Path, path: str) -> Optional[Path]:
        """Locate a workflow's XML under source_dir.

        ETL.Elements paths are relative to the project's source/ folder
        (_etl/<repo>/<folder>/tasks/wf.xml), but source_dir may be source/_etl,
        so retry with the path's leading folders dropped.
        """
        parts = Path(path).parts
        for start in range(len(parts)):
            xml = source_dir.joinpath(*parts[start:])
            if xml.is_file():
                return xml
        return None

    @staticmethod
    def _is_workflow_file(wa: WorkflowAnalysis, dataset_has_workflow_signals: bool) -> bool:
        """Determine if a file represents a real workflow.

        Primary signals (definitive):
          - workflow_tasks: Category=Workflow instances (Session, Command, Start)
          - has_workflow_declaration: Folder-level Workflow/Session declaration

        Fallback (legacy datasets only):
          - source/target defs are accepted ONLY when no file in the dataset
            has primary workflow signals — indicating a pre-Arrange legacy export
            where mapping files with Folder defs are the top-level units.
        """
        if wa.workflow_tasks or wa.has_workflow_declaration:
            return True
        if not dataset_has_workflow_signals:
            return bool(wa.source_definitions or wa.target_definitions)
        return False

    def _get_or_create_workflow(
        self, workflows: Dict[str, WorkflowAnalysis], component: Component
    ) -> WorkflowAnalysis:
        """Get or create a WorkflowAnalysis for the component's file."""
        file_name = component.file_name

        if file_name not in workflows:
            workflow_name = file_name.rsplit("/", 1)[-1] if "/" in file_name else file_name
            workflows[file_name] = WorkflowAnalysis(
                name=workflow_name,
                path=file_name,
                technology=component.technology,
            )

        return workflows[file_name]

    def _add_component_to_workflow(
        self, workflow: WorkflowAnalysis, component: Component
    ) -> None:
        """Route a component to the appropriate collection within the workflow."""
        category = component.category

        if category == "Folder":
            self._handle_folder_component(workflow, component)
        elif category == "Workflow":
            workflow.workflow_tasks.append(component)
        elif category == "Mapping":
            self._add_to_mapping(workflow, component)

    def _handle_folder_component(
        self, workflow: WorkflowAnalysis, component: Component
    ) -> None:
        """Handle folder-level components (declarations, source/target defs)."""
        subtype = component.subtype

        if subtype == "Source Definition":
            workflow.source_definitions.append(component)
        elif subtype == "Target Definition":
            workflow.target_definitions.append(component)
        elif subtype in ("Workflow", "Session"):
            workflow.has_workflow_declaration = True

    def _add_to_mapping(
        self, workflow: WorkflowAnalysis, component: Component
    ) -> None:
        """Add a component to its parent mapping."""
        mapping_info = self._parse_mapping_path(component.full_name)

        if not mapping_info:
            # Can't determine mapping — add as orphan workflow task
            workflow.workflow_tasks.append(component)
            return

        mapping_name, mapping_path = mapping_info

        if mapping_path not in workflow.mappings:
            workflow.mappings[mapping_path] = Mapping(
                name=mapping_name,
                full_path=mapping_path,
            )

        workflow.mappings[mapping_path].components.append(component)

    @staticmethod
    def _parse_mapping_path(full_name: str) -> Optional[Tuple[str, str]]:
        """Parse the mapping name and path from a component's full_name.

        Informatica full_name format: 'ETL.<mapping_name>.<component_name>'
        or 'FolderName.<mapping_name>.<component_name>'

        Returns (mapping_name, mapping_path) or None if can't parse.
        """
        parts = full_name.split(".")
        if len(parts) >= 3:
            # Path is everything except the last element (component name)
            mapping_path = ".".join(parts[:-1])
            mapping_name = parts[-2] if len(parts) >= 2 else parts[0]
            return mapping_name, mapping_path

        return None
