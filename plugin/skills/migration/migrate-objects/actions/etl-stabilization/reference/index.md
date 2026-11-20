## Reference Index

Quick-lookup index for all reference files. Load on-demand — only read a file when its content is needed for the current step.

### Protocols

Rules and conventions that govern skill behavior.

| File | Purpose |
|------|---------|
| [protocols/element-statuses.md](protocols/element-statuses.md) | Canonical element status list, valid transitions, and rules |
| [protocols/phase-execution.md](protocols/phase-execution.md) | Full phase execution protocol (orchestration, dbt, final validation, validation gate) |
| [orchestration-tags.md](orchestration-tags.md) | Canonical tag reference: container vs non-container patterns, replacement boundaries |

### Platforms

Platform-specific guides are organized under `platforms/{platform_id}/`. See [platforms/README.md](../platforms/README.md) for how to add a new platform.

| Platform | Profile | Orchestration Guide | Transformation Guide | Element Types | EWIs |
|----------|---------|--------------------|-----------------------|---------------|------|
| SSIS | [platform-profile.md](../platforms/ssis/platform-profile.md) | [control-flow-guide.md](../platforms/ssis/control-flow-guide.md) | [dataflow-guide.md](../platforms/ssis/dataflow-guide.md) | [element-types.md](../platforms/ssis/element-types.md) | [ewi/](../platforms/ssis/ewi/) |
| Informatica | [platform-profile.md](../platforms/informatica/platform-profile.md) | [workflow-guide.md](../platforms/informatica/workflow-guide.md) | [mapping-guide.md](../platforms/informatica/mapping-guide.md) | [element-types.md](../platforms/informatica/element-types.md) | [ewi/](../platforms/informatica/ewi/) |

### Shared EWI / FDM Fix Guides

Decision trees and fix patterns for SnowConvert conversion issues that are not platform-specific. Read the relevant guide before fixing an element with that code.

| File | Code | Description |
|------|------|-------------|
| [ewi/SSC-EWI-TS0077.md](ewi/SSC-EWI-TS0077.md) | SSC-EWI-TS0077 | T-SQL conversion issue |
| [ewi/SSC-FDM-0007.md](ewi/SSC-FDM-0007.md) | SSC-FDM-0007 | Functional difference marker |

T-SQL codes inside an Execute SQL task or a procedure (CLR, linked servers, collation, and others) have guides under [`rule-engine/resolving-ewis/reference/`](../../../rule-engine/resolving-ewis/reference/): for example [SSC-FDM-TS0080](../../../rule-engine/resolving-ewis/reference/SSC-FDM-TS0080.md) and [linked-servers.md](../../../rule-engine/resolving-ewis/reference/linked-servers.md).

### SSIS-Specific EWI / FDM Fix Guides

Located under `platforms/ssis/ewi/`. These guides are loaded when `platform_id` is `ssis`.

| File | Code | Description |
|------|------|-------------|
| [SSC-EWI-SSIS0001.md](../platforms/ssis/ewi/SSC-EWI-SSIS0001.md) | SSC-EWI-SSIS0001 | Data flow component not supported (includes third-party connectors) |
| [SSC-EWI-SSIS0002.md](../platforms/ssis/ewi/SSC-EWI-SSIS0002.md) | SSC-EWI-SSIS0002 | SSIS expression conversion issues |
| [SSC-EWI-SSIS0003.md](../platforms/ssis/ewi/SSC-EWI-SSIS0003.md) | SSC-EWI-SSIS0003 | Execute SQL Task conversion |
| [SSC-EWI-SSIS0004.md](../platforms/ssis/ewi/SSC-EWI-SSIS0004.md) | SSC-EWI-SSIS0004 | Script Task conversion |
| [SSC-EWI-SSIS0005.md](../platforms/ssis/ewi/SSC-EWI-SSIS0005.md) | SSC-EWI-SSIS0005 | Execute Package task became an async `EXECUTE TASK` |
| [SSC-EWI-SSIS0006.md](../platforms/ssis/ewi/SSC-EWI-SSIS0006.md) | SSC-EWI-SSIS0006 | Execute Package parameter bindings not passed to the child |
| [SSC-EWI-SSIS0007.md](../platforms/ssis/ewi/SSC-EWI-SSIS0007.md) | SSC-EWI-SSIS0007 | Property expressions on an executable not converted |
| [SSC-EWI-SSIS0008.md](../platforms/ssis/ewi/SSC-EWI-SSIS0008.md) | SSC-EWI-SSIS0008 | Execute Package task references an external package |
| [SSC-EWI-SSIS0009.md](../platforms/ssis/ewi/SSC-EWI-SSIS0009.md) | SSC-EWI-SSIS0009 | Unexpected exception converting a data flow component |
| [SSC-EWI-SSIS0010.md](../platforms/ssis/ewi/SSC-EWI-SSIS0010.md) | SSC-EWI-SSIS0010 | Second writer to a table that already has a model |
| [SSC-EWI-SSIS0011.md](../platforms/ssis/ewi/SSC-EWI-SSIS0011.md) | SSC-EWI-SSIS0011 | Result binding on a non-query statement (variable never set) |
| [SSC-EWI-SSIS0012.md](../platforms/ssis/ewi/SSC-EWI-SSIS0012.md) | SSC-EWI-SSIS0012 | Execute SQL XML result set not supported |
| [SSC-EWI-SSIS0013.md](../platforms/ssis/ewi/SSC-EWI-SSIS0013.md) | SSC-EWI-SSIS0013 | SqlStatementSource expression with unsupported patterns |
| [SSC-EWI-SSIS0014.md](../platforms/ssis/ewi/SSC-EWI-SSIS0014.md) | SSC-EWI-SSIS0014 | For Loop container conversion |
| [SSC-EWI-SSIS0015.md](../platforms/ssis/ewi/SSC-EWI-SSIS0015.md) | SSC-EWI-SSIS0015 | Send Mail file attachments not supported |
| [SSC-EWI-SSIS0016.md](../platforms/ssis/ewi/SSC-EWI-SSIS0016.md) | SSC-EWI-SSIS0016 | Send Mail priority (High/Low) ignored |
| [SSC-EWI-SSIS0017.md](../platforms/ssis/ewi/SSC-EWI-SSIS0017.md) | SSC-EWI-SSIS0017 | Send Mail body from a file connection not supported |
| [SSC-EWI-SSIS0018.md](../platforms/ssis/ewi/SSC-EWI-SSIS0018.md) | SSC-EWI-SSIS0018 | Send Mail HTML body sent as plain text |
| [SSC-EWI-SSIS0019.md](../platforms/ssis/ewi/SSC-EWI-SSIS0019.md) | SSC-EWI-SSIS0019 | Character Map operation other than upper/lowercase not translated |
| [SSC-EWI-SSIS0020.md](../platforms/ssis/ewi/SSC-EWI-SSIS0020.md) | SSC-EWI-SSIS0020 | Bulk Insert native/widenative data file not supported |
| [SSC-EWI-SSIS0021.md](../platforms/ssis/ewi/SSC-EWI-SSIS0021.md) | SSC-EWI-SSIS0021 | Bulk Insert LastRow not supported |
| [SSC-EWI-SSIS0022.md](../platforms/ssis/ewi/SSC-EWI-SSIS0022.md) | SSC-EWI-SSIS0022 | Bulk Insert FireTriggers not supported |
| [SSC-EWI-SSIS0023.md](../platforms/ssis/ewi/SSC-EWI-SSIS0023.md) | SSC-EWI-SSIS0023 | Bulk Insert format file |
| [SSC-EWI-SSIS0024.md](../platforms/ssis/ewi/SSC-EWI-SSIS0024.md) | SSC-EWI-SSIS0024 | Bulk Insert stage and file upload |
| [SSC-EWI-SSIS0025.md](../platforms/ssis/ewi/SSC-EWI-SSIS0025.md) | SSC-EWI-SSIS0025 | Flat File Source file name not resolved |
| [SSC-EWI-SSIS0026.md](../platforms/ssis/ewi/SSC-EWI-SSIS0026.md) | SSC-EWI-SSIS0026 | Property expression not supported (`Disable`, connection properties) |
| [SSC-EWI-SSIS0027.md](../platforms/ssis/ewi/SSC-EWI-SSIS0027.md) | SSC-EWI-SSIS0027 | Flat File Source connection manager not found |
| [SSC-EWI-SSIS0028.md](../platforms/ssis/ewi/SSC-EWI-SSIS0028.md) | SSC-EWI-SSIS0028 | Excel Source error-row redirection not translated |
| [SSC-EWI-SSIS0029.md](../platforms/ssis/ewi/SSC-EWI-SSIS0029.md) | SSC-EWI-SSIS0029 | Excel Source query parameters not translated |
| [SSC-EWI-SSIS0030.md](../platforms/ssis/ewi/SSC-EWI-SSIS0030.md) | SSC-EWI-SSIS0030 | Excel Source uses a project-level connection manager |
| [SSC-EWI-SSIS0031.md](../platforms/ssis/ewi/SSC-EWI-SSIS0031.md) | SSC-EWI-SSIS0031 | Excel stage file path variable needs mapping (older output) |
| [SSC-EWI-SSIS0032.md](../platforms/ssis/ewi/SSC-EWI-SSIS0032.md) | SSC-EWI-SSIS0032 | Excel Source sheet or query from a variable |
| [SSC-EWI-SSIS0033.md](../platforms/ssis/ewi/SSC-EWI-SSIS0033.md) | SSC-EWI-SSIS0033 | Excel Source SQL command not applied |
| [SSC-EWI-SSIS0034.md](../platforms/ssis/ewi/SSC-EWI-SSIS0034.md) | SSC-EWI-SSIS0034 | Flat file format (RaggedRight/Mixed) not supported |
| [SSC-EWI-SSIS0035.md](../platforms/ssis/ewi/SSC-EWI-SSIS0035.md) | SSC-EWI-SSIS0035 | Flat file header row delimiter is not a newline |
| [SSC-EWI-SSIS0036.md](../platforms/ssis/ewi/SSC-EWI-SSIS0036.md) | SSC-EWI-SSIS0036 | Flat File feature not supported (code page, locale, qualifiers, ...) |
| [SSC-EWI-SSIS0037.md](../platforms/ssis/ewi/SSC-EWI-SSIS0037.md) | SSC-EWI-SSIS0037 | SSIS expression function not reviewed (`TOKEN`, `TOKENCOUNT`, ...) |
| [SSC-EWI-SSIS0038.md](../platforms/ssis/ewi/SSC-EWI-SSIS0038.md) | SSC-EWI-SSIS0038 | Fuzzy Lookup scores only the first of several fuzzy columns |
| [SSC-EWI-SSIS0039.md](../platforms/ssis/ewi/SSC-EWI-SSIS0039.md) | SSC-EWI-SSIS0039 | Fuzzy Lookup exact join columns ignored (full CROSS JOIN) |
| [SSC-EWI-SSIS0041.md](../platforms/ssis/ewi/SSC-EWI-SSIS0041.md) | SSC-EWI-SSIS0041 | File System Task connection manager not found |
| [SSC-EWI-SSIS0043.md](../platforms/ssis/ewi/SSC-EWI-SSIS0043.md) | SSC-EWI-SSIS0043 | File System Task SetAttributes not supported |
| [SSC-EWI-SSIS0044.md](../platforms/ssis/ewi/SSC-EWI-SSIS0044.md) | SSC-EWI-SSIS0044 | COPY FILES destination is a directory prefix |
| [SSC-EWI-SSIS0045.md](../platforms/ssis/ewi/SSC-EWI-SSIS0045.md) | SSC-EWI-SSIS0045 | Character Map new-column mode not translated (older output) |
| [SSC-EWI-SSIS0046.md](../platforms/ssis/ewi/SSC-EWI-SSIS0046.md) | SSC-EWI-SSIS0046 | SSIS system variable not supported |
| [SSC-EWI-SSIS0047.md](../platforms/ssis/ewi/SSC-EWI-SSIS0047.md) | SSC-EWI-SSIS0047 | File System Task path needs manual stage mapping |
| [SSC-EWI-SSIS0048.md](../platforms/ssis/ewi/SSC-EWI-SSIS0048.md) | SSC-EWI-SSIS0048 | Fail-if-destination-exists not reproduced (COPY FILES overwrites) |
| [SSC-EWI-SSIS0049.md](../platforms/ssis/ewi/SSC-EWI-SSIS0049.md) | SSC-EWI-SSIS0049 | Data Flow error-output path |
| [SSC-EWI-SSIS0050.md](../platforms/ssis/ewi/SSC-EWI-SSIS0050.md) | SSC-EWI-SSIS0050 | Execute SQL `?` marker left without a parameter binding |
| [SSC-EWI-SSIS0051.md](../platforms/ssis/ewi/SSC-EWI-SSIS0051.md) | SSC-EWI-SSIS0051 | Fixed-width column layout incomplete (missing widths) |
| [SSC-EWI-SSIS0052.md](../platforms/ssis/ewi/SSC-EWI-SSIS0052.md) | SSC-EWI-SSIS0052 | Fuzzy Lookup reference columns missing (empty SELECT lists) |
| [SSC-FDM-SSIS0001.md](../platforms/ssis/ewi/SSC-FDM-SSIS0001.md) | SSC-FDM-SSIS0001 | SSIS variable conversion |
| [SSC-FDM-SSIS0002.md](../platforms/ssis/ewi/SSC-FDM-SSIS0002.md) | SSC-FDM-SSIS0002 | SSIS connection manager |
| [SSC-FDM-SSIS0003.md](../platforms/ssis/ewi/SSC-FDM-SSIS0003.md) | SSC-FDM-SSIS0003 | SSIS precedence constraint |
| [SSC-FDM-SSIS0004.md](../platforms/ssis/ewi/SSC-FDM-SSIS0004.md) | SSC-FDM-SSIS0004 | SSIS event handler |
| [SSC-FDM-SSIS0005.md](../platforms/ssis/ewi/SSC-FDM-SSIS0005.md) | SSC-FDM-SSIS0005 | SSIS package configuration |
| [SSC-FDM-SSIS0006.md](../platforms/ssis/ewi/SSC-FDM-SSIS0006.md) | SSC-FDM-SSIS0006 | SSIS logging provider |
| [SSC-FDM-SSIS0007.md](../platforms/ssis/ewi/SSC-FDM-SSIS0007.md) | SSC-FDM-SSIS0007 | Send Mail SMTP connection not applicable |
| [SSC-FDM-SSIS0008.md](../platforms/ssis/ewi/SSC-FDM-SSIS0008.md) | SSC-FDM-SSIS0008 | Send Mail From address added to the body |
| [SSC-FDM-SSIS0009.md](../platforms/ssis/ewi/SSC-FDM-SSIS0009.md) | SSC-FDM-SSIS0009 | Send Mail CC recipients merged into To |
| [SSC-FDM-SSIS0010.md](../platforms/ssis/ewi/SSC-FDM-SSIS0010.md) | SSC-FDM-SSIS0010 | Send Mail BCC recipients merged into To and visible |
| [SSC-FDM-SSIS0011.md](../platforms/ssis/ewi/SSC-FDM-SSIS0011.md) | SSC-FDM-SSIS0011 | Bulk Insert MaximumErrors semantics differ from `ON_ERROR` |
| [SSC-FDM-SSIS0012.md](../platforms/ssis/ewi/SSC-FDM-SSIS0012.md) | SSC-FDM-SSIS0012 | Bulk Insert BatchSize not available |
| [SSC-FDM-SSIS0013.md](../platforms/ssis/ewi/SSC-FDM-SSIS0013.md) | SSC-FDM-SSIS0013 | Bulk Insert KeepIdentity disabled |
| [SSC-FDM-SSIS0014.md](../platforms/ssis/ewi/SSC-FDM-SSIS0014.md) | SSC-FDM-SSIS0014 | Bulk Insert TableLock not needed |
| [SSC-FDM-SSIS0015.md](../platforms/ssis/ewi/SSC-FDM-SSIS0015.md) | SSC-FDM-SSIS0015 | Bulk Insert SortedData hint not available |
| [SSC-FDM-SSIS0016.md](../platforms/ssis/ewi/SSC-FDM-SSIS0016.md) | SSC-FDM-SSIS0016 | Bulk Insert CheckConstraints (`COPY` fails on `CHECK` tables) |
| [SSC-FDM-SSIS0017.md](../platforms/ssis/ewi/SSC-FDM-SSIS0017.md) | SSC-FDM-SSIS0017 | Bulk Insert field terminator missing, `','` assumed |
| [SSC-FDM-SSIS0018.md](../platforms/ssis/ewi/SSC-FDM-SSIS0018.md) | SSC-FDM-SSIS0018 | Bulk Insert row terminator missing, `'\r\n'` assumed |
| [SSC-FDM-SSIS0019.md](../platforms/ssis/ewi/SSC-FDM-SSIS0019.md) | SSC-FDM-SSIS0019 | Excel file must be staged (older output) |
| [SSC-FDM-SSIS0020.md](../platforms/ssis/ewi/SSC-FDM-SSIS0020.md) | SSC-FDM-SSIS0020 | Legacy .xls / .xlsb workbook |
| [SSC-FDM-SSIS0021.md](../platforms/ssis/ewi/SSC-FDM-SSIS0021.md) | SSC-FDM-SSIS0021 | Pivot PassThroughUnmatchedPivotKeys not reproduced |
| [SSC-FDM-SSIS0022.md](../platforms/ssis/ewi/SSC-FDM-SSIS0022.md) | SSC-FDM-SSIS0022 | Pivot assumes sorted input |
| [SSC-FDM-SSIS0023.md](../platforms/ssis/ewi/SSC-FDM-SSIS0023.md) | SSC-FDM-SSIS0023 | Circular variable reference replaced by the type's default |
| [SSC-FDM-SSIS0024.md](../platforms/ssis/ewi/SSC-FDM-SSIS0024.md) | SSC-FDM-SSIS0024 | Fuzzy Lookup uses JAROWINKLER_SIMILARITY; unmatched rows dropped |
| [SSC-FDM-SSIS0025.md](../platforms/ssis/ewi/SSC-FDM-SSIS0025.md) | SSC-FDM-SSIS0025 | Variable must hold a Snowflake stage path |
| [SSC-FDM-SSIS0026.md](../platforms/ssis/ewi/SSC-FDM-SSIS0026.md) | SSC-FDM-SSIS0026 | CreateDirectory writes a .dummy placeholder via COPY INTO |
| [SSC-FDM-SSIS0027.md](../platforms/ssis/ewi/SSC-FDM-SSIS0027.md) | SSC-FDM-SSIS0027 | Cache Transform duplicate-key check not enforced |
| [SSC-FDM-SSIS0028.md](../platforms/ssis/ewi/SSC-FDM-SSIS0028.md) | SSC-FDM-SSIS0028 | Stage paths are prefixes, not directories |
| [SSC-FDM-SSIS0029.md](../platforms/ssis/ewi/SSC-FDM-SSIS0029.md) | SSC-FDM-SSIS0029 | Disabled task commented out |
| [SSC-FDM-SSIS0030.md](../platforms/ssis/ewi/SSC-FDM-SSIS0030.md) | SSC-FDM-SSIS0030 | Sort EliminateDuplicates survivor row not determined |
| [SSC-FDM-SSIS0031.md](../platforms/ssis/ewi/SSC-FDM-SSIS0031.md) | SSC-FDM-SSIS0031 | Output column renamed for a name collision |
| [SSC-FDM-SSIS0032.md](../platforms/ssis/ewi/SSC-FDM-SSIS0032.md) | SSC-FDM-SSIS0032 | Full-replace destination converted to a Dynamic Table |
| [SSC-FDM-SSIS0033.md](../platforms/ssis/ewi/SSC-FDM-SSIS0033.md) | SSC-FDM-SSIS0033 | Emptying statement removed for a Dynamic Table |

### Informatica-Specific EWI / FDM Fix Guides

Located under `platforms/informatica/ewi/`. These guides are loaded when `platform_id` is `informatica`.

| File | Code | Description |
|------|------|-------------|
| [SSC-EWI-INF0001.md](../platforms/informatica/ewi/SSC-EWI-INF0001.md) | SSC-EWI-INF0001 | PowerCenter transformation not supported |
| [SSC-EWI-INF0003.md](../platforms/informatica/ewi/SSC-EWI-INF0003.md) | SSC-EWI-INF0003 | Workflow element cannot be converted |
| [SSC-EWI-INF0038.md](../platforms/informatica/ewi/SSC-EWI-INF0038.md) | SSC-EWI-INF0038 | Informatica conversion issue |
| [SSC-EWI-INF0039.md](../platforms/informatica/ewi/SSC-EWI-INF0039.md) | SSC-EWI-INF0039 | Informatica conversion issue |
| [SSC-EWI-INF0040.md](../platforms/informatica/ewi/SSC-EWI-INF0040.md) | SSC-EWI-INF0040 | Informatica conversion issue |
| [SSC-EWI-INF0050.md](../platforms/informatica/ewi/SSC-EWI-INF0050.md) | SSC-EWI-INF0050 | User-defined function call not converted |
| [SSC-FDM-INF0002.md](../platforms/informatica/ewi/SSC-FDM-INF0002.md) | SSC-FDM-INF0002 | Informatica functional difference |
| [SSC-FDM-INF0015.md](../platforms/informatica/ewi/SSC-FDM-INF0015.md) | SSC-FDM-INF0015 | Informatica functional difference |
| [SSC-FDM-INF0016.md](../platforms/informatica/ewi/SSC-FDM-INF0016.md) | SSC-FDM-INF0016 | Informatica functional difference |

### Agent Prompts

Templates loaded when spawning autonomous batch agents. Each prompt wires the agent to the appropriate sub-skill.

| File | Agent | Loaded by |
|------|-------|-----------|
| [agent-prompts/context-mapper.md](agent-prompts/context-mapper.md) | Context mapper (Planning Step 6) | Orchestrator |
| [agent-prompts/apply-fixes.md](agent-prompts/apply-fixes.md) | Mechanical tag replacement agent | Orchestrator (Execution) |

Note: Test generation and fixing agents (`orchestration-test-gen`, `orchestration-fixer`, `dbt-test-gen`, `dbt-fixer`) read their task mode specifications directly from their SKILL.md files (§ Task Mode section), not from reference prompts.

### Templates

Templates for generated artifacts.

| File | Purpose |
|------|---------|
| [templates/ROADMAP_TEMPLATE.md](templates/ROADMAP_TEMPLATE.md) | Template for agent-authored ROADMAP.md |
| [templates/batch-artifacts.md](templates/batch-artifacts.md) | Batch artifact and learning artifact format specs |
| [templates/baseline-artifacts.md](templates/baseline-artifacts.md) | Baseline report schema (baseline_batch_{B}.md format) |
| [templates/fix-log-format.md](templates/fix-log-format.md) | Cross-phase fix log format (fix-log.md structure) |
| [templates/report-template.html](templates/report-template.html) | HTML report template (CSS + shell for `generate_report.py`) |

### Other

| File | Purpose |
|------|---------|
| [tools.md](tools.md) | Consolidated script and MCP tool reference |
| [examples.md](examples.md) | Worked examples of common fix patterns |
| [troubleshooting.md](troubleshooting.md) | Common failure scenarios and resolutions |
