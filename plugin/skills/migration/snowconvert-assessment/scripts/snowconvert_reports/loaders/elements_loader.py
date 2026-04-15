from pathlib import Path

from ..models import Element
from .csv_reader import load_csv_as


def load_elements(csv_path: str | Path) -> list[Element]:
    """Load all elements from Elements.csv."""
    return load_csv_as(csv_path, Element.from_csv_row)
