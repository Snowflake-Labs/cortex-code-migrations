# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""PDF is a shareable summary. Long lists stay in HTML and the AIM app."""

from __future__ import annotations

import html

# Letter-page body is about this many table rows after header and margins.
PRINT_ROWS_PER_PAGE = 25
EXCLUSION_PRINT_PAGES = 3
ETL_TABLE_PRINT_PAGES = 2
EXCLUSION_PRINT_ROWS = PRINT_ROWS_PER_PAGE * EXCLUSION_PRINT_PAGES
ETL_TABLE_PRINT_ROWS = PRINT_ROWS_PER_PAGE * ETL_TABLE_PRINT_PAGES
# Flagged-object rows wrap, so a row cap is not a page cap. Clip the table to this.
PRINT_CLIP_INCHES_PER_PAGE = 9.5

PDF_FULL_VIEW = (
    "The full view is in the HTML report, or open the assessment in the AIM app."
)


def print_note(lead: str) -> str:
    """Note shown only when printing. ``lead`` is plain text."""
    text = f"{lead} {PDF_FULL_VIEW}".strip()
    return f'<p class="print-only print-note">{html.escape(text)}</p>'


def print_omit_class(index: int, limit: int) -> str:
    return " print-omit" if index >= limit else ""
