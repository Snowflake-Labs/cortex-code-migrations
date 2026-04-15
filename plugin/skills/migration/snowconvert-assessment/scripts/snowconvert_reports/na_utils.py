"""Shared N/A sentinel detection and sanitization utilities."""

from __future__ import annotations

import re

NA_VALUES = frozenset({"N/A", "n/a", "NA", "na", ""})

_NA_SEGMENT_RE = re.compile(r"\[N/A\]\.")


def is_na(value: str | None) -> bool:
    """Return True if *value* is None, empty, or a common N/A sentinel."""
    if value is None:
        return True
    return str(value).strip() in NA_VALUES


def sanitize_na(value: str | None, fallback: str = "-") -> str:
    """Replace N/A-like values with *fallback*."""
    return fallback if is_na(value) else str(value).strip()


def strip_na_identifier(identifier: str) -> str:
    """Remove ``[N/A].`` segments from a multi-part SQL identifier.

    ``[N/A].[dbo].[MyTable]`` → ``[dbo].[MyTable]``
    """
    if not identifier:
        return identifier
    return _NA_SEGMENT_RE.sub("", identifier)
