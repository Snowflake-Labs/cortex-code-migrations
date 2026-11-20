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

**Owners, other users and this month's spend.** Read these before the cap is asked (Step 3). All are
read-only:

```sql
SHOW WAREHOUSES LIKE '<WAREHOUSE>';            -- "owner"
SHOW COMPUTE POOLS LIKE '<COMPUTE_POOL>';      -- "owner", "num_services", "num_jobs"
SHOW SERVICES IN COMPUTE POOL <COMPUTE_POOL>;  -- the services and jobs <ROLE> can see

SELECT COALESCE(SUM(CREDITS_USED), 0) AS WAREHOUSE_CREDITS
  FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
  WHERE WAREHOUSE_NAME = UPPER('<WAREHOUSE>')
    AND START_TIME >= DATE_TRUNC('MONTH', CURRENT_TIMESTAMP());
SELECT COALESCE(SUM(CREDITS_USED), 0) AS POOL_CREDITS
  FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWPARK_CONTAINER_SERVICES_HISTORY
  WHERE COMPUTE_POOL_NAME = UPPER('<COMPUTE_POOL>')
    AND START_TIME >= DATE_TRUNC('MONTH', CURRENT_TIMESTAMP());
```

Count only rows whose `name` is exactly the object's (`_` is a wildcard in `LIKE`). Use the exact name, without
`UPPER`, for a quoted mixed-case name. The sum of the two credits is `<MONTH_SPEND>`. These views lag by up to
a few hours, so it is a floor. A failing spend query (`does not exist or not authorized`, usually because
`SNOWFLAKE.USAGE_VIEWER` is missing) means the spend is **unknown**. Say so on the card. It does not stop the
offer.

An object is **shared** when its owner is not `<ROLE>`, or when the pool runs a service other than this
migration's orchestrator and worker. The warehouse is also shared when the user says it serves other work. A
cap on a shared object stops everyone who uses it, not only DMV, so recommend a dedicated warehouse and pool if
they want the cap to stop only this migration.

`SHOW SERVICES` lists only services `<ROLE>` holds a privilege on (unless it has MANAGE GRANTS), so owning the
pool does not mean every service on it is visible: another team's service can run there unseen, and the stop
suspends it too. Reconcile the counts: `num_services` + `num_jobs` from `SHOW COMPUTE POOLS` counts every
service and job running on the pool, visible or not. Compare it with the `SHOW SERVICES` rows whose `status`
is `RUNNING` and that are this migration's orchestrator, worker or their jobs. When the pool's count is
higher, or the pool row or its counts cannot be read, isolation cannot be established: the pool is
**possibly shared**. Treat it like a shared pool on the card; it does not stop the offer.

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
CALL SNOWCONVERT_AI.BUDGETS.DMV_<POOL_ID>_BUDGET!GET_SPENDING_HISTORY(
  TIME_LOWER_BOUND => DATE_TRUNC('MONTH', CURRENT_TIMESTAMP()),
  TIME_UPPER_BOUND => CURRENT_TIMESTAMP());
```

The sum of `CREDITS_SPENT` is `<BUDGET_SPEND>`: what the budget has already counted against its limit this
month. It can be less than `<MONTH_SPEND>`, since the budget counts an object only from when it was added. If
the call fails, `<BUDGET_SPEND>` is **unknown**; say so on the card.

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

Open the card with what Step 1 read:

> `<WAREHOUSE>` is owned by `<WAREHOUSE_OWNER>` and `<COMPUTE_POOL>` by `<POOL_OWNER>`. This month they have
> used about `<MONTH_SPEND>` credits so far.

Add each warning that applies:

- **A shared object:** "`<OBJECT>` is owned by `<OWNER>` (or: also runs `<OTHER_SERVICES>`). When the cap trips,
  it suspends `<OBJECT>` for everyone who uses it, not only this migration."
- **Possibly shared:** "`<COMPUTE_POOL>` runs `<POOL_COUNT>` services and jobs, and I can see only
  `<VISIBLE_COUNT>` of them as this migration's (or: I could not read how many it runs). Others may run there
  that `<ROLE>` cannot see, and the cap would suspend them too." Recommend a dedicated pool as for a shared one.
- **A new budget's first month** (Step 5 creates it): "The `<MONTH_SPEND>` credits used so far this month are
  not counted: a new budget counts objects added to it one by one only from when they are added (their
  earlier usage is not backfilled), so this month the cap counts only what they spend from now on; from next
  month it counts the whole month." A `PROJECTED`
  basis forecasts from those few days only, so it may stop too early or too late this month. The same holds
  for an object an existing budget does not link yet.
- **An existing budget near the cap:** the budget already counts `<BUDGET_SPEND>` this month, so a limit whose
  threshold is at or below it trips at its next refresh. Never suggest a limit at or below `<BUDGET_SPEND>`.
  When you give example limits, start them above it with room for the migration. If the user picks a limit
  whose threshold is at or below it, say that before Step 5: "This cap is already reached, so it would suspend
  `<WAREHOUSE>` and `<COMPUTE_POOL>` within hours of being set." Ask them to confirm it or pick another.
- **Spend unknown:** "I could not read this month's spend." For an existing budget whose `<BUDGET_SPEND>` is
  unknown, add: "so I cannot tell whether this cap is already reached."

Still offer the cap. The warnings tell the user what it will stop, and the user decides. A no is a decline.

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

`SHOW GRANTS TO ROLE` lists only direct grants, not those `<ROLE>` inherits through a role granted to it. With
`<ROLE>` as the session's role, a privilege the `ON` results list for another grantee is held when
`SELECT IS_ROLE_IN_SESSION('<grantee_name>');` returns `TRUE`. For the two database roles,
`IS_DATABASE_ROLE_IN_SESSION` takes the relative name and reads it in the session's database (a fully
qualified `'SNOWFLAKE.BUDGET_CREATOR'` always returns `FALSE`), so switch to `SNOWFLAKE` and back:

```sql
SELECT CURRENT_DATABASE();   -- note it, to restore below
USE DATABASE SNOWFLAKE;
SELECT IS_DATABASE_ROLE_IN_SESSION('BUDGET_CREATOR'), IS_DATABASE_ROLE_IN_SESSION('USAGE_VIEWER');
USE DATABASE <previous_database>;   -- skip when CURRENT_DATABASE() was NULL
```

If `USE DATABASE SNOWFLAKE` fails, the role holds neither database role. Only what none of these shows is missing.

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
