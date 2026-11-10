---
name: no-source-project
description: Run setup without a source connection for a project that never reads the source database (nothing to extract; AI-First ETL run by an external_command launcher).
license: Proprietary. See License-Skills for complete terms
---

# No-source project

A source connection is required everywhere else in setup. This is the one
exception, and it applies only when **both** hold:

- Nothing is extracted from the source database: the code came from files
  (`code_source` is not `extract`), tables included.
- The ETL is AI-First: every registered ETL unit has `kind = 'etl'` and
  `extensions.sourcePlatform` set (Apache Hop, for example). Its source side runs
  through an `external_command` launcher, not on the source database. Before
  registration, the user has said they have ETL code (`has_etl_code`).

`configure(no_source_connection=true)` refuses any other project shape: code
extracted from the database, no ETL declared, or a native SSIS or Informatica
package registered. The answer also stops counting if such a package is
registered later; setup then asks for a source again.

## The answer

Offer **No source connection**, described as "Nothing to extract; the ETL runs
through its launcher", next to the existing connections. On that answer:

```
configure(no_source_connection=true)
```

It completes `configureExtractionSource` and the source half of the locked
`configureSandboxProfile`. It also removes a source connection saved earlier as
the project default, so `scai test etl-validate` and deploy never open or test
it. `configure()` then reports `no_source_connection: true`. A later
`configure(source_connection=<name>)` replaces the answer.

Never edit `profiles.local.yaml` or `project.local.yml` by hand to blank a
source. `configure` and `scai profile create` do it.

## Sandbox profile (configure-sandbox-profile.md)

- **Step 3:** the source is answered. Ask only for a missing Snowflake
  connection, and say the sandbox has no source connection.
- **Step 4:** with no source to query, take the source databases from the
  registered code units, or from the existing `source:` keys of
  `.scai/bindings/database-bindings.yaml`.
- **Step 6:** create the profile with `--no-source-connection` in place of
  `--source-connection <source>` (`scai profile create` refuses a missing
  source without it). Persist with `no_source_connection=true` in place of
  `source_connection`:

```bash
scai profile create <name> \
  --no-source-connection \
  --snowflake-connection <snowflake> \
  --database-bindings .scai/bindings/database-bindings.yaml \
  --sandbox \
  --description "Sandbox profile for migrating <project-name> — Snowflake connection used by AIM for deploy, validate, and test."
```

```
configure(
  sandbox_profile="<name>",
  no_source_connection=true,
  snowflake_connection="<snowflake>",
  ensure_target_database=true
)
```
