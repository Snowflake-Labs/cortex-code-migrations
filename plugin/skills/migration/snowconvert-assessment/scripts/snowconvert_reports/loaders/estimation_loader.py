import json
from pathlib import Path

from ..models import IssueEstimationEntry, ObjectEstimation, SeverityBaseline
from .csv_reader import load_csv_as


def load_issues_estimation_json(
    json_path: str | Path,
) -> tuple[dict[str, IssueEstimationEntry], dict[str, SeverityBaseline]]:
    """Load IssuesEstimation.*.json, returning issue_map and severity_map."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    issue_map = {}
    for entry_dict in data.get("Issues", []):
        entry = IssueEstimationEntry.from_dict(entry_dict)
        issue_map[entry.code] = entry

    severity_map = {}
    for entry_dict in data.get("Severities", []):
        entry = SeverityBaseline.from_dict(entry_dict)
        severity_map[entry.severity] = entry

    return issue_map, severity_map


def load_object_estimations(csv_path: str | Path) -> list[ObjectEstimation]:
    """Load TopLevelObjectsEstimation.*.csv."""
    return load_csv_as(csv_path, ObjectEstimation.from_csv_row)
