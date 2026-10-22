# SSC-EWI-0073 - Pending Functional Equivalence Review

SnowConvert marks nodes with this EWI when a source construct has no
direct 1:1 equivalent in Snowflake. It is not SQL-Server-specific — any
source dialect can produce it, including Redshift. Route to the correct
sub-skill based on the node type in the EWI marker.

**The marker does not mean the construct was translated.** On a Redshift
dbt project the converter tagged `listaggdistinct(...)` with this EWI and
left the call text unchanged, so the model failed at runtime with
`Unknown function LISTAGGDISTINCT`. Treat an unresolved 0073 as unconverted
until you have read the emitted expression.

## Routing

```
What node appears in the !!!RESOLVE EWI!!! marker?
│
├── ERROR_NUMBER / ERROR_MESSAGE / ERROR_SEVERITY
│   ERROR_STATE / ERROR_LINE / ERROR_PROCEDURE
│   → 0073-Error-Handling.md
│
├── STArea / STIntersection (chained with STArea)
│   STUnion (chained with STArea) / STIntersects
│   → 0073-Geospatial-Methods.md
│
└── A function that does not exist on Snowflake, where the
    source dialect is Redshift (e.g. listaggdistinct)
    → dbt dialect notes, see Sub-Skills below
```

## Sub-Skills

| Node Pattern | Sub-Skill | Scope |
|-------------|-----------|-------|
| `ERROR_*()` functions | [0073-Error-Handling.md](0073-Error-Handling.md) | TRY..CATCH → EXCEPTION, SQLCODE/SQLERRM/SQLSTATE |
| `STArea` + chained methods | [0073-Geospatial-Methods.md](0073-Geospatial-Methods.md) | STArea → ST_AREA_ELLIPSOIDAL UDF. UDF DDL: `UDF_Helpers/ST_AREA_ELLIPSOIDAL.sql` |
| Unknown function, Redshift source | [redshift.md](../../../../dbt/actions/fix-dbt-macros/reference/dialect-notes/redshift.md) | Redshift → Snowflake dialect patterns. `listaggdistinct` is a customer-defined Redshift UDF, not a Snowflake function; it maps to native `LISTAGG(DISTINCT …)`. Do not confuse it with the already-native `LISTAGG(DISTINCT …) WITHIN GROUP` form, which must be left alone. |

## Resources

- [SnowConvert SSC-EWI-0073](https://docs.snowconvert.com/sc/general/technical-documentation/issues-and-troubleshooting/conversion-issues/general/ssc-ewi-0073)
