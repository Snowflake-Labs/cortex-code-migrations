---
name: budget-guardrail
description: Cap the spend of DMV's SPCS infrastructure — one custom Snowflake Budget over the project's warehouse and compute pool, with a custom action that turns off auto-resume and suspends both when spend reaches a threshold. Runs before the first data_infrastructure(mode="up") whenever the orchestrator or a worker is on SPCS.
parent_skill: data-infrastructure-setup
license: Proprietary. See License-Skills for complete terms
---

# Budget Guardrail

Idle or forgotten SPCS infrastructure keeps spending credits: the compute pool bills while the orchestrator
or worker service runs, and the warehouse wakes for every orchestrator query. This skill sets a hard
backstop: one **custom budget** that tracks the warehouse and the compute pool, and a **custom action** that
turns off auto-resume and suspends both when spend reaches a threshold of the monthly limit.

## When this runs

| Situation | What to do |
|-----------|------------|
| Step 0 of `../SKILL.md` put the orchestrator **or** a worker on SPCS (SPCS + SPCS, or either hybrid split) and Question 0 resolved the pool | Run this skill **before the first** `data_infrastructure(mode="up")` |
| Resuming a configured SPCS / hybrid project whose warehouse or pool is in no budget | Run it before `up` (see Idempotency in `../SKILL.md`) |
| Resuming a configured SPCS / hybrid project whose warehouse and pool both list `DMV_<POOL_ID>_BUDGET` | Run Steps 1, 2 and 6 before `up`: they are read-only. Linked objects do not prove the action can run; repair what Step 6 finds only after a yes |
| The user asks to cap, limit or budget the migration's spend | Run it |
| Fully local (no compute pool) | Skip it. Offer the optional resource monitor in Step 5 instead |

**The user decides.** Bring the guardrail up every time it applies, but **run nothing until the user says
yes**. They can decline (no grants, a budget managed elsewhere, a PoC). On a decline, tell them:

> No spend cap is in place: the warehouse and the compute pool keep spending until teardown.

Then return to the caller. Do not block `up` on it. Every way this skill can end without a cap is a decline
and ends the same way, with the no-cap line and return: a no to any offer, grants that cannot be had, a
**Stop and ask** in Step 2 that the user does not resolve, or a Step 5 script that stops at an error and is
not re-run. The caller then continues to `up`.

## Step 1 — Identify the two objects

- **Compute pool:** the one Question 0 resolved, or `compute_pool` in `.scai/settings/cloud-migration.yaml`.
- **Warehouse:** the **migration warehouse**, the one the orchestrator runs on: `warehouse = "<WAREHOUSE>"`
  under the active connection in `~/.snowflake/config.toml`, as settled by Question 2 of `../SKILL.md`. The
  caller resolves it before loading this skill. If it is still unset, ask Question 2 now and set it in
  `config.toml` first. Do not take the warehouse from the session you run SQL in: it can be a different one,
  and the cap would then stop the wrong warehouse while the migration's keeps spending.
- **Role:** `SELECT CURRENT_ROLE();` — this role will own the budget and the procedure.
- **`<POOL_ID>`:** the pool name in upper case, with every character other than `A`–`Z`, `0`–`9` and `_`
  replaced by `_` (pool `dmv_pool` gives `DMV_POOL`). The budget is `DMV_<POOL_ID>_BUDGET` and the procedure
  `DMV_<POOL_ID>_STOP()`. A pool is in only one custom budget, so naming both after it keeps another
  project's guardrail in the same account from being reused or replaced.

If the warehouse also serves other workloads, say so: the cap stops them too. Recommend a dedicated warehouse
for the migration if they want the cap to stop only DMV.

## Step 2 — Check for existing budgets (before any change)

Everything in this step is read-only.

```sql
SELECT SYSTEM$SHOW_BUDGETS_FOR_RESOURCE('WAREHOUSE', '<WAREHOUSE>');
SELECT SYSTEM$SHOW_BUDGETS_FOR_RESOURCE('COMPUTE_POOL', '<COMPUTE_POOL>');
SHOW SCHEMAS LIKE 'BUDGETS' IN DATABASE SNOWCONVERT_AI;
```

Each `SYSTEM$SHOW_BUDGETS_FOR_RESOURCE` returns `[]` or a list of budget names. An object added directly can
be in **only one custom budget**, and `ADD_RESOURCE` **silently moves** it out of the one it is in, so another
team's budget would stop tracking it with no warning.

**The schema.** Step 5 creates `SNOWCONVERT_AI.BUDGETS`, so on a first run it is not there yet. `SHOW SCHEMAS`
lists only schemas the role holds a privilege on, so no row means the schema is absent *or* hidden from this
role; Snowflake does not tell the two apart. A role with MANAGE GRANTS sees every schema (check
`SHOW GRANTS TO ROLE <ROLE>;`), so for it no row means absent. For any other role, say on the Step 3 card that
`<ROLE>` cannot see the schema: it is new, or another role owns it and `<ROLE>` has no grant on it. If
`SHOW SCHEMAS` itself fails with `does not exist or not authorized`, the role lacks USAGE on `SNOWCONVERT_AI`:
that is a missing grant (Step 4). If the user picks another schema in Step 3, run this step again for it.

When the schema is visible, look for this pool's guardrail in it:

```sql
SHOW SNOWFLAKE.CORE.BUDGET LIKE 'DMV_<POOL_ID>_BUDGET' IN SCHEMA SNOWCONVERT_AI.BUDGETS;
SHOW PROCEDURES LIKE 'DMV_<POOL_ID>_STOP' IN SCHEMA SNOWCONVERT_AI.BUDGETS;
```

`_` is a wildcard in `LIKE`, so count only a row whose `name` is exactly the one asked for. Then inspect only
what exists. **If the budget exists:**

```sql
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_LINKED_RESOURCES();
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_CUSTOM_ACTIONS();
```

**If the procedure exists:**

```sql
DESCRIBE PROCEDURE SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_STOP();
```

A budget is **this project's** when its linked resources are only `<WAREHOUSE>` and `<COMPUTE_POOL>`, or a
subset of them, and its actions call only `DMV_<POOL_ID>_STOP`. A procedure is this project's when its body is
this skill's stop for exactly those two objects. A run that stopped partway leaves a subset: the budget
without the procedure, the procedure without the budget, or both without every resource or the action.

| Result | Action |
|--------|--------|
| Schema absent (no row, and the role has MANAGE GRANTS) | No named objects. Continue to Step 3; Step 5 creates the schema |
| Schema hidden (no row, and the role lacks MANAGE GRANTS) | No named objects this role can see. Continue to Step 3 and say it on the card. Nothing is overwritten if it exists: Step 5's first `CREATE` in it fails with `does not exist or not authorized` and the script stops there. Then **stop and ask** for USAGE, CREATE SNOWFLAKE.CORE.BUDGET and CREATE PROCEDURE on it, or for another schema. If neither can be had, that is a decline: say the no-cap line and return |
| Either object lists a budget other than `SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET` | **Stop and ask.** Name the budget and the object. Do not add that object unless the user confirms it may leave that budget. Offer to cover only the free object, or to go on without a cap. Going on without one is a decline: say the no-cap line and return |
| The named budget links a resource other than these two, calls another procedure, or the procedure suspends anything else | **Stop and ask.** Show what it covers. Change nothing unless the user confirms it is theirs and may be changed. If the only difference is the warehouse, offer the warehouse change below. If they do not confirm, that is a decline: say the no-cap line and return |
| Neither named object exists | Continue to Step 3 |
| Budget only, and it is this project's | Continue to Step 3. Step 5 keeps the budget, adds any object not yet linked, then creates the procedure, its grants and the action |
| Procedure only, and it is this project's | Continue to Step 3. Step 5 creates the budget and links both objects, replaces the procedure with the same body, then grants it and adds the action |
| Both exist and are this project's, but an object or the action is missing | Continue to Step 3. Step 5 adds only what is missing |
| Both objects list `DMV_<POOL_ID>_BUDGET`, and it is this project's guardrail with one action | Read it back (Step 6). It is in place only when Step 6 passes; return then |

**The migration warehouse changed** (the guardrail covers `<OLD_WAREHOUSE>`, and Question 2 or
`config.toml` now names `<WAREHOUSE>`): the old warehouse stays capped and the new one is not. Check the new
warehouse as above, then show this, and run it only after a yes:

```sql
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!REMOVE_RESOURCE(
  SELECT SYSTEM$REFERENCE('WAREHOUSE', '<OLD_WAREHOUSE>', 'SESSION', 'APPLYBUDGET'));
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!ADD_RESOURCE(
  SELECT SYSTEM$REFERENCE('WAREHOUSE', '<WAREHOUSE>', 'SESSION', 'APPLYBUDGET'));
```

Then re-create the procedure and re-grant its USAGE to the application, as in Step 5, with `<WAREHOUSE>`, and
read it back (Step 6). The action references the procedure by name, so it does not need to be added again.

## Step 3 — Ask for the cap (one card)

Ask together:

1. **Monthly limit** in credits — the budget's spending limit.
2. **Threshold %** of that limit at which to stop everything — default `100` (0–1000).
3. **Basis** — **`ACTUAL`** (recommended: stops when real spend reaches the threshold) or **`PROJECTED`**
   (stops early, when Snowflake projects spend will reach it by month end).

Also confirm the schema that holds the budget and the procedure: `SNOWCONVERT_AI.BUDGETS` by default, kept
apart from the orchestrator's schemas so their cleanup never drops the guardrail.

## Step 4 — Check grants

Run `SHOW GRANTS TO ROLE <ROLE>;`, `SHOW GRANTS ON WAREHOUSE <WAREHOUSE>;` and
`SHOW GRANTS ON COMPUTE POOL <COMPUTE_POOL>;`. The role needs:

| Needed for | Privilege |
|------------|-----------|
| Creating the budget | database roles `SNOWFLAKE.BUDGET_CREATOR` and `SNOWFLAKE.USAGE_VIEWER`; USAGE on the database and CREATE SNOWFLAKE.CORE.BUDGET and CREATE PROCEDURE on the schema |
| Adding the two objects | APPLYBUDGET on the warehouse and on the pool (the budget's owner already holds its ADMIN instance role) |
| The procedure's own actions (it runs as its owner) | OPERATE and MODIFY on the warehouse and on the pool |

For anything missing, show the exact statements for an admin to run, then wait:

```sql
GRANT DATABASE ROLE SNOWFLAKE.BUDGET_CREATOR TO ROLE <ROLE>;
GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE <ROLE>;
GRANT USAGE ON DATABASE SNOWCONVERT_AI TO ROLE <ROLE>;
GRANT CREATE SCHEMA ON DATABASE SNOWCONVERT_AI TO ROLE <ROLE>;   -- only if BUDGETS does not exist yet
GRANT CREATE SNOWFLAKE.CORE.BUDGET, CREATE PROCEDURE ON SCHEMA SNOWCONVERT_AI.BUDGETS TO ROLE <ROLE>;
GRANT APPLYBUDGET, OPERATE, MODIFY ON WAREHOUSE <WAREHOUSE> TO ROLE <ROLE>;
GRANT APPLYBUDGET, OPERATE, MODIFY ON COMPUTE POOL <COMPUTE_POOL> TO ROLE <ROLE>;
```

If the grants cannot be had, this is a decline: say the no-cap line above and return.

## Step 5 — Show the SQL, then run it after a yes

Show the whole script with the user's values filled in. Run nothing until the user says yes to **this**
script. Run it statement by statement and stop at the first error. Show the error and what already ran, then
offer to fix the cause and run the script again (Step 2's rows for a partial run say what is left), or to go on
without a cap. Going on without one is a decline: say the no-cap line and return.

```sql
CREATE SCHEMA IF NOT EXISTS SNOWCONVERT_AI.BUDGETS;

-- The budget and its monthly limit in credits
CREATE SNOWFLAKE.CORE.BUDGET IF NOT EXISTS SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET();
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!SET_SPENDING_LIMIT(<LIMIT>);

-- The two objects it tracks
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!ADD_RESOURCE(
  SELECT SYSTEM$REFERENCE('WAREHOUSE', '<WAREHOUSE>', 'SESSION', 'APPLYBUDGET'));
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!ADD_RESOURCE(
  SELECT SYSTEM$REFERENCE('COMPUTE POOL', '<COMPUTE_POOL>', 'SESSION', 'APPLYBUDGET'));

-- The stop. Auto-resume goes off first so nothing restarts either object in between.
-- It tries all four changes, skips a suspend only for an object already SUSPENDED, and fails if any change
-- failed, so Snowflake retries the action (once) instead of taking a partial stop for a full one.
CREATE OR REPLACE PROCEDURE SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_STOP()
RETURNS STRING
LANGUAGE SQL
EXECUTE AS OWNER
AS
$$
DECLARE
  failed BOOLEAN DEFAULT FALSE;
  obj_state STRING;
  stop_failed EXCEPTION (-20001, 'DMV budget stop failed: <WAREHOUSE> or <COMPUTE_POOL> may still be running. Check their state and the OPERATE and MODIFY grants of the procedure owner.');
BEGIN
  BEGIN
    ALTER WAREHOUSE <WAREHOUSE> SET AUTO_RESUME = FALSE;
  EXCEPTION
    WHEN OTHER THEN failed := TRUE;
  END;
  BEGIN
    ALTER COMPUTE POOL <COMPUTE_POOL> SET AUTO_RESUME = FALSE;
  EXCEPTION
    WHEN OTHER THEN failed := TRUE;
  END;
  BEGIN
    obj_state := NULL;
    SHOW WAREHOUSES LIKE '<WAREHOUSE>';
    SELECT "state" INTO :obj_state FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
      WHERE UPPER("name") = UPPER('<WAREHOUSE>');
    IF (obj_state IS DISTINCT FROM 'SUSPENDED') THEN
      ALTER WAREHOUSE <WAREHOUSE> SUSPEND;
    END IF;
  EXCEPTION
    WHEN OTHER THEN failed := TRUE;
  END;
  BEGIN
    obj_state := NULL;
    SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';
    SELECT "state" INTO :obj_state FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
      WHERE UPPER("name") = UPPER('<COMPUTE_POOL>');
    IF (obj_state IS DISTINCT FROM 'SUSPENDED') THEN
      ALTER COMPUTE POOL <COMPUTE_POOL> SUSPEND;
    END IF;
  EXCEPTION
    WHEN OTHER THEN failed := TRUE;
  END;
  IF (failed) THEN
    RAISE stop_failed;
  END IF;
  RETURN 'DMV warehouse and compute pool suspended by budget';
END;
$$;

-- The SNOWFLAKE application calls the procedure. Re-grant whenever the procedure is replaced.
GRANT USAGE ON DATABASE SNOWCONVERT_AI TO APPLICATION SNOWFLAKE;
GRANT USAGE ON SCHEMA SNOWCONVERT_AI.BUDGETS TO APPLICATION SNOWFLAKE;
GRANT USAGE ON PROCEDURE SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_STOP() TO APPLICATION SNOWFLAKE;

-- Call it when <BASIS> spend reaches <THRESHOLD>% of the limit. <BASIS> is 'ACTUAL' or 'PROJECTED'.
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!ADD_CUSTOM_ACTION(
  SYSTEM$REFERENCE('PROCEDURE', 'SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_STOP()', 'SESSION', 'USAGE'),
  ARRAY_CONSTRUCT(),
  '<BASIS>',
  <THRESHOLD>);
```

Step 2 has confirmed that any existing `DMV_<POOL_ID>_*` object is this project's, so the `CREATE OR REPLACE`
only replaces this project's procedure. **Completing a partial run:** show and run only what Step 2 found
missing. Skip `ADD_RESOURCE` for an object the budget already links, and skip `ADD_CUSTOM_ACTION` when
`GET_CUSTOM_ACTIONS` already lists `DMV_<POOL_ID>_STOP` with the user's basis and threshold: running it again
adds a second action (a budget holds at most 10). If the budget lists an action but the procedure was missing,
`CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!REMOVE_CUSTOM_ACTIONS();` and add it again after the procedure
is created. To change the threshold or basis, remove the actions the same way, then add it again.

**Optional, warehouse only:** a resource monitor reacts faster than a budget, but it cannot cover a compute
pool. Offer it, and run it only on a separate yes:

```sql
CREATE RESOURCE MONITOR DMV_<WAREHOUSE>_MONITOR WITH CREDIT_QUOTA = <LIMIT> FREQUENCY = MONTHLY
  START_TIMESTAMP = IMMEDIATELY TRIGGERS ON <THRESHOLD> PERCENT DO SUSPEND;
ALTER WAREHOUSE <WAREHOUSE> SET RESOURCE_MONITOR = DMV_<WAREHOUSE>_MONITOR;
```

This needs ACCOUNTADMIN, and replaces any monitor the warehouse already has, so check
`SHOW WAREHOUSES LIKE '<WAREHOUSE>';` first.

## Step 6 — Read it back

```sql
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_SPENDING_LIMIT();
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_LINKED_RESOURCES();
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_CUSTOM_ACTIONS();
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!CONFIRM_CUSTOM_ACTIONS_ACCESS();
```

Confirm both objects are linked and one action is set with the user's basis and threshold. Then check
`CONFIRM_CUSTOM_ACTIONS_ACCESS`: `GET_CUSTOM_ACTIONS` still lists an action whose procedure was replaced or lost
its grant, but only `IS_VALID = TRUE` means the budget can call it. If `IS_VALID` is FALSE, the guardrail is
**not** in place: show the `REASON`, re-run the three `GRANT ... TO APPLICATION SNOWFLAKE` statements of Step 5
after a yes, and check again. If `REASON` says the procedure is missing, or `GET_CUSTOM_ACTIONS` shows no action
or more than one, or an object is not linked, re-granting is not enough: take the matching Step 2 row and complete
it through Steps 3 to 5.

Whenever the read-back fails, tell the user before anything runs:

> The spend cap is not working: `DMV_<POOL_ID>_BUDGET` tracks the warehouse and the compute pool, but its stop
> action is missing or cannot run, so nothing stops them at the threshold.

Then offer the repair above, run only after a yes, or a decline. On a decline, give the no-cap message from
"When this runs" and return. Do not report the guardrail in place until a read-back passes. When it passes, tell
them the caveats below.

## Caveats — always tell the user

- **It is a backstop, not a meter.** The budget refreshes up to every **6.5 hours**, so spend can pass the
  threshold before the action fires. `SET_REFRESH_TIER('TIER_1H')` refreshes hourly, but costs 12 times as
  much to run the budget.
- **An `ACTUAL` action fires at most once a month** (a `PROJECTED` one at most once a day). After a trip and
  a recovery in the same month, an `ACTUAL` cap will not fire again until next month.
  Snowflake retries a failed action once, so if the stop fails twice (a lost grant, an object mid-resize),
  nothing is stopped until the next window: check both objects' state after a budget notification.
- **Running work is not killed.** Suspending the warehouse lets running queries finish. Suspending the pool
  suspends its services (the orchestrator and an SPCS worker, and any other service on that pool), while
  running jobs finish first.
- **Each object can be in only one custom budget**, so adding either one later to another budget silently
  removes it from this one.
- **After a trip, `data_infrastructure(mode="up")` fails** until auto-resume is back on. Raise the limit
  first if the migration still needs more, then recover:

```sql
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!SET_SPENDING_LIMIT(<NEW_LIMIT>);   -- if needed
ALTER WAREHOUSE <WAREHOUSE> SET AUTO_RESUME = TRUE;
ALTER COMPUTE POOL <COMPUTE_POOL> SET AUTO_RESUME = TRUE;
ALTER COMPUTE POOL <COMPUTE_POOL> RESUME;
```

Then call `data_infrastructure(mode="up")` and check `job_status()` for any wave that was in flight.

**To remove the guardrail:** `DROP SNOWFLAKE.CORE.BUDGET SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET;` then
`DROP PROCEDURE SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_STOP();`.

Return control to the caller.
