"""Core data models for lineage gap validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

RelationType = Literal["INSERT", "UPDATE", "SELECT-FROM", "EXECUTE"]


@dataclass(frozen=True)
class LineageEdge:
    """A single lineage edge representing a data dependency.
    
    Attributes:
        caller_workflow: The workflow name (e.g., "wf_MT_RSTD_BOOKINGS_FMTH")
        part: The transformation/part name within the workflow (e.g., "SQ_BOOKINGS", "TGT_MT_RSTD_BOOKINGS")
        table: Normalized table name (e.g., "MT_RSTD_BOOKINGS_FMTH")
        relation_type: The type of relationship (INSERT/UPDATE/SELECT-FROM/EXECUTE)
    """
    
    caller_workflow: str
    part: str
    table: str
    relation_type: RelationType
    
    def __post_init__(self) -> None:
        """Validate that relation_type is one of the expected values."""
        valid_types = set(get_args(RelationType))
        if self.relation_type not in valid_types:
            raise ValueError(
                f"Invalid relation_type '{self.relation_type}'. "
                f"Must be one of: {valid_types}"
            )


@dataclass(frozen=True)
class DiffResult:
    """Result of comparing XML ground-truth lineage against CUR lineage.
    
    Attributes:
        matched: Edges present in both XML and CUR with matching relation types
        missing_in_cur: Edges in XML ground-truth but not in CUR (engine gaps)
        extra_in_cur: Edges in CUR but not in XML ground-truth (potential false positives)
        relation_type_mismatch: Edges where table name matches but relation type differs
    """
    
    matched: set[LineageEdge]
    missing_in_cur: set[LineageEdge]
    extra_in_cur: set[LineageEdge]
    relation_type_mismatch: set[tuple[LineageEdge, LineageEdge]]  # (xml_edge, cur_edge)


@dataclass(frozen=True)
class GapAttribution:
    """Attribution of missing edges to known open tickets.
    
    Attributes:
        ticket: GitHub issue number (e.g., "2035", "2021", "1932")
        description: Human-readable description of the gap
        edges: Set of missing edges attributed to this ticket
    """
    
    ticket: str
    description: str
    edges: set[LineageEdge]
