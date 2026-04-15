import sys
from pathlib import Path
from typing import Dict, Tuple

# Add shared scripts to path for snowconvert_reports
_scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports.loaders import read_csv_rows
from ..models import Issue, Component


class IssueRepository:
    def __init__(self, file_path: str, issue_lookup_service):
        self.file_path = Path(file_path)
        self.issue_lookup_service = issue_lookup_service

    def load_and_attach_issues(self, components_by_key: Dict[Tuple[str, str], Component]) -> Tuple[int, int]:
        if not self.file_path.exists():
            raise FileNotFoundError(f"Issues file not found: {self.file_path}")

        matched = 0
        not_matched = 0

        for row in read_csv_rows(self.file_path):
            component_full_name = row.get('ComponentFullName', '').strip()
            if not component_full_name:
                continue

            issue_code = row.get('Code', '').strip()
            effort_hours, severity = self.issue_lookup_service.get_effort_and_severity(issue_code)

            issue = Issue(
                code=issue_code,
                name=row.get('Name', '').strip(),
                description=row.get('Description', '').strip(),
                component_full_name=component_full_name,
                effort_hours=effort_hours,
                severity=severity
            )

            parent_file_name = row.get('ParentFileName', '').strip()
            component_key = (parent_file_name, issue.component_full_name)

            if component_key in components_by_key:
                components_by_key[component_key].issues.append(issue)
                matched += 1
            else:
                not_matched += 1

        return matched, not_matched
