# Alteryx Element Types

Tool kinds and their Snowflake/dbt equivalents. The tool kind comes from the last segment of
`GuiSettings/@Plugin`.

| Tool | Snowflake / dbt equivalent | Notes |
|------|---------------------------|-------|
| `DbFileInput` | dbt source, or a staging model selecting from it | The tool's `Query` decides the column set |
| `DbFileOutput` | materialized model (table) | The unit's terminal outputs |
| `Filter` | `WHERE` predicate | Two branches; only wired anchors exist downstream |
| `Formula` | projected expressions in a `SELECT` | May overwrite an existing field |
| `AlteryxSelect` | explicit column list, with `AS` for renames | Unselected fields are dropped |
| `Join` | `JOIN` | Anchor decides inner vs left/right-only |
| `Union` | `UNION ALL` | `ByName` vs `ByPosition` changes the result |
| `Unique` | `QUALIFY ROW_NUMBER() OVER (PARTITION BY key)` | Needs a deterministic order to be reproducible |
| `Summarize` | `GROUP BY` with aggregates | Output is group-by fields plus aggregates only |
| `Sort` | `ORDER BY` | Ordering alone is not durable in a table materialization |
| `Sample` | `LIMIT`, or a windowed filter | Row choice is order-dependent |
| `RunCommand` | no equivalent | External process; classify as an external dependency |

## Elements with no equivalent

`RunCommand`, `Email`, and the R/Python tools invoke something outside the warehouse. They cannot be
expressed as a dbt model and should be classified as external dependencies rather than treated as
convertible transformations.

## Reading a converted element

For a unit converted through the AI-First path:

- `ETL.Elements.FullName` is the bare `ToolID` (`3`), and `Category` is `source`, `transformation`,
  or `target`.
- `ETL.Issues.ComponentFullName` states the same element as `m_3`. The two reports spell one fact
  two ways; when correlating them, normalize to the bare id.
- The remediation brief states elements as bare ids in `element_ids` and the generated files in
  `models`, so it joins directly against `ETL.Elements`.
