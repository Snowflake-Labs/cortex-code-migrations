from pathlib import Path

from ..models import PartitionMember
from .csv_reader import load_csv_as


def load_partition_membership(csv_path: str | Path) -> list[PartitionMember]:
    """Load partition membership from PartitionMembership.csv."""
    return load_csv_as(csv_path, PartitionMember.from_csv_row)
