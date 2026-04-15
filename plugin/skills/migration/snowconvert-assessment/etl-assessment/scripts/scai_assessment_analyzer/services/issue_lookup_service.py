import sys
from pathlib import Path
from typing import Tuple

# Add shared scripts to path for snowconvert_reports
_scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports import IssueEffortService


class IssueLookupService:
    def __init__(self, lookup_function=None):
        if lookup_function:
            self._custom_lookup = lookup_function
            self._service = None
        else:
            self._custom_lookup = None
            self._service = IssueEffortService.from_bundled_reference()

    def get_effort_and_severity(self, issue_code: str) -> Tuple[float, str]:
        if self._custom_lookup:
            issue_info = self._custom_lookup(issue_code)
            if not issue_info:
                return 0.0, 'Unknown'
            manual_effort = float(issue_info.get('ManualEffort', 0) or 0)
            severity = issue_info.get('Severity', 'Unknown')
            if manual_effort < 0:
                return 0.0, severity
            if 'EWI' in issue_code:
                return manual_effort / 60.0, severity
            return manual_effort, severity
        return self._service.get_effort_and_severity(issue_code)
