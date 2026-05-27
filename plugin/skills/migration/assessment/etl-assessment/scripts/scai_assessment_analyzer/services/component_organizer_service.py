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

from pathlib import PureWindowsPath
from typing import Dict, Optional, Tuple

from ..models import Component, DataFlow, PackageAnalysis


class ComponentOrganizerService:
    def organize_by_packages(self, components_by_key: Dict[Tuple[str, str], Component]) -> Dict[str, PackageAnalysis]:
        packages = {}

        for component in components_by_key.values():
            package = self._get_or_create_package(packages, component)
            self._add_component_to_package(package, component)

        return packages

    def _get_or_create_package(self, packages: Dict[str, PackageAnalysis], component: Component) -> PackageAnalysis:
        package_path = component.file_name

        if package_path not in packages:
            # `file_name` may arrive in POSIX or Windows form; PureWindowsPath
            # treats both `/` and `\\` as separators on every OS.
            package_name = PureWindowsPath(package_path).name or package_path
            packages[package_path] = PackageAnalysis(
                name=package_name,
                path=package_path,
                technology=component.technology
            )

        return packages[package_path]

    def _add_component_to_package(self, package: PackageAnalysis, component: Component):
        if component.subtype == 'ConnectionManager':
            package.connection_managers.append(component)
        elif component.category == 'Data Flow':
            self._add_to_data_flow(package, component)
        else:
            package.control_flow_components.append(component)

    def _add_to_data_flow(self, package: PackageAnalysis, component: Component):
        data_flow_info = self._parse_data_flow_path(component.full_name)

        if not data_flow_info:
            package.control_flow_components.append(component)
            return

        data_flow_name, data_flow_path = data_flow_info

        if data_flow_path not in package.data_flows:
            package.data_flows[data_flow_path] = DataFlow(
                name=data_flow_name,
                full_path=data_flow_path
            )

        package.data_flows[data_flow_path].components.append(component)

    def _parse_data_flow_path(self, full_name: str) -> Optional[Tuple[str, str]]:
        parts = full_name.split('\\')
        if len(parts) >= 3:
            data_flow_path = '\\'.join(parts[:-1])
            data_flow_name = parts[-2]
            return data_flow_name, data_flow_path

        return None

