# Alteryx Tool Guide

How to read transformation logic out of a tool node's `<Properties><Configuration>`.

Every tool keeps its settings in its own element vocabulary, so there is no single generic reader.
The tools below are the ones the Order Enrichment workload exercises; read the configuration
verbatim rather than assuming a shape.

## DbFileInput / DbFileOutput

The source and target tools. Configuration carries a `File` element and, for database sources, a
`Query`. The `Query` is the authority on which columns enter the flow — a downstream assertion about
a column that the query never selects is testing something the source does not produce.

For an AI-First conversion these become the dbt sources and the materialized output models.

## Filter

```xml
<Configuration>
  <Expression>[Status] = "ACTIVE"</Expression>
</Configuration>
```

- The predicate is an Alteryx formula expression, not SQL. Field references are bracketed
  (`[Status]`), string literals use double quotes, and the operators are Alteryx's.
- The tool has **two** outputs, `True` and `False`. Which one is wired downstream determines the row
  set under test. A `False` branch is a real branch, not dead code.

## Formula

```xml
<Configuration>
  <FormulaFields>
    <FormulaField expression="..." field="NewField" size="..." type="..."/>
  </FormulaFields>
</Configuration>
```

Each `FormulaField` either creates a field or overwrites an existing one. `@field` is the output
name, `@expression` is the logic, `@type`/`@size` are the declared output type. A Formula that
overwrites an existing field changes that field's meaning from this point downstream.

## AlteryxSelect

Projection and rename, and it is where columns silently disappear.

```xml
<SelectFields>
  <SelectField field="OrderID" selected="True" rename="order_id"/>
  <SelectField field="Internal" selected="False"/>
</SelectFields>
```

- `@selected="False"` drops the field. A downstream reference to a dropped field is a source-level
  defect, not a conversion defect.
- `@rename` changes the field's name downstream; assertions must use the renamed form.
- A `*Unknown` entry governs fields not listed explicitly, so an absent field is not necessarily
  dropped — check for it before concluding a column was removed.

## Join

Configuration lists the join key pairs. The tool has three outputs:

| Anchor | Rows |
|--------|------|
| `Join` | matched rows from both inputs |
| `Left` | left rows with no match |
| `Right` | right rows with no match |

Only the wired anchors exist downstream. A conversion that renders a `Join` anchor as an inner join
is correct; one that renders it as a left join is not, and vice versa for the `Left` anchor.

Joined output carries fields from **both** inputs, and Alteryx prefixes duplicated names rather than
failing.

## Union

```xml
<Configuration>
  <Mode>ByName</Mode>
</Configuration>
```

- `ByName` matches fields across inputs by name; `ByPosition` matches by ordinal. The two produce
  different results whenever the inbound field orders differ.
- **Heterogeneous inputs are the recurring hazard.** If one inbound branch lacks a field the other
  has, `ByName` yields nulls for the missing side. A conversion that instead selects that column
  from the branch lacking it fails at execution, and the fix belongs in the union model — decide
  whether the field should be null-filled or whether the branch should supply it.

## Unique

Configuration lists the fields forming the uniqueness key. Two outputs: `Unique` (first occurrence
per key) and `Duplicate` (the rest). "First" is order-dependent, so an assertion about *which* row
survives needs a deterministic ordering to be meaningful.

## Summarize

```xml
<SummarizeFields>
  <SummarizeField field="Region" action="GroupBy"/>
  <SummarizeField field="Amount" action="Sum" rename="Total_Amount"/>
</SummarizeFields>
```

- `action="GroupBy"` fields become the `GROUP BY`; every other action is an aggregate.
- `@rename` sets the output column name. Alteryx also applies default names (`Sum_Amount`) when no
  rename is given, so check whether the converted name came from `@rename` or from the default.
- The output schema is **only** the group-by fields plus the aggregates. Any other field is gone,
  and a downstream reference to one is a source-level defect.
