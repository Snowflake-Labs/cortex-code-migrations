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

"""Snowflake documentation link for a SnowConvert issue code, as browser JS.

One source for every static HTML report that links an EWI, FDM, PRF or OOS code:
the waves report's object details and the effort tab's EWI breakdown both inline
it. It is plain JS with single braces; interpolate it whole into an f-string so
it is never parsed as replacement fields. It declares top-level ``const``s, so
inline it once per script scope (the effort mixin wraps it in its own IIFE).
"""

# Keep in step with ISSUE_DOC_FAMILY in dashboard-ui snowconvertIssueDescriptions.ts.
ISSUE_DOCUMENTATION_URL_JS = r"""
        const ISSUE_DOCS_ROOT = 'https://docs.snowflake.com/en/migrations/aim-for-datawarehouses/code-conversion/issues-and-troubleshooting';
        const DIALECT_PAGE_STEM = {
            BQ: 'bigquery', DB: 'db2', HV: 'hive', INF: 'informatica', OR: 'oracle',
            PG: 'postgresql', RS: 'redshift', SPK: 'spark', SSIS: 'ssis', SY: 'sybase',
            TD: 'teradata', TS: 'sqlServer', VT: 'vertica',
        };
        const ISSUE_DOC_FAMILY = {
            EWI: { folder: 'conversion-issues', suffix: 'EWI', dialects: null },
            FDM: { folder: 'functional-difference', suffix: 'FDM', dialects: null },
            PRF: { folder: 'performance-review', suffix: 'PRF', dialects: ['OR', 'TS'] },
            OOS: { folder: 'out-of-scope', suffix: 'OOS', dialects: [] },
        };

        function issueDocumentationUrl(code) {
            const match = /^SSC-(EWI|FDM|PRF|OOS)-([A-Z]*)\d+$/i.exec(String(code || '').trim());
            if (!match) return '';
            const family = ISSUE_DOC_FAMILY[match[1].toUpperCase()];
            if (!family) return '';
            const infix = match[2].toUpperCase();
            const stem = DIALECT_PAGE_STEM[infix];
            const hasDialectPage = stem && (family.dialects === null || family.dialects.indexOf(infix) !== -1);
            const page = hasDialectPage ? stem + family.suffix : 'general' + family.suffix;
            return ISSUE_DOCS_ROOT + '/' + family.folder + '/' + page + '#' + String(code).trim().toLowerCase();
        }
"""
