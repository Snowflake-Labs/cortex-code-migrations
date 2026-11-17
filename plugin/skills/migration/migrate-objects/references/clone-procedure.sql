-- SnowConvert AI testing: the reference clone procedure.
--
-- scai test validate isolates each data-changing test in a clone of the target database.
-- This procedure makes that clone with the same statement validate runs itself, and hands the
-- clone database to the role validate connects with, so that role never needs CREATE DATABASE.
-- Inside the clone every object keeps the owner it has in the source, exactly as when that role
-- clones the database itself.
-- Users who share the runner role are not separated from each other. The procedure's user
-- check prevents accidents, not misuse.
-- The procedure does not check the caller's role: every role with USAGE on it can clone every
-- allowlisted source, and each clone goes to the runner role. Use one procedure per runner role.
--
-- No new role is required. Any existing role that holds CREATE DATABASE, for example the
-- customer's DBA role or SYSADMIN, runs this script and owns the procedure. A dedicated role
-- is optional, for least privilege. <INSTALLER_ROLE> below is that role. It must hold:
--   GRANT CREATE DATABASE ON ACCOUNT TO ROLE <INSTALLER_ROLE>;
--     -- The body runs CREATE OR REPLACE DATABASE.
--   GRANT ROLE MIGRATION_ROLE TO ROLE <INSTALLER_ROLE>;
--     -- The runner role has to be granted to the installer, or the handover is refused.
--   GRANT USAGE ON DATABASE MIGRATION_TARGET TO ROLE <INSTALLER_ROLE>;
--   GRANT USAGE ON ALL SCHEMAS IN DATABASE MIGRATION_TARGET TO ROLE <INSTALLER_ROLE>;
--   GRANT USAGE ON FUTURE SCHEMAS IN DATABASE MIGRATION_TARGET TO ROLE <INSTALLER_ROLE>;
--     -- The clone reads each allowlisted source. Repeat this trio for each one.
--   GRANT USAGE ON DATABASE SNOWCONVERT_AI TO ROLE <INSTALLER_ROLE> WITH GRANT OPTION;
--   GRANT CREATE SCHEMA ON DATABASE SNOWCONVERT_AI TO ROLE <INSTALLER_ROLE>;
--     -- On the metadata database: USAGE with grant option, plus CREATE SCHEMA. Ownership of that database covers both.
-- The installer role needs USAGE on a warehouse, and the session must have one, for the schema check: RESULT_SCAN fails with 000606 without it.
--   GRANT USAGE ON WAREHOUSE <WAREHOUSE> TO ROLE <INSTALLER_ROLE>;
-- Run USE WAREHOUSE <WAREHOUSE>; first unless the connection already selects one the role can use.
-- Then run this whole script as <INSTALLER_ROLE>. Edit the two SET lines and the ALLOWLIST line first;
-- every THEN in the allowlist is the RUNNER_ROLE value.
-- Run it in a client that stops at the first error: Snowsight (Run all) or snow sql -f, not one that continues past errors, or the schema check cannot stop the install.

SET METADATA_DATABASE = 'SNOWCONVERT_AI';  -- your SnowConvert metadata database, as scai resolves it (CUSTOM_SNOWCONVERT_DATABASE, else CUSTOM_SNOWFLAKE_DATABASE_FOR_METADATA, else metadata_database in .scai/config/plugin.yml, else SNOWCONVERT_AI); unquoted
SET RUNNER_ROLE = 'MIGRATION_ROLE';        -- the role scai test validate connects with
-- Keep the ISOLATION schema and CREATE_TEST_CLONE names: under isolation_strategy auto, scai test validate looks for the procedure by exactly this name in the metadata database.

SET ISOLATION_SCHEMA = $METADATA_DATABASE || '.ISOLATION';
SET CLONE_PROCEDURE = $ISOLATION_SCHEMA || '.CREATE_TEST_CLONE';
CREATE SCHEMA IF NOT EXISTS IDENTIFIER($ISOLATION_SCHEMA) WITH MANAGED ACCESS;
-- An existing ISOLATION schema is kept as it is, so stop unless it is managed-access and owned by this role.
SHOW SCHEMAS LIKE 'ISOLATION' IN DATABASE IDENTIFIER($METADATA_DATABASE);
SELECT CAST(IFF(COUNT_IF("owner" = CURRENT_ROLE() AND "options" LIKE '%MANAGED ACCESS%') = 1, '0',
  'ISOLATION schema exists but is not managed-access and owned by ' || CURRENT_ROLE()) AS INT)
  FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

CREATE OR REPLACE PROCEDURE IDENTIFIER($CLONE_PROCEDURE)(SOURCE_DATABASE VARCHAR, CLONE_NAME VARCHAR)
RETURNS VARCHAR
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  not_allowed EXCEPTION (-20001, 'clone request refused: source database is not on the clone allowlist');
  bad_name EXCEPTION (-20002, 'clone request refused: clone name must be <SOURCE>_REPLAY_<...>_<YOUR USER>_<8 hex>');
  runner_role VARCHAR;
  user_part VARCHAR;
BEGIN
  -- ALLOWLIST: one WHEN per source database, each THEN the runner role (RUNNER_ROLE above). Bare, upper-case names.
  runner_role := CASE :SOURCE_DATABASE WHEN 'MIGRATION_TARGET' THEN 'MIGRATION_ROLE' END;
  IF (runner_role IS NULL OR NOT REGEXP_LIKE(:SOURCE_DATABASE, '[A-Z_][A-Z0-9_$]*') OR NOT REGEXP_LIKE(:runner_role, '[A-Z_][A-Z0-9_$]*')) THEN
    RAISE not_allowed;
  END IF;
  -- The caller's user, folded exactly as scai folds it into the clone names it makes. The fold leaves only
  -- A-Z, 0-9 and _, so user_part is safe inside the pattern below; the source is compared literally, never as a pattern.
  user_part := TRIM(UPPER(REGEXP_REPLACE(CURRENT_USER(), '[^0-9A-Za-z]+', '_')), '_');
  IF (:CLONE_NAME IS NULL OR :user_part = '' OR NOT STARTSWITH(:CLONE_NAME, :SOURCE_DATABASE || '_REPLAY_')
      OR NOT REGEXP_LIKE(SUBSTR(:CLONE_NAME, LENGTH(:SOURCE_DATABASE) + 9), '([A-Z0-9_]*_)?' || :user_part || '_[0-9A-F]{8}')) THEN
    RAISE bad_name;
  END IF;
  CREATE OR REPLACE DATABASE IDENTIFIER(:CLONE_NAME) CLONE IDENTIFIER(:SOURCE_DATABASE);
  GRANT OWNERSHIP ON DATABASE IDENTIFIER(:CLONE_NAME) TO ROLE IDENTIFIER(:runner_role) COPY CURRENT GRANTS;
  RETURN CLONE_NAME;
END;
$$;

GRANT USAGE ON DATABASE IDENTIFIER($METADATA_DATABASE) TO ROLE IDENTIFIER($RUNNER_ROLE);
GRANT USAGE ON SCHEMA IDENTIFIER($ISOLATION_SCHEMA) TO ROLE IDENTIFIER($RUNNER_ROLE);
GRANT USAGE ON PROCEDURE IDENTIFIER($CLONE_PROCEDURE)(VARCHAR, VARCHAR) TO ROLE IDENTIFIER($RUNNER_ROLE);
