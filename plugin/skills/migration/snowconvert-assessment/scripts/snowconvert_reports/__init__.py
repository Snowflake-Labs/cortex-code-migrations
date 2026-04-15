"""snowconvert_reports -- shared data access layer for SnowConvert assessment reports."""

from .na_utils import NA_VALUES, is_na, sanitize_na, strip_na_identifier
from .models import (
    IssueRecord,
    Element,
    TopLevelCodeUnit,
    ObjectReference,
    PartitionMember,
    IssueEstimationEntry,
    SeverityBaseline,
    ObjectEstimation,
)
from .loaders import (
    read_csv_rows,
    load_csv_as,
    load_elements,
    load_issues,
    load_code_units,
    load_object_references,
    load_missing_references,
    load_partition_membership,
    load_issues_estimation_json,
    load_object_estimations,
    parse_graph_summary,
    parse_cycles,
    parse_excluded_edges,
    # Registry loaders
    load_registry_entries,
    build_id_to_name_map,
    load_code_units_from_registry,
    load_object_references_from_registry,
    load_missing_references_from_registry,
    # Unified (auto-dispatch) loaders
    load_code_units_auto,
    load_object_references_auto,
    load_missing_references_auto,
)
from .services import (
    IssueEffortService,
    ReportFinder,
)

__all__ = [
    # N/A utilities
    "NA_VALUES",
    "is_na",
    "sanitize_na",
    "strip_na_identifier",
    # Models
    "IssueRecord",
    "Element",
    "TopLevelCodeUnit",
    "ObjectReference",
    "PartitionMember",
    "IssueEstimationEntry",
    "SeverityBaseline",
    "ObjectEstimation",
    # Loaders
    "read_csv_rows",
    "load_csv_as",
    "load_elements",
    "load_issues",
    "load_code_units",
    "load_object_references",
    "load_missing_references",
    "load_partition_membership",
    "load_issues_estimation_json",
    "load_object_estimations",
    "parse_graph_summary",
    "parse_cycles",
    "parse_excluded_edges",
    # Registry loaders
    "load_registry_entries",
    "build_id_to_name_map",
    "load_code_units_from_registry",
    "load_object_references_from_registry",
    "load_missing_references_from_registry",
    # Unified (auto-dispatch) loaders
    "load_code_units_auto",
    "load_object_references_auto",
    "load_missing_references_auto",
    # Services
    "IssueEffortService",
    "ReportFinder",
]
