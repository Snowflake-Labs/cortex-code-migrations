# Action: Finish Objects

Merge completed objects into `main`.

## Step 1: Confirm selection

Call `migration_status(mode="my_objects_details", group="done")` to fetch the list of object IDs ready to merge. Confirm with the user (all or a subset).

## Step 2: Run

```
transition_status(status="finish", where="id IN ('<id1>', '<id2>')")
```

The handler creates a feature branch `migrate-<USER_ID>-<HASH>`, extracts each object's registered files (`files.source.path`, `files.converted.path`, `files.artifacts.path`, `registry/<id>.json`) from the user branch, ff-merges into `main`, and marks the objects done. Files outside the selection stay on the user branch.

After the merge succeeds, the handler automatically scans for objects that were blocked with `error="dependency"` and depend on any of the just-finished objects. Their error stamps are cleared so the next `migration_status` walk picks them up as ready. If the response includes `"woke_dependents": N` (N > 0), tell the user:

> Also unblocked **N** object(s) that were waiting on these dependencies. They'll appear in your next status check.

On error (e.g. merge conflict), surface to the user; do not retry.

Return to [../SKILL.md](../SKILL.md).
