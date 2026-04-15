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

"""Issue reference data loader - delegates to shared snowconvert_reports library."""

import sys
from pathlib import Path
from typing import Dict, Optional, Any

# Add shared scripts to path for snowconvert_reports
_scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports import IssueEffortService


class IssueLoader:
    """Delegates to IssueEffortService from the shared library."""

    _service: Optional[IssueEffortService] = None

    @classmethod
    def _get_service(cls) -> IssueEffortService:
        if cls._service is None:
            cls._service = IssueEffortService.from_bundled_reference()
        return cls._service

    @classmethod
    def load_issues(cls) -> Dict[str, Any]:
        service = cls._get_service()
        return {code: {'Code': code, 'Severity': entry.severity, 'ManualEffort': entry.manual_effort, 'FriendlyName': entry.friendly_name}
                for code, entry in service._issue_map.items()}

    @classmethod
    def get_issue_info(cls, code: str) -> Optional[Dict[str, Any]]:
        service = cls._get_service()
        entry = service.get_entry(code)
        if entry is None:
            return None
        return {'Code': entry.code, 'Severity': entry.severity, 'ManualEffort': entry.manual_effort, 'FriendlyName': entry.friendly_name}

    @classmethod
    def clear_cache(cls):
        cls._service = None
