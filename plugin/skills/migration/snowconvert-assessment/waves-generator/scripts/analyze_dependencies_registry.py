#!/usr/bin/env python3
"""Registry-native dependency graph analysis and wave generation."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from analyze_dependencies import (
    DependencyGraph,
    analyze_dependencies,
    analyze_excluded_edges,
    analyze_graph_structure,
    create_deployment_partitions,
    load_etl_elements,
    merge_small_partitions,
    write_results,
)
from find_dependencies_by_object_registry import (
    generate_missing_dependencies_report_from_registry,
)
from registry_support import (
    build_id_to_entry_map,
    build_id_to_object_name_map,
    build_missing_objects,
    build_registry_object_id,
    entry_to_object_info,
    is_deployable_entry,
    load_registry_entries,
    missing_dependency_name,
)


def _discover_etl_packages(reports_dir: str | None) -> Dict[str, Dict[str, str]]:
    """Load ETL package metadata from reports dir when available."""
    if not reports_dir:
        return {}

    reports_path = Path(reports_dir)
    if not reports_path.exists():
        return {}

    candidate = reports_path / "ETL.Elements.NA.csv"
    if candidate.exists():
        return load_etl_elements(str(candidate))

    matches = list(reports_path.glob("ETL.Elements.*.csv"))
    if matches:
        return load_etl_elements(str(matches[0]))
    return {}


def build_dependency_graph_from_registry(
    registry_dir: str | Path,
    reports_dir: str | None = None,
) -> Tuple[DependencyGraph[str], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Build a dependency graph from registry JSON files."""
    graph: DependencyGraph[str] = DependencyGraph()
    entries = load_registry_entries(registry_dir)
    id_to_entry = build_id_to_entry_map(entries)
    id_to_name = build_id_to_object_name_map(entries)

    deployable_entries = [entry for entry in entries if is_deployable_entry(entry)]
    valid_object_names = {
        build_registry_object_id(entry)
        for entry in deployable_entries
    }

    for entry in deployable_entries:
        object_name = build_registry_object_id(entry)
        graph.add_object_info(object_name, entry_to_object_info(entry))
        graph.all_nodes.add(object_name)

    etl_packages = _discover_etl_packages(reports_dir)
    for package_name, package_info in etl_packages.items():
        if package_name in graph.all_nodes:
            continue
        graph.add_object_info(
            package_name,
            {
                "category": "ETL",
                "code_unit": "ETL PACKAGE",
                "file_name": f"{package_name}.dtsx",
                "line_number": "N/A",
                "conversion_status": package_info.get("status", "Unknown"),
                "technology": package_info.get("technology", "ETL"),
                "subtype": package_info.get("subtype", "Package"),
            },
        )
        graph.all_nodes.add(package_name)

    missing_objects = build_missing_objects(entries)
    excluded_edges: List[Dict[str, Any]] = []
    missing_counter = 0

    for entry in deployable_entries:
        caller = build_registry_object_id(entry)

        for dep in entry.get("dependencies", {}).get("dependsOn", []):
            relation_types = dep.get("relationTypes", []) or [""]
            dep_id = (dep.get("id") or "").strip()
            referenced = id_to_name.get(dep_id, "")
            referenced_entry = id_to_entry.get(dep_id)
            referenced_defined = bool(referenced) and (
                referenced in valid_object_names
            )

            if dep.get("isMissing", False) and not referenced:
                missing_counter += 1
                referenced = missing_dependency_name(dep, missing_counter)

            if not referenced and dep_id:
                referenced = dep_id

            for relation_type in relation_types:
                if relation_type == "FOREIGN KEY":
                    excluded_edges.append(
                        {
                            "caller": caller,
                            "caller_defined": True,
                            "referenced": referenced,
                            "referenced_defined": referenced_defined,
                            "relation_type": relation_type,
                            "line": "0",
                            "exclusion_reason": "FOREIGN KEY",
                        }
                    )
                    continue

                if dep.get("isMissing", False):
                    excluded_edges.append(
                        {
                            "caller": caller,
                            "caller_defined": True,
                            "referenced": referenced,
                            "referenced_defined": False,
                            "relation_type": relation_type,
                            "line": "0",
                            "exclusion_reason": "Referenced Undefined",
                        }
                    )
                    continue

                # Non-deployable registry targets stay excluded to match CSV behavior.
                if referenced_defined:
                    graph.add_edge(caller, referenced)
                    continue

                excluded_reason = "Referenced Undefined"
                if referenced_entry and not is_deployable_entry(referenced_entry):
                    excluded_reason = "Referenced Excluded"

                excluded_edges.append(
                    {
                        "caller": caller,
                        "caller_defined": True,
                        "referenced": referenced or dep_id or "UNKNOWN_REFERENCE",
                        "referenced_defined": False,
                        "relation_type": relation_type,
                        "line": "0",
                        "exclusion_reason": excluded_reason,
                    }
                )

    return graph, excluded_edges, missing_objects


def generate_wave_deployment_order(output_folder: Path) -> None:
    """Generate ``wave_deployment_order.json`` from partition membership."""
    partition_membership_path = output_folder / "partition_membership.csv"
    deployment_order_path = output_folder / "wave_deployment_order.json"

    if not partition_membership_path.exists():
        print("Warning: partition_membership.csv not found")
        return

    wave_deployment_order: Dict[str, Dict[str, Any]] = {}
    with partition_membership_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            wave_num = row["partition_number"]
            if wave_num not in wave_deployment_order:
                wave_deployment_order[wave_num] = {
                    "wave_number": wave_num,
                    "deployment_order": [],
                    "objects_detail": [],
                }

            object_name = row["object"]
            wave_deployment_order[wave_num]["deployment_order"].append(object_name)
            wave_deployment_order[wave_num]["objects_detail"].append(
                {
                    "name": object_name,
                    "category": row["category"],
                    "is_root": row["is_root"].lower() == "true",
                    "is_leaf": row["is_leaf"].lower() == "true",
                    "deployment_position": len(
                        wave_deployment_order[wave_num]["deployment_order"]
                    ),
                }
            )

    for wave_data in wave_deployment_order.values():
        wave_data["total_objects"] = len(wave_data["deployment_order"])

    output_data = {
        "metadata": {
            "description": (
                "Wave deployment order from partition_membership "
                "(already topologically sorted)"
            ),
            "total_waves": len(wave_deployment_order),
            "total_objects": sum(
                len(wave["deployment_order"])
                for wave in wave_deployment_order.values()
            ),
            "ordering_algorithm": (
                "Kahn's algorithm (topological sort) - applied in "
                "analyze_dependencies_registry.py"
            ),
            "ordering_rule": "Dependencies before dependents within each wave",
        },
        "waves": wave_deployment_order,
    }

    with deployment_order_path.open("w", encoding="utf-8") as handle:
        json.dump(output_data, handle, indent=2)

    print(f"Wave deployment order generated: {deployment_order_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze SQL object dependencies from registry and create deployment partitions",
    )
    parser.add_argument(
        "--registry-dir",
        required=True,
        help="Path to registry directory containing JSON entries",
    )
    parser.add_argument(
        "--reports-dir",
        help="Optional SnowConvert reports directory for ETL.Elements CSV supplement",
    )
    parser.add_argument(
        "--output",
        "-d",
        required=True,
        help="Output directory for analysis results",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=40,
        help="Minimum partition size (default: 40)",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=80,
        help="Maximum partition size (default: 80)",
    )
    parser.add_argument(
        "--prioritize",
        action="append",
        help="Object name or pattern to prioritize for earlier placement",
    )
    parser.add_argument(
        "--prioritize-file",
        help="Path to a file containing object names or patterns to prioritize",
    )
    parser.add_argument(
        "--no-category-waves",
        action="store_true",
        help="Disable category-based wave ordering (TABLE→VIEW→FUNCTION first)",
    )
    args = parser.parse_args()

    prioritize_patterns: List[str] = []
    if args.prioritize:
        prioritize_patterns.extend(args.prioritize)

    if args.prioritize_file:
        with open(args.prioritize_file, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#"):
                    prioritize_patterns.append(line)

    print("Configuration:")
    print(f"  Registry directory: {args.registry_dir}")
    print(f"  Reports directory: {args.reports_dir or 'N/A'}")
    print(f"  Output directory: {args.output}")
    print(f"  Partition size range: {args.min_size}-{args.max_size}")
    if prioritize_patterns:
        print(f"  Prioritization patterns: {len(prioritize_patterns)}")
        for pattern in prioritize_patterns:
            print(f"    - {pattern}")
    print()

    print("Building dependency graph from registry...")
    graph, excluded_edges, missing_objects = build_dependency_graph_from_registry(
        args.registry_dir,
        args.reports_dir,
    )
    print(
        f"Graph loaded: {len(graph.all_nodes)} nodes, "
        f"{sum(len(deps) for deps in graph.graph.values())} edges"
    )
    print(f"Excluded edges: {len(excluded_edges)}")

    print("\nAnalyzing excluded edges...")
    excluded_analysis = analyze_excluded_edges(excluded_edges)

    print("\nAnalyzing dependencies...")
    dependency_results = analyze_dependencies(graph)

    print("\nAnalyzing graph structure...")
    graph_structure = analyze_graph_structure(graph)

    print("\nCreating deployment partitions...")
    partitions, partition_dependency_matrix, scc_priority_list = (
        create_deployment_partitions(
            graph,
            min_size=args.min_size,
            max_size=args.max_size,
            prioritize_patterns=prioritize_patterns,
            category_waves=not args.no_category_waves,
        )
    )

    print(f"Initial partitions created: {len(partitions)}")

    print("\nMerging small partitions...")
    partitions = merge_small_partitions(
        partitions,
        graph,
        min_size=args.min_size,
        max_size=args.max_size,
    )
    print(f"After merging: {len(partitions)} partitions")

    # Re-analyze partitions after merging to match CSV output contract.
    print("\nRe-analyzing merged partitions...")
    for partition in partitions:
        nodes = partition.nodes
        root_nodes = set()
        leaf_nodes = set()

        for node in nodes:
            all_deps = graph.get_direct_dependencies(node)
            all_dependents = graph.get_direct_dependents(node)
            if len(all_deps) == 0:
                root_nodes.add(node)
            if len(all_dependents) == 0:
                leaf_nodes.add(node)

        partition.root_nodes = root_nodes
        partition.leaf_nodes = leaf_nodes

        internal_deps = 0
        external_deps = 0
        deps_by_partition = defaultdict(int)

        for node in nodes:
            deps = graph.get_direct_dependencies(node)
            for dep in deps:
                if dep in nodes:
                    internal_deps += 1
                    continue
                external_deps += 1
                for candidate in partitions:
                    if dep in candidate.nodes:
                        deps_by_partition[candidate.partition_number] += 1
                        break

        partition.internal_dependencies = internal_deps
        partition.external_dependencies = external_deps
        partition.dependencies_by_partition = dict(deps_by_partition)

        node_types = defaultdict(int)
        for node in nodes:
            category = graph.object_info.get(node, {}).get("category", "Unknown")
            node_types[category] += 1
        partition.node_types = dict(node_types)

    partition_dependency_matrix = {}
    for i, partition_i in enumerate(partitions):
        for j, partition_j in enumerate(partitions):
            if i <= j:
                continue
            edge_count = 0
            for node_i in partition_i.nodes:
                deps = graph.get_direct_dependencies(node_i)
                for dep in deps:
                    if dep in partition_j.nodes:
                        edge_count += 1
            if edge_count > 0:
                key = (partition_i.partition_number, partition_j.partition_number)
                partition_dependency_matrix[key] = edge_count

    print("\nWriting results...")
    output_folder = write_results(
        dependency_results,
        graph_structure,
        excluded_analysis,
        partitions,
        partition_dependency_matrix,
        graph,
        args.output,
        missing_objects,
        excluded_edges,
        scc_priority_list,
    )
    print(f"\nDone! Output folder: {output_folder}")

    print("\nGenerating missing dependencies report...")
    generate_missing_dependencies_report_from_registry(
        args.registry_dir,
        output_folder / "missing_dependencies.json",
    )

    print("\nGenerating wave deployment order from partition_membership.csv...")
    generate_wave_deployment_order(output_folder)


if __name__ == "__main__":
    main()
