import json
from collections import defaultdict
from typing import Dict

from ..models import PackageAnalysis


class AnalysisService:
    def create_summary(self, packages: Dict[str, PackageAnalysis]) -> dict:
        return {
            'packages': len(packages),
            'total components': sum(p.total_components for p in packages.values()),
            'connection managers': sum(p.total_connection_managers for p in packages.values()),
            'control flow components': sum(p.total_control_flow_components for p in packages.values()),
            'data flows': sum(len(p.data_flows) for p in packages.values()),
            'data flow components': sum(p.total_data_flow_components for p in packages.values()),
            'EWIs': sum(p.total_ewi_count for p in packages.values()),
            'FDMs': sum(p.total_fdm_count for p in packages.values()),
            'PRFs': sum(p.total_prf_count for p in packages.values()),
            'estimated effort hours': self._calculate_total_effort(packages),
            'EWI distribution': self._aggregate_severity_distribution(packages),
            'not supported elements': self._aggregate_not_supported_components(packages),
            'ai_summary': ''
        }

    def _calculate_total_effort(self, packages: Dict[str, PackageAnalysis]) -> int:
        total = sum(float(p.calculate_complexity()['totalEffortHours']) for p in packages.values())
        return round(total)

    def _aggregate_severity_distribution(self, packages: Dict[str, PackageAnalysis]) -> dict:
        severity_distribution = defaultdict(int)

        for package in packages.values():
            for component in package.all_components:
                for issue in component.issues:
                    severity_key = issue.severity.capitalize()
                    if severity_key != 'None':
                        severity_distribution[severity_key] += 1

        return dict(sorted(severity_distribution.items()))

    def _aggregate_not_supported_components(self, packages: Dict[str, PackageAnalysis]) -> dict:
        total_count = sum(len(p.not_supported_components) for p in packages.values())
        unique_types = set()

        for package in packages.values():
            unique_types.update(package.unique_not_supported_types)

        return {
            'total_count': total_count,
            'component_types': sorted(unique_types)
        }

    def export_to_json(self, packages: Dict[str, PackageAnalysis], output_path: str):
        summary = self.create_summary(packages)
        packages_data = []
        
        for key in sorted(packages.keys()):
            package_dict = packages[key].to_dict()
            package_dict['ai_analysis'] = {
                'status': 'PENDING',
                'analysis': '',
                'classification': '',
                'estimated_effort_hours': ''
            }
            packages_data.append(package_dict)

        output_data = {
            'summary': summary,
            'packages': packages_data
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

