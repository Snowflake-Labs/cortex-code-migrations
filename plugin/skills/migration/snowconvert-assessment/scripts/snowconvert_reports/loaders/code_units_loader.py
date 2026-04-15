from pathlib import Path

from ..models import TopLevelCodeUnit
from .csv_reader import load_csv_as


def load_code_units(csv_path: str | Path) -> list[TopLevelCodeUnit]:
    """Load all top-level code units from TopLevelCodeUnits.csv."""
    return load_csv_as(csv_path, TopLevelCodeUnit.from_csv_row)
