#!/usr/bin/env python3
"""LINEAGE — surface the emitted project's cross-unit dependencies for the Code Unit Registry.

WHY THIS EXISTS. I-31 / `SNOW-3956440` Component 3: an AI-First-converted unit's registry entry
carries no `dependencies.dependsOn`, so the assessment reports built from the registry
(`ObjectReferences.*.csv`, missing-dependency analysis, ...) are silently incomplete for every unit
that took this path. `registry_loader.py::load_object_references_from_registry()` already
reconstructs those reports generically from any entry's `dependencies.dependsOn` array -- nothing
new is needed on that side once the array is populated. What's missing is the array itself.

WHY THIS IS A SEPARATE, READ-ONLY SCRIPT AND NOT A REGISTRY WRITE. Resolving a referenced table
name to the *other* unit's registry id is a name-matching problem this driver cannot do
deterministically: `emit_sources_yml.py` documents that the emitter never invents a database or
schema for a `source()` call (dbt resolves an undeclared source schema to the source's own name), so
a `source('raw', 'CUSTOMER')` call in the SQL is only ever a bare object name, not the bracketed
`[db].[schema].[name]` the registry's other entries carry. Matching that name to a registry id is
exactly the kind of ambiguous, sometimes-many-candidates lookup `query_registry` exists for and a
committed regex does not. So this script stops at the deterministic half -- which tables this
project's SQL actually reads, read off the bytes -- and leaves resolution + the `update_registry`
call to the agent driving the skill, the same division convert/etl-aifirst/SKILL.md Step 2 already
uses for the CUR-write decision itself.

WHAT IT DOES NOT REPORT: `ref()` calls. This emitter names models after the source document's own
node ids (`remediation_brief.py` notes models are named like `int_m_5`), so a `ref()` between two
models of the SAME emitted project is intra-unit structure, not a dependency on another registered
code unit -- reporting it as one would put a unit's own sub-models into its `dependsOn` array.

Usage:  lineage.py <out-root> [report-path]
Exit:   0 wrote (or found nothing to write, which is a valid, reported state -- a project with no
          `source()` calls truly has no external dependencies)
        1 no emitted dbt project under <out-root> -- UNMEASURED, not "zero dependencies"
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gate_b import GateBError, find_project, parse_model  # noqa: E402


def collect_sources(project_dir):
    """Walk the emitted project's models/ and return the union of `source()` calls.

    Returns a sorted list of ``[schema, table]`` pairs (the two arguments the SQL passed to
    `source(...)`, verbatim -- not resolved against any real database) plus, separately, the
    intra-project `ref()` names found, reported for visibility but not treated as dependencies.
    """
    models_dir = os.path.join(project_dir, "models")
    sources = set()
    refs = set()
    per_model = {}
    for base, _dirs, files in sorted(os.walk(models_dir)):
        for f in sorted(files):
            if not f.endswith(".sql"):
                continue
            path = os.path.join(base, f)
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            facts = parse_model(text)
            model = os.path.splitext(f)[0]
            rel = os.path.relpath(path, project_dir)
            per_model[model] = {"sql_file": rel, "refs": facts["refs"], "sources": facts["sources"]}
            refs.update(facts["refs"])
            for s in facts["sources"]:
                schema, table = s.split(".", 1)
                sources.add((schema, table))
    return sorted(sources), sorted(refs), per_model


def main(argv):
    if len(argv) not in (2, 3):
        print("usage: lineage.py <out-root> [report-path]", file=sys.stderr)
        return 1
    out_root = argv[1]
    report_path = argv[2] if len(argv) == 3 else os.path.join(
        out_root, "Reports", "AiFirstLineage", "lineage.json")

    try:
        project_dir, _others = find_project(out_root)
    except GateBError as exc:
        print("lineage        : UNMEASURED -- %s" % exc)
        return 1

    sources, intra_project_refs, per_model = collect_sources(project_dir)
    report = {
        "project": os.path.relpath(project_dir, out_root),
        "sources": [{"schema": s, "table": t} for s, t in sources],
        "intra_project_refs": intra_project_refs,
        "models": per_model,
    }
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")

    print("lineage        : %d external source(s) across %d model(s) -> %s" % (
        len(sources), len(per_model), report_path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
