#!/usr/bin/env python3
# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Bindable-format catalog tokens from convert (`${name}`, `<%name%>`).

AIM convert defaults to bindable format, so CUR ``source.database`` / identity
segments may be tokens. Assessment display and registry object ids unwrap exact
tokens to the canonical catalog name — matching C# ``BindableDatabaseToken`` and
Rust ``registry::unwrap_bindable_token``.
"""

from __future__ import annotations


def unwrap_bindable_token(value: str | None) -> str:
    """Return the canonical name when *value* is exactly one bindable token."""
    if value is None:
        return ""
    trimmed = value.strip()
    if trimmed.startswith("${") and trimmed.endswith("}") and len(trimmed) >= 4:
        inner = trimmed[2:-1].strip()
        if inner and "}" not in inner:
            return inner
    if trimmed.startswith("<%") and trimmed.endswith("%>") and len(trimmed) >= 5:
        inner = trimmed[2:-2].strip()
        if inner and "%" not in inner:
            return inner
    return trimmed
