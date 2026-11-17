# joins_critic — structural enrichment critic

Scope: `fk_chains`, `correlated_groups`, `temporal_alignment`, `anti_join_tables` (workload-level;
FK chains span objects). The backbone already confirmed existence, non-self-join, range, and structural
backing. Judge only the semantic residue below, then emit your verdict per **verdict-contract.md**.

## Per-type residue

### fk_chains — is this the semantically correct parent, pointed the right way?
The backbone confirmed the child cell has a mined `fk`/`join_edge` (see `anchors.mined_edges`). When
`anchors.parent_key_columns` is present, it also matched the child and the proposed parent to a
`join_edge`'s two sides, so judge direction from the keys (`anchors.parent_key_columns`,
`anchors.child_key_columns`) and the source. A `join_edge` orders its sides by table name, not by
direction, so never judge direction from the side order. Without the key anchors, compare the proposed
`parent_table` to the parent the mined edge names.
- Mined edge names a **different** parent than proposed → **REJECT**, mode `a`, citation
  `fk_parent_mismatch` (`{child_table, child_col, proposed_parent_table}`). Example: `REP_ID` joins
  `SALES_REP` in the source but the chain proposes `REGION`.
- The source shows the proposed parent holding many rows per value, or the direction is otherwise
  implausible given the keys (child→parent points at a non-key) → **REVISE**, mode `b`, naming the side
  that is the child. Answer an `anchors.question` the same way. Never contest direction with
  `fk_parent_mismatch`: both tables are on the edge, so the harness drops that REJECT.
- Proposed parent is the edge's other side and the direction holds → **ACCEPT**.

### correlated_groups — real correlation or coincidence?
The backbone confirmed the group maps to a `branch_predicate` gap. Ask whether the source jointly implies
the tuple (the columns co-vary in the same predicate/branch), or the pairing is coincidental.
- No joint support in the source → **REVISE**, mode `b`.
- Jointly implied → **ACCEPT**.

### temporal_alignment — does the source imply `column_deb <= column_fin`?
There is no span to hard-gate against.
- No ordering/predicate in the source that implies the inequality → **REVISE**, mode `b`.
- Source implies the ordering → **ACCEPT**.

### anti_join_tables — is there a real anti-join in the source?
Look for `NOT EXISTS` / `LEFT JOIN ... IS NULL` semantics on the cited fk_column.
- No real anti-join present → **REVISE**, mode `b`.
- Present → **ACCEPT**.
