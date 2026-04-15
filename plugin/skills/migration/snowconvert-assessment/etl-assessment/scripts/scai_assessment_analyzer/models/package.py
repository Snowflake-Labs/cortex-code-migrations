import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from collections import defaultdict

from .component import Component
from .data_flow import DataFlow
from ..utils import sanitize_filename


@dataclass
class PackageAnalysis:
    name: str
    path: str
    technology: str
    connection_managers: List[Component] = field(default_factory=list)
    control_flow_components: List[Component] = field(default_factory=list)
    data_flows: Dict[str, DataFlow] = field(default_factory=dict)
    control_flow_dag_file: Optional[str] = None

    @property
    def all_components(self) -> List[Component]:
        components = list(self.connection_managers)
        components.extend(self.control_flow_components)
        for df in self.data_flows.values():
            components.extend(df.components)
        return components

    @property
    def execution_components(self) -> List[Component]:
        components = list(self.control_flow_components)
        for df in self.data_flows.values():
            components.extend(df.components)
        return components

    @property
    def total_components(self) -> int:
        return len(self.all_components)

    @property
    def total_connection_managers(self) -> int:
        return len(self.connection_managers)

    @property
    def total_control_flow_components(self) -> int:
        return len(self.control_flow_components)

    @property
    def total_data_flow_components(self) -> int:
        return sum(len(df.components) for df in self.data_flows.values())

    def _aggregate_execution_field(self, field_getter) -> Dict[str, int]:
        summary = defaultdict(int)
        for component in self.execution_components:
            key = field_getter(component)
            if key and (field_getter.__name__ != '<lambda>' or key.upper() != 'N/A'):
                summary[key] += 1
        return dict(summary)

    @property
    def status_summary(self) -> Dict[str, int]:
        return self._aggregate_execution_field(lambda c: c.status if c.status.upper() != 'N/A' else None)

    @property
    def subtype_summary(self) -> Dict[str, int]:
        return self._aggregate_execution_field(lambda c: c.subtype)

    def _count_issues_by_type(self, issue_type: str) -> int:
        return sum(c.count_issues_by_type(issue_type) for c in self.all_components)

    def _aggregate_unique_issues(self, issue_type: str) -> Set[str]:
        codes = set()
        for component in self.all_components:
            codes.update(component.unique_issues_by_type(issue_type))
        return codes

    @property
    def total_ewi_count(self) -> int:
        return self._count_issues_by_type('EWI')

    @property
    def total_fdm_count(self) -> int:
        return self._count_issues_by_type('FDM')

    @property
    def total_prf_count(self) -> int:
        return self._count_issues_by_type('PRF')

    @property
    def unique_ewis(self) -> Set[str]:
        return self._aggregate_unique_issues('EWI')

    @property
    def unique_fdms(self) -> Set[str]:
        return self._aggregate_unique_issues('FDM')

    @property
    def unique_prfs(self) -> Set[str]:
        return self._aggregate_unique_issues('PRF')

    @property
    def not_supported_components(self) -> List[Component]:
        """Get all components with NotSupported status."""
        return [c for c in self.execution_components if c.status == 'NotSupported']

    @property
    def unique_not_supported_types(self) -> Set[str]:
        """Get unique component types (subtypes) that are NotSupported."""
        return {c.subtype for c in self.not_supported_components}

    def calculate_conversion_rate(self) -> Dict[str, float]:
        total = len(self.execution_components)
        if total == 0:
            return {'success_rate': 0.0, 'partial_rate': 0.0, 'not_supported_rate': 0.0}

        status_counts = self.status_summary
        return {
            'success_rate': round((status_counts.get('Success', 0) / total) * 100, 2),
            'partial_rate': round((status_counts.get('Partial', 0) / total) * 100, 2),
            'not_supported_rate': round((status_counts.get('NotSupported', 0) / total) * 100, 2)
        }

    def calculate_complexity(self) -> Dict:
        severity_frequency = defaultdict(int)
        total_effort = 0.0

        for component in self.all_components:
            for issue in component.issues:
                severity_frequency[issue.severity.capitalize()] += 1
                total_effort += issue.effort_hours

        complexity_level = self._determine_complexity_level(
            self.total_ewi_count,
            dict(severity_frequency)
        )

        return {
            'severityFrequency': dict(severity_frequency),
            'totalEffortHours': total_effort,
            'complexity': complexity_level
        }

    def _determine_complexity_level(self, ewi_count: int, severity_freq: Dict[str, int]) -> str:
        if ewi_count == 0:
            return 'Very Easy'

        critical_count = severity_freq.get('Critical', 0)
        has_high = severity_freq.get('High', 0) > 0
        has_medium = severity_freq.get('Medium', 0) > 0
        has_low = severity_freq.get('Low', 0) > 0

        if critical_count >= 20:
            return 'Very Complex'
        if has_high or critical_count > 0:
            return 'Complex'
        if has_medium:
            return 'Medium'
        if has_low:
            return 'Easy'

        return 'Very Complex'

    def get_unique_issues(self) -> Dict[str, List[Dict]]:
        details = defaultdict(list)
        seen_issues = set()

        for component in self.all_components:
            for issue in component.issues:
                issue_key = f"{issue.code}|{issue.description}"
                if issue_key not in seen_issues:
                    seen_issues.add(issue_key)
                    details[issue.issue_type].append({
                        'code': issue.code,
                        'description': issue.description,
                        'severity': issue.severity
                    })

        return dict(details)

    def calculate_flags(self) -> Dict[str, bool]:
        """Calculate package flags based on component analysis."""
        flags = {}
        
        # Check if package has any Script Tasks
        has_scripts = any(
            component.subtype == 'Microsoft.ScriptTask' 
            for component in self.all_components
        )
        flags['has_scripts'] = has_scripts
        
        return flags

    def get_control_flow_dag_filename(self) -> str:
        """Get the control flow DAG filename for this package."""
        package_sanitized = sanitize_filename(self.path)
        return f"{package_sanitized}__control_flow.html"

    def to_dict(self) -> dict:
        result = {
            'name': self.name,
            'path': self.path,
            'technology': self.technology,
            'flags': self.calculate_flags(),
            'metrics': {
                'total_components': self.total_components,
                'total_connection_managers': self.total_connection_managers,
                'total_control_flow_components': self.total_control_flow_components,
                'total_data_flow_components': self.total_data_flow_components,
                'total_data_flows': len(self.data_flows),
                'conversion_rates': self.calculate_conversion_rate(),
                'status_summary': self.status_summary,
                'subtype_summary': self.subtype_summary,
                'issue_counts': {
                    'total_ewis': self.total_ewi_count,
                    'total_fdms': self.total_fdm_count,
                    'total_prfs': self.total_prf_count,
                    'unique_ewis': sorted(self.unique_ewis),
                    'unique_fdms': sorted(self.unique_fdms),
                    'unique_prfs': sorted(self.unique_prfs)
                },
                'not_supported_elements': {
                    'total_count': len(self.not_supported_components),
                    'component_types': sorted(self.unique_not_supported_types)
                },
                'package_complexity': self.calculate_complexity()
            },
            'issue_details': self.get_unique_issues(),
            'connection_managers': [c.to_dict('Connection Manager') for c in self.connection_managers],
            'control_flow_components': [c.to_dict() for c in self.control_flow_components],
            'data_flows': [df.to_dict(package_path=self.path) for df in sorted(self.data_flows.values(), key=lambda x: x.full_path)]
        }
        
        # Add control flow DAG file path if there are control flow components
        if self.control_flow_components:
            result['control_flow_dag_file'] = f"dags/{self.get_control_flow_dag_filename()}"
        elif self.control_flow_dag_file:
            result['control_flow_dag_file'] = self.control_flow_dag_file
            
        return result

