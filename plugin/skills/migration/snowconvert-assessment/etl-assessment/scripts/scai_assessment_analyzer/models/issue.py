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

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    code: str
    name: str
    description: str
    component_full_name: str
    effort_hours: float
    severity: str

    @property
    def issue_type(self) -> str:
        if 'EWI' in self.code:
            return 'EWI'
        elif 'FDM' in self.code:
            return 'FDM'
        elif 'PRF' in self.code:
            return 'PRF'
        return 'UNKNOWN'

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'type': self.issue_type,
            'description': self.description,
            'severity': self.severity
        }

