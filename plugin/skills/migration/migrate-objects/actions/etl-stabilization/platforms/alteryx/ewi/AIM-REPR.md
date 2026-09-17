# AIM-REPR — the element has no faithful representation

A `REPR` finding means the migrator could not place the element in its vocabulary. Either no member
described it, or it was degraded into a catch-all class that loses meaning.

Full codes carry a per-instance digest (`AIM-REPR-507534cad1e5`). This guide covers the family.

## Reasons

| Reason | Meaning |
|--------|---------|
| `no-vocabulary-member` | no representation kind describes this tool |
| `degraded-to-catch-all-class` | represented, but as a generic class that drops its specifics |

`REPR` findings on `element:containment-scope`, `element:transformation`, and `element:role` are all
about *what the element is*, so start from the tool kind in `GuiSettings/@Plugin`.

## Fixing

1. Identify the tool kind and read `element-types.md` for its Snowflake equivalent.
2. If a straightforward equivalent exists — `Summarize` is `GROUP BY`, `Unique` is a
   `QUALIFY ROW_NUMBER()` — write the model directly from the tool's configuration.
3. If none exists, the finding is correct and residual. Record the gap rather than approximating it
   with something that quietly computes a different result.

## Do not silently approximate

A degraded-to-catch-all element is reported precisely because the specifics were lost. Replacing it
with a plausible-looking passthrough clears the finding while leaving the data wrong, which is worse
than the honest report — the finding is the only signal that the meaning is missing.

Where the source is genuinely ambiguous, say so in the stabilization notes and leave the element
flagged for review.
