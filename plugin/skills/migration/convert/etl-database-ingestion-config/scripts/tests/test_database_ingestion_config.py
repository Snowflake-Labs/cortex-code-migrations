"""Schema 1.0 validation and round-trip for database-ingestion-config.json."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "database_ingestion_config.py"
_spec = importlib.util.spec_from_file_location("database_ingestion_config", SCRIPT)
config = importlib.util.module_from_spec(_spec)
sys.modules["database_ingestion_config"] = config
_spec.loader.exec_module(config)


def document(**overrides) -> dict:
    body = {
        "schemaVersion": "1.0",
        "landing": {"database": "LANDING_DB"},
        "rules": [
            {
                "id": "include-source",
                "action": "include",
                "source": {"connection": "SourceConnection"},
            }
        ],
    }
    body.update(overrides)
    return body


def dumps(body: dict) -> str:
    return json.dumps(body)


class ValidateTests(unittest.TestCase):
    def test_minimal_document_is_valid(self) -> None:
        config.validate_text(dumps(document()))

    def test_modes_override_and_exclude_are_valid(self) -> None:
        body = document(
            landing={
                "database": "LANDING_DB",
                "schema": "RAW",
                "tablePrefix": "RAW_",
                "mode": "snapshot",
            },
            rules=[
                {
                    "id": "include-server",
                    "action": "include",
                    "mode": "sqlServerChangeTracking",
                    "source": {"server": "sales-sql.example.com", "database": "SALESPROD"},
                },
                {
                    "id": "exclude-audit",
                    "action": "exclude",
                    "source": {
                        "server": "sales-sql.example.com",
                        "database": "SALESPROD",
                        "schema": "AUDIT",
                    },
                },
                {
                    "id": "include-table",
                    "action": "include",
                    "mode": "sqlServerCdc",
                    "source": {
                        "connection": "HR_ORACLE",
                        "database": "HRPROD",
                        "schema": "HR",
                        "table": "EMPLOYEES",
                    },
                    "landing": {"schema": "RAW_PEOPLE", "table": "RAW_EMPLOYEES"},
                },
            ],
        )
        config.validate_text(dumps(body))

    def test_exclude_landing_names_the_rule_path(self) -> None:
        body = document(
            rules=[
                {
                    "id": "exclude-audit",
                    "action": "exclude",
                    "source": {"connection": "SourceConnection"},
                    "landing": {"schema": "RAW"},
                }
            ]
        )
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.rules[0].landing", str(caught.exception))

    def test_exclude_mode_names_the_rule_path(self) -> None:
        body = document(
            rules=[
                {
                    "id": "exclude-audit",
                    "action": "exclude",
                    "mode": "snapshot",
                    "source": {"connection": "SourceConnection"},
                }
            ]
        )
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.rules[0].mode", str(caught.exception))

    def test_server_and_connection_together_fail(self) -> None:
        body = document(
            rules=[
                {
                    "id": "both",
                    "action": "include",
                    "source": {"server": "host", "connection": "SourceConnection"},
                }
            ]
        )
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.rules[0].source", str(caught.exception))

    def test_schema_without_database_fails(self) -> None:
        body = document(
            rules=[
                {
                    "id": "schema-only",
                    "action": "include",
                    "source": {"connection": "SourceConnection", "schema": "HR"},
                }
            ]
        )
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.rules[0].source.schema", str(caught.exception))

    def test_landing_table_without_source_table_fails(self) -> None:
        body = document(
            rules=[
                {
                    "id": "override",
                    "action": "include",
                    "source": {"connection": "SourceConnection", "database": "HRPROD"},
                    "landing": {"table": "RAW_EMPLOYEES"},
                }
            ]
        )
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.rules[0].landing.table", str(caught.exception))

    def test_unknown_key_names_its_path(self) -> None:
        body = document()
        body["openflow"] = {}
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.openflow", str(caught.exception))

    def test_secret_key_is_rejected(self) -> None:
        body = document()
        body["landing"]["password"] = "nope"
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(body))
        self.assertIn("$.landing.password", str(caught.exception))

    def test_empty_rules_fail(self) -> None:
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(document(rules=[])))
        self.assertIn("$.rules", str(caught.exception))

    def test_wrong_schema_version_fails(self) -> None:
        with self.assertRaises(config.ConfigError) as caught:
            config.validate_text(dumps(document(schemaVersion="2.0")))
        self.assertIn("$.schemaVersion", str(caught.exception))


class RoundTripTests(unittest.TestCase):
    def test_optional_fields_survive_and_defaults_are_not_added(self) -> None:
        original = {
            "schemaVersion": "1.0",
            "landing": {"database": "LANDING_DB", "tablePrefix": "STG_"},
            "rules": [
                {
                    "id": "include-source",
                    "action": "include",
                    "mode": "sqlServerCdc",
                    "source": {"server": "sales.example.com"},
                }
            ],
        }
        rewritten = json.loads(config.round_trip(dumps(original)))
        self.assertEqual(rewritten, original)
        self.assertNotIn("schema", rewritten["landing"])
        self.assertNotIn("mode", rewritten["landing"])

    def test_invalid_document_is_not_rewritten(self) -> None:
        with self.assertRaises(config.ConfigError):
            config.round_trip(dumps(document(rules=[])))


if __name__ == "__main__":
    unittest.main()
