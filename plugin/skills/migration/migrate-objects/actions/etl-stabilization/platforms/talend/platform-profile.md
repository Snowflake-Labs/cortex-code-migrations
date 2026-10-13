# Platform Profile: Talend

## Identity
- platform_id: talend
- platform_name: "Talend Open Studio / Talend Data Integration"
- source_file_extension: .item
- source_file_label: "Talend job (or joblet) definition"
- source_file_format: XML (EMF/XMI model)

## Source of Truth
- source_description: >
    A `.item` file is an EMF/XMI document describing one Talend job or joblet: a flat list of
    component instances under `<node componentName="...">`, the wiring between them under
    `<connection>` (data rows on `FLOW`, execution triggers on `SUBJOB_OK`/`ON_COMPONENT_OK`/
    `RUN_IF`, fan-out on `PARALLELIZE`), and grouping metadata under `<subjob>`. Each node's own
    settings live in its `<elementParameter field=... name=... value=.../>` children, and its
    column schema lives in `<metadata connector="FLOW"><column .../></metadata>`. `tMap` is the
    exception: its column-level logic lives in `<nodeData><outputTables><mapperTableEntries
    expression=... name=.../></outputTables></nodeData>`, not in `elementParameter`. Unlike a
    `.yxmd` canvas, a Talend job has a real orchestration layer — `subjob` triggers and
    `tRunJob` calls sequence execution independently of the data-row graph.
- assertion_derivation: >
    Derive test assertions from the component's own configuration in the `.item` XML — the
    `mapperTableEntries/@expression` in a `tMap`, the `WHERE`/filter condition text in a
    `tFilterRow`'s `elementParameter`, the `QUERY` value on a `tDBInput` — NOT from the converted
    Snowflake SQL. When a unit was converted through the AI-First path, the emitted SQL is a
    model-authored reading of the source and is exactly what is under test; treating it as the
    specification would validate the conversion against itself.
- traceability_format: "-- (Trace: Talend {source} → {logic} → {expected})"

## Guides
- orchestration_guide: workflow-guide.md
- transformation_guide: tool-guide.md
- element_types: element-types.md
- ewi_directory: ewi/

## Dead Code Stripping
- strip_script: null
- strip_description: null

## Element Classification
- disabled_marker: null
- disabled_reason: "not-verified-in-reference-corpus — no disabled component was present in the 34-item AdW2017 corpus this pack was built from; confirm the marker empirically against a real disabled node before relying on it, rather than assuming the value below"
- pipeline_type: null
- external_dep_types:
  - tFileList
  - tFileCopy
  - tFileDelete
  - tFileExist
  - tFileRename
  - tFileUnarchive
  - tHttpRequest
  - tREST
  - tSOAP
  - tWebService
  - tFileFetch
  - tSalesforceInput
  - tSalesforceOutput
  - tKafkaInput
  - tKafkaOutput
  - tJMSInput
  - tJMSOutput
  - tSendMail
  - tFTPGet
  - tFTPPut
  - tSFTP
  - tAmazonS3Input
  - tAmazonS3Output
  - tAzureBlobInput
  - tAzureBlobOutput
  - tGoogleStorageInput
  - tGoogleStorageOutput

## Source-Specific Vocabulary
- orchestration_term: "job"
- transformation_term: "component"
- unit_term: "Talend job"
- task_term: "subjob"
- container_term: "job"
- variable_binding: "context.VariableName"
- sql_source_attribute: "QUERY"
