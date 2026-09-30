#!/usr/bin/env python3
"""
SAS Migration Assessment Tool

Standalone CLI that analyzes SAS files and produces:
  - assessment.json (structured metrics per file + portfolio)
  - assessment_report.md (human-readable report)
  - assessment_report.html (self-contained, SCAI-themed HTML report)
  - dependency_dag.mmd (Mermaid diagram of cross-file dependencies)
  - egp_extracted/<project>/ (only for .egp inputs: one .sas per task,
    egp_manifest.json with the recovered process flow, egp_flow.mmd)

Usage:
  python assess_sas.py /path/to/sas/files --output ./assessment_output
  python assess_sas.py /path/to/single_file.sas --output ./results
  python assess_sas.py /path/to/sas/ --config custom_config.json
  python assess_sas.py /path/to/project.egp --output ./results
  python assess_sas.py /path/to/egps/ --output ./results --egp-extract-only
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Set

from sas_analyzer import SASParser, ComplexityScorer, TierClassifier, DependencyTracker, AssessmentReporter
from sas_analyzer.source_io import read_sas_source
from sas_analyzer import egp_extractor
import tables as tables_json

SAS_SUFFIX = '.sas'
EGP_SUFFIX = '.egp'
EGP_OUTPUT_DIR = 'egp_extracted'
# Files this tool writes; a directory holding one is a previous run's output, not source.
OUTPUT_MARKERS = ('assessment.json', egp_extractor.MANIFEST_NAME)


def _output_dirs(root: Path, output_dir: Optional[Path]) -> Set[Path]:
    dirs = {m.parent.resolve() for name in OUTPUT_MARKERS for m in root.rglob(name)}
    if output_dir is not None:
        dirs.add(output_dir.resolve())
    dirs.discard(root.resolve())
    return dirs


def find_source_files(source: str, output_dir: Optional[Path] = None):
    """Return ``(sas_files, egp_files)`` under ``source``, skipping this tool's output directories."""
    source_path = Path(source)
    if source_path.is_file() and source_path.suffix.lower() in (SAS_SUFFIX, EGP_SUFFIX):
        is_egp = source_path.suffix.lower() == EGP_SUFFIX
        return ([], [source_path]) if is_egp else ([source_path], [])
    if source_path.is_dir():
        skip = _output_dirs(source_path, output_dir)
        files = sorted(p for p in source_path.rglob('*')
                       if p.is_file() and not any(d in skip for d in p.resolve().parents))
        return ([p for p in files if p.suffix.lower() == SAS_SUFFIX],
                [p for p in files if p.suffix.lower() == EGP_SUFFIX])
    print(f"Error: '{source}' is not a .sas/.egp file or directory.", file=sys.stderr)
    sys.exit(1)


def find_sas_files(source: str) -> list:
    return find_source_files(source)[0]


def extract_egp_projects(egp_files, output_dir: Path):
    """Extract every ``.egp``; return ``(sas_paths, projects, sessions, edges, failures)``.
    ``sessions`` groups a project's files into one SAS session (shared WORK)."""
    sas_paths, projects, sessions, edges, failures = [], [], {}, [], []
    used_prefixes = set()
    for egp in egp_files:
        prefix = egp_extractor.safe_name(egp.stem)
        while prefix in used_prefixes:
            prefix += '_'
        used_prefixes.add(prefix)
        try:
            project, written = egp_extractor.extract_egp(egp, output_dir / EGP_OUTPUT_DIR / prefix, prefix)
        except egp_extractor.EgpError as exc:
            failures.append({'source': str(egp), 'error': str(exc)})
            print(f"  Warning: could not extract {egp}: {exc}", file=sys.stderr)
            continue
        s = egp_extractor.summary(project)
        print(f"  Extracted {egp.name}: {s['code_tasks']} code task(s), {s['no_code_tasks']} without code, "
              f"{s['flows']} flow(s), {s['orphaned_zip_code']} stale ZIP entr(ies) ignored")
        sas_paths.extend(written)
        projects.append(project)
        for path in written:
            sessions[path.name] = f'egp:{prefix}'
        file_of = {t.id: Path(t.sas_file).name for t in project.code_tasks() if t.sas_file}
        edges.extend((file_of[a], file_of[b]) for a, b in project.task_edges() if a in file_of and b in file_of)
    return sas_paths, projects, sessions, edges, failures


def egp_section(projects, failures, disagreements) -> dict:
    return {
        'projects': [egp_extractor.manifest(p) for p in projects],
        'failed': failures,
        'flow_vs_inferred': disagreements,
    }


def load_config(config_path: str = None) -> dict:
    default_config = {
        'complexity_thresholds': {
            'low_max': 50,
            'medium_max': 150,
        },
        'volume_thresholds': {
            'low_max': 250,
            'medium_max': 1000,
        },
    }
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            user_config = json.load(f)
        for key in default_config:
            if key in user_config:
                default_config[key].update(user_config[key])
    return default_config


def main():
    ap = argparse.ArgumentParser(description='SAS Migration Assessment Tool')
    ap.add_argument('source', help='Path to a .sas/.egp file or a directory containing them')
    ap.add_argument('--output', '-o', default='./assessment_output', help='Output directory for results')
    ap.add_argument('--config', '-c', help='Path to config.json with custom thresholds')
    ap.add_argument('--format', choices=['json', 'md', 'html', 'all'], default='all', help='Output format')
    ap.add_argument('--egp-extract-only', action='store_true',
                    help='Only extract .egp projects into <output>/egp_extracted; skip the assessment')
    args = ap.parse_args()

    config = load_config(args.config)
    output_dir = Path(args.output)

    sas_files, egp_files = find_source_files(args.source, output_dir)
    egp_projects, egp_sessions, egp_edges, egp_failures = [], {}, [], []
    if egp_files:
        print(f"Found {len(egp_files)} Enterprise Guide project(s); extracting...")
        extracted, egp_projects, egp_sessions, egp_edges, egp_failures = extract_egp_projects(egp_files, output_dir)
        sas_files = sas_files + extracted
        if args.egp_extract_only:
            print(f"  Extracted to: {output_dir / EGP_OUTPUT_DIR}")
            sys.exit(1 if egp_failures and not egp_projects else 0)
    if not sas_files:
        print("No .sas files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(sas_files)} SAS file(s) to analyze...")

    parser = SASParser()
    scorer = ComplexityScorer(config)
    classifier = TierClassifier()
    dep_tracker = DependencyTracker()
    reporter = AssessmentReporter(config)

    scripts = []
    scores = []
    classifications = []
    file_analyses = {}

    for sas_file in sas_files:
        try:
            content, normalised = read_sas_source(sas_file)
        except Exception as e:
            print(f"  Warning: Could not read {sas_file}: {e}", file=sys.stderr)
            continue

        script = parser.parse(content, filename=sas_file.name)
        script.line_endings_normalised = normalised
        score = scorer.score_script(script)
        classification = classifier.classify_file(script)
        deps = dep_tracker.analyze_file(script)

        scripts.append(script)
        scores.append(score)
        classifications.append(classification)
        file_analyses[script.filename] = deps

        parser = SASParser()

    if not scripts:
        print("Error: No files could be parsed.", file=sys.stderr)
        sys.exit(1)

    graph = dep_tracker.build_cross_file_graph(file_analyses, DependencyTracker.session_groups(sas_files, egp_sessions))
    flow_disagreements = DependencyTracker.merge_explicit_edges(graph, egp_edges, egp_sessions) if egp_files else None
    server_hints = {lib: DependencyTracker.SERVER_LIBREF_ENGINE for p in egp_projects for lib in p.server_librefs}
    graph['data_source_inventory'] = dep_tracker.build_source_inventory(file_analyses, server_hints)
    mermaid_str = dep_tracker.generate_mermaid_with_externals(graph, file_analyses)

    assessment = reporter.generate_assessment(scripts, scores, classifications, graph, file_analyses)
    if egp_files:
        assessment['egp_projects'] = egp_section(egp_projects, egp_failures, flow_disagreements)

    output_dir.mkdir(parents=True, exist_ok=True)

    if args.format in ('json', 'all'):
        json_path = output_dir / 'assessment.json'
        reporter.write_json(assessment, str(json_path))
        print(f"  Written: {json_path}")

        tables_path = output_dir / 'tables.json'
        tables_json.seed(tables_path, graph['external_inputs'], dep_tracker.build_output_tables(file_analyses))
        print(f"  Written: {tables_path}")

    if args.format in ('md', 'all'):
        md_path = output_dir / 'assessment_report.md'
        reporter.write_markdown(assessment, str(md_path))
        print(f"  Written: {md_path}")

    if args.format in ('html', 'all'):
        html_path = output_dir / 'assessment_report.html'
        reporter.write_html(assessment, mermaid_str, str(html_path))
        print(f"  Written: {html_path}")

    dag_path = output_dir / 'dependency_dag.mmd'
    reporter.write_mermaid_dag(mermaid_str, str(dag_path))
    print(f"  Written: {dag_path}")

    total = len(scripts)
    tier_dist = assessment['portfolio_summary']['tier_distribution']
    complexity_dist = assessment['portfolio_summary']['complexity_distribution']

    print(f"\n{'='*60}")
    print(f"  ASSESSMENT COMPLETE: {total} files analyzed")
    print(f"{'='*60}")
    print(f"  Tier 1 (SQL):          {tier_dist.get('TIER_1_SQL', 0):>4} ({tier_dist.get('TIER_1_SQL', 0)/total*100:.0f}%)")
    print(f"  Tier 2 (Stored Proc):  {tier_dist.get('TIER_2_SP', 0):>4} ({tier_dist.get('TIER_2_SP', 0)/total*100:.0f}%)")
    print(f"  Tier 3 (PySpark):      {tier_dist.get('TIER_3_PYSPARK', 0):>4} ({tier_dist.get('TIER_3_PYSPARK', 0)/total*100:.0f}%)")
    print(f"  ---")
    print(f"  Complexity LOW:        {complexity_dist.get('LOW', 0):>4} ({complexity_dist.get('LOW', 0)/total*100:.0f}%)")
    print(f"  Complexity MEDIUM:     {complexity_dist.get('MEDIUM', 0):>4} ({complexity_dist.get('MEDIUM', 0)/total*100:.0f}%)")
    print(f"  Complexity HIGH:       {complexity_dist.get('HIGH', 0):>4} ({complexity_dist.get('HIGH', 0)/total*100:.0f}%)")
    unrecognised = assessment['portfolio_summary'].get('unrecognised_procs') or {}
    if unrecognised:
        print(f"  Unrecognised PROCs (LOW confidence): {', '.join(f'{k} x{v}' for k, v in unrecognised.items())}")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
