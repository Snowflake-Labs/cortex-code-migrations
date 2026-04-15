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
            package_name = package_path.split('/')[-1]
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

