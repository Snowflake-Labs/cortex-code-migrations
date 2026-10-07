"""Read SAS source with every line-ending variant collapsed to ``\\n``.

``Path.read_text()`` uses universal newlines, which turns ``\\r\\r\\n`` (common
in files round-tripped through Windows tooling) into TWO lines and doubled line
counts. Reading with ``newline=''`` and normalising explicitly treats any run of
``\\r`` before ``\\n``, or a lone ``\\r``, as one line break.

Only the parsed text is normalised; checksums must still be taken over the raw
bytes so CUR ids/checksums do not churn.
"""

import re
from pathlib import Path
from typing import Tuple

_LINE_BREAK = re.compile(r'\r*\n|\r')
# First line of the comment egp_extractor writes above each extracted task.
EGP_HEADER_MARKER = '/* Extracted from Enterprise Guide project:'


def strip_egp_header(text: str) -> str:
    """Drop the extractor's provenance comment so it is not counted as source lines."""
    if not text.startswith(EGP_HEADER_MARKER):
        return text
    end = text.find('*/\n')
    return text[end + 3:] if end != -1 else text


def normalise_newlines(raw: str) -> Tuple[str, bool]:
    """Return ``(text, changed)`` where ``changed`` means non-``\\n`` breaks existed."""
    text = _LINE_BREAK.sub('\n', raw)
    return text, text != raw


def read_sas_source(path: Path) -> Tuple[str, bool]:
    """Read a ``.sas`` file; return ``(normalised_text, line_endings_normalised)``."""
    with open(path, encoding='utf-8', errors='replace', newline='') as fh:
        text, changed = normalise_newlines(fh.read())
    return strip_egp_header(text), changed
