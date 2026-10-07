# Action: Claim Objects

Add new objects to the working set.

> **Claim small batches.** Migrations are collaborative: an object claimed by one user is hidden from every other user's picker (`migration_status(next_objects)` excludes anyone's active claims). Claiming a large batch starves teammates of work and locks objects you may not get to for hours. Default to **showing the first 5 ready objects** (the picker's default page size) and let the user pick which to claim. Only fetch more when the user *explicitly* asks for a larger view (e.g. "show me 20", "list the whole wave"). Re-enter this skill after the user finishes a batch to show the next page.
>
> **Never auto-claim.** A casual "go ahead", "yes", "claim", or "next" is approval to *enter this skill and show the picker* — it is **not** approval to claim specific IDs. Always render the picker (Step 2) and wait for the user to name which objects to claim before calling `transition_status`.
>
> **Never substitute a category filter for picker IDs.** Do not claim with `where="source.objectType = 'table'"` or any other broad predicate as a shortcut. The `where` clause must be `id IN (...)` listing IDs the user picked from the picker output.

## Step 1: Discover

```
migration_status(mode="next_objects")
```

**Call the tool with no `limit` argument.** The tool returns 5 by default — that is the right number for the picker render.

> **`limit` rule.** Pass `limit` **only** when the user typed an explicit numeric request in this turn — e.g. "show me 20", "list 15 ready objects", "claim the whole wave (~30)". A casual "go ahead", "yes", "more", "show some more", or "next" is **not** an explicit request. If the user wants more without a number, ask "how many?" before calling the tool.

## Step 2: Confirm

> **Whatever the user said to enter this skill is not approval to claim specific IDs.** Even if the previous turn's answer was "claim", "pick up work", or "go ahead", that approval was for *entering* this skill — the IDs come from this turn's picker output, which the user has not yet seen. Render the list, then stop and wait.

Render the `objects` returned by Step 1 as a numbered list with id, name, object type, and the step the object is actually at — `pending at '<next_task>'`, taken verbatim from the entry's `next_task`. Objects reach the picker at whatever step they stopped on, so never assume it is `deploy`; the app's Tasks panel labels the same payload the same way, and a guessed step contradicts it on screen. Omit the label for an entry with no `next_task`. For any entry with `blocked: true`, append a `BLOCKED at <blocked_at>: <missing_deps> missing deps` marker instead.

If `total_available` exceeds the number of returned `objects`, tell the user how many ready objects exist in total and that they can ask for a numeric `limit` (e.g. "show me 20") to view more.

Then offer concrete picker options and **wait for the user's response.** Example render:

```
Next 5 ready objects (12 total):

1. [Staging].[CWSO_CUST_TBL]      table       pending at 'deploy'
2. [Staging].[CWSO_SOPEVEH_TBL]   table       BLOCKED at deploy: 2 missing deps
3. [Staging].[CWSO_ITEM_TBL]      table       pending at 'migrateData'
4. [Reporting].[v_daily_sales]    view        pending at 'validateView'
5. [Reporting].[sp_load_sales]    procedure   pending at 'createTests'

Pick one or more by number or name, or say "all 5 shown", "first 3", or "show more".
```

**Do not call `transition_status` until the user names which objects to claim in this turn.** Without a specific pick, there is nothing to claim — re-prompt instead of guessing.

> **A bare "all" means the objects shown, not `total_available`.** The picker is one page of the ready set, so offer the page size in the option wording ("all 5 shown") rather than an unscoped "all" a user reads as the whole set. Resolving it to the page is right — a large claim starves teammates — but say so in the reply; a user who wants the rest asks for a numeric `limit` (Step 1).

## Step 3: Claim

```
transition_status(status="begin", where="id IN ('<id1>', '<id2>')")
```

The `where` clause must be `id IN (...)` with the specific IDs the user picked in Step 2 — never a category predicate.

Say how many objects you claimed out of the `total_available` ready ones — a pick the user phrased as a whole-set word is otherwise indistinguishable from the whole set, and they cannot tell from your reply that it was narrowed to the page.

Surface any error and stop without retry.

If the response includes `reclaimed_from_other_sessions`, tell the user which objects were re-claimed from a previous session (include the session ID and timestamp) before proceeding with any deployment or migration work.

After a successful claim, call
`migration_status(mode="my_objects_summary")` again and follow the returned
group's `user_label` and `instructions`. For ETL, the machine may return
**Stabilize ETL package** or **Deploy** according to the project's persisted
`etl_flow`; do not assume either route and do not load an executor skill before
reading the machine result.

Return to [../SKILL.md](../SKILL.md).
