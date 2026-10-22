# Talend Job Guide

How to read execution structure out of a `.item` document.

## A Talend job has a real orchestration layer

This is the difference that matters most when comparing Talend to Alteryx. A `.yxmd` canvas has
no orchestration at all — execution order is implied entirely by the data-row connection graph. A
Talend `.item` job has both: a data-row graph (`connectorName="FLOW"`) AND an independent trigger
graph (`connectorName="SUBJOB_OK"` / `ON_COMPONENT_OK"` / `"RUN_IF"` / `"PARALLELIZE"`) that
sequences components regardless of whether a row ever flows between them.

Two consequences for stabilization:

- A `tRunJob` node calling another job is a dependency edge, not a data-flow node. It never
  produces columns and is never converted to a model itself — see `tool-guide.md` and
  `element-types.md`.
- "Execution order" questions must be answered by walking the trigger graph (`subjob`/
  `SUBJOB_OK`/`RUN_IF`/`PARALLELIZE`), separately from the `FLOW` graph that decides column
  lineage. Reading only one of the two graphs under-states real execution structure.

## Shape

```xml
<model:JobletProcess defaultContext="Default" jobType="Standard">
  <context name="Default">
    <contextParameter name="DI_CNTL_Schema" type="id_String" value="dbo"/>
  </context>
  <node componentName="tMap" componentVersion="2.1" posX="352" posY="64">
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tMap_2"/>
    <metadata connector="FLOW" name="outAssets">
      <column name="pid" nullable="true" type="id_String"/>
    </metadata>
    <nodeData xsi:type="TalendMapper:MapperData">
      <outputTables name="outAssets">
        <mapperTableEntries expression="row1.pid" name="pid" nullable="true" type="id_String"/>
      </outputTables>
    </nodeData>
  </node>
  <connection connectorName="FLOW" source="tAssertCatcher_2" target="tMap_2"/>
  <connection connectorName="SUBJOB_OK" label="OnSubjobOk" source="tRunJob_1" target="tParallelize_1"/>
  <subjob>
    <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tAssertCatcher_2"/>
  </subjob>
</model:JobletProcess>
```

- **`node/@componentName`** names the component kind (`tMap`, `tMSSqlInput`, ...).
  `elementParameter[@name="UNIQUE_NAME"]/@value` (e.g. `tMap_2`) is the element identity — the
  trailing digits are what `ETL.Elements.FullName` states for the converted element.
- **`context/contextParameter`** are the job's variables (`context.VariableName` in every other
  component's config). A job's contexts (`Default`, `Dev`, `Prod`, `Test`, ...) are alternate
  value sets for the *same* parameter names, not different variables — read the context actually
  selected at run time, not just the first one in the document.
- **Node order in the document is authoring order, not execution order.** Do not infer sequence
  from it — walk the connection graph instead.

## Walking the two graphs

### The data-row graph (`FLOW`)

```xml
<connection connectorName="FLOW" label="row1" source="tAssertCatcher_2" target="tMap_2"/>
```

Each `FLOW` connection carries `@source`/`@target` (both element ids) and a `@label` naming the
output the row came from. A `tMap` with multiple `outputTables` (main + reject + additional
outputs) has one `FLOW` connection per output; only the wired ones exist downstream — the same
rule as an Alteryx `Filter`'s `True`/`False` anchors.

### The trigger graph (`SUBJOB_OK`, `ON_COMPONENT_OK`, `ON_COMPONENT_ERROR`, `RUN_IF`, `PARALLELIZE`)

```xml
<connection connectorName="SUBJOB_OK" label="OnSubjobOk" source="tRunJob_1" target="tParallelize_1"/>
<connection connectorName="PARALLELIZE" label="Parallelize" source="tParallelize_1" target="tRunJob_2"/>
```

| Connector | Meaning |
|-----------|---------|
| `SUBJOB_OK` | run the target only after the source subjob finished successfully |
| `ON_COMPONENT_OK` / `ON_COMPONENT_ERROR` | run the target after one specific component succeeded / failed |
| `RUN_IF` | run the target only if a boolean expression on the source is true |
| `PARALLELIZE` | fan out to every target concurrently (see `tParallelize` in `element-types.md`) |

A `tRunJob` chain sequenced entirely by `SUBJOB_OK`/`PARALLELIZE` (no `FLOW` between them) has no
data dependency to derive — it is pure execution order, and belongs in the dbt project's run order
or `depends_on` config, not in a model's `SELECT`.

## Subjobs

```xml
<subjob>
  <elementParameter field="TEXT" name="UNIQUE_NAME" show="false" value="tAssertCatcher_2"/>
  <elementParameter field="TEXT" name="SUBJOB_TITLE" value="AssetCatcher invoked on Error"/>
</subjob>
```

A `<subjob>` groups the components reachable from one starting node into a titled unit on the
canvas. It carries a label and color, not additional graph edges — the actual membership of a
subjob is derived by tracing `FLOW`/trigger connections from its `UNIQUE_NAME` node, not from the
`<subjob>` element itself.

## Contexts and variable binding

Every `elementParameter` value of the form `context.VariableName` (e.g. `context.DI_CNTL_Server`)
resolves against the job's active `<context name="...">` block. A job with `Dev`/`Test`/`Prod`
contexts is *not* four different jobs — verify which context a given run actually selected before
asserting on a resolved connection string or credential.

## No disabled-node marker verified

Alteryx and SSIS both carry an explicit disabled marker in their source documents. No disabled
component was present anywhere in the 34-item AdW2017 reference corpus this pack was built from,
so `platform-profile.md` states `disabled_marker: null` rather than guessing at one. If a disabled
Talend node is encountered, confirm its marker against the actual `.item` XML before writing
stabilization logic that depends on it.
