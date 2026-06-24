"""Informatica lineage gap validation tool.

Validates CUR-populated lineage against XML ground-truth from Informatica workflows.
"""

from __future__ import annotations

__all__ = ["LineageEdge", "DiffResult", "GapAttribution"]

from .models import DiffResult, GapAttribution, LineageEdge
