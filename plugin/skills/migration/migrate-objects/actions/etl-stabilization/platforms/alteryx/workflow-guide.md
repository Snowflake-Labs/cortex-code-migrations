# Alteryx Workflow Guide

How to read execution structure out of a `.yxmd` document.

## The document has no orchestration layer

This is the difference that matters most when comparing Alteryx to SSIS or Informatica. A `.dtsx`
package has a control flow that sequences tasks; an Informatica workflow sequences sessions. A
`.yxmd` has neither. It is one data-flow canvas, and execution order is implied entirely by the
connection graph.

Two consequences for stabilization:

- There is no orchestration `.sql` in the converted unit to parse for elements. A unit converted
  from a `.yxmd` is a dbt project plus the assessment that names its elements. The scanner derives
  the element list from `ETL.Elements.*.csv` for exactly this reason.
- "Execution order" questions are answered by walking `<Connections>`, not by reading a sequence.

## Shape

```xml
<AlteryxDocument yxmdVer="2024.1">
  <Nodes>
    <Node ToolID="3">
      <GuiSettings Plugin="AlteryxBasePluginsGui.Union.Union"/>
      <Properties><Configuration>...</Configuration></Properties>
    </Node>
  </Nodes>
  <Connections>
    <Connection>
      <Origin ToolID="1" Connection="Output"/>
      <Destination ToolID="3" Connection="Input"/>
    </Connection>
  </Connections>
  <Properties/>
</AlteryxDocument>
```

- **`Node/@ToolID`** is the element identity. It is a bare number (`3`), and it is what
  `ETL.Elements.FullName` states for the converted element.
- **`GuiSettings/@Plugin`** names the tool kind. It is a dotted assembly path
  (`AlteryxBasePluginsGui.Union.Union`); the last segment is the tool name.
- **`<Nodes>` order is canvas order, not execution order.** Do not infer sequence from it.

## Walking the graph

Build predecessors and successors from `<Connections>`. Each `Connection` has an `Origin` and a
`Destination`, both carrying a `ToolID` and an anchor name.

Anchor names carry real semantics and must not be flattened:

| Anchor | On | Meaning |
|--------|-----|---------|
| `Output` | most tools | the single result stream |
| `True` / `False` | Filter | the rows that passed / failed the predicate |
| `Left` / `Right` | Join | the two join inputs |
| `Join` / `Left` / `Right` | Join outputs | matched rows / left-only / right-only |
| `Input` | most tools | the single input stream |

A Filter feeding a Join from its `True` anchor means only passing rows reach the join. A brief item
about a Join whose upstream is a Filter has to be read with the anchor in hand, or the row set under
test is wrong.

## Fan-in and fan-out

A tool may have several inbound connections on the same anchor. A Union with two `Input`
connections is the common case and is where heterogeneous-schema defects appear: if the two inbound
branches do not carry the same field set, the union has to reconcile them, and a column selected
from a branch that lacks it is a genuine source-level ambiguity rather than a conversion bug.

Always check whether the inbound branches of a Union agree on their field lists before accepting an
assertion about its output columns.

## Disabled tools

A node carrying `Disabled="True"` in its configuration does not run. Classify it as
`disabled-in-source` and do not write assertions against it.
