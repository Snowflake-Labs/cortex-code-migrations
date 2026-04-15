import re
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional
from collections import defaultdict

from .component import Component
from ..utils import sanitize_filename


@dataclass
class DataFlow:
    name: str
    full_path: str
    components: List[Component] = field(default_factory=list)
    dag_file: Optional[str] = None

    @property
    def total_components(self) -> int:
        return len(self.components)

    def _aggregate_by_field(self, field_getter) -> Dict[str, int]:
        summary = defaultdict(int)
        for component in self.components:
            key = field_getter(component)
            if key and (field_getter.__name__ != '<lambda>' or key.upper() != 'N/A'):
                summary[key] += 1
        return dict(summary)

    @property
    def status_summary(self) -> Dict[str, int]:
        return self._aggregate_by_field(lambda c: c.status if c.status.upper() != 'N/A' else None)

    @property
    def subtype_summary(self) -> Dict[str, int]:
        return self._aggregate_by_field(lambda c: c.subtype)

    def _aggregate_unique_issues(self, issue_type: str) -> Set[str]:
        codes = set()
        for component in self.components:
            codes.update(component.unique_issues_by_type(issue_type))
        return codes

    @property
    def total_ewi_count(self) -> int:
        return sum(c.ewi_count for c in self.components)

    @property
    def total_fdm_count(self) -> int:
        return sum(c.fdm_count for c in self.components)

    @property
    def total_prf_count(self) -> int:
        return sum(c.prf_count for c in self.components)

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
        return [c for c in self.components if c.status == 'NotSupported']

    @property
    def unique_not_supported_types(self) -> Set[str]:
        """Get unique component types (subtypes) that are NotSupported."""
        return {c.subtype for c in self.not_supported_components}

    def calculate_conversion_rate(self) -> Dict[str, float]:
        if self.total_components == 0:
            return {'success_rate': 0.0, 'partial_rate': 0.0, 'not_supported_rate': 0.0}

        status_counts = self.status_summary
        total = self.total_components
        return {
            'success_rate': round((status_counts.get('Success', 0) / total) * 100, 2),
            'partial_rate': round((status_counts.get('Partial', 0) / total) * 100, 2),
            'not_supported_rate': round((status_counts.get('NotSupported', 0) / total) * 100, 2)
        }

    def get_dag_filename(self, package_path: str) -> str:
        """Generate the expected DAG HTML filename for this data flow."""
        package_sanitized = sanitize_filename(package_path)
        # Use full_path for unique filename (handles duplicate names in different containers)
        path_parts = self.full_path.replace('\\', '/').split('/')
        # Skip "Package" prefix and use remaining path for unique naming
        path_parts = [p for p in path_parts if p and p != 'Package']
        unique_suffix = '_'.join(path_parts)
        return f"{package_sanitized}__{sanitize_filename(unique_suffix)}_data_flow.html"
    
    def to_dict(self, package_path: str = None) -> dict:
        result = {
            'name': self.name,
            'full_path': self.full_path,
            'metrics': {
                'total_components': self.total_components,
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
                'not_supported_components': {
                    'total_count': len(self.not_supported_components),
                    'component_types': sorted(self.unique_not_supported_types)
                }
            },
            'components': [c.to_dict() for c in self.components]
        }
        
        # Include DAG file reference if package_path is provided
        if package_path:
            result['dag_file'] = f"dags/{self.get_dag_filename(package_path)}"
        elif self.dag_file:
            result['dag_file'] = self.dag_file
        
        return result

