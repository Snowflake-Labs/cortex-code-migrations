from pathlib import Path

from ..models import ObjectReference
from .csv_reader import load_csv_as


def load_object_references(csv_path: str | Path) -> list[ObjectReference]:
    """Load all object references from ObjectReferences.*.csv."""
    return load_csv_as(csv_path, ObjectReference.from_csv_row)


def load_missing_references(csv_path: str | Path) -> list[ObjectReference]:
    """Load only MISSING references from ObjectReferences.*.csv."""

    def factory(row: dict[str, str]) -> ObjectReference | None:
        ref = ObjectReference.from_csv_row(row)
        return ref if ref.is_missing_reference else None

    return load_csv_as(csv_path, factory)
