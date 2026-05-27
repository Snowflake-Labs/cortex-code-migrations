# Action: Claim Objects

Add new objects to the working set.

> **Claim small batches.** Migrations are collaborative: an object claimed by one user is hidden from every other user's picker (`migration_status(next_objects)` excludes anyone's active claims). Claiming a large batch starves teammates of work and locks objects you may not get to for hours. Default to **at most 5 objects per claim**, and re-enter this skill to claim more after finishing some. Only exceed 5 when the user *explicitly* asks for a larger batch (e.g. "claim 20", "grab the whole wave"). A casual "go ahead" or "yes" is **not** an explicit request — claim 5.
>
> **Never substitute a category filter for picker IDs.** Do not claim with `where="source.objectType = 'table'"` or any other broad predicate as a shortcut. The `where` clause must be `id IN (...)` listing IDs the user picked from the picker output.

## Step 1: Discover

```
migration_status(mode="next_objects")
```

**Call the tool with no `limit` argument.** The tool returns 5 by default — that is the right number for the picker render.

> **`limit` rule.** Pass `limit` **only** when the user typed an explicit numeric request in this turn — e.g. "show me 20", "list 15 ready objects", "claim the whole wave (~30)". A casual "go ahead", "yes", "more", "show some more", or "next" is **not** an explicit request. If the user wants more without a number, ask "how many?" before calling the tool.

Show `objects` (available) to the user. If `total_available` exceeds the number of returned `objects`, also tell the user how many ready objects exist and that they can re-run with a numeric `limit` (e.g. "show me 20") to view more. User picks one or more object IDs from `objects`.

If the user gives an ambiguous "go ahead" without naming objects or a count, default to claiming **the first 5** (or fewer, if `objects` has fewer) and tell them so — do not claim everything returned, do not call `next_objects` with a higher `limit`.

## Step 2: Claim

```
transition_status(status="begin", where="id IN ('<id1>', '<id2>')")
```

The `where` clause must be `id IN (...)` with the specific IDs from Step 1 — never a category predicate.

Surface any error and stop without retry.

Return to [../SKILL.md](../SKILL.md).
