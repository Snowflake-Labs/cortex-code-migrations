from pathlib import Path
from typing import Any


def parse_graph_summary(txt_path: str | Path) -> dict[str, Any]:
    """Parse graph_summary.txt for graph statistics."""
    summary: dict[str, Any] = {
        "total_nodes": 0,
        "total_edges": 0,
        "avg_dependencies": 0.0,
        "weakly_connected_components": 0,
        "strongly_connected_components": 0,
        "cyclic_dependencies": 0,
        "root_nodes": 0,
        "leaf_nodes": 0,
        "max_dependencies": 0,
        "max_dependents": 0,
        "generated_timestamp": "",
    }

    content = Path(txt_path).read_text()
    field_map = {
        "Generated:": "generated_timestamp",
        "Total Nodes (Objects):": "total_nodes",
        "Total Edges (Dependencies):": "total_edges",
        "Average Dependencies per Node:": "avg_dependencies",
        "Weakly Connected Components": "weakly_connected_components",
        "Strongly Connected Components:": "strongly_connected_components",
        "Cyclic Dependencies": "cyclic_dependencies",
        "Root Nodes": "root_nodes",
        "Leaf Nodes": "leaf_nodes",
        "Max Dependencies:": "max_dependencies",
        "Max Dependents:": "max_dependents",
    }

    for line in content.split("\n"):
        line = line.strip()
        for marker, key in field_map.items():
            if marker in line:
                value = line.split(":")[-1].strip().replace(",", "")
                summary[key] = value
                break

    return summary


def parse_cycles(txt_path: str | Path) -> list[dict[str, Any]]:
    """Parse cycles.txt for cyclic dependency information."""
    cycles: list[dict[str, Any]] = []
    lines = Path(txt_path).read_text().strip().split("\n")

    if len(lines) < 2:
        return cycles

    current_cycle: dict[str, Any] | None = None
    for line in lines[1:]:
        line = line.strip()
        if line.startswith("Cycle ") and "(" in line:
            if current_cycle:
                cycles.append(current_cycle)
            parts = line.split("(")
            cycle_num = parts[0].replace("Cycle", "").replace(":", "").strip()
            node_count = parts[1].split(" ")[0] if len(parts) > 1 else "0"
            current_cycle = {
                "cycle_num": cycle_num,
                "node_count": node_count,
                "nodes": [],
            }
        elif line.startswith("- ") and current_cycle:
            current_cycle["nodes"].append(line[2:].strip())

    if current_cycle:
        cycles.append(current_cycle)

    return cycles


def parse_excluded_edges(txt_path: str | Path) -> dict[str, Any]:
    """Parse excluded_edges_analysis.txt."""
    excluded: dict[str, Any] = {
        "total_excluded": 0,
        "undefined_caller": 0,
        "undefined_referenced": 0,
        "both_undefined": 0,
        "exclusion_reasons": [],
        "relation_types": [],
        "top_undefined_referenced": [],
    }

    content = Path(txt_path).read_text()
    lines = content.split("\n")

    for i, line in enumerate(lines):
        line = line.strip()
        if "Total Excluded Edges:" in line:
            excluded["total_excluded"] = (
                line.split(":")[-1].strip().replace(",", "")
            )
        elif "Edges with undefined caller:" in line:
            excluded["undefined_caller"] = (
                line.split(":")[-1].strip().replace(",", "")
            )
        elif "Edges with undefined referenced object:" in line:
            excluded["undefined_referenced"] = (
                line.split(":")[-1].strip().replace(",", "")
            )
        elif "Edges with both undefined:" in line:
            excluded["both_undefined"] = (
                line.split(":")[-1].strip().replace(",", "")
            )
        elif "EXCLUSION REASONS" in line:
            excluded["exclusion_reasons"] = _parse_key_value_section(
                lines, i + 2
            )
        elif "RELATION TYPES" in line:
            excluded["relation_types"] = _parse_key_value_section(
                lines, i + 2, key_name="type"
            )
        elif "TOP 20 UNDEFINED REFERENCED OBJECTS" in line:
            excluded["top_undefined_referenced"] = (
                _parse_top_undefined_section(lines, i + 2)
            )

    return excluded


def _parse_key_value_section(
    lines: list[str],
    start: int,
    key_name: str = "reason",
) -> list[dict[str, str]]:
    """Parse a colon-separated key:value section until a blank or section line."""
    results = []
    j = start
    while j < len(lines):
        raw = lines[j].strip()
        if not raw or raw.startswith("=") or raw.startswith("RELATION") or raw.startswith("TOP"):
            break
        if ":" in raw:
            key, count = raw.rsplit(":", 1)
            results.append(
                {key_name: key.strip(), "count": count.strip().replace(",", "")}
            )
        j += 1
    return results


def _parse_top_undefined_section(
    lines: list[str], start: int, limit: int = 10
) -> list[dict[str, str]]:
    """Parse top undefined referenced objects section."""
    results = []
    j = start
    while j < len(lines) and len(results) < limit:
        raw = lines[j].strip()
        if not raw or raw.startswith("=") or raw.startswith("SAMPLE"):
            break
        if "x -" in raw:
            parts = raw.split("x -", 1)
            if len(parts) == 2:
                results.append(
                    {"count": parts[0].strip(), "object": parts[1].strip()}
                )
        j += 1
    return results
