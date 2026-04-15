from pathlib import Path
from typing import Optional

from ..models import IssueRecord
from .csv_reader import load_csv_as


def load_issues(
    csv_path: str | Path,
    *,
    filter_code: Optional[str] = None,
) -> list[IssueRecord]:
    """Load issues from Issues.csv, optionally filtering by issue code."""

    def factory(row: dict[str, str]) -> IssueRecord | None:
        record = IssueRecord.from_csv_row(row)
        if filter_code and record.code != filter_code:
            return None
        return record

    return load_csv_as(csv_path, factory)
