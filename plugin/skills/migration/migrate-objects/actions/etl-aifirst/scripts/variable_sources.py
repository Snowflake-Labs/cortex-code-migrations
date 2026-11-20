"""Where a unit's run-time variables get their values, outside the unit document.

Read by `Identification.unit_variables()` through the platform table's
`structure.parameters.project_config` / `environment_config` blocks. Two sources, both files the
registration step copies with the document (it copies the whole `--source` folder):

  project      the closest ancestor folder of the document holding the project file (Hop:
               `project-config.json`, values under `config.variables`). The same "closest project"
               rule as SnowConvert's SSIS `Project.params` lookup.
  environment  every JSON file under that project whose only top-level key is the declared
               variables key (Hop: `{"variables": [...]}`), sorted by relative path. One of them
               is chosen per run (`hop-run -e`), which is the parameter-file shape.

With no project file found, the environment search root is the document's own folder.
"""

from __future__ import annotations

import json
from pathlib import Path

# Never walk above these: the vendored source root and repository roots.
_STOP_NAMES = {"_etl_aifirst"}
_STOP_MARKERS = (".git", ".scai")


def _named_values(rows) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and isinstance(row.get("name"), str) and row["name"]:
            value = row.get("value")
            out.setdefault(row["name"], "" if value is None else str(value))
    return out


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def find_project(doc_path: str, file_name: str) -> Path | None:
    here = Path(doc_path).resolve().parent
    for folder in (here, *here.parents):
        if (folder / file_name).is_file():
            return folder / file_name
        if folder.name in _STOP_NAMES or any((folder / m).exists() for m in _STOP_MARKERS):
            return None
    return None


def project_variables(project_file: Path | None, variables_path: list[str]) -> dict[str, str]:
    if project_file is None:
        return {}
    node = _load_json(project_file)
    for key in variables_path:
        node = node.get(key) if isinstance(node, dict) else None
    return _named_values(node)


def environment_files(root: Path, variables_key: str, exclude_dirs: list[str]) -> list[tuple[str, dict[str, str]]]:
    found = []
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root)
        if set(rel.parts[:-1]) & set(exclude_dirs):
            continue
        data = _load_json(path)
        if isinstance(data, dict) and list(data) == [variables_key] and isinstance(data[variables_key], list):
            found.append((rel.as_posix(), _named_values(data[variables_key])))
    return found


def discover(doc_path: str, spec: dict) -> dict:
    """The project file, its variables, and the environment files with their variables."""
    project_spec = spec.get("project_config") or {}
    env_spec = spec.get("environment_config") or {}
    project_file = find_project(doc_path, project_spec["file"]) if project_spec else None
    root = project_file.parent if project_file else Path(doc_path).resolve().parent
    return {
        "project_file": project_file,
        "project": project_variables(project_file, project_spec.get("variables_path") or []),
        "environments": (environment_files(root, env_spec["variables_key"], env_spec.get("exclude_dirs") or [])
                         if env_spec else []),
    }
