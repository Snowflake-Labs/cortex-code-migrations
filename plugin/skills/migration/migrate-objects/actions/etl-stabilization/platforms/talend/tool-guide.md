# Talend Component Guide

How to read transformation logic out of a component node's `elementParameter`/`metadata`/`nodeData`.

Every component keeps its settings in its own element vocabulary, so there is no single generic
reader. Read the configuration verbatim rather than assuming a shape — the components below are
the ones observed in the AdW2017 reference corpus, plus `tMap`, which is the component every real
Talend job uses for its actual column logic.

## t*Input / t*Output (database sources and targets)

```xml
<node componentName="tMSSqlOutput" componentVersion="0.102">
  <elementParameter field="TEXT" name="HOST" value="context.DI_CNTL_Server"/>
  <elementParameter field="DBTABLE" name="TABLE" value="&quot;cntl_AssertCatcher&quot;"/>
  <elementParameter field="CLOSED_LIST" name="DATA_ACTION" value="INSERT"/>
  <metadata connector="FLOW" name="tMSSqlOutput_2">
    <column name="pid" type="id_String" sourceType="VARCHAR" length="20"/>
  </metadata>
</node>
```

- Connection parameters (`HOST`, `PORT`, `DBNAME`, `USER`, `PASS`) are dbt profile concerns, not
  model logic — do not carry them into the generated SQL.
- `TABLE` names the target/source table; XML-decode it (`&quot;` → `"`) before reading.
- For an input, a `QUERY` (or `MEMO_SQL`) `elementParameter` is the authority on which columns
  enter the flow — a downstream assertion about a column the query never selects is testing
  something the source does not produce, exactly as with Alteryx's `DbFileInput`/`Query`.
- For an output, `TABLE_ACTION` (`NONE`/`CREATE`/`DROP_CREATE`/`CREATE_IF_NOT_EXISTS`) and
  `DATA_ACTION` (`INSERT`/`UPDATE`/`UPSERT`/`DELETE`) decide full-refresh vs. incremental
  materialization — see the Materialization Decision Tree in
  `translation-references`/`project-conventions/materialization-strategy.md` for the mapping.
- `metadata/column` states the exact column name, type, length, and nullability. This is more
  reliable than reverse-engineering it from a query string.

## tMap

```xml
<node componentName="tMap">
  <nodeData xsi:type="TalendMapper:MapperData">
    <inputTables name="row1" sizeState="INTERMEDIATE">
      <mapperTableEntries name="pid" nullable="true" type="id_String"/>
    </inputTables>
    <outputTables name="outAssets" sizeState="INTERMEDIATE">
      <mapperTableEntries expression="row1.pid" name="pid" nullable="true" type="id_String"/>
      <mapperTableEntries expression="TalendDate.getCurrentDate()" name="load_dt" nullable="true" type="id_Date"/>
    </outputTables>
    <outputTables name="rejects" reject="true">
      <mapperTableEntries expression="row1.pid" name="pid" nullable="true" type="id_String"/>
    </outputTables>
  </nodeData>
</node>
```

`tMap` is the central transformation component, and its logic lives in `nodeData`, **not** in
`elementParameter` like every other component:

- `inputTables[@name]` names each inbound flow (`row1`, `row2`, ...). An `inputTables` carrying
  `@lookupMode` is a lookup input, not a primary input — it becomes a `LEFT JOIN`, and
  `@matchingMode="ALL_MATCHES"` means the join is many-to-many (no implicit dedup).
- `outputTables[@name]/mapperTableEntries` is the actual column mapping: `@expression` is the
  source expression, `@name` is the output column name. An empty `@expression` means straight
  passthrough of the same-named input column.
- `varTables/mapperTableEntries` are intermediate calculations, reusable across multiple output
  columns — inline them or lift them into their own CTE, but do not duplicate the expression
  per output column that references the same var.
- `outputTables[@reject="true"]` is the reject flow. It gets its own model
  (`<model>__rejected.sql`) or is dropped, per the unit's actual downstream wiring — a reject
  table with nothing connected past it carries no data-flow obligation.
- Translate `TalendDate.*`/`StringHandling.*`/`Numeric.*`/`Math.*`/`Relational.*` Java calls using
  the function table below. These are Talend's built-in routine namespaces, not arbitrary Java.

### Talend Java routine → Snowflake SQL

| Talend Java | Snowflake SQL |
|-------------|--------------|
| `StringHandling.UPCASE(x)` | `UPPER(x)` |
| `StringHandling.DOWNCASE(x)` | `LOWER(x)` |
| `StringHandling.TRIM(x)` | `TRIM(x)` |
| `StringHandling.LEFT(x, n)` / `.RIGHT(x, n)` | `LEFT(x, n)` / `RIGHT(x, n)` |
| `StringHandling.LEN(x)` | `LENGTH(x)` |
| `StringHandling.INDEX(x, s)` | `POSITION(s IN x)` |
| `StringHandling.SUBSTR(x, s, l)` | `SUBSTR(x, s, l)` |
| `StringHandling.REPLACE(x, o, n)` | `REPLACE(x, o, n)` |
| `StringHandling.IS_EMPTY(x)` | `(x IS NULL OR x = '')` |
| `TalendDate.getCurrentDate()` | `CURRENT_DATE()` |
| `TalendDate.parseDate(fmt, x)` | `TRY_TO_DATE(x, fmt)` |
| `TalendDate.formatDate(fmt, x)` | `TO_CHAR(x, fmt)` |
| `TalendDate.addDate(d, n, "dd")` | `DATEADD(DAY, n, d)` |
| `TalendDate.diffDate(d1, d2, "dd")` | `DATEDIFF(DAY, d2, d1)` |
| `TalendDate.getPartOfDate("YEAR", d)` | `YEAR(d)` |
| `Numeric.sequence("s", 1, 1)` | `ROW_NUMBER() OVER (ORDER BY 1)` |
| `Relational.ISNULL(x)` | `x IS NULL` |
| `Math.abs(x)` / `Math.round(x)` | `ABS(x)` / `ROUND(x)` |
| Java ternary `a == null ? b : a` | `COALESCE(a, b)` |
| Java string `+` | `||` |

The ternary and `+` rows carry the same silent-wrong-answer risk as Alteryx's Formula tool: a
missed `COALESCE` conversion produces a NULL comparison that fails silently rather than erroring,
and a missed `||` conversion, unlike Alteryx, does not even raise a type error in every dialect —
verify each translated expression against the source `@expression`, not against neighboring
generated SQL.

## tFilterRow

The filter condition is an `elementParameter` (field-operator-value triples, not a single
expression string like Alteryx's `Filter`). Read every condition row and confirm the combinator
(`AND`/`OR`) — misreading it on a filter with more than one condition row is a common source of a
stabilization mismatch.

## tAggregateRow

`elementParameter` lists group-by fields and aggregate operations (`sum`, `max`, `min`, `first`,
`last`, `count`, `avg`, `list`), the same shape as Alteryx's `Summarize`. The output schema is
**only** the group-by fields plus the declared aggregates — a downstream reference to any other
field is a source-level defect, not a conversion defect.

## tRunJob

`tRunJob` calls another Talend job. It is never converted to a model — see `workflow-guide.md`. Its
`elementParameter` names the called job (`PROCESS:PROCESS_TYPE_PROCESS`/`PROCESS:PROCESS_TYPE_VERSION`
or a `processName` value); the calling relationship becomes a dbt `ref()`/`depends_on` edge if a
real data dependency exists, or is dropped entirely if the two jobs share no table.

## Components with no SQL equivalent observed in the corpus

`tSendMail`, `tSetGlobalVar`, `tParallelize`, `tStatCatcher`, `tLogCatcher`, `tFlowMeterCatcher`,
and `tAssertCatcher` all appear in the AdW2017 corpus and have no dbt SQL equivalent. See
`element-types.md`'s "Components with no SQL equivalent" table for the full category list and
recommended remediation target for each — this guide does not repeat that table.
