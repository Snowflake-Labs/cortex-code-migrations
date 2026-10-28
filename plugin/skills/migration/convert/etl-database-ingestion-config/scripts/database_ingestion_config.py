#!/usr/bin/env python3
"""Validate schema 1.0 database-ingestion-config.json before conversion.

The accepted document is the engine schema: schemaVersion, landing, and rules.
Optional fields that are present are kept on round-trip. Defaults are not
invented. Secret-shaped keys are rejected. This script does not call Openflow.
"""

from __future__ import annotations

import json
import sys
from typing import Any

SCHEMA_VERSION = "1.0"
CONFIG_NAME = "database-ingestion-config.json"
MODES = ("snapshot", "sqlServerChangeTracking", "sqlServerCdc")
TOP_LEVEL = ("schemaVersion", "landing", "rules")
LANDING_KEYS = ("database", "mode", "schema", "tablePrefix")
RULE_KEYS = ("id", "action", "mode", "source", "landing")
SOURCE_KEYS = ("server", "connection", "database", "schema", "table")
LANDING_OVERRIDE_KEYS = ("schema", "table")
SECRET_KEYS = frozenset(
    {
        "credential",
        "key",
        "password",
        "privateKey",
        "private_key",
        "secret",
        "token",
    }
)


class ConfigError(Exception):
    """One schema failure. The message names the JSON path."""


def validate_text(text: str) -> None:
    """Raise ConfigError on the first problem. Return when the document is valid."""
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise ConfigError(
            f"{CONFIG_NAME} is not valid JSON: {error.msg} at line {error.lineno}"
        ) from error
    if not isinstance(document, dict):
        raise ConfigError("$ must be an object.")
    _reject_secrets(document, "$")
    _require_object_keys(document, TOP_LEVEL, "$")
    version = _required_string(document, "schemaVersion", "$")
    if version != SCHEMA_VERSION:
        raise ConfigError(
            f"Unsupported schemaVersion '{version}' at $.schemaVersion. "
            f"Expected '{SCHEMA_VERSION}'."
        )
    landing = _required_object(document, "landing", "$")
    _parse_landing(landing)
    rules = _required_array(document, "rules", "$")
    if len(rules) == 0:
        raise ConfigError("$.rules must contain at least one inclusion or exclusion rule.")
    seen_ids: set[str] = set()
    for index, rule in enumerate(rules):
        rule_id = _parse_rule(rule, index)
        if rule_id in seen_ids:
            raise ConfigError(f"Rule id '{rule_id}' occurs more than once in $.rules.")
        seen_ids.add(rule_id)


def round_trip(text: str) -> str:
    """Return indented JSON with the same keys. Fail before any rewrite."""
    validate_text(text)
    document = json.loads(text)
    return json.dumps(document, indent=2) + "\n"


def _parse_landing(landing: dict[str, Any]) -> None:
    _require_object_keys(landing, LANDING_KEYS, "$.landing")
    _required_string(landing, "database", "$.landing")
    _optional_string(landing, "schema", "$.landing")
    prefix = _optional_string(landing, "tablePrefix", "$.landing")
    if prefix is not None and len(prefix) > 200:
        raise ConfigError("$.landing.tablePrefix cannot exceed 200 characters.")
    _parse_mode(_optional_string(landing, "mode", "$.landing"), "$.landing.mode")


def _parse_rule(token: Any, index: int) -> str:
    path = f"$.rules[{index}]"
    if not isinstance(token, dict):
        raise ConfigError(f"{path} must be an object.")
    _require_object_keys(token, RULE_KEYS, path)
    rule_id = _required_string(token, "id", path)
    action = _required_string(token, "action", path)
    if action not in ("include", "exclude"):
        raise ConfigError(f"{path}.action must be 'include' or 'exclude', got '{action}'.")
    source = _parse_source(_required_object(token, "source", path), path)
    mode = _parse_mode(_optional_string(token, "mode", path), f"{path}.mode")
    if "landing" in token:
        if action == "exclude":
            raise ConfigError(f"{path}.landing is not allowed on an exclusion rule.")
        landing = token["landing"]
        if not isinstance(landing, dict):
            raise ConfigError(f"{path}.landing must be an object.")
        _parse_landing_override(landing, path, source)
    if action == "exclude" and mode is not None:
        raise ConfigError(f"{path}.mode is not allowed on an exclusion rule.")
    return rule_id


def _parse_source(source: dict[str, Any], rule_path: str) -> dict[str, str]:
    path = f"{rule_path}.source"
    _require_object_keys(source, SOURCE_KEYS, path)
    values = {name: _optional_string(source, name, path) for name in SOURCE_KEYS}
    present = {name: value for name, value in values.items() if value is not None}
    has_server = "server" in present
    has_connection = "connection" in present
    if has_server == has_connection:
        raise ConfigError(f"{path} must define exactly one of 'server' or 'connection'.")
    if "schema" in present and "database" not in present:
        raise ConfigError(f"{path}.schema requires {path}.database.")
    if "table" in present and "schema" not in present:
        raise ConfigError(f"{path}.table requires {path}.schema.")
    return present


def _parse_landing_override(
    landing: dict[str, Any], rule_path: str, source: dict[str, str]
) -> None:
    path = f"{rule_path}.landing"
    _require_object_keys(landing, LANDING_OVERRIDE_KEYS, path)
    schema = _optional_string(landing, "schema", path)
    table = _optional_string(landing, "table", path)
    if schema is None and table is None:
        raise ConfigError(f"{path} must define 'schema', 'table', or both.")
    if table is not None and "table" not in source:
        raise ConfigError(f"{path}.table requires an exact {rule_path}.source.table match.")


def _parse_mode(value: str | None, path: str) -> str | None:
    if value is None:
        return None
    if value not in MODES:
        raise ConfigError(
            f"{path} must be 'snapshot', 'sqlServerChangeTracking', or 'sqlServerCdc', "
            f"got '{value}'."
        )
    return value


def _reject_secrets(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in {name.lower() for name in SECRET_KEYS} or key in SECRET_KEYS:
                if key.lower() in {item.lower() for item in SECRET_KEYS}:
                    raise ConfigError(
                        f"Forbidden secret-shaped key '{key}' at {path}.{key}. "
                        "Credentials must be supplied out of band."
                    )
            child_path = f"{path}.{key}"
            _reject_secrets(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secrets(child, f"{path}[{index}]")


def _require_object_keys(value: dict[str, Any], allowed: tuple[str, ...], path: str) -> None:
    unknown = next((key for key in value if key not in allowed), None)
    if unknown is not None:
        names = ", ".join(sorted(allowed))
        raise ConfigError(
            f"Unknown key '{unknown}' at {path}.{unknown}. Allowed keys: {names}."
        )


def _required_object(parent: dict[str, Any], name: str, parent_path: str) -> dict[str, Any]:
    if name not in parent:
        raise ConfigError(f"Missing required object at {parent_path}.{name}.")
    value = parent[name]
    if not isinstance(value, dict):
        raise ConfigError(f"{parent_path}.{name} must be an object.")
    return value


def _required_array(parent: dict[str, Any], name: str, parent_path: str) -> list[Any]:
    if name not in parent:
        raise ConfigError(f"Missing required array at {parent_path}.{name}.")
    value = parent[name]
    if not isinstance(value, list):
        raise ConfigError(f"{parent_path}.{name} must be an array.")
    return value


def _required_string(parent: dict[str, Any], name: str, parent_path: str) -> str:
    value = _optional_string(parent, name, parent_path)
    if value is None:
        raise ConfigError(f"Missing required non-empty string at {parent_path}.{name}.")
    return value


def _optional_string(parent: dict[str, Any], name: str, parent_path: str) -> str | None:
    if name not in parent:
        return None
    value = parent[name]
    if not isinstance(value, str):
        raise ConfigError(f"{parent_path}.{name} must be a string.")
    if value.strip() == "":
        raise ConfigError(f"{parent_path}.{name} must be a non-empty string.")
    return value


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("validate", "round-trip"):
        print(
            "usage: database_ingestion_config.py validate|round-trip FILE",
            file=sys.stderr,
        )
        return 2
    command, path = argv[1], argv[2]
    try:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        if command == "validate":
            validate_text(text)
            return 0
        sys.stdout.write(round_trip(text))
        return 0
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
