# Platform Profile: Alteryx

## Identity
- platform_id: alteryx
- platform_name: "Alteryx Designer"
- source_file_extension: .yxmd
- source_file_label: "Alteryx workflow"
- source_file_format: XML

## Source of Truth
- source_description: >
    The .yxmd workflow is a single XML document describing one data-flow
    canvas: a flat list of tool nodes under <Nodes>, the anchor-to-anchor
    wiring between them under <Connections>, and per-tool configuration
    inside each node's <Properties><Configuration> element. Unlike SSIS or
    Informatica there is no separate orchestration layer -- no package
    control flow, no workflow or session wrapper. Execution order is implied
    entirely by the connection graph.
- assertion_derivation: >
    Derive test assertions from the tool configuration in the .yxmd document
    -- the Filter expression, the Formula field definitions, the Summarize
    group-by and aggregate actions, the Join anchors -- NOT from the
    converted Snowflake SQL. When a unit was converted through the AI-First
    path, the emitted SQL is a model-authored reading of the source and is
    exactly what is under test; treating it as the specification would
    validate the conversion against itself.
- traceability_format: "-- (Trace: Alteryx {source} → {logic} → {expected})"

## Guides
- orchestration_guide: workflow-guide.md
- transformation_guide: tool-guide.md
- element_types: element-types.md
- ewi_directory: ewi/

## Dead Code Stripping
- strip_script: null
- strip_description: null

## Element Classification
- disabled_marker: 'Disabled="True"'
- disabled_reason: "disabled-in-source"
- pipeline_type: null
- external_dep_types:
  - RunCommand
  - Email
  - DbFileInput
  - DbFileOutput

## Source-Specific Vocabulary
- orchestration_term: "workflow"
- transformation_term: "tool"
- unit_term: "Alteryx workflow"
- task_term: "tool"
- container_term: "container"
- variable_binding: "%Question.name%"
- sql_source_attribute: "Query"
