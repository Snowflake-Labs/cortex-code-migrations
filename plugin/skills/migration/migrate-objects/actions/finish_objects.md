# Action: Finish Objects

Merge completed objects into `main`.

## Step 1: Confirm selection

Call `migration_status(mode="my_objects_details", group="done")` to fetch the list of object IDs ready to merge. Confirm with the user (all or a subset).

## Step 2: Run

```
transition_status(status="finish", where="id IN ('<id1>', '<id2>')")
```

The handler stamps each object done (`isDone`), then lands its registered files (`files.source.path`, `files.converted.path`, `files.artifacts.path`, `registry/<id>.json`) on top of `origin/main` using pure git plumbing — it builds the commit in a throwaway index and pushes the commit SHA directly, so your working tree never leaves your current branch (the response reports the new commit as `merge_commit`). It then rebases your branch onto the updated `origin/main`, pulling in any teammates' merged work. Files outside the selection stay on your branch.

After the merge succeeds, the handler automatically scans for objects that were blocked with `error="dependency"` and depend on any of the just-finished objects. Their error stamps are cleared so the next `migration_status` walk picks them up as ready. If the response includes `"woke_dependents": N` (N > 0), tell the user:

> Also unblocked **N** object(s) that were waiting on these dependencies. They'll appear in your next status check.

### Relaying git activity

The response includes a `git_activity` array of human-readable strings describing the git operations that ran. **Always relay these to the user** (as a brief summary or bullet list) so they understand what happened to their repo. Example:

> - Pushed commit abc1234f to origin/main with 3 files (registry/obj-1.json, snowflake/proc_1.sql, snowflake/proc_1_test.sql)
> - Rebased branch 'migrate-alice' onto origin/main
> - Unblocked 2 object(s) that depended on the finished objects

On error (e.g. merge conflict), attempt to resolve it:

1. Read each conflicted file and decide the correct resolution (accept incoming, keep current, or merge both sides).
2. Edit the files to remove conflict markers and produce correct content.
3. Stage the resolved files with `git add`.
4. Continue the operation (`git rebase --continue` or `git merge --continue`).
5. Retry the tool call.

If resolution is ambiguous (both sides made substantive, incompatible logic changes), surface the conflict to the user with the relevant file contents and ask which version to keep.

Return to [../SKILL.md](../SKILL.md).
