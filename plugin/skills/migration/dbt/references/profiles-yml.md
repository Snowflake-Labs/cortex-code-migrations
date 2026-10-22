# Rewriting profiles.yml for Snowflake

Step 3.3 says what must be true of the output. This file is the template, the authentication
choice, and the `target.name` hazard in full.

## Why every target must be rewritten

SnowConvert copies `source/profiles.yml` to `snowflake/profiles.yml` unmodified, so it always
contains `type: redshift` (or bigquery, databricks, …) on every run. Replace the connection
details of **every** target — `type`, host, credentials — leaving no target still typed to the
source adapter. A target left on the source platform means a stray `--target` or a stale
`target:` default silently points dbt back at it.

## Do not collapse or rename the targets

`target.name` is frequently load-bearing *program logic* rather than an environment label:
models, macros, and `dbt_project.yml` branch on it. Check before touching the names:

```bash
grep -rn 'target\.name' snowflake/models snowflake/macros snowflake/dbt_project.yml | wc -l
```

If that is nonzero, keep every existing target name.

Pay particular attention to `generate_alias_name.sql` / `generate_schema_name.sql`: a target
name that no longer appears in their `in [...]` tests silently renames or relocates **every
model in the project**, and `dbt parse` and `dbt compile` both still pass. One real project had
6 Redshift targets and 111 `target.name` references; collapsing them to a single target named
`snowflake` would have re-pointed 71 files' branch selection and renamed all 2,033 models.

For the `target:` default, prefer whichever existing name keeps user-prefixed aliases, so a run
cannot clobber shared relations.

## Template

One entry per existing target name, connection details shared by anchor:

```yaml
<project_name>:
  target: <existing_default_target_name>
  outputs:
    <existing_target_name_1>: &snowflake_conn
      type: snowflake
      account: "{{ env_var('DBT_SNOWFLAKE_ACCOUNT') }}"
      user: "{{ env_var('DBT_SNOWFLAKE_USER') }}"
      role: "{{ env_var('DBT_SNOWFLAKE_ROLE') }}"
      # authentication — key pair shown; see the table below for alternatives
      private_key_path: "{{ env_var('DBT_SNOWFLAKE_PRIVATE_KEY_PATH', '') }}"
      private_key_passphrase: "{{ env_var('DBT_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE', '') }}"
      database: "{{ env_var('DBT_SNOWFLAKE_DATABASE', '<TARGET_DATABASE>') }}"
      warehouse: "{{ env_var('DBT_SNOWFLAKE_WAREHOUSE', '<TARGET_WAREHOUSE>') }}"
      schema: "<TARGET_SCHEMA>"
      threads: 4
    <existing_target_name_2>:
      <<: *snowflake_conn
      schema: "<OTHER_SCHEMA>"
```

Fill placeholders from `configure()`.

## Authentication

**Pick exactly one method.** The auth keys belong on every target, which is what the
`&snowflake_conn` anchor and `<<:` merge are for.

| Method | Keys | When |
|---|---|---|
| Key pair | `private_key_path` (or inline `private_key`) + `private_key_passphrase` | **Default choice.** The only unattended method that is not deprecated |
| SSO / interactive | `authenticator: externalbrowser` | Local development only — prompts a browser, so it cannot run unattended |
| Password | `password` | Snowflake ended single-access password login on 2026-08-31; service users (`TYPE = LEGACY_SERVICE`) only |
| Password + MFA | `authenticator: username_password_mfa` + `password` | Interactive use where key pair is not yet set up |

**Never write a credential into the file** — not a real one and not a dummy that looks real.
Every secret goes through `env_var()` indirection, exactly as `account`/`user` already do, and
the value lives in the environment.

Give every `env_var()` a default (e.g. `"{{ env_var('DBT_SNOWFLAKE_DATABASE', 'dwh') }}"`, and
`''` for the auth keys) so a missing variable degrades instead of becoming a hard parse
failure — `dbt parse` evaluates these at parse time even though it never connects.

## Verify before the execution gate

`dbt parse` and `dbt compile` never authenticate, so a broken credential first surfaces inside
Step 5.3's execution gate, where it is indistinguishable from a conversion defect. `dbt debug`
tests credentials specifically:

```bash
dbt debug --project-dir <DBT_PROJECT_PATH> --profiles-dir <PROFILES_DIR>
```

Run it once per target that Step 5.3 will use. It must report a passing connection before
`dbt seed` / `dbt run --empty`.
