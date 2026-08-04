# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the permissions and limitations under the License.

"""Migration effort estimation using flat phase budgets and LOC-based partial formulas."""

from __future__ import annotations

import csv
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Maps display names in Base_estimates CSV → TopLevelCodeUnits Category
_OBJECT_TYPE_MAP = {
    "tables": "TABLE",
    "views": "VIEW",
    "functions": "FUNCTION",
    "stored procedures": "PROCEDURE",
}

# Categories excluded from object counts and effort (not migratable DDL inventory)
_SKIP_EFFORT_CATEGORIES = frozenset({
    "OUT OF SCOPE",
    "SESSION / BATCH CONTROL",
})

_SKIP_DDL_CATEGORIES = set(_SKIP_EFFORT_CATEGORIES)

# Migration effort calculator (flat budgets + LOC-based partials)
_TABLE_FLAT_HOURS = 80.0
_PROC_SUCCESS_FLAT_HOURS = 160.0
_SYNONYM_FLAT_HOURS = 4.0
_SUCCESS_REVIEW_HOURS = 0.1
_ISSUE_SEVERITY_HOURS = {"high": 0.5, "critical": 1.5}
# Fallback dataclass defaults only. Base_estimates.csv's `meta` rows
# (workload_small_max_objects / workload_medium_max_objects) are the single
# source of truth and override these whenever the CSV loads successfully; keep
# both in sync if the bundled CSV's tier thresholds ever change.
_WORKLOAD_SIZE_SMALL_MAX = 500
_WORKLOAD_SIZE_MEDIUM_MAX = 1500

_HOURS_PER_WORK_DAY = 8.0

# Shares the ``.nav-preview-badge`` CSS class defined in generate_multi_report.py's
# stylesheet (embedded in the same HTML page) so the badge markup is defined once.
EFFORT_PREVIEW_BADGE_HTML = '<span class="nav-preview-badge">Preview</span>'

EFFORT_DISCLAIMER_HTML = (
    '<p style="color: #0369A1; background: #F0F9FF; border: 1px solid #BAE6FD; '
    'border-radius: 8px; padding: 12px 14px; font-size: 0.88rem; line-height: 1.5; '
    'margin-bottom: 20px;">'
    "<strong>Disclaimer:</strong> These estimates are a best-effort recommendation only. "
    "Actual effort may vary based on project scope, team experience, data quality, "
    "and migration complexity."
    "</p>"
)
_DDL_EXCLUDED_DISPLAY_TYPES = frozenset({"Index", "Flow Control"})
_DATA_MIGRATION_FLAT_HOURS = 8.0
DEFAULT_BASE_ESTIMATES_CSV = Path(__file__).parent / "Base_estimates.csv"
_FIXED_BUDGET_COMPONENTS = frozenset(
    {
        "Fixed Budget",
        "Data Migration",
        "Optimization",
        "Integration Testing",
        "Integration Testing Bug Fix",
        "UAT",
        "Delivery",
    }
)

_CATEGORY_DISPLAY = {
    "TABLE": "Table",
    "EXTERNAL TABLE": "External Table",
    "VIEW": "View",
    "MATERIALIZED VIEW": "Materialized View",
    "PROCEDURE": "Procedure",
    "FUNCTION": "Function",
    "INDEX": "Index",
    "SYNONYM": "Synonym",
    "SCHEMA": "Schema",
    "TYPE": "Type",
    "DATABASE": "Database",
}

_DDL_NOTES = {
    "Synonym": "Replace with Snowflake aliases or views; flat effort in Fixed Budget",
}

_CALCULATOR_TO_DDL = {
    "tables": "Table",
    "views": "View",
    "functions": "Function",
    "stored procedures": "Procedure",
}


# SnowConvert ``SourceLanguage`` values and common aliases for SQL Server / T-SQL.
_SQL_SERVER_DIALECT_VALUES = frozenset({
    "transact",
    "sql server",
    "sqlserver",
    "t-sql",
    "tsql",
    "t sql",
    "mssql",
    "ms sql",
    "microsoft sql server",
})

# SnowConvert ``SourceLanguage`` values and common aliases for Amazon Redshift.
_REDSHIFT_DIALECT_VALUES = frozenset({
    "redshift",
    "amazon redshift",
    "aws redshift",
})

# effort dialect key → the frozenset of source_language values that map to it
_DIALECT_VALUE_SETS: Dict[str, frozenset] = {
    "sqlserver": _SQL_SERVER_DIALECT_VALUES,
    "redshift": _REDSHIFT_DIALECT_VALUES,
}

# Each dialect's rates are tuned independently, so each gets its own bundled CSV.
_DIALECT_BASE_ESTIMATES = {
    "sqlserver": "Base_estimates.csv",
    "redshift": "Base_estimates.redshift.csv",
}


def _normalize_dialect(dialect: str) -> str:
    return re.sub(r"[\s_\-]+", " ", (dialect or "").strip().lower())


def resolve_effort_dialect(source_language: str) -> Optional[str]:
    """Map a project ``source_language`` to a supported effort dialect key.

    Returns ``"sqlserver"``, ``"redshift"``, or ``None`` for unsupported dialects.
    Matches the whole normalized string against a set (no substring matching), so a
    word merely containing a dialect name never enables the feature.
    """
    normalized = _normalize_dialect(source_language)
    if not normalized:
        return None
    for key, values in _DIALECT_VALUE_SETS.items():
        if normalized in values:
            return key
    return None


def read_project_source_language(project_dir: Optional[Path]) -> str:
    """Read ``source_language`` from ``{project_dir}/.scai/config/project.yml``.

    ``project.yml`` is a flat ``key: value`` document, so a dependency-free line reader
    is used (PyYAML is not available in the assessment environment). Returns ``""`` when
    ``project_dir`` is falsy, the file is absent/unreadable, or the key is missing.
    """
    if not project_dir:
        return ""
    yml = Path(project_dir) / ".scai" / "config" / "project.yml"
    if not yml.exists():
        return ""
    try:
        for line in yml.read_text(encoding="utf-8-sig").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, _, value = stripped.partition(":")
            if key.strip() == "source_language":
                return value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _default_base_estimates_for(dialect_key: str) -> Path:
    """Resolve the bundled Base_estimates CSV for a dialect key."""
    filename = _DIALECT_BASE_ESTIMATES.get(dialect_key, "Base_estimates.csv")
    return Path(__file__).parent / filename


def is_effort_estimation_supported(project_dir: Path) -> bool:
    """Return True when the project's ``source_language`` is a supported effort dialect.

    Dialect is read exclusively from ``{project_dir}/.scai/config/project.yml``. Runs
    without a project directory are unsupported and produce no effort tab.
    """
    return resolve_effort_dialect(read_project_source_language(project_dir)) is not None


def classify_workload_size(
    total_objects: int,
    config: Optional[EffortEstimateConfig] = None,
) -> str:
    """Map total workload object count to Small / Medium / Large tier."""
    cfg = config or get_effort_estimate_config()
    if total_objects <= cfg.workload_small_max:
        return "small"
    if total_objects <= cfg.workload_medium_max:
        return "medium"
    return "large"


def workload_size_label(
    tier: str,
    config: Optional[EffortEstimateConfig] = None,
) -> str:
    """Human-readable workload tier label for overview UI."""
    cfg = config or get_effort_estimate_config()
    labels = {
        "small": f"Small (up to {cfg.workload_small_max:,} objects)",
        "medium": (
            f"Medium ({cfg.workload_small_max + 1:,}"
            f"–{cfg.workload_medium_max:,} objects)"
        ),
        "large": f"Large (more than {cfg.workload_medium_max:,} objects)",
    }
    return labels.get(tier, tier.title())


def count_workload_objects(ddl_summary: Dict[str, Dict[str, Any]]) -> int:
    """Count migratable objects used for workload tier sizing."""
    return sum(
        st.get("total", 0)
        for name, st in ddl_summary.items()
        if name not in _DDL_EXCLUDED_DISPLAY_TYPES
    )


def compute_tiered_phase_budgets(
    total_objects: int,
    config: Optional[EffortEstimateConfig] = None,
) -> Dict[Tuple[str, str], float]:
    """Return phase fixed budgets scaled by workload size tier.

    Keyed by (component, object_type) lowercased display labels — not the CSV
    ``Key`` slug — so callers can look up a phase the same way it's rendered.
    """
    cfg = config or get_effort_estimate_config()
    tier = classify_workload_size(total_objects, cfg)
    return {
        (phase.component.lower(), phase.object_type.lower()): phase.hours_by_tier[tier]
        for phase in cfg.phase_budgets
    }


def _parse_tier_to_min_pct(tier_str: str) -> int:
    t = tier_str.strip().lower()
    if "full" in t:
        return 100
    if "partially" in t:
        return 0
    m = re.search(r"(\d+)\s*[-–]\s*\d+\s*%", t)
    if m:
        return int(m.group(1))
    return 0


def _loc_pct_is_measured(loc_pct_str: str) -> bool:
    """True when the report actually carries a parseable LoC conversion percentage.

    ``_parse_loc_pct`` infers 100% from ``ConversionStatus == Success`` when the cell is
    missing, which is fine for tier bucketing but must not drive an effort discount —
    otherwise absent data reads as perfect conversion and zeroes the budget.
    """
    return bool(loc_pct_str) and bool(re.sub(r"[^0-9.]", "", str(loc_pct_str)))


def _parse_loc_pct(loc_pct_str: str, conversion_status: str) -> float:
    if loc_pct_str:
        cleaned = re.sub(r"[^0-9.]", "", str(loc_pct_str))
        if cleaned:
            return float(cleaned)
    status = str(conversion_status).strip().lower()
    if status == "success":
        return 100.0
    if status in ("failure", "notsupported", "not supported"):
        return 0.0
    return 0.0


def _conversion_bucket(category: str, pct: float) -> str:
    """Map an object to a tier bucket key used for quantity counting."""
    cat = category.upper()
    if cat in ("TABLE", "VIEW", "FUNCTION"):
        return "full" if pct >= 100 else "partial"
    if cat == "PROCEDURE":
        if pct >= 100:
            return "full"
        if pct >= 75:
            return "75-99"
        if pct >= 50:
            return "50-75"
        if pct >= 25:
            return "25-50"
        return "0-25"
    return "partial"


def _normalize_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "success":
        return "Success"
    if s in ("partial", "action required", "actionrequired"):
        return "Partial"
    if s in ("notsupported", "not supported", "failure"):
        return "Unsupported"
    return "Partial"


@dataclass
class CalculatorRow:
    component: str
    object_type: str
    quantity: Any  # int, float, or display str
    baseline_hours: float
    total_baseline_hours: float
    fde_hours: float
    comments: str = ""
    # Pre-weighting hours, so the summary can report what conversion automation saved.
    unweighted_fde_hours: float = 0.0


@dataclass(frozen=True)
class PhaseBudgetTemplate:
    key: str
    component: str
    object_type: str
    hours_by_tier: Dict[str, float]


@dataclass(frozen=True)
class CalculatorRowTemplate:
    key: str
    component: str
    object_type: str
    quantity_rule: str
    baseline_hours: float
    comments: str = ""


@dataclass
class EffortEstimateConfig:
    workload_small_max: int = _WORKLOAD_SIZE_SMALL_MAX
    workload_medium_max: int = _WORKLOAD_SIZE_MEDIUM_MAX
    tables_views_flat_hours: float = 4.0
    code_conversion_per_object_hours: float = 1.0
    data_migration_flat_hours: float = _DATA_MIGRATION_FLAT_HOURS
    conversion_weighted: bool = False
    phase_budgets: Tuple[PhaseBudgetTemplate, ...] = ()
    calculator_rows: Tuple[CalculatorRowTemplate, ...] = ()


_CONFIG_CACHE: Dict[str, EffortEstimateConfig] = {}


def _parse_config_float(value: Any, default: float = 0.0) -> float:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning(
            "Base_estimates.csv: could not parse numeric value %r; using default %s",
            value,
            default,
        )
        return default


def _parse_config_int(value: Any, default: int = 0) -> int:
    return int(_parse_config_float(value, float(default)))


def load_effort_estimate_config(csv_path: Path) -> EffortEstimateConfig:
    """Load calculator templates, rates, and workload tier thresholds from CSV."""
    path = Path(csv_path)
    cache_key = str(path.resolve())
    if cache_key in _CONFIG_CACHE:
        return _CONFIG_CACHE[cache_key]

    cfg = EffortEstimateConfig()
    phase_rows: List[PhaseBudgetTemplate] = []
    calculator_rows: List[CalculatorRowTemplate] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            section = (row.get("Section") or "").strip().lower()
            key = (row.get("Key") or "").strip()
            if not section:
                continue

            if section == "meta":
                if key == "workload_small_max_objects":
                    cfg.workload_small_max = _parse_config_int(
                        row.get("Small"), cfg.workload_small_max
                    )
                elif key == "workload_medium_max_objects":
                    cfg.workload_medium_max = _parse_config_int(
                        row.get("Medium"), cfg.workload_medium_max
                    )
                elif key == "conversion_weighted":
                    cfg.conversion_weighted = _parse_config_int(row.get("Small")) == 1
                continue

            if section == "rate":
                baseline = _parse_config_float(row.get("Baseline Hours"))
                if key == "tables_views_flat":
                    cfg.tables_views_flat_hours = baseline
                elif key == "code_conversion_per_object":
                    cfg.code_conversion_per_object_hours = baseline
                elif key == "data_migration_flat":
                    cfg.data_migration_flat_hours = baseline
                continue

            if section == "phase":
                phase_rows.append(
                    PhaseBudgetTemplate(
                        key=key,
                        component=(row.get("Migration Component") or "").strip(),
                        object_type=(row.get("Object Type") or "").strip(),
                        hours_by_tier={
                            "small": _parse_config_float(row.get("Small")),
                            "medium": _parse_config_float(row.get("Medium")),
                            "large": _parse_config_float(row.get("Large")),
                        },
                    )
                )
                continue

            if section == "calculator":
                calculator_rows.append(
                    CalculatorRowTemplate(
                        key=key,
                        component=(row.get("Migration Component") or "").strip(),
                        object_type=(row.get("Object Type") or "").strip(),
                        quantity_rule=(row.get("Quantity Rule") or "").strip().lower(),
                        baseline_hours=_parse_config_float(row.get("Baseline Hours")),
                        comments=(row.get("Comments") or "").strip(),
                    )
                )

    cfg.phase_budgets = tuple(phase_rows)
    cfg.calculator_rows = tuple(calculator_rows)
    _CONFIG_CACHE[cache_key] = cfg
    return cfg


def get_effort_estimate_config(
    csv_path: Optional[Path] = None,
) -> EffortEstimateConfig:
    """Return cached effort config, defaulting to bundled Base_estimates.csv."""
    return load_effort_estimate_config(csv_path or DEFAULT_BASE_ESTIMATES_CSV)


def _find_toplevel_code_units_csv(reports_dir: Path) -> Optional[Path]:
    reports_dir = Path(reports_dir)
    dirs = [reports_dir]
    sub = reports_dir / "SnowConvert"
    if sub.exists():
        dirs.append(sub)
    for d in dirs:
        for pattern in ("TopLevelCodeUnits.NA.csv", "TopLevelCodeUnits.*.csv"):
            matches = list(d.glob(pattern))
            if matches:
                return matches[0]
    return None


def _find_report_csv(reports_dir: Path, base_name: str) -> Optional[Path]:
    reports_dir = Path(reports_dir)
    dirs = [reports_dir]
    sub = reports_dir / "SnowConvert"
    if sub.exists():
        dirs.append(sub)
    for d in dirs:
        for pattern in (f"{base_name}.NA.csv", f"{base_name}.*.csv"):
            matches = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return matches[0]
    return None


def _csv_field(row: dict, *names: str) -> str:
    for name in names:
        for key, val in row.items():
            if key.strip().lower() == name.lower():
                return str(val or "").strip()
    return ""


def _severity_bucket(severity: str) -> str:
    s = (severity or "").strip().lower()
    if s in ("none", "info"):
        return "none_info"
    if s == "low":
        return "low"
    if s == "medium":
        return "medium"
    if s == "high":
        return "high"
    if s == "critical":
        return "critical"
    return "none_info"


def _new_ddl_row() -> Dict[str, Any]:
    return {
        "total": 0,
        "success": 0,
        "partial": 0,
        "unsupported": 0,
        "lines_of_code": 0,
        "issues_none_info": 0,
        "issues_low": 0,
        "issues_medium": 0,
        "issues_high": 0,
        "issues_critical": 0,
        "effort_hours": 0.0,
        "notes": "",
        "pct_auto": 0.0,
    }


def merge_issue_counts_into_ddl(
    ddl_summary: Dict[str, Dict[str, Any]],
    issues_path: Path,
    code_unit_map: Dict[str, str],
) -> None:
    """Attach Issues.csv severity counts to each DDL object type."""
    with open(issues_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cu_id = _csv_field(row, "CodeUnitId", "Code Unit Id")
            category = code_unit_map.get(cu_id, "")
            if not category:
                continue
            display = _CATEGORY_DISPLAY.get(category, category.title())
            if display not in ddl_summary:
                continue
            bucket = _severity_bucket(_csv_field(row, "Severity"))
            key = f"issues_{bucket}"
            if key in ddl_summary[display]:
                ddl_summary[display][key] += 1


def build_top_ddl_issues(issues_path: Optional[Path], limit: int = 10) -> List[Dict[str, Any]]:
    if not issues_path or not issues_path.exists():
        return []
    counts: Counter[str] = Counter()
    meta: Dict[str, Dict[str, str]] = {}
    with open(issues_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = _csv_field(row, "Code")
            if not code:
                continue
            counts[code] += 1
            if code not in meta:
                meta[code] = {
                    "code": code,
                    "name": _csv_field(row, "Name"),
                    "severity": _csv_field(row, "Severity") or "—",
                }
    result = []
    for code, count in counts.most_common(limit):
        entry = dict(meta[code])
        entry["occurrences"] = count
        result.append(entry)
    return result


def assign_ddl_effort_from_calculator(
    ddl_summary: Dict[str, Dict[str, Any]],
    calculator_rows: List[CalculatorRow],
) -> None:
    """Sum FDE hours from calculator tiers into DDL object types."""
    for row in calculator_rows:
        comp = row.component.strip().lower()
        if not comp.startswith("code conversion"):
            continue
        m = re.match(r"^(.+?)\s*\(", row.object_type, re.I)
        if not m:
            continue
        display = _CALCULATOR_TO_DDL.get(m.group(1).strip().lower())
        if display and display in ddl_summary:
            ddl_summary[display]["effort_hours"] += row.fde_hours
    for display, note in _DDL_NOTES.items():
        if display in ddl_summary and not ddl_summary[display]["notes"]:
            ddl_summary[display]["notes"] = note


def _exclude_effort_category(category: str) -> bool:
    return category.upper() in _SKIP_EFFORT_CATEGORIES


def _partial_effort_hours(category: str, loc: int) -> float:
    """Partial-conversion effort (50% testing-framework discount already applied)."""
    if category == "PROCEDURE":
        return 0.25 if loc < 50 else 0.50
    if loc < 50:
        return 0.25
    if loc <= 200:
        return 0.50
    return 1.25


def count_quantities_from_code_units(
    csv_path: Path,
) -> Tuple[Dict[str, int], Dict[str, Any], Dict[str, str]]:
    """Count unique CodeUnitId per tier and build DDL summary (migration inventory rules).

    Excludes SESSION / BATCH CONTROL and OUT OF SCOPE rows. Each CodeUnitId is
    counted once (duplicate CSV rows from batch/session artifacts are ignored).

    Also returns a CodeUnitId → Category map built in this same pass, so callers
    merging in Issues.csv counts (see ``merge_issue_counts_into_ddl``) don't need
    a second full scan of the same CSV just to look up categories.
    """
    tier_counts: Dict[str, int] = {}
    ddl: Dict[str, Dict[str, Any]] = {}
    code_unit_categories: Dict[str, str] = {}
    seen_ids: set[str] = set()

    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            category = _csv_field(row, "Category").upper()
            if not category or _exclude_effort_category(category) or category in ("INDEX", "FLOW CONTROL"):
                continue
            cu_id = _csv_field(row, "CodeUnitId", "Code Unit Id")
            if not cu_id or cu_id in seen_ids:
                continue
            seen_ids.add(cu_id)
            code_unit_categories[cu_id] = category

            loc_pct_cell = _csv_field(row, "LoCConversionPercentage")
            pct = _parse_loc_pct(loc_pct_cell, _csv_field(row, "ConversionStatus"))
            pct_measured = _loc_pct_is_measured(loc_pct_cell)
            status = _normalize_status(_csv_field(row, "ConversionStatus"))
            try:
                loc = int(_csv_field(row, "Lines of Code", "LinesOfCode") or 0)
            except ValueError:
                loc = 0

            if category in _OBJECT_TYPE_MAP.values():
                bucket = _conversion_bucket(category, pct)
                obj_label = next(
                    (k for k, v in _OBJECT_TYPE_MAP.items() if v == category),
                    category.lower(),
                )
                tier_label = _tier_label_for_bucket(bucket)
                key = f"{obj_label} ({tier_label})".lower()
                tier_counts[key] = tier_counts.get(key, 0) + 1

            cat_key = _CATEGORY_DISPLAY.get(category, category.title())
            if cat_key not in ddl:
                ddl[cat_key] = _new_ddl_row()
            ddl[cat_key]["total"] += 1
            if status == "Success":
                ddl[cat_key]["success"] += 1
            elif status == "Unsupported":
                ddl[cat_key]["unsupported"] += 1
            else:
                ddl[cat_key]["partial"] += 1
            ddl[cat_key]["lines_of_code"] += loc
            ddl[cat_key].setdefault("_objects", []).append(
                {
                    "category": category,
                    "status": status,
                    "loc": loc,
                    "pct": pct,
                    "pct_measured": pct_measured,
                }
            )

    for stats in ddl.values():
        total = stats["total"]
        stats["pct_auto"] = round(stats["success"] / total, 4) if total else 0.0

    return tier_counts, ddl, code_unit_categories


def _per_object_ddl_effort(display: str, obj: Dict[str, Any]) -> float:
    """Incremental per-object DDL effort for object types without a flat table/view budget."""
    cat = obj["category"]
    loc = obj["loc"]
    status = obj["status"]
    effort = 0.0
    if status == "Partial":
        effort = _partial_effort_hours(cat, loc)
    elif status == "Success" and display not in ("Procedure",):
        effort = _SUCCESS_REVIEW_HOURS
    return effort


def _table_view_flat_effort(
    stats: Dict[str, Any],
    config: Optional[EffortEstimateConfig] = None,
) -> float:
    """Flat conversion effort for all tables or all views when at least one object exists."""
    cfg = config or get_effort_estimate_config()
    return cfg.tables_views_flat_hours if stats.get("total", 0) else 0.0


def _code_conversion_object_effort(
    stats: Dict[str, Any],
    config: Optional[EffortEstimateConfig] = None,
) -> float:
    """Flat per-object code conversion effort (functions and stored procedures)."""
    cfg = config or get_effort_estimate_config()
    return round(stats.get("total", 0) * cfg.code_conversion_per_object_hours, 2)


# Code-conversion calculator quantity rules → the DDL display type they cost.
_CODE_CONVERSION_RULE_TO_DISPLAY = {
    "ddl_table_count": "Table",
    "ddl_view_count": "View",
    "ddl_external_table_count": "External Table",
    "ddl_materialized_view_count": "Materialized View",
    "ddl_function_count": "Function",
    "ddl_procedure_count": "Procedure",
}

# DDL display types priced as a single flat budget for the whole category.
_ALWAYS_FLAT_CODE_CONVERSION_TYPES = frozenset({"Table", "View"})

# Flat only for dialects whose CSV declares the matching calculator row. Pricing these
# flat without that row moves the DDL breakdown without moving the calculator total the
# Overview card reads, so the two tables would disagree.
_CSV_GATED_FLAT_CODE_CONVERSION_TYPES = frozenset(
    {"External Table", "Materialized View"}
)

_FLAT_CATEGORY_LABELS = {
    "External Table": "external tables",
    "Materialized View": "materialized views",
}


def _flat_code_conversion_types(config: EffortEstimateConfig) -> FrozenSet[str]:
    """DDL display types this dialect prices as one flat budget for the whole category."""
    declared = {
        _CODE_CONVERSION_RULE_TO_DISPLAY.get(tmpl.quantity_rule)
        for tmpl in config.calculator_rows
    }
    return _ALWAYS_FLAT_CODE_CONVERSION_TYPES | (
        _CSV_GATED_FLAT_CODE_CONVERSION_TYPES & declared
    )


def _object_manual_fractions(stats: Dict[str, Any]) -> List[float]:
    """Per-object share still needing manual work, clamped to [0, 1].

    An object whose LoC conversion percentage was never measured counts as fully manual:
    the alternative credits automation for data the report does not contain.
    """
    fractions: List[float] = []
    for o in stats.get("_objects", []):
        if not o.get("pct_measured", False):
            fractions.append(1.0)
            continue
        fractions.append(min(1.0, max(0.0, 1.0 - (o.get("pct", 0.0) / 100.0))))
    return fractions


def _type_manual_fraction(stats: Dict[str, Any], flat_budget: bool = False) -> float:
    """Share of an object type's budget still needing manual work.

    ``1.0`` means nothing auto-converted (full budget), ``0.0`` means SnowConvert
    converted everything (no manual effort).

    Per-object types use the mean, which is identical to summing
    ``baseline × (1 - conversion_rate)`` over the objects.

    Flat-budget types are all-or-nothing. Their rate is one budget for the whole
    category "regardless of count", so a mean would price the same unconverted object at
    the full budget when it stands alone and at ~0 among converted siblings — 4.0h vs
    0.04h for one failed table among 99 successes, and exactly 0.0h among 999.
    """
    fractions = _object_manual_fractions(stats)
    if not fractions:
        return 1.0
    if flat_budget:
        return 1.0 if any(f > 0.0 for f in fractions) else 0.0
    return sum(fractions) / len(fractions)


def _ddl_notes_for_display(
    display: str,
    config: EffortEstimateConfig,
    flat_types: FrozenSet[str],
) -> str:
    if display == "Table":
        return (
            f"Flat {config.tables_views_flat_hours:.0f}h for all tables "
            "(half business day)"
        )
    if display == "View":
        return (
            f"Flat {config.tables_views_flat_hours:.0f}h for all views "
            "(half business day)"
        )
    if display in _CSV_GATED_FLAT_CODE_CONVERSION_TYPES and display in flat_types:
        return (
            f"Flat {config.tables_views_flat_hours:.0f}h for all "
            f"{_FLAT_CATEGORY_LABELS[display]}"
        )
    if display == "Function":
        return f"{config.code_conversion_per_object_hours:g}h per function"
    if display == "Procedure":
        return f"{config.code_conversion_per_object_hours:g}h per stored procedure"
    return ""


def compute_fixed_budget_items(
    ddl_summary: Dict[str, Dict[str, Any]],
    total_objects: Optional[int] = None,
    config: Optional[EffortEstimateConfig] = None,
) -> Dict[str, float]:
    """Flat migration budgets shown separately from per-object DDL effort."""
    cfg = config or get_effort_estimate_config()
    if total_objects is None:
        total_objects = count_workload_objects(ddl_summary)
    tier = classify_workload_size(total_objects, cfg)
    items: Dict[str, float] = {}
    if ddl_summary.get("Synonym", {}).get("total", 0):
        items["Synonym conversion"] = _SYNONYM_FLAT_HOURS
    items["Data migration (DMVA)"] = cfg.data_migration_flat_hours
    items["Data refresh and validation"] = cfg.data_migration_flat_hours
    for phase in cfg.phase_budgets:
        label = f"{phase.component} — {phase.object_type}"
        items[label] = phase.hours_by_tier[tier]
    return items


def compute_ddl_effort(
    ddl_summary: Dict[str, Dict[str, Any]],
    config: Optional[EffortEstimateConfig] = None,
) -> None:
    """Apply per-object DDL effort for the conversion assessment table."""
    cfg = config or get_effort_estimate_config()
    flat_types = _flat_code_conversion_types(cfg)
    for display in list(ddl_summary.keys()):
        if display in _DDL_EXCLUDED_DISPLAY_TYPES:
            ddl_summary.pop(display, None)
            continue

        stats = ddl_summary[display]
        stats["effort_hours"] = 0.0
        objects = stats.get("_objects", [])

        note = _DDL_NOTES.get(display) or _ddl_notes_for_display(display, cfg, flat_types)
        if note:
            stats["notes"] = note

        if display in flat_types:
            stats["effort_hours"] = _table_view_flat_effort(stats, cfg)
        elif display in ("Function", "Procedure"):
            stats["effort_hours"] = _code_conversion_object_effort(stats, cfg)
        else:
            for obj in objects:
                stats["effort_hours"] += _per_object_ddl_effort(display, obj)
            stats["effort_hours"] += (
                stats.get("issues_high", 0) * _ISSUE_SEVERITY_HOURS["high"]
                + stats.get("issues_critical", 0) * _ISSUE_SEVERITY_HOURS["critical"]
            )

        # Scale code-conversion effort by the un-converted share so the breakdown
        # matches the weighted calculator (fully auto-converted types read 0h).
        if cfg.conversion_weighted and display in _CODE_CONVERSION_RULE_TO_DISPLAY.values():
            stats["effort_hours"] *= _type_manual_fraction(
                stats, flat_budget=display in flat_types
            )

        stats["effort_hours"] = round(stats["effort_hours"], 2)


def _calc_row(
    component: str,
    object_type: str,
    quantity: Any,
    baseline: float,
    total_baseline: float,
    fde: float,
    comments: str = "",
) -> CalculatorRow:
    return CalculatorRow(
        component=component,
        object_type=object_type,
        quantity=quantity,
        baseline_hours=baseline,
        total_baseline_hours=round(total_baseline, 2),
        fde_hours=round(fde, 2),
        comments=comments,
        unweighted_fde_hours=round(fde, 2),
    )


def _calculator_code_conversion_fde(
    fde_mode: str,
    tier_key: str,
    qty: int,
    tier_counts: Dict[str, int],
    ddl_summary: Dict[str, Dict[str, Any]],
) -> float:
    """Compute FDE hours for one code-conversion calculator row."""
    if fde_mode == "flat_zero":
        return 0.0
    if fde_mode == "flat_table":
        return _TABLE_FLAT_HOURS if ddl_summary.get("Table", {}).get("total", 0) else 0.0
    if fde_mode == "flat_proc":
        return _PROC_SUCCESS_FLAT_HOURS if qty else 0.0
    if fde_mode == "success_review":
        return qty * _SUCCESS_REVIEW_HOURS
    if fde_mode == "partial_view":
        return sum(
            _partial_effort_hours("VIEW", o["loc"])
            for o in ddl_summary.get("View", {}).get("_objects", [])
            if o["status"] == "Partial"
        )
    if fde_mode == "partial_function":
        return sum(
            _partial_effort_hours("FUNCTION", o["loc"])
            for o in ddl_summary.get("Function", {}).get("_objects", [])
            if o["status"] == "Partial"
        )
    if fde_mode == "partial_proc_tier":
        fde = 0.0
        for o in ddl_summary.get("Procedure", {}).get("_objects", []):
            if o["status"] != "Partial":
                continue
            bucket = _conversion_bucket("PROCEDURE", o["pct"])
            label = _tier_label_for_bucket(bucket).lower()
            if tier_key.endswith(f"({label})"):
                fde += _partial_effort_hours("PROCEDURE", o["loc"])
        return fde
    return 0.0


def _resolve_calculator_quantity(
    rule: str,
    ddl_summary: Dict[str, Dict[str, Any]],
    tier_counts: Dict[str, int],
) -> Tuple[Any, int]:
    if rule == "constant":
        return "Constant", 1
    if rule == "ddl_table_count":
        qty = ddl_summary.get("Table", {}).get("total", 0)
        return qty, qty
    if rule == "ddl_view_count":
        qty = ddl_summary.get("View", {}).get("total", 0)
        return qty, qty
    if rule == "ddl_external_table_count":
        qty = ddl_summary.get("External Table", {}).get("total", 0)
        return qty, qty
    if rule == "ddl_materialized_view_count":
        qty = ddl_summary.get("Materialized View", {}).get("total", 0)
        return qty, qty
    if rule == "ddl_function_count":
        qty = ddl_summary.get("Function", {}).get("total", 0)
        return qty, qty
    if rule == "ddl_procedure_count":
        qty = ddl_summary.get("Procedure", {}).get("total", 0)
        return qty, qty
    logger.warning(
        "Base_estimates.csv: unrecognized Quantity Rule %r; row will render as 0. "
        "Known rules: constant, ddl_table_count, ddl_view_count, "
        "ddl_external_table_count, ddl_materialized_view_count, ddl_function_count, "
        "ddl_procedure_count.",
        rule,
    )
    return 0, 0


def _resolve_calculator_fde(
    rule: str,
    qty_num: int,
    baseline: float,
    comments: str,
    config: EffortEstimateConfig,
) -> float:
    if "included" in comments.lower():
        return 0.0
    if rule == "constant":
        return baseline
    if rule in (
        "ddl_table_count",
        "ddl_view_count",
        "ddl_external_table_count",
        "ddl_materialized_view_count",
    ):
        return baseline if qty_num > 0 else 0.0
    if rule in ("ddl_function_count", "ddl_procedure_count"):
        return round(baseline * qty_num, 2)
    return round(baseline * qty_num, 2)


def build_effort_calculator(
    tier_counts: Dict[str, int],
    ddl_summary: Dict[str, Dict[str, Any]],
    config: EffortEstimateConfig,
) -> List[CalculatorRow]:
    """Build migration calculator rows from Base_estimates.csv templates."""
    rows: List[CalculatorRow] = []
    total_objects = count_workload_objects(ddl_summary)
    workload_tier = classify_workload_size(total_objects, config)
    tier_comment = f"{workload_size_label(workload_tier, config)} flat budget"
    flat_types = _flat_code_conversion_types(config)

    for tmpl in config.calculator_rows:
        qty_display, qty_num = _resolve_calculator_quantity(
            tmpl.quantity_rule,
            ddl_summary,
            tier_counts,
        )
        baseline = tmpl.baseline_hours
        naive_fde = _resolve_calculator_fde(
            tmpl.quantity_rule, qty_num, baseline, tmpl.comments, config
        )
        fde = naive_fde
        # Charge manual effort only for the portion SnowConvert did not auto-convert.
        # Applies to code conversion only — converted objects still need unit testing.
        if config.conversion_weighted and tmpl.component.strip().lower() == "code conversion":
            display = _CODE_CONVERSION_RULE_TO_DISPLAY.get(tmpl.quantity_rule)
            if display:
                fraction = _type_manual_fraction(
                    ddl_summary.get(display, {}),
                    flat_budget=display in flat_types,
                )
                fde = round(naive_fde * fraction, 2)
        total_baseline = (
            baseline
            if tmpl.quantity_rule == "constant"
            else round(baseline * qty_num, 2)
        )
        row = _calc_row(
            tmpl.component,
            tmpl.object_type,
            qty_display,
            baseline,
            total_baseline,
            fde,
            tmpl.comments,
        )
        row.unweighted_fde_hours = round(naive_fde, 2)
        rows.append(row)

    for phase in config.phase_budgets:
        hours = phase.hours_by_tier[workload_tier]
        rows.append(
            _calc_row(
                phase.component,
                phase.object_type,
                "Flat budget",
                hours,
                hours,
                hours,
                tier_comment,
            )
        )

    return rows


def _tier_label_for_bucket(bucket: str) -> str:
    mapping = {
        "full": "Full Converted",
        "partial": "Partially Converted",
        "75-99": "75-99% Converted",
        "50-75": "50-75% Converted",
        "25-50": "25-50% Converted",
        "0-25": "0-25% Converted",
    }
    return mapping.get(bucket, bucket)


def _is_fixed_budget_calculator_row(row: CalculatorRow) -> bool:
    return row.component.strip() in _FIXED_BUDGET_COMPONENTS


def _code_conversion_fde(rows: List[CalculatorRow]) -> float:
    return round(
        sum(r.fde_hours for r in rows if r.component.strip() == "Code Conversion"),
        2,
    )


def _code_conversion_testing_fde(rows: List[CalculatorRow]) -> float:
    return round(
        sum(
            r.fde_hours
            for r in rows
            if r.component.strip().lower() == "code conversion testing"
        ),
        2,
    )


def summarize_calculator(
    rows: List[CalculatorRow],
    ddl_summary: Dict[str, Any],
    config: Optional[EffortEstimateConfig] = None,
) -> Dict[str, Any]:
    """Aggregate totals for overview summary cards."""
    cfg = config or get_effort_estimate_config()
    total_baseline = round(sum(r.total_baseline_hours for r in rows), 2)
    ddl_objects = count_workload_objects(ddl_summary)
    workload_size_tier = classify_workload_size(ddl_objects, cfg)
    fixed_budget_items = compute_fixed_budget_items(ddl_summary, ddl_objects, cfg)

    conversion_fde = _code_conversion_fde(rows)
    conversion_naive = round(
        sum(
            r.unweighted_fde_hours
            for r in rows
            if r.component.strip() == "Code Conversion"
        ),
        2,
    )
    hours_saved = round(max(0.0, conversion_naive - conversion_fde), 2)
    # Share of the conversion budget automation removed. Derived from the same two
    # figures as hours_saved, so the headline can never disagree with the hours beside
    # it — unlike ddl_auto_pct, which counts objects by ConversionStatus and is free to
    # diverge from the LoC-based weighting.
    conversion_automated_pct = (
        round(hours_saved / conversion_naive, 4) if conversion_naive else 0.0
    )
    testing_fde = _code_conversion_testing_fde(rows)
    # "Synonym conversion" is a fixed-budget line item with no matching
    # Base_estimates.csv calculator row (no Quantity Rule fits a per-synonym flat
    # budget), so it must be folded in here explicitly or its hours never reach
    # fixed_budget_fde_hours / total_fde_hours despite showing in the tooltip.
    synonym_fde = fixed_budget_items.get("Synonym conversion", 0.0)
    fixed_budget_fde = round(
        sum(r.fde_hours for r in rows if _is_fixed_budget_calculator_row(r)) + synonym_fde,
        2,
    )
    ddl_fde = round(conversion_fde + testing_fde, 2)
    total_fde = round(sum(r.fde_hours for r in rows) + synonym_fde, 2)

    ddl_success = sum(s["success"] for s in ddl_summary.values())
    ddl_auto_pct = round(ddl_success / ddl_objects, 4) if ddl_objects else 0.0

    return {
        "total_baseline_hours": total_baseline,
        "total_fde_hours": total_fde,
        "ddl_fde_hours": ddl_fde,
        "conversion_fde_hours": conversion_fde,
        "code_conversion_naive_hours": conversion_naive,
        "hours_saved_by_automation": hours_saved,
        "conversion_automated_pct": conversion_automated_pct,
        "conversion_weighted": cfg.conversion_weighted,
        "testing_fde_hours": testing_fde,
        "fixed_budget_fde_hours": fixed_budget_fde,
        "fixed_budget_items": fixed_budget_items,
        "workload_size_tier": workload_size_tier,
        "workload_object_count": ddl_objects,
        "workload_small_max": cfg.workload_small_max,
        "workload_medium_max": cfg.workload_medium_max,
        "ddl_objects": ddl_objects,
        "ddl_auto_pct": ddl_auto_pct,
        "ddl_summary": ddl_summary,
    }


def _esc(text: Any) -> str:
    import html

    return html.escape(str(text)) if text is not None else ""


def _hours_to_rounded_days(hours: float) -> int:
    """Convert effort hours to whole days, rounded up (8h work day)."""
    if hours <= 0:
        return 0
    return int(math.ceil(hours / _HOURS_PER_WORK_DAY))


def _days_label(days: int) -> str:
    return f"{days:,} day" if days == 1 else f"{days:,} days"


def _render_fixed_budget_info_icon(
    fixed_items: Dict[str, float],
    workload_tier: str,
    total_objects: int,
) -> str:
    """Info icon with hover tooltip listing fixed budget line items."""
    if not fixed_items:
        return ""
    header = (
        f"<div style='margin-bottom:8px;font-weight:600;'>"
        f"{_esc(workload_size_label(workload_tier))} · {total_objects:,} objects"
        f"</div>"
    )
    tooltip_lines = header + "".join(
        f"<div style='margin-bottom:4px;'>{_esc(label)}: {hours:g} h</div>"
        for label, hours in fixed_items.items()
    )
    return (
        f'<span class="info-icon" style="margin-left:4px;">i'
        f'<span class="tooltip">{tooltip_lines}</span></span>'
    )


def render_overview_section_b_html(assessment: Dict[str, Any]) -> str:
    """Section B on Overview: effort summary for SQL Server DDL + fixed budgets."""
    s = assessment["summary"]
    ddl = s.get("ddl_summary", {})
    ddl_rows = ""
    for obj_type in sorted(ddl.keys()):
        if obj_type in _DDL_EXCLUDED_DISPLAY_TYPES:
            continue
        st = ddl[obj_type]
        pct = f"{st['pct_auto'] * 100:.1f}%"
        ddl_rows += f"""
        <tr>
            <td>{_esc(obj_type)}</td>
            <td class="ctr">{st['total']}</td>
            <td class="ctr">{st['success']}</td>
            <td class="ctr">{st['partial']}</td>
            <td class="ctr">{st['unsupported']}</td>
            <td class="ctr">{pct}</td>
        </tr>"""

    fixed_items = s.get("fixed_budget_items", {})
    workload_tier = s.get("workload_size_tier", "small")
    workload_objects = s.get("workload_object_count", s.get("ddl_objects", 0))
    fixed_info_icon = _render_fixed_budget_info_icon(
        fixed_items, workload_tier, workload_objects
    )
    workload_subtitle = (
        f"<div style='font-size:0.72rem;color:#64748B;margin-top:4px;'>"
        f"{_esc(workload_size_label(workload_tier))}</div>"
    )

    total_days = _hours_to_rounded_days(s.get("total_fde_hours", 0))

    # One metric among several, so it carries the shared card styling rather than a
    # colour and type size that would read as the section's headline.
    automation_card = ""
    if s.get("conversion_weighted") and s.get("hours_saved_by_automation", 0) > 0:
        auto_pct = s.get("conversion_automated_pct", 0) * 100
        automation_card = f"""
                <div class="effort-card">
                    <div class="effort-card-num">{auto_pct:.0f}%</div>
                    <div class="effort-card-lbl">Automated conversion</div>
                </div>"""

    return f"""
            <h2 id="effort-estimates" style="font-size: 1.5rem; font-weight: 700; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                <span style="background: #E0F2FE; color: #0284C7; padding: 4px 10px; border-radius: 6px; font-size: 0.9rem;">Section B</span>
                Estimated effort to migrate
                {EFFORT_PREVIEW_BADGE_HTML}
            </h2>
            {EFFORT_DISCLAIMER_HTML}
            <p style="color: #64748B; font-size: 0.95rem; margin-bottom: 20px; line-height: 1.6;">
                Effort summary using migration assessment formulas (flat phase budgets, LOC-based partials).
                Quantities reflect unique converted objects (session and batch rows excluded).
            </p>

            <div class="effort-cards">
                <div class="effort-card">
                    <div class="effort-card-num">{_days_label(total_days)}</div>
                    <div class="effort-card-lbl">Total Effort</div>
                </div>
                <div class="effort-card">
                    <div class="effort-card-num">{s.get('ddl_fde_hours', 0):,.1f} h</div>
                    <div class="effort-card-lbl">DDL Effort · {s.get('ddl_objects', 0):,} objects · {s.get('ddl_auto_pct', 0) * 100:.1f}% auto-converted · includes unit testing</div>
                </div>
                {automation_card}
                <div style="background: white; padding: 18px; border-radius: 12px; border-top: 4px solid #FF9F36; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                    <div style="font-size: 0.78rem; color: #64748B; font-weight: 600; text-transform: uppercase; display: flex; align-items: center;">
                        Fixed Budget{fixed_info_icon}
                    </div>
                    <div style="font-size: 1.6rem; font-weight: 800; color: #102E46; margin-top: 4px;">{s.get('fixed_budget_fde_hours', 0):,.1f} h</div>
                    {workload_subtitle}
                </div>
            </div>

            <h3 style="font-size: 1.1rem; font-weight: 700; color: #102E46; margin-bottom: 12px;">DDL conversion breakdown</h3>
            <div class="effort-table-wrap">
                <table class="effort-table">
                    <thead>
                        <tr>
                            <th>Object Type</th>
                            <th class="ctr">Total</th>
                            <th class="ctr">Success</th>
                            <th class="ctr">Partial</th>
                            <th class="ctr">Unsupported</th>
                            <th class="ctr">% Auto-Converted</th>
                        </tr>
                    </thead>
                    <tbody>{ddl_rows}</tbody>
                </table>
            </div>

            <div style="background: #F0F9FF; border: 1px solid #BAE6FD; border-radius: 10px; padding: 16px 20px; margin-bottom: 40px;">
                <p style="margin: 0 0 8px 0; color: #102E46; font-weight: 600;">Need line-item detail?</p>
                <p style="margin: 0 0 12px 0; color: #475569; font-size: 0.9rem; line-height: 1.5;">
                    The Effort Estimates tab shows the full migration calculator — every component, conversion tier quantity, baseline hours, and total time.
                </p>
                <a @click="activeTab = 'effort-estimates'"
                   style="display: inline-block; background: #005C8F; color: white; padding: 10px 18px; border-radius: 8px; font-weight: 600; font-size: 0.9rem; cursor: pointer; text-decoration: none;">
                    Open detailed effort calculator →
                </a>
            </div>
    """


def _render_ddl_assessment_table(
    ddl_summary: Dict[str, Dict[str, Any]],
    testing_fde: float = 0.0,
) -> str:
    rows_html = ""
    totals = _new_ddl_row()
    for obj_type in sorted(ddl_summary.keys()):
        if obj_type in _DDL_EXCLUDED_DISPLAY_TYPES:
            continue
        st = ddl_summary[obj_type]
        for k in totals:
            if k in ("pct_auto", "notes"):
                continue
            if isinstance(totals[k], (int, float)):
                totals[k] += st.get(k, 0)
        pct = f"{st['pct_auto'] * 100:.1f}%"
        effort = f"{st.get('effort_hours', 0):,.1f}" if st.get("effort_hours") else "—"
        rows_html += f"""
        <tr>
            <td>{_esc(obj_type)}</td>
            <td class="ctr">{st['total']:,}</td>
            <td class="ctr">{st['success']:,}</td>
            <td class="ctr">{st['partial']:,}</td>
            <td class="ctr">{st['unsupported']:,}</td>
            <td class="ctr">{pct}</td>
            <td class="num">{st['lines_of_code']:,}</td>
            <td class="ctr">{st['issues_none_info']:,}</td>
            <td class="ctr">{st['issues_low']:,}</td>
            <td class="ctr">{st['issues_medium']:,}</td>
            <td class="ctr">{st['issues_high']:,}</td>
            <td class="ctr">{st['issues_critical']:,}</td>
            <td class="num" style="font-weight:600;">{effort}</td>
            <td style="color:#64748B;font-size:0.8rem;">{_esc(st.get('notes', ''))}</td>
        </tr>"""
    total_pct = f"{(totals['success'] / totals['total'] * 100):.1f}%" if totals["total"] else "—"
    # Always the true sum of the rows displayed above (+ testing) so TOTALS never
    # understates what's visibly listed in this table.
    total_effort = round(totals["effort_hours"] + testing_fde, 1)
    if testing_fde:
        rows_html += f"""
        <tr style="background:#F8FAFC;">
            <td style="padding:8px 12px;">Code Conversion Testing</td>
            <td colspan="11" style="padding:8px 12px;color:#64748B;font-size:0.8rem;">Unit testing for functions and stored procedures</td>
            <td style="padding:8px 12px;text-align:right;font-weight:600;">{testing_fde:,.1f}</td>
            <td style="padding:8px 12px;color:#64748B;font-size:0.8rem;">1h per object (see calculator)</td>
        </tr>"""
    rows_html += f"""
        <tr class="effort-total">
            <td>TOTALS</td>
            <td class="ctr">{totals['total']:,}</td>
            <td class="ctr">{totals['success']:,}</td>
            <td class="ctr">{totals['partial']:,}</td>
            <td class="ctr">{totals['unsupported']:,}</td>
            <td class="ctr">{total_pct}</td>
            <td class="num">{totals['lines_of_code']:,}</td>
            <td class="ctr">{totals['issues_none_info']:,}</td>
            <td class="ctr">{totals['issues_low']:,}</td>
            <td class="ctr">{totals['issues_medium']:,}</td>
            <td class="ctr">{totals['issues_high']:,}</td>
            <td class="ctr">{totals['issues_critical']:,}</td>
            <td class="num">{total_effort:,.1f}</td>
            <td></td>
        </tr>"""
    return rows_html


def _render_calculator_rows(rows: List[CalculatorRow]) -> str:
    """Render the migration effort calculator's line-item rows."""
    calc_body = ""
    for r in rows:
        qty = r.quantity
        qty_disp = _esc(qty) if not isinstance(qty, (int, float)) else f"{int(qty):,}" if qty else "0"
        calc_body += f"""
        <tr>
            <td>{_esc(r.component)}</td>
            <td>{_esc(r.object_type)}</td>
            <td class="num">{qty_disp}</td>
            <td class="num">{r.baseline_hours:g}</td>
            <td class="num" style="font-weight:600;">{r.fde_hours:,.1f}</td>
            <td style="color:#64748B;font-size:0.85rem;">{_esc(r.comments)}</td>
        </tr>"""
    return calc_body


def _render_top_issues_section(top_issues: List[Dict[str, Any]]) -> str:
    """Top DDL issues-by-occurrence section; empty if there are no issues."""
    if not top_issues:
        return ""

    issues_html = ""
    for issue in top_issues:
        issues_html += f"""
        <tr>
            <td>{_esc(issue['code'])}</td>
            <td>{_esc(issue.get('name', ''))}</td>
            <td class="ctr">{_esc(issue.get('severity', '—'))}</td>
            <td class="ctr">{issue['occurrences']:,}</td>
        </tr>"""

    return f"""
        <h2 id="effort-top-issues" style="font-size:1.35rem;font-weight:700;color:#102E46;margin:32px 0 12px;">Top issues (DDL) – by occurrence</h2>
        <p style="color:#64748B;font-size:0.9rem;margin-bottom:12px;">Top conversion issues by occurrence count across DDL objects.</p>
        <div class="effort-table-wrap">
            <table class="effort-table">
                <thead><tr>
                    <th>Issue Code</th>
                    <th>Name</th>
                    <th class="ctr">Severity</th>
                    <th class="ctr">Occurrences</th>
                </tr></thead>
                <tbody>{issues_html}</tbody>
            </table>
        </div>"""


def _render_effort_formulas_legend(s: Dict[str, Any]) -> str:
    """Collapsible legend explaining how each effort figure is derived."""
    weighting_note = ""
    if s.get("conversion_weighted"):
        weighting_note = (
            "<p><strong>Automated conversion:</strong> code-conversion effort is charged "
            "only for the share SnowConvert did not convert automatically. Per-object "
            "types (functions, stored procedures) scale by effort × (1 − conversion rate). "
            "Flat-category budgets (tables, views) are all-or-nothing: a category costs 0h "
            "once every object in it auto-converted, and its full budget while any object "
            "still needs manual work. "
            f"On this workload automation avoided ≈ {s.get('hours_saved_by_automation', 0):,.0f} h "
            "of manual conversion.</p>"
        )
    return f"""
        <details style="margin-bottom:32px;background:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;padding:16px;">
            <summary style="font-weight:700;color:#102E46;cursor:pointer;">Effort formulas &amp; legend</summary>
            <div style="margin-top:12px;font-size:0.88rem;color:#475569;line-height:1.6;">
                <p><strong>DDL:</strong> Tables = flat 4h total; Views = flat 4h total; Functions and stored procedures = 1h each for conversion (plus 1h each for unit testing in the calculator).</p>
                {weighting_note}
                <p><strong>Fixed Budget:</strong> Data migration setup plus phase budgets scaled by workload size — Small (≤{s.get('workload_small_max', 500):,} objects), Medium ({s.get('workload_small_max', 500) + 1:,}–{s.get('workload_medium_max', 1500):,}), Large (&gt;{s.get('workload_medium_max', 1500):,}). Rates are configured in Base_estimates.csv.</p>
                <p><strong>Sources:</strong> SnowConvert conversion statistics — object conversion rates and issue severity counts.</p>
            </div>
        </details>"""


def render_effort_tab_html(assessment: Dict[str, Any]) -> str:
    """Full effort page aligned with the migration assessment workbook sections."""
    rows = assessment["calculator_rows"]
    s = assessment["summary"]
    ddl = s.get("ddl_summary", {})
    top_issues = assessment.get("top_issues", [])

    ddl_effort = s.get("ddl_fde_hours", 0)

    calc_body = _render_calculator_rows(rows)
    issues_section = _render_top_issues_section(top_issues)
    formulas_legend = _render_effort_formulas_legend(s)

    return f"""
    <div class="tab-content" :class="{{active: activeTab === 'effort-estimates'}}">
        <div style="margin-bottom: 24px;">
            <h1 style="font-size: 1.875rem; font-weight: 800; color: #102E46; margin-bottom: 8px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
                Migration effort estimates
                {EFFORT_PREVIEW_BADGE_HTML}
            </h1>
            {EFFORT_DISCLAIMER_HTML}
            <p style="color: #64748B; font-size: 1rem; line-height: 1.6;">
                Derived from SnowConvert conversion results. Tables and views use a flat 4h conversion budget each;
                data migration setup and phase budgets appear under Fixed Budget on the Overview tab.
            </p>
        </div>

        <div class="effort-cards">
            <div class="effort-card">
                <div class="effort-card-num">{s.get('ddl_objects', 0):,}</div>
                <div class="effort-card-lbl">Total DDL Objects</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{s.get('ddl_auto_pct', 0) * 100:.1f}%</div>
                <div class="effort-card-lbl">DDL Auto-Converted</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{s.get('total_fde_hours', 0):,.1f} h</div>
                <div class="effort-card-lbl">Total Effort</div>
            </div>
            <div class="effort-card">
                <div class="effort-card-num">{ddl_effort:,.1f} h</div>
                <div class="effort-card-lbl">DDL Effort</div>
            </div>
        </div>

        <h2 id="effort-ddl-assessment" style="font-size:1.35rem;font-weight:700;color:#102E46;margin-bottom:12px;">DDL conversion effort</h2>
        <div class="effort-table-wrap" style="margin-bottom:32px;">
            <table class="effort-table compact">
                <thead><tr>
                    <th>Object Type</th>
                    <th class="ctr">Total</th>
                    <th class="ctr">Success</th>
                    <th class="ctr">Partial</th>
                    <th class="ctr">Unsupported</th>
                    <th class="ctr">% Auto-Conv.</th>
                    <th class="num">Lines of Code</th>
                    <th class="ctr">None/Info</th>
                    <th class="ctr">Low</th>
                    <th class="ctr">Medium</th>
                    <th class="ctr">High</th>
                    <th class="ctr">Critical</th>
                    <th class="num">Effort (h)</th>
                    <th>Notes</th>
                </tr></thead>
                <tbody>{_render_ddl_assessment_table(ddl, s.get("testing_fde_hours", 0))}</tbody>
            </table>
        </div>

        {issues_section}

        <h2 id="effort-calculator" style="font-size:1.35rem;font-weight:700;color:#102E46;margin:32px 0 12px;">Migration effort calculator</h2>
        <p style="color:#64748B;font-size:0.9rem;margin-bottom:12px;">Line-item estimate broken down by migration component; quantities reflect unique conversion tiers per object type.</p>
        <div class="effort-table-wrap">
            <table class="effort-table">
                <thead><tr>
                    <th>Migration Component</th>
                    <th>Object Type</th>
                    <th class="num">Quantity</th>
                    <th class="num">Baseline Hours</th>
                    <th class="num">Total Time</th>
                    <th>Comments</th>
                </tr></thead>
                <tbody>
                    {calc_body}
                    <tr class="effort-total">
                        <td colspan="4">TOTAL</td>
                        <td class="num">{s.get('total_fde_hours', 0):,.1f}</td>
                        <td></td>
                    </tr>
                </tbody>
            </table>
        </div>

        {formulas_legend}
    </div>
    """


def _warn_on_unmeasured_conversion(
    ddl_summary: Dict[str, Dict[str, Any]],
    csv_path: Path,
) -> None:
    """Warn when conversion weighting ran without LoC conversion data to weight by."""
    objects = [o for s in ddl_summary.values() for o in s.get("_objects", [])]
    if not objects:
        return
    unmeasured = sum(1 for o in objects if not o.get("pct_measured", False))
    if not unmeasured:
        return
    logger.warning(
        "%s: %d of %d code units have no parseable LoCConversionPercentage. Conversion "
        "weighting charges full manual effort for those objects rather than crediting "
        "automation for data the report does not contain.",
        csv_path.name,
        unmeasured,
        len(objects),
    )


def build_effort_assessment(
    reports_dir: Path,
    base_estimates_csv: Optional[Path] = None,
    project_dir: Optional[Path] = None,
) -> Optional[Dict[str, Any]]:
    """Build the full effort assessment payload for a supported source dialect.

    The dialect is resolved from ``{project_dir}/.scai/config/project.yml`` only.
    ``base_estimates_csv`` overrides the CSV; when omitted the per-dialect bundled CSV
    is used (``Base_estimates.redshift.csv`` for Redshift, ``Base_estimates.csv`` for
    SQL Server). Returns ``None`` for unsupported dialects so the tab is omitted
    entirely rather than rendered half-populated.
    """
    source_dialect = read_project_source_language(project_dir)
    dialect_key = resolve_effort_dialect(source_dialect)
    if dialect_key is None:
        return None

    csv_path = _find_toplevel_code_units_csv(reports_dir)
    if not csv_path:
        return None

    config_csv = base_estimates_csv or _default_base_estimates_for(dialect_key)
    config = load_effort_estimate_config(config_csv)
    tier_counts, ddl_summary, code_unit_categories = count_quantities_from_code_units(csv_path)
    issues_path = _find_report_csv(reports_dir, "Issues")
    if issues_path:
        merge_issue_counts_into_ddl(ddl_summary, issues_path, code_unit_categories)

    calculator_rows = build_effort_calculator(tier_counts, ddl_summary, config)
    compute_ddl_effort(ddl_summary, config)
    top_issues = build_top_ddl_issues(issues_path)
    summary = summarize_calculator(calculator_rows, ddl_summary, config)

    if config.conversion_weighted:
        _warn_on_unmeasured_conversion(ddl_summary, csv_path)

    for stats in ddl_summary.values():
        stats.pop("_objects", None)

    return {
        "source_dialect": source_dialect,
        "calculator_rows": calculator_rows,
        "summary": summary,
        "top_issues": top_issues,
    }
