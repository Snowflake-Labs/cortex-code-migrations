from dataclasses import dataclass


@dataclass(frozen=True)
class IssueEstimationEntry:
    """A single issue from IssuesEstimation.*.json -> Issues[]."""

    code: str
    severity: str
    manual_effort: float
    friendly_name: str

    @staticmethod
    def from_dict(d: dict) -> "IssueEstimationEntry":
        effort = d.get("ManualEffort", 0)
        return IssueEstimationEntry(
            code=d.get("Code", ""),
            severity=d.get("Severity", "Unknown"),
            manual_effort=0.0 if effort == -1 else float(effort or 0),
            friendly_name=d.get("FriendlyName", ""),
        )


@dataclass(frozen=True)
class SeverityBaseline:
    """A severity baseline from IssuesEstimation.*.json -> Severities[]."""

    severity: str
    manual_effort: float

    @staticmethod
    def from_dict(d: dict) -> "SeverityBaseline":
        return SeverityBaseline(
            severity=d.get("Severity", ""),
            manual_effort=float(d.get("ManualEffort", 0) or 0),
        )


@dataclass(frozen=True)
class ObjectEstimation:
    """A single row from TopLevelObjectsEstimation.*.csv."""

    object_id: str
    manual_effort_minutes: float
    conversion_status: str
    ewis_number: int
    highest_ewi_severity: str

    @staticmethod
    def from_csv_row(row: dict[str, str]) -> "ObjectEstimation":
        def safe_float(val: str) -> float:
            try:
                return float(val) if val else 0.0
            except ValueError:
                return 0.0

        def safe_int(val: str) -> int:
            try:
                return int(val) if val else 0
            except ValueError:
                return 0

        return ObjectEstimation(
            object_id=row.get("Object Id", "").strip(),
            manual_effort_minutes=safe_float(
                row.get("Manual Effort", "0").strip()
            ),
            conversion_status=row.get("ConversionStatus", "").strip(),
            ewis_number=safe_int(row.get("EWIsNumber", "0").strip()),
            highest_ewi_severity=row.get("HighestEWISeverity", "").strip(),
        )
