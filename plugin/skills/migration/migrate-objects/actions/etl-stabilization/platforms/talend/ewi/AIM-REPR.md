# AIM-REPR — the element has no faithful representation

A `REPR` finding means the migrator could not place the element in its vocabulary. Either no member
described it, or it was degraded into a catch-all class that loses meaning.

Full codes carry a per-instance digest (`AIM-REPR-507534cad1e5`). This guide covers the family.

## Reasons

| Reason | Meaning |
|--------|---------|
| `no-vocabulary-member` | no representation kind describes this component |
| `degraded-to-catch-all-class` | represented, but as a generic class that drops its specifics |

`REPR` findings on `element:containment-scope`, `element:transformation`, and `element:role` are
all about *what the element is*, so start from the component kind in `node/@componentName`.

## Fixing

1. Identify the component kind and read `element-types.md` for its Snowflake equivalent.
2. If a straightforward equivalent exists — `tAggregateRow` is `GROUP BY`, `tUniqRow` is a
   `QUALIFY ROW_NUMBER()` — write the model directly from the component's configuration.
3. If none exists — anything in `element-types.md`'s "Components with no SQL equivalent" table —
   the finding is correct and residual. Record the gap and the recommended remediation target
   rather than approximating it with something that quietly computes a different result.

## Do not silently approximate

A degraded-to-catch-all element is reported precisely because the specifics were lost. Replacing it
with a plausible-looking passthrough clears the finding while leaving the data wrong, which is worse
than the honest report — the finding is the only signal that the meaning is missing.

This applies with extra force to the deliberately unsupported categories (file operations, API/HTTP,
messaging, cloud storage, email/FTP) — these are not gaps to be closed with generated SQL. The
correct fix is to record the recommended external tool from `element-types.md`, not to invent a
SQL body for a component that has none by design.

Where the source is genuinely ambiguous, say so in the stabilization notes and leave the element
flagged for review.
