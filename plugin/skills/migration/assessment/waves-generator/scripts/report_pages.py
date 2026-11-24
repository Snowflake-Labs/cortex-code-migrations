# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
"""Shareable assessment report folder, zip, and extra HTML pages."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple


REPORT_FOLDER_NAME = "report"
ARCHIVE_FOLDER_NAME = "reports"
SHARE_ZIP_NAME = "assessment-report.zip"
PRINT_HTML_NAME = "print.html"

# Sibling HTML files next to the journey hub. `journey` is the hub filename
# (index.html in production, report.html in some tests).
SECTION_FILES = {
    "journey": "index.html",
    "discovery": "discovery.html",
    "business-use-cases": "business-use-cases.html",
    "pending-objects": "pending-objects.html",
    "overview": "overview.html",
    "conversion-issues": "conversion-issues.html",
    "effort-estimates": "effort-estimates.html",
    "waves": "dependencies.html",
    "exclusion": "exclusion.html",
    "dynamic-sql": "dynamic-sql.html",
    "etl": "etl.html",
    "data-migration": "data-migration.html",
    "testing": "testing.html",
    "virtualization": "virtualization.html",
}

MANAGED_HTML = frozenset({*SECTION_FILES.values(), PRINT_HTML_NAME})
SIDECAR_DIRS = ("waves", "informatica_mappings", "packages", "dags")
SHARE_MEMBERS = frozenset({*MANAGED_HTML, "index.pdf", "index.result.json", "objects.html"})


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def write_simple_page(path: Path, title: str, body: str, *, home_href: str = "index.html") -> None:
    Path(path).write_text(_page(title, body, home_href=home_href), encoding="utf-8")


def _page(title: str, body: str, *, home_href: str = "../index.html") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{_esc(title)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               margin: 0; color: #102E46; background: #F8FBFC; }}
        .bar {{ background: #005C8F; color: #fff; padding: 16px 24px;
                display: flex; justify-content: space-between; align-items: center; gap: 16px; }}
        .bar a {{ color: #CFECEF; }}
        main {{ padding: 24px; max-width: 1400px; margin: 0 auto; }}
        table {{ width: 100%; border-collapse: collapse; background: #fff; }}
        th, td {{ border-bottom: 1px solid #E5E7EB; padding: 8px 10px; text-align: left;
                  font-size: 0.85rem; vertical-align: top; }}
        th {{ background: #F9FAFB; color: #6B7280; font-size: 0.75rem; text-transform: uppercase; }}
        .badge-ok {{ color: #065F46; }}
        .badge-bad {{ color: #991B1B; }}
        .nav {{ display: flex; gap: 12px; }}
    </style>
</head>
<body>
    <div class="bar">
        <strong>{_esc(title)}</strong>
        <div class="nav">
            <a href="{_esc(home_href)}">Report home</a>
        </div>
    </div>
    <main>
        {body}
    </main>
</body>
</html>
"""


def report_stamp(generated_at: Optional[datetime] = None) -> str:
    when = generated_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _extended_win_path(path: Path | str) -> str:
    """Absolute path Windows file APIs accept past the 260-char MAX_PATH limit."""
    absolute = os.path.abspath(os.fspath(path))
    if os.name != "nt":
        return absolute
    if absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def _copy2_extended(src, dst, *args, **kwargs):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    return shutil.copy2(_extended_win_path(src), _extended_win_path(dst), *args, **kwargs)


def clear_stale_section_pages(report_dir: Path, keep: set[str]) -> None:
    """Remove section HTML this run is not rewriting, so a prior page cannot linger."""
    report_dir = Path(report_dir)
    for name in MANAGED_HTML:
        if name in keep:
            continue
        path = report_dir / name
        if path.is_file():
            path.unlink()


def _share_dir(report_dir: Path) -> Path:
    return report_dir.parent if report_dir.name == REPORT_FOLDER_NAME else report_dir


def _share_members(report_dir: Path, extra_files: Optional[set[str]] = None) -> list[Path]:
    names = set(SHARE_MEMBERS)
    if extra_files:
        names.update(extra_files)
    members: list[Path] = []
    for name in sorted(names):
        path = report_dir / name
        if path.is_file():
            members.append(path)
    for sub in SIDECAR_DIRS:
        folder = report_dir / sub
        if folder.is_dir():
            members.extend(path for path in sorted(folder.rglob("*")) if path.is_file())
    return members


def publish_shareable_report(
    report_dir: Path,
    generated_at: Optional[datetime] = None,
    *,
    extra_files: Optional[set[str]] = None,
) -> Tuple[Path, Path]:
    """Copy report pages to ``share/reports/report_<stamp>/`` and zip them beside that.

    ``share`` is the parent when the pages live in a ``report/`` folder, else the
    page folder itself. Only generated pages and ETL sidecars are copied, so a
    custom ``-o`` directory's other files stay out of the zip.

    ETL DAG HTML names are often longer than Windows MAX_PATH once they sit under
    ``reports/report_<stamp>/dags/``. Use the ``\\\\?\\`` prefix so copy/zip still work.
    Zip is written even when the timestamped copy cannot place every file.
    """
    report_dir = Path(report_dir)
    share_dir = _share_dir(report_dir)
    stamp = report_stamp(generated_at)
    archive_dir = share_dir / ARCHIVE_FOLDER_NAME / f"report_{stamp}"
    zip_path = share_dir / SHARE_ZIP_NAME
    members = _share_members(report_dir, extra_files)

    copy_error: Optional[BaseException] = None
    try:
        if archive_dir.exists():
            shutil.rmtree(_extended_win_path(archive_dir))
        archive_dir.parent.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)
        for file in members:
            dest = archive_dir / file.relative_to(report_dir)
            _copy2_extended(file, dest)
    except (OSError, shutil.Error) as exc:
        copy_error = exc

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file in members:
            zf.write(_extended_win_path(file), file.relative_to(report_dir).as_posix())

    if copy_error is not None:
        raise copy_error
    return archive_dir, zip_path
