# database-ingestion-config.json

Schema `1.0`. The validator in `scripts/database_ingestion_config.py` is the check this skill runs. It rejects unknown keys, so a document that passes here is the document conversion will parse.

The file is operator input. Credentials stay out of it: the validator rejects `credential`, `key`, `password`, `privateKey`, `private_key`, `secret`, and `token` at any depth.

## Document

| Field | Rule |
|---|---|
| `schemaVersion` | `"1.0"` |
| `landing.database` | Required. The Snowflake database converted snapshot SQL targets. |
| `landing.schema` | Optional. Omitted, the engine uses `RAW`. |
| `landing.tablePrefix` | Optional, at most 200 characters. Omitted, snapshot tables use `RAW_`. |
| `landing.mode` | Optional. `snapshot`, `sqlServerChangeTracking`, or `sqlServerCdc`. |
| `rules` | At least one rule. Each `id` is unique. |

Write `landing.schema`, `landing.tablePrefix`, and `landing.mode` only when the user sets them. The engine fills the two defaults above when those keys are absent.

## Rules

| Field | Rule |
|---|---|
| `action` | `include` or `exclude` |
| `source` | Exactly one of `server` or `connection`. Then optional `database`, `schema`, `table`, in that order: `schema` requires `database`, and `table` requires `schema`. |
| `mode` | Include rules only. Same three values as `landing.mode`. A rule mode overrides the landing mode for that rule. |
| `landing` | Include rules only. `schema`, `table`, or both. `table` requires `source.table`. |

An exclude rule has `id`, `action`, and `source`. `mode` and `landing` on an exclude rule fail validation.

`sqlServerChangeTracking` and `sqlServerCdc` are accepted by this file. Conversion decides whether a connection can use them and records a rejection on the database manifest when it cannot.
