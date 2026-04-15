from dataclasses import dataclass, field
from typing import List, Set, Optional, Dict, Any

from .issue import Issue


@dataclass
class Component:
    full_name: str
    file_name: str
    technology: str
    category: str
    subtype: str
    status: str
    entry_kind: str
    additional_info: str
    issues: List[Issue] = field(default_factory=list)
    sql_task_details: Optional[Dict[str, Any]] = field(default=None)

    def count_issues_by_type(self, issue_type: str) -> int:
        return sum(1 for issue in self.issues if issue.issue_type == issue_type)

    def unique_issues_by_type(self, issue_type: str) -> Set[str]:
        return {issue.code for issue in self.issues if issue.issue_type == issue_type}

    @property
    def ewi_count(self) -> int:
        return self.count_issues_by_type('EWI')

    @property
    def fdm_count(self) -> int:
        return self.count_issues_by_type('FDM')

    @property
    def prf_count(self) -> int:
        return self.count_issues_by_type('PRF')

    @property
    def unique_ewis(self) -> Set[str]:
        return self.unique_issues_by_type('EWI')

    @property
    def unique_fdms(self) -> Set[str]:
        return self.unique_issues_by_type('FDM')

    @property
    def unique_prfs(self) -> Set[str]:
        return self.unique_issues_by_type('PRF')

    def to_dict(self, override_category: str = None) -> dict:
        result = {
            'full_name': self.full_name,
            'category': override_category or self.category,
            'subtype': self.subtype,
            'status': self.status,
            'entry_kind': self.entry_kind,
            'additional_info': self.additional_info,
            'issue_counts': {
                'ewis': self.ewi_count,
                'fdms': self.fdm_count,
                'prfs': self.prf_count
            },
            'issues': [issue.to_dict() for issue in self.issues]
        }
        
        # Include SQL task details for ExecuteSQLTask components
        if self.sql_task_details:
            result['sql_task_details'] = self.sql_task_details
        
        return result

