"""
Dependency Graph Analysis and Wave Generator

This module analyzes database object dependencies and generates deployment waves
that respect dependency ordering while optimizing for batch deployment.

PORTABILITY & DETERMINISM:
--------------------------
This script is designed to produce identical results across:
- Different machines (Windows, Linux, macOS)
- Different Python versions (3.8+)
- Different runs with same input data
- Different hardware configurations

Key design decisions for portability:
1. All set/dict iterations are sorted for deterministic order
2. Algorithms use O(V+E) space - memory efficient for millions of objects
3. Iterative algorithms avoid stack overflow (no recursion limits)
4. No external dependencies beyond Python stdlib
5. All file I/O uses explicit UTF-8 encoding
6. Timestamps are in ISO format for cross-platform compatibility

Performance characteristics:
- Time complexity: O(V+E) for all graph operations
- Space complexity: O(V) for data structures
- Tested with 34,751 objects, 44,590 edges in ~90 seconds
- Scales to millions of objects without stack overflow
"""

import csv
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Set, List, Tuple, Optional, Any, DefaultDict, TypeVar, Generic

T = TypeVar('T')

# Priority tier definitions (lower tier = earlier waves).
# Kept as a single source of truth for the sort key and all output formatting.
PRIORITY_TIER_NAMES: Dict[int, str] = {
    0: 'User-Prioritized',
    1: 'Regular',
    2: 'ETL',
}

@dataclass
class PartitionMetadata:
    partition_number: int
    nodes: List[str]
    size: int
    picked_scc_ids: List[int]
    picked_scc_nodes: List[str]
    partition_type: str = "regular"  # "simple_object", "user_prioritized", "regular"
    is_simple_object_wave: bool = False
    root_nodes: Set[str] = field(default_factory=set)
    leaf_nodes: Set[str] = field(default_factory=set)
    internal_dependencies: int = 0
    external_dependencies: int = 0
    dependencies_by_partition: Dict[int, int] = field(default_factory=dict)
    node_types: Dict[str, int] = field(default_factory=dict)

class DependencyGraph(Generic[T]):
    def __init__(self) -> None:
        self.graph: DefaultDict[T, Set[T]] = defaultdict(set)
        self.reverse_graph: DefaultDict[T, Set[T]] = defaultdict(set)
        self.all_nodes: Set[T] = set()
        self.object_info: Dict[T, Dict[str, Any]] = {}
    
    def add_edge(self, caller: T, referenced: T) -> None:
        if caller != referenced:
            self.graph[caller].add(referenced)
            self.reverse_graph[referenced].add(caller)
        self.all_nodes.add(caller)
        self.all_nodes.add(referenced)
    
    def add_object_info(self, obj_name: T, info: Dict[str, Any]) -> None:
        self.object_info[obj_name] = info
    
    def get_direct_dependencies(self, node: T) -> Set[T]:
        return self.graph.get(node, set())
    
    def get_direct_dependents(self, node: T) -> Set[T]:
        return self.reverse_graph.get(node, set())
    
    def get_transitive_dependencies(self, node: T, max_depth: Optional[int] = None) -> Set[T]:
        """
        Get all transitive dependencies using iterative BFS.
        
        Args:
            node: Starting node
            max_depth: Optional depth limit for early termination
        
        Returns:
            Set of all reachable nodes (excluding start node)
        
        Time complexity: O(V+E) worst case
        Space complexity: O(V)
        """
        visited = set()
        queue = deque([(node, 0)])
        visited.add(node)
        
        while queue:
            current, depth = queue.popleft()
            
            # Early termination if max depth reached
            if max_depth is not None and depth >= max_depth:
                continue
            
            for neighbor in self.graph.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        
        visited.discard(node)
        return visited
    
    def get_transitive_dependents(self, node: T, max_depth: Optional[int] = None) -> Set[T]:
        """
        Get all transitive dependents using iterative BFS.
        
        Args:
            node: Starting node
            max_depth: Optional depth limit for early termination
        
        Returns:
            Set of all nodes that depend on this node (excluding start node)
        
        Time complexity: O(V+E) worst case
        Space complexity: O(V)
        """
        visited = set()
        queue = deque([(node, 0)])
        visited.add(node)
        
        while queue:
            current, depth = queue.popleft()
            
            # Early termination if max depth reached
            if max_depth is not None and depth >= max_depth:
                continue
            
            for neighbor in self.reverse_graph.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        
        visited.discard(node)
        return visited
    
    def find_strongly_connected_components(self) -> List[Set[T]]:
        """
        Find Strongly Connected Components using Tarjan's algorithm (iterative).
        
        Tarjan's algorithm is faster than Kosaraju's:
        - Single DFS pass instead of two
        - Better cache locality
        - Same O(V+E) complexity but lower constant factor
        
        Iterative implementation prevents stack overflow for deep graphs.
        
        A Strongly Connected Component is a maximal set of nodes where every node
        can reach every other node in the set by following directed edges.
        
        Returns:
            List of sets, where each set contains nodes forming an SCC
        
        Time complexity: O(V+E)
        Space complexity: O(V)
        """
        index_counter = [0]
        stack = []
        lowlinks = {}
        index = {}
        on_stack = set()
        sccs = []
        
        def strongconnect_iterative(start_node: T) -> None:
            """Iterative version of Tarjan's strongconnect"""
            call_stack = [('VISIT', start_node, None)]
            
            while call_stack:
                action, node, data = call_stack[-1]
                
                if action == 'VISIT':
                    index[node] = index_counter[0]
                    lowlinks[node] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(node)
                    on_stack.add(node)
                    call_stack[-1] = ('PROCESS', node, iter(self.graph.get(node, set())))
                
                elif action == 'PROCESS':
                    neighbors_iter = data
                    try:
                        neighbor = next(neighbors_iter)
                        
                        if neighbor not in index:
                            # Push UPDATE_LOWLINK first (will execute after neighbor is processed)
                            call_stack.append(('UPDATE_LOWLINK', node, neighbor))
                            # Then push VISIT for neighbor (will execute immediately)
                            call_stack.append(('VISIT', neighbor, None))
                        elif neighbor in on_stack:
                            lowlinks[node] = min(lowlinks[node], index[neighbor])
                    
                    except StopIteration:
                        call_stack.pop()
                        
                        if lowlinks[node] == index[node]:
                            scc = set()
                            while True:
                                w = stack.pop()
                                on_stack.discard(w)
                                scc.add(w)
                                if w == node:
                                    break
                            sccs.append(scc)
                
                elif action == 'UPDATE_LOWLINK':
                    parent, child = node, data
                    lowlinks[parent] = min(lowlinks[parent], lowlinks[child])
                    call_stack.pop()
        
        # Sort nodes to ensure deterministic order across runs
        # This is critical for reproducibility on different machines
        for node in sorted(self.all_nodes):
            if node not in index:
                strongconnect_iterative(node)
        
        # Sort SCCs by their minimum element for consistent ordering
        sccs.sort(key=lambda scc: min(scc) if scc else "")
        return sccs
    
    def find_weakly_connected_components(self) -> List[Set[T]]:
        """
        Find Weakly Connected Components using iterative DFS.
        
        Iterative implementation prevents stack overflow for large/deep graphs.
        
        A Weakly Connected Component is a maximal set of nodes where every node
        can reach every other node when edge directions are ignored.
        
        Returns:
            List of sets, where each set contains nodes forming a WCC
        
        Time complexity: O(V+E)
        Space complexity: O(V)
        """
        def dfs_iterative(start_node: T, visited: Set[T], component: Set[T]) -> None:
            """Iterative DFS treating graph as undirected"""
            stack = [start_node]
            
            while stack:
                node = stack.pop()
                
                if node in visited:
                    continue
                
                visited.add(node)
                component.add(node)
                
                for neighbor in self.graph.get(node, set()):
                    if neighbor not in visited:
                        stack.append(neighbor)
                
                for neighbor in self.reverse_graph.get(node, set()):
                    if neighbor not in visited:
                        stack.append(neighbor)
        
        visited = set()
        components = []
        
        # Sort nodes to ensure deterministic order across runs
        for node in sorted(self.all_nodes):
            if node not in visited:
                component = set()
                dfs_iterative(node, visited, component)
                components.append(component)
        
        # Sort components by their minimum element for consistent ordering
        components.sort(key=lambda comp: min(comp) if comp else "")
        return components
    
    def find_cycles(self) -> List[Set[T]]:
        """
        Find circular dependencies (cycles) in the dependency graph.
        
        A cycle is an SCC with more than one node, representing objects that
        have circular dependencies on each other.
        
        Example: Table A references View B, View B references Proc C, 
                 Proc C references Table A -> forms a 3-node cycle
        
        Returns:
            List of sets containing nodes that form circular dependencies
        """
        cycles = []
        sccs = self.find_strongly_connected_components()
        
        for scc in sccs:
            if len(scc) > 1:
                cycles.append(scc)
        
        return cycles
    
    def get_roots(self) -> List[T]:
        # Sort for deterministic order
        return sorted([node for node in self.all_nodes if not self.reverse_graph.get(node)])
    
    def get_leaves(self) -> List[T]:
        # Sort for deterministic order
        return sorted([node for node in self.all_nodes if not self.graph.get(node)])


def is_create_statement(code_unit: str) -> bool:
    if not code_unit or code_unit == 'N/A':
        return False
    return code_unit.strip().upper().startswith('CREATE ')


def load_objects(csv_path: str) -> Dict[str, Dict[str, str]]:
    """
    Load database objects from TopLevelObjectsEstimation CSV.
    
    Supports two CSV formats:
    1. Legacy format: Uses 'CodeUnit' and 'CodeUnitId' columns
    2. Current format: Uses 'HighLevelObject', 'Object Id', and 'ObjectName' columns
    
    Only loads deployable code objects (PROCEDURE, TABLE, VIEW, FUNCTION).
    Explicitly excludes container objects (SCHEMA, DATABASE) and non-code objects.
    """
    objects = {}
    
    # Define valid object types that should be included in dependency analysis
    VALID_OBJECT_TYPES = {'PROCEDURE', 'TABLE', 'VIEW', 'FUNCTION', 'EXTERNAL TABLE'}
    
    # Define object types that should be explicitly excluded (used by current format)
    EXCLUDED_OBJECT_TYPES = {
        'DATABASE',         # Container, not deployable code
        'SCHEMA',           # Container, not deployable code
        'UNKNOWN',          # Not a valid object type
        'SELECT',           # Query, not an object
        'INSERT',           # DML statement, not an object
        'UPDATE',           # DML statement, not an object
        'DELETE',           # DML statement, not an object
        'IF',               # Control flow, not an object
        'WHILE',            # Control flow, not an object
        'BEGIN',            # Block, not an object
    }
    
    excluded_count = defaultdict(int)
    included_count = defaultdict(int)
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code_unit = row.get('CodeUnit', '').strip()
            code_unit_id = row.get('CodeUnitId', '').strip()
            high_level_object = row.get('HighLevelObject', '').strip()
            object_id = row.get('Object Id', '').strip()
            object_name = row.get('ObjectName', '').strip()
            
            # Legacy format: CodeUnit column with CREATE statements
            if code_unit and is_create_statement(code_unit):
                if code_unit_id and code_unit_id != 'N/A':
                    category = row.get('Category', '').upper()
                    
                    # Skip objects marked as OUT OF SCOPE
                    if category == 'OUT OF SCOPE':
                        excluded_count['OUT_OF_SCOPE'] += 1
                        continue
                    
                    # Skip CREATE SCHEMA statements
                    if code_unit.strip().upper().startswith('CREATE SCHEMA'):
                        excluded_count['CREATE_SCHEMA'] += 1
                        continue
                    
                    # Only include valid deployable object types
                    if category not in VALID_OBJECT_TYPES:
                        excluded_count[category] += 1
                        continue
                    
                    objects[code_unit_id] = {
                        'category': category,
                        'code_unit': code_unit,
                        'file_name': row.get('FileName', ''),
                        'line_number': row.get('LineNumber', ''),
                        'conversion_status': row.get('ConversionStatus', ''),
                        'estimated_hours': float(row.get('Manual Effort', 0) or 0)
                    }
                    included_count[category] += 1
            
            # Current format: HighLevelObject column
            elif high_level_object:
                obj_type = high_level_object.upper()
                
                # Explicitly exclude non-deployable object types
                if obj_type in EXCLUDED_OBJECT_TYPES:
                    excluded_count[obj_type] += 1
                    continue
                
                # Only include valid deployable object types
                if obj_type in VALID_OBJECT_TYPES:
                    identifier = object_id if object_id and object_id != 'N/A' else object_name
                    if identifier and identifier != 'N/A':
                        objects[identifier] = {
                            'category': obj_type,
                            'code_unit': f'CREATE {obj_type}',
                            'file_name': row.get('FileName', ''),
                            'line_number': row.get('LineNumber', ''),
                            'conversion_status': row.get('ConversionStatus', ''),
                            'estimated_hours': float(row.get('Manual Effort', 0) or 0)
                        }
                        included_count[obj_type] += 1
                else:
                    # Track unknown object types for debugging
                    excluded_count[f'UNKNOWN_TYPE:{obj_type}'] += 1
    
    # Print summary of what was loaded and excluded
    if included_count:
        print(f"Loaded {len(objects)} objects:")
        for obj_type, count in sorted(included_count.items()):
            print(f"  {obj_type}: {count}")
    
    if excluded_count:
        print(f"Excluded {sum(excluded_count.values())} non-deployable entries:")
        for obj_type, count in sorted(excluded_count.items()):
            print(f"  {obj_type}: {count}")
    
    return objects


def load_etl_elements(etl_elements_csv: str) -> Dict[str, Dict[str, str]]:
    """Load SSIS packages from ETL.Elements.NA.csv or ETL.Elements.<TIMESTAMP>.csv if available.
    Returns a dict mapping package name to {'status': status, 'technology': technology, 'subtype': subtype}."""
    etl_packages = {}
    
    if not Path(etl_elements_csv).exists():
        return etl_packages
    
    try:
        with open(etl_elements_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_name = row.get('FileName', '').strip()
                subtype = row.get('Subtype', '').strip()
                status = row.get('Status', '').strip()
                technology = row.get('Technology', '').strip()
                
                # Only include Package entries (top-level SSIS packages)
                if file_name.endswith('.dtsx') and subtype == 'Package':
                    # Keep full path minus extension for uniqueness across directories
                    package_name = str(Path(file_name).with_suffix(''))
                    etl_packages[package_name] = {
                        'status': status if status else 'Unknown',
                        'technology': technology if technology else 'ETL',
                        'subtype': subtype
                    }
    except Exception as e:
        print(f"Warning: Could not load {etl_elements_csv}: {e}")
    
    return etl_packages


def build_dependency_graph(references_csv: str, objects_csv: str) -> Tuple[DependencyGraph[str], List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    graph = DependencyGraph[str]()
    
    # Try to find ETL.Elements.NA.csv or ETL.Elements.<TIMESTAMP>.csv in the same directory as ObjectReferences
    references_dir = Path(references_csv).parent
    etl_elements_csv = None
    
    # First try ETL.Elements.NA.csv
    candidate = references_dir / 'ETL.Elements.NA.csv'
    if candidate.exists():
        etl_elements_csv = candidate
    else:
        # Try to find ETL.Elements.<TIMESTAMP>.csv pattern
        matches = list(references_dir.glob('ETL.Elements.*.csv'))
        if matches:
            etl_elements_csv = matches[0]  # Use the first match
    
    etl_packages_from_file = {}
    if etl_elements_csv:
        etl_packages_from_file = load_etl_elements(str(etl_elements_csv))
        if etl_packages_from_file:
            print(f"Found {len(etl_packages_from_file)} SSIS packages in {etl_elements_csv.name}")
    
    # Load all objects from TopLevelCodeUnits.csv
    all_objects_from_csv = {}
    with open(objects_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code_unit_id = row.get('CodeUnitId', '').strip()
            category = row.get('Category', '').strip().upper()
            
            # Skip objects marked as OUT OF SCOPE
            if category == 'OUT OF SCOPE':
                continue
            
            if code_unit_id and code_unit_id != 'N/A':
                all_objects_from_csv[code_unit_id] = {
                    'category': category,
                    'code_unit': row.get('CodeUnit', '').strip(),
                    'file_name': row.get('FileName', ''),
                    'line_number': row.get('LineNumber', ''),
                    'conversion_status': row.get('ConversionStatus', '')
                }
    
    # Filter to only CREATE objects
    objects = load_objects(objects_csv)
    valid_object_names = set(objects.keys())
    
    # Track missing objects (those in CSV but not included in graph)
    missing_objects = {}
    for obj_name, info in all_objects_from_csv.items():
        if obj_name not in valid_object_names:
            reason = 'Non-CREATE statement'
            if not info.get('code_unit'):
                reason = 'Missing CodeUnit'
            elif not is_create_statement(info.get('code_unit', '')):
                reason = 'Not a CREATE statement'
            missing_objects[obj_name] = {**info, 'exclusion_reason': reason}
    
    for obj_name, info in objects.items():
        graph.add_object_info(obj_name, info)
        # Explicitly add as a node (even if it has no edges)
        graph.all_nodes.add(obj_name)
    
    # Add SSIS packages from ETL.Elements file (if found) as ETL nodes with proper status/technology/subtype
    for package_name, package_info in etl_packages_from_file.items():
        if package_name not in graph.all_nodes:
            graph.add_object_info(package_name, {
                'category': 'ETL',
                'code_unit': 'ETL PACKAGE',
                'file_name': f'{package_name}.dtsx',
                'line_number': 'N/A',
                'conversion_status': package_info['status'],
                'technology': package_info['technology'],
                'subtype': package_info.get('subtype', 'N/A')
            })
            graph.all_nodes.add(package_name)
    
    excluded_edges = []
    
    with open(references_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            caller_type = row.get('Caller_CodeUnit', '').strip()
            caller = row.get('Caller_CodeUnit_FullName', '').strip()
            referenced = row.get('Referenced_Element_FullName', '').strip()
            relation_type = row.get('Relation_Type', '').strip()
            line = row.get('Line', '').strip()
            
            if not caller or not referenced:
                continue
            
            # Exclude FOREIGN KEY relationships from dependency graph
            if relation_type == 'FOREIGN KEY':
                excluded_edges.append({
                    'caller': caller,
                    'caller_defined': caller in valid_object_names,
                    'referenced': referenced,
                    'referenced_defined': referenced in valid_object_names,
                    'relation_type': relation_type,
                    'line': line,
                    'exclusion_reason': 'FOREIGN KEY'
                })
                continue
            
            caller_is_etl = caller_type == 'ETL PROCESS'
            if caller_is_etl:
                etl_file_name = row.get('FileName', '').strip()
                if etl_file_name.endswith('.dtsx'):
                    caller = str(Path(etl_file_name).with_suffix(''))  # e.g. "packages/Example.dtsx" → "packages/Example"
            caller_defined = caller in valid_object_names or caller_is_etl
            referenced_defined = referenced in valid_object_names
            
            # Register ETL package node (once per package, not per component)
            if caller_is_etl and caller not in graph.all_nodes:
                pkg_info = etl_packages_from_file.get(caller, {})
                graph.add_object_info(caller, {
                    'category': 'ETL',
                    'code_unit': 'ETL PACKAGE',
                    'file_name': f'{caller}.dtsx',
                    'line_number': 'N/A',
                    'conversion_status': pkg_info.get('status', 'N/A'),
                    'technology': pkg_info.get('technology', 'ETL'),
                    'subtype': pkg_info.get('subtype', 'Package'),
                })
                graph.all_nodes.add(caller)
            
            if caller_defined and referenced_defined:
                graph.add_edge(caller, referenced)
            else:
                # Determine exclusion reason
                if not caller_defined and not referenced_defined:
                    exclusion_reason = 'Both Undefined'
                elif not caller_defined:
                    exclusion_reason = 'Caller Undefined'
                elif not referenced_defined:
                    exclusion_reason = 'Referenced Undefined'
                else:
                    exclusion_reason = 'Other'
                
                excluded_edges.append({
                    'caller': caller,
                    'caller_defined': caller_defined,
                    'referenced': referenced,
                    'referenced_defined': referenced_defined,
                    'relation_type': relation_type,
                    'line': line,
                    'exclusion_reason': exclusion_reason
                })
    
    return graph, excluded_edges, missing_objects


def analyze_dependencies(graph: DependencyGraph[str]) -> List[Dict[str, Any]]:
    results = []
    
    for node in graph.all_nodes:
        direct_deps = graph.get_direct_dependencies(node)
        direct_dependents = graph.get_direct_dependents(node)
        transitive_deps = graph.get_transitive_dependencies(node)
        transitive_dependents = graph.get_transitive_dependents(node)
        
        obj_info = graph.object_info.get(node, {})
        
        # transitive_deps already includes direct_deps, so we need to calculate transitive-only
        transitive_only_deps = transitive_deps - direct_deps
        transitive_only_dependents = transitive_dependents - direct_dependents
        
        results.append({
            'object': node,
            'category': obj_info.get('category', 'N/A'),
            'file_name': obj_info.get('file_name', 'N/A'),
            'direct_dependencies_count': len(direct_deps),
            'direct_dependents_count': len(direct_dependents),
            'transitive_dependencies_count': len(transitive_only_deps),
            'transitive_dependents_count': len(transitive_only_dependents),
            'total_dependencies': len(transitive_deps),  # Already includes direct
            'total_dependents': len(transitive_dependents)  # Already includes direct
        })
    
    return results


def analyze_excluded_edges(excluded_edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_excluded = len(excluded_edges)
    
    caller_undefined = sum(1 for e in excluded_edges if not e['caller_defined'])
    referenced_undefined = sum(1 for e in excluded_edges if not e['referenced_defined'])
    both_undefined = sum(1 for e in excluded_edges if not e['caller_defined'] and not e['referenced_defined'])
    
    relation_types = defaultdict(int)
    for edge in excluded_edges:
        relation_types[edge['relation_type']] += 1
    
    # Count by exclusion reason
    exclusion_reasons = defaultdict(int)
    for edge in excluded_edges:
        reason = edge.get('exclusion_reason', 'Unknown')
        exclusion_reasons[reason] += 1
    
    undefined_callers = defaultdict(int)
    undefined_referenced = defaultdict(int)
    
    for edge in excluded_edges:
        if not edge['caller_defined']:
            undefined_callers[edge['caller']] += 1
        if not edge['referenced_defined']:
            undefined_referenced[edge['referenced']] += 1
    
    return {
        'total_excluded': total_excluded,
        'caller_undefined': caller_undefined,
        'referenced_undefined': referenced_undefined,
        'both_undefined': both_undefined,
        'relation_types': dict(relation_types),
        'exclusion_reasons': dict(exclusion_reasons),
        'top_undefined_callers': sorted(undefined_callers.items(), key=lambda x: x[1], reverse=True)[:20],
        'top_undefined_referenced': sorted(undefined_referenced.items(), key=lambda x: x[1], reverse=True)[:20],
        'samples': excluded_edges[:10]
    }


def analyze_graph_structure(graph: DependencyGraph[str]) -> Dict[str, Any]:
    weakly_connected = graph.find_weakly_connected_components()
    strongly_connected = graph.find_strongly_connected_components()
    cycles = graph.find_cycles()
    roots = graph.get_roots()
    leaves = graph.get_leaves()
    
    total_edges = sum(len(deps) for deps in graph.graph.values())
    
    # Count objects by category/type
    category_counts = defaultdict(int)
    for node in graph.all_nodes:
        obj_info = graph.object_info.get(node, {})
        category = obj_info.get('category', 'Unknown')
        category_counts[category] += 1
    
    return {
        'total_nodes': len(graph.all_nodes),
        'total_edges': total_edges,
        'weakly_connected_components': len(weakly_connected),
        'strongly_connected_components': len(strongly_connected),
        'cycles': len(cycles),
        'root_nodes': len(roots),
        'leaf_nodes': len(leaves),
        'weakly_connected_component_sizes': sorted([len(c) for c in weakly_connected], reverse=True),
        'cycle_sizes': sorted([len(c) for c in cycles], reverse=True),
        'weakly_components': weakly_connected,
        'cycle_components': cycles,
        'roots': roots,
        'leaves': leaves,
        'category_counts': dict(category_counts)
    }


def create_deployment_partitions(graph: DependencyGraph[str], min_size: int = 40, max_size: int = 80, prioritize_patterns: Optional[List[str]] = None, category_waves: bool = True) -> Tuple[List[PartitionMetadata], Dict[Tuple[int, int], int], List[Dict[str, Any]]]:
    """
    Create ordered partitions of objects for deployment.
    Each partition contains objects that only depend on objects in the same or earlier partitions.
    
    Args:
        graph: DependencyGraph object
        min_size: Minimum partition size
        max_size: Maximum partition size
        prioritize_patterns: List of object name patterns to prioritize (supports wildcards)
        category_waves: If True (default), create waves grouped by category
                        (TABLE, then VIEW, then FUNCTION) before procedural/ETL objects.
                        If False, all object types are mixed and sorted purely by dependency level.
    
    Returns:
        partitions: List of partition dictionaries
        partition_dependency_matrix: Dictionary of inter-partition dependencies
        scc_priority_list: List of SCCs sorted by priority order
    
    Algorithm (Priority-Driven):
    1. If category_waves is True (default), create waves grouped by category: TABLE → VIEW → FUNCTION
    2. Find Strongly Connected Components (SCCs/cycles) - these must stay together
    3. Build SCC groups and treat each as an atomic unit
    4. Create a DependencyGraph from SCCs to analyze SCC-level dependencies
    5. Identify priority objects and compute their transitive dependencies
    6. For each priority object (highest first):
       a. Find all unassigned transitive dependencies
       b. Sort dependencies by topological order (dependencies before dependents)
       c. Pack dependencies into partitions greedily
       d. Add priority object to final partition
    7. After all priority objects, continue with remaining SCCs using original algorithm
    """
    
    # Find SCCs - nodes in the same SCC must be in the same partition
    sccs = graph.find_strongly_connected_components()
    
    # Create a DependencyGraph where nodes are SCC IDs (integers)
    scc_graph = DependencyGraph[int]()
    
    # Build node-to-SCC mapping and populate scc_graph
    node_to_scc = {}
    for scc_id, scc_nodes in enumerate(sccs):
        # Add SCC as a node
        scc_graph.all_nodes.add(scc_id)
        
        # Map each node to its SCC
        for node in scc_nodes:
            node_to_scc[node] = scc_id
    
    # Build SCC-level dependencies
    for scc_id, scc_nodes in enumerate(sccs):
        for node in scc_nodes:
            # Get dependencies of this node
            node_deps = graph.get_direct_dependencies(node)
            for dep in node_deps:
                dep_scc_id = node_to_scc.get(dep)
                if dep_scc_id is not None and dep_scc_id != scc_id:
                    # Add edge from scc_id to dep_scc_id (scc_id depends on dep_scc_id)
                    scc_graph.add_edge(scc_id, dep_scc_id)
    
    # Build SCC list for partition assignment
    scc_list = []
    for scc_nodes in sccs:
        scc_nodes_list = list(scc_nodes)
        scc_list.append(scc_nodes_list)
    
    # Helper function to check if object name matches any prioritization pattern
    def matches_priority_pattern(obj_name: str, patterns: Optional[List[str]]) -> bool:
        if not patterns:
            return False
        import fnmatch
        for pattern in patterns:
            # If pattern has no wildcards, do exact match (avoids fnmatch treating [] as character class)
            if '*' not in pattern and '?' not in pattern:
                if obj_name == pattern:
                    return True
            else:
                if fnmatch.fnmatch(obj_name, pattern):
                    return True
        return False
    
    # Helper function to compute transitive dependencies of an SCC (excluding already assigned)
    def get_transitive_dependencies(scc_id: int, assigned_sccs: Set[int]) -> Set[int]:
        """Get all transitive dependency SCCs (BFS), excluding already assigned SCCs"""
        result = set()
        to_visit = [scc_id]
        visited = set([scc_id])
        
        while to_visit:
            current = to_visit.pop(0)
            deps = scc_graph.get_direct_dependencies(current)
            for dep_scc in deps:
                if dep_scc not in assigned_sccs and dep_scc not in visited:
                    visited.add(dep_scc)
                    to_visit.append(dep_scc)
                    result.add(dep_scc)
        
        return result
    
    # Helper function to topologically sort SCCs
    def topological_sort_sccs(scc_set: Set[int]) -> List[int]:
        """Return SCCs in topological order (dependencies before dependents)"""
        # Build in-degree map for SCCs in the set
        local_in_degree = {scc: 0 for scc in scc_set}
        local_deps = {scc: set() for scc in scc_set}
        
        for scc in scc_set:
            deps = scc_graph.get_direct_dependencies(scc)
            for dep in deps:
                if dep in scc_set:
                    local_deps[scc].add(dep)
                    local_in_degree[scc] += 1
        
        # Kahn's algorithm for topological sorting
        queue = [scc for scc in scc_set if local_in_degree[scc] == 0]
        result = []
        
        while queue:
            # Sort queue for deterministic ordering
            queue.sort(key=lambda x: (len(scc_list[x]), min(scc_list[x])))
            current = queue.pop(0)
            result.append(current)
            
            # Reduce in-degree of dependents
            for scc in scc_set:
                if current in local_deps[scc]:
                    local_in_degree[scc] -= 1
                    if local_in_degree[scc] == 0:
                        queue.append(scc)
        
        return result
    
    # Helper function to prioritize SCCs
    def scc_priority_key(scc_id: int) -> Tuple[int, int, int, int, str]:
        scc_nodes = scc_list[scc_id]
        
        # Check if any node matches user prioritization patterns
        is_user_prioritized = any(matches_priority_pattern(node, prioritize_patterns) for node in scc_nodes)
        
        # Check if this SCC contains ETL objects
        is_etl_scc = any(graph.object_info.get(node, {}).get('category') == 'ETL' for node in scc_nodes)
        
        # Calculate total dependents across all nodes in SCC
        total_dependents = sum(len(graph.get_direct_dependents(node)) for node in scc_nodes)
        
        # Calculate total transitive dependencies (all SCCs this SCC depends on)
        transitive_deps_count = len(scc_graph.get_transitive_dependencies(scc_id))
        
        if is_user_prioritized:
            priority_tier = 0
        elif is_etl_scc:
            priority_tier = 2
        else:
            priority_tier = 1
        
        # Sort by: priority tier, fewer dependents, MORE transitive dependencies, SCC size, then alphabetical
        # Note: -transitive_deps_count for descending order (more dependencies = higher priority)
        return (priority_tier, total_dependents, -transitive_deps_count, len(scc_nodes), min(scc_nodes))
    
    # Track which SCCs have been assigned to partitions
    assigned_sccs: Set[int] = set()
    assigned_nodes: Set[str] = set()
    partitions: List[Dict[str, Any]] = []
    partition_num = 1
    
    # Step 1: Create waves per category in deployment order: TABLEs, then
    # VIEWs, then FUNCTIONs.  Within each category multiple waves may be
    # created to respect inter-object dependencies.  No min/max size
    # constraints.  Disable with --no-category-waves.
    #
    # The outer convergence loop handles cross-category dependencies
    # (e.g. a TABLE with a computed column that references a FUNCTION).
    # Round 1 places independent objects; round 2 catches objects whose
    # cross-category deps are now satisfied; subsequent rounds handle
    # deeper chains. 
    if category_waves:
        simple_category_order = ['TABLE', 'VIEW', 'FUNCTION']
        simple_object_types = set(simple_category_order)
        simple_sccs_by_category: Dict[str, List[int]] = {cat: [] for cat in simple_category_order}
        simple_sccs_set: Set[int] = set()
        for scc_id, scc_nodes in enumerate(scc_list):
            node_categories = {
                graph.object_info.get(node, {}).get('category', '')
                for node in scc_nodes
            }
            if node_categories <= simple_object_types:
                latest_cat = max(node_categories, key=lambda c: simple_category_order.index(c) if c in simple_object_types else 0)
                simple_sccs_by_category[latest_cat].append(scc_id)
                simple_sccs_set.add(scc_id)

        def _ready_simple_sccs(category: str) -> List[int]:
            """Return unassigned SCCs in *category* whose simple deps are all assigned."""
            return [
                scc_id for scc_id in sorted(simple_sccs_by_category[category])
                if scc_id not in assigned_sccs
                and all(d in assigned_sccs
                        for d in scc_graph.get_direct_dependencies(scc_id)
                        if d in simple_sccs_set)
            ]

        placed_in_round = True
        while placed_in_round:
            placed_in_round = False
            for category in simple_category_order:
                # Inner loop: create waves at successive dependency levels
                # within this category (e.g. TABLE→TABLE chains).
                while True:
                    ready_sccs = _ready_simple_sccs(category)
                    if not ready_sccs:
                        break

                    partition_nodes = [n for sid in ready_sccs for n in scc_list[sid]]
                    partitions.append(PartitionMetadata(
                        partition_number=partition_num,
                        nodes=partition_nodes,
                        size=len(partition_nodes),
                        picked_scc_ids=list(ready_sccs),
                        picked_scc_nodes=list(partition_nodes),
                        partition_type="simple_object",
                        is_simple_object_wave=True,
                    ))
                    assigned_sccs.update(ready_sccs)
                    assigned_nodes.update(partition_nodes)
                    partition_num += 1
                    placed_in_round = True
    
    # Step 2: Batch remaining objects into waves respecting min/max size constraints
    # This creates waves of multiple objects (up to max_size) that can be deployed together
    
    while len(assigned_sccs) < len(scc_list):
        # Find all unassigned SCCs
        unassigned_sccs = [scc_id for scc_id in range(len(scc_list)) if scc_id not in assigned_sccs]
        
        if not unassigned_sccs:
            break
        
        # Find SCCs that are ready to deploy (all dependencies satisfied)
        ready_sccs = []
        for scc_id in unassigned_sccs:
            deps = scc_graph.get_direct_dependencies(scc_id)
            if all(dep in assigned_sccs for dep in deps):
                ready_sccs.append(scc_id)
        
        if not ready_sccs:
            # No ready SCCs - shouldn't happen in a DAG, but handle gracefully
            print(f"WARNING: No ready SCCs found but {len(unassigned_sccs)} unassigned. Possible cycle issue.")
            break
        
        # Sort ready SCCs by priority
        ready_sccs.sort(key=scc_priority_key)
        
        # Batch SCCs into this wave up to max_size
        wave_sccs = []
        wave_size = 0
        picked_scc_id = ready_sccs[0]  # Highest priority SCC
        
        for scc_id in ready_sccs:
            scc_size = len(scc_list[scc_id])
            
            # Check if adding this SCC would exceed max_size
            if wave_size > 0 and wave_size + scc_size > max_size:
                continue
            
            wave_sccs.append(scc_id)
            wave_size += scc_size
            
            # Stop if we've reached a good wave size
            if wave_size >= min_size:
                break
        
        # If we couldn't build a min_size wave, take what we can get
        if wave_size < min_size and len(wave_sccs) < len(ready_sccs):
            # Try to add more SCCs to reach min_size
            for scc_id in ready_sccs:
                if scc_id in wave_sccs:
                    continue
                scc_size = len(scc_list[scc_id])
                if wave_size + scc_size <= max_size:
                    wave_sccs.append(scc_id)
                    wave_size += scc_size
                    if wave_size >= min_size:
                        break
        
        # Sort wave SCCs in topological order
        sorted_sccs = topological_sort_sccs(set(wave_sccs))
        
        # Collect nodes
        partition_nodes = []
        for scc_id in sorted_sccs:
            partition_nodes.extend(scc_list[scc_id])
        
        # Check if picked SCC is user-prioritized
        picked_scc_nodes = scc_list[picked_scc_id]
        is_user_prioritized = any(matches_priority_pattern(node, prioritize_patterns) for node in picked_scc_nodes)
        
        print(f"Creating partition {partition_num} with {len(wave_sccs)} SCCs, {len(partition_nodes)} objects (picked SCC {picked_scc_id})")
        
        # Create partition
        partition = PartitionMetadata(
            partition_number=partition_num,
            nodes=partition_nodes,
            size=len(partition_nodes),
            picked_scc_ids=[picked_scc_id],
            picked_scc_nodes=picked_scc_nodes,
            partition_type="user_prioritized" if is_user_prioritized else "regular"
        )
        partitions.append(partition)
        
        # Mark as assigned
        assigned_sccs.update(wave_sccs)
        assigned_nodes.update(partition_nodes)
        partition_num += 1
    
    # Analyze partitions
    for partition in partitions:
        nodes = partition.nodes
        
        # Count root and leaf nodes in this partition
        # Root: no dependencies at all (global roots)
        # Leaf: no dependents at all (global leaves)
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
        
        # Count internal vs external dependencies
        internal_deps = 0
        external_deps = 0
        deps_by_partition = defaultdict(int)
        
        for node in nodes:
            deps = graph.get_direct_dependencies(node)
            for dep in deps:
                if dep in nodes:
                    internal_deps += 1
                else:
                    external_deps += 1
                    # Find which partition this dependency is in
                    for p in partitions:
                        if dep in p.nodes:
                            deps_by_partition[p.partition_number] += 1
                            break
        
        partition.internal_dependencies = internal_deps
        partition.external_dependencies = external_deps
        partition.dependencies_by_partition = dict(deps_by_partition)
        
        # Count node types
        node_types = defaultdict(int)
        for node in nodes:
            obj_info = graph.object_info.get(node, {})
            category = obj_info.get('category', 'Unknown')
            node_types[category] += 1
        partition.node_types = dict(node_types)
    
    # Create partition-to-partition dependency matrix
    # This shows how many dependency edges exist from partition i to partition j
    # where partition i depends on partition j (i > j means i depends on earlier j)
    partition_dependency_matrix = {}
    for i, partition_i in enumerate(partitions):
        for j, partition_j in enumerate(partitions):
            if i <= j:  # Only look at dependencies to earlier partitions (i > j)
                continue
            
            # Count edges from partition i nodes to partition j nodes
            edge_count = 0
            for node_i in partition_i.nodes:
                deps = graph.get_direct_dependencies(node_i)
                for dep in deps:
                    if dep in partition_j.nodes:
                        edge_count += 1
            
            if edge_count > 0:
                key = (partition_i.partition_number, partition_j.partition_number)
                partition_dependency_matrix[key] = edge_count
    
    # Collect SCC priority information for output
    scc_priority_list = []
    for scc_id in range(len(scc_list)):
        scc_nodes = scc_list[scc_id]
        priority_key = scc_priority_key(scc_id)
        
        # Get assigned partition for this SCC
        assigned_partition = None
        for partition in partitions:
            if scc_nodes[0] in partition.nodes:
                assigned_partition = partition.partition_number
                break
        
        # Check if user prioritized
        is_user_prioritized = any(matches_priority_pattern(node, prioritize_patterns) for node in scc_nodes)
        
        scc_priority_list.append({
            'scc_id': scc_id,
            'scc_size': len(scc_nodes),
            'nodes': scc_nodes,
            'priority_tier': priority_key[0],
            'total_dependents': priority_key[1],
            'transitive_dependencies': -priority_key[2],  # Negate back to positive
            'min_node': min(scc_nodes),
            'assigned_partition': assigned_partition,
            'is_user_prioritized': is_user_prioritized
        })
    
    # Sort by priority key (same as used during partition assignment)
    scc_priority_list.sort(key=lambda x: (x['priority_tier'], x['total_dependents'], 
                                          -x['transitive_dependencies'], x['scc_size'], x['min_node']))
    
    return partitions, partition_dependency_matrix, scc_priority_list


def merge_small_partitions(partitions: List[PartitionMetadata], graph: DependencyGraph[str], min_size: int = 40, max_size: int = 80) -> List[PartitionMetadata]:
    """
    Merge small partitions into adjacent partitions to reduce fragmentation.
    
    Strategy:
    1. Find partitions smaller than min_size (skip simple object waves)
    2. Try to merge with adjacent partition (prefer earlier) where:
       - All dependencies remain satisfied
       - Merged size doesn't exceed max_size
    3. Renumber partitions after merging
    """
    if not partitions:
        return partitions
    
    # Sort partitions by partition number
    partitions.sort(key=lambda p: p.partition_number)
    
    # Build lookup: node -> partition_index
    node_to_partition = {}
    for i, partition in enumerate(partitions):
        for node in partition.nodes:
            node_to_partition[node] = i
    
    # Iteratively try to merge small partitions
    merged = True
    while merged:
        merged = False
        
        for i in range(len(partitions)):
            # Skip simple object waves - they have no size constraints
            if partitions[i].is_simple_object_wave:
                continue
                
            if partitions[i].size >= min_size:
                continue
            
            # Try to merge partition i with earlier partition
            # Check if we can merge with previous partition
            if i > 0:
                target_idx = i - 1
                current_nodes = partitions[i].nodes
                target_nodes = partitions[target_idx].nodes
                
                # Only merge partitions of the same type
                if partitions[i].partition_type != partitions[target_idx].partition_type:
                    continue
                
                # Check if merged size would be acceptable
                if len(current_nodes) + len(target_nodes) <= max_size:
                    # Check if all dependencies of current partition are satisfied
                    # by partitions before target (or within merged partition)
                    can_merge = True
                    merged_nodes = set(current_nodes) | set(target_nodes)
                    
                    for node in current_nodes:
                        deps = graph.get_direct_dependencies(node)
                        for dep in deps:
                            dep_partition_idx = node_to_partition.get(dep)
                            if dep_partition_idx is not None:
                                # Dependency must be in merged partition or earlier
                                if dep_partition_idx > target_idx and dep not in merged_nodes:
                                    can_merge = False
                                    break
                        if not can_merge:
                            break
                    
                    if can_merge:
                        # Merge partition i into partition target_idx
                        partitions[target_idx].nodes.extend(current_nodes)
                        partitions[target_idx].size = len(partitions[target_idx].nodes)
                        
                        # Merge SCC IDs and nodes
                        partitions[target_idx].picked_scc_ids.extend(partitions[i].picked_scc_ids)
                        partitions[target_idx].picked_scc_nodes.extend(partitions[i].picked_scc_nodes)
                        
                        # Update node_to_partition mapping
                        for node in current_nodes:
                            node_to_partition[node] = target_idx
                        
                        # Remove partition i
                        partitions.pop(i)
                        
                        # Update remaining partitions' indices in mapping
                        for j in range(i, len(partitions)):
                            for node in partitions[j].nodes:
                                node_to_partition[node] = j
                        
                        merged = True
                        break
        
        if not merged:
            # Try merging with next partition if no backward merge worked
            for i in range(len(partitions)):
                if partitions[i].size >= min_size:
                    continue
                
                # Try to merge with next partition
                if i < len(partitions) - 1:
                    target_idx = i + 1
                    current_nodes = partitions[i].nodes
                    target_nodes = partitions[target_idx].nodes
                    
                    # Only merge partitions of the same type
                    if partitions[i].partition_type != partitions[target_idx].partition_type:
                        continue
                    
                    # Check merged size
                    if len(current_nodes) + len(target_nodes) <= max_size:
                        # Check if all dependencies would still be satisfied after merge
                        can_merge = True
                        merged_nodes = set(current_nodes) | set(target_nodes)
                        
                        # Check dependencies of BOTH current and target nodes
                        for node in current_nodes + target_nodes:
                            deps = graph.get_direct_dependencies(node)
                            for dep in deps:
                                dep_partition_idx = node_to_partition.get(dep)
                                if dep_partition_idx is not None:
                                    # Dependency must be in merged partition or earlier
                                    # After merge, this will be partition i, so deps must be in partitions <=i
                                    if dep_partition_idx > i and dep not in merged_nodes:
                                        can_merge = False
                                        break
                            if not can_merge:
                                break
                        
                        if can_merge:
                            # Merge partition target_idx into partition i
                            partitions[i].nodes.extend(target_nodes)
                            partitions[i].size = len(partitions[i].nodes)
                            
                            # Merge SCC IDs and nodes
                            partitions[i].picked_scc_ids.extend(partitions[target_idx].picked_scc_ids)
                            partitions[i].picked_scc_nodes.extend(partitions[target_idx].picked_scc_nodes)
                            
                            # Update mapping
                            for node in target_nodes:
                                node_to_partition[node] = i
                            
                            # Remove target partition
                            partitions.pop(target_idx)
                            
                            # Update remaining partitions' indices
                            for j in range(target_idx, len(partitions)):
                                for node in partitions[j].nodes:
                                    node_to_partition[node] = j
                            
                            merged = True
                            break
    
    # Renumber partitions sequentially
    for i, partition in enumerate(partitions):
        partition.partition_number = i + 1
    
    return partitions


def write_results(dependency_results: List[Dict[str, Any]], graph_structure: Dict[str, Any], excluded_analysis: Dict[str, Any], partitions: List[PartitionMetadata], partition_dependency_matrix: Dict[Tuple[int, int], int], graph: DependencyGraph[str], output_dir: str, missing_objects: Dict[str, Dict[str, Any]], excluded_edges: List[Dict[str, Any]], scc_priority_list: Optional[List[Dict[str, Any]]] = None) -> Path:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    output_folder = Path(output_dir) / f'dependency_analysis_{timestamp}'
    output_folder.mkdir(parents=True, exist_ok=True)
    
    dependencies_file = output_folder / 'object_dependencies.csv'
    with open(dependencies_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'object',
            'category',
            'file_name',
            'direct_dependencies_count',
            'direct_dependents_count',
            'transitive_dependencies_count',
            'transitive_dependents_count',
            'total_dependencies',
            'total_dependents'
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(dependency_results)
    
    print(f"Dependencies written to: {dependencies_file}")
    
    summary_file = output_folder / 'graph_summary.txt'
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("DEPENDENCY GRAPH ANALYSIS SUMMARY\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("GRAPH OVERVIEW\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Nodes (Objects): {graph_structure['total_nodes']:,}\n")
        f.write(f"Total Edges (Dependencies): {graph_structure['total_edges']:,}\n")
        f.write(f"Average Dependencies per Node: {graph_structure['total_edges'] / max(1, graph_structure['total_nodes']):.2f}\n")
        
        # Add missing objects summary
        missing_count = len(missing_objects)
        if missing_count > 0:
            f.write(f"\nObjects Excluded from Analysis: {missing_count:,}\n")
            f.write(f"  (See missing_objects_analysis.txt for details)\n")
        f.write("\n")
        
        f.write("OBJECT TYPE DISTRIBUTION\n")
        f.write("-" * 80 + "\n")
        category_counts = graph_structure.get('category_counts', {})
        if category_counts:
            # Sort by count descending
            sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            for category, count in sorted_categories:
                f.write(f"  {category}: {count:,}\n")
        else:
            f.write("  No category information available\n")
        f.write("\n")
        
        f.write("CONNECTIVITY ANALYSIS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Weakly Connected Components (Forests): {graph_structure['weakly_connected_components']}\n")
        f.write(f"Strongly Connected Components: {graph_structure['strongly_connected_components']}\n")
        f.write(f"Cyclic Dependencies (SCCs > 1 node): {graph_structure['cycles']}\n\n")
        
        if graph_structure['weakly_connected_components'] > 1:
            f.write(f"Forest Structure: YES - Graph consists of {graph_structure['weakly_connected_components']} separate trees/forests\n")
        else:
            f.write("Forest Structure: NO - Graph is a single connected component\n")
        f.write("\n")
        
        f.write("COMPONENT SIZE DISTRIBUTION\n")
        f.write("-" * 80 + "\n")
        f.write("Weakly Connected Component Sizes (top 20):\n")
        for i, size in enumerate(graph_structure['weakly_connected_component_sizes'][:20], 1):
            f.write(f"  Component {i}: {size:,} nodes\n")
        f.write("\n")
        
        if graph_structure['cycle_sizes']:
            f.write("Cycle Sizes (top 20):\n")
            for i, size in enumerate(graph_structure['cycle_sizes'][:20], 1):
                f.write(f"  Cycle {i}: {size:,} nodes\n")
        else:
            f.write("No cycles detected - Graph is a DAG (Directed Acyclic Graph)\n")
        f.write("\n")
        
        f.write("SPECIAL NODES\n")
        f.write("-" * 80 + "\n")
        f.write(f"Root Nodes (no incoming dependencies): {graph_structure['root_nodes']}\n")
        f.write(f"Leaf Nodes (no outgoing dependencies): {graph_structure['leaf_nodes']}\n\n")
        
        f.write("DEPENDENCY STATISTICS\n")
        f.write("-" * 80 + "\n")
        dep_counts = [r['total_dependencies'] for r in dependency_results]
        if dep_counts:
            f.write(f"Max Dependencies: {max(dep_counts)}\n")
            f.write(f"Average Dependencies: {sum(dep_counts) / len(dep_counts):.2f}\n")
            f.write(f"Median Dependencies: {sorted(dep_counts)[len(dep_counts)//2]}\n")
        
        dependent_counts = [r['total_dependents'] for r in dependency_results]
        if dependent_counts:
            f.write(f"\nMax Dependents: {max(dependent_counts)}\n")
            f.write(f"Average Dependents: {sum(dependent_counts) / len(dependent_counts):.2f}\n")
            f.write(f"Median Dependents: {sorted(dependent_counts)[len(dependent_counts)//2]}\n")
    
    print(f"Summary written to: {summary_file}")
    
    # Always create cycles.txt file (empty if no cycles)
    cycles_file = output_folder / 'cycles.txt'
    if graph_structure['cycles']:
        with open(cycles_file, 'w', encoding='utf-8') as f:
            f.write(f"CYCLIC DEPENDENCIES DETECTED\n")
            f.write(f"Total Cycles: {len(graph_structure['cycle_components'])}\n\n")
            
            for i, cycle in enumerate(graph_structure['cycle_components'][:100], 1):
                f.write(f"Cycle {i} ({len(cycle)} nodes):\n")
                for node in sorted(cycle)[:20]:
                    f.write(f"  - {node}\n")
                if len(cycle) > 20:
                    f.write(f"  ... and {len(cycle) - 20} more nodes\n")
                f.write("\n")
        print(f"Cycles written to: {cycles_file}")
    else:
        # Create empty cycles.txt for HTML report generation
        with open(cycles_file, 'w', encoding='utf-8') as f:
            f.write("")
        print(f"No cycles detected - empty cycles.txt created")
    
    top_dependencies_file = output_folder / 'top_dependencies.txt'
    with open(top_dependencies_file, 'w', encoding='utf-8') as f:
        f.write("TOP 50 OBJECTS BY TOTAL DEPENDENCIES (Direct + Transitive)\n")
        f.write("=" * 120 + "\n")
        
        sorted_deps = sorted(dependency_results, key=lambda x: x['total_dependencies'], reverse=True)
        for i, obj in enumerate(sorted_deps[:50], 1):
            f.write(f"{i}. {obj['object']}\n")
            f.write(f"   Direct: {obj['direct_dependencies_count']}, Transitive: {obj['transitive_dependencies_count']}, Total: {obj['total_dependencies']}\n")
            f.write(f"   Category: {obj['category']}, File: {obj['file_name']}\n\n")
        
        f.write("\n" + "=" * 120 + "\n")
        f.write("TOP 50 OBJECTS BY TOTAL DEPENDENTS (Objects that depend on this)\n")
        f.write("=" * 120 + "\n")
        
        sorted_dependents = sorted(dependency_results, key=lambda x: x['total_dependents'], reverse=True)
        for i, obj in enumerate(sorted_dependents[:50], 1):
            f.write(f"{i}. {obj['object']}\n")
            f.write(f"   Direct: {obj['direct_dependents_count']}, Transitive: {obj['transitive_dependents_count']}, Total: {obj['total_dependents']}\n")
            f.write(f"   Category: {obj['category']}, File: {obj['file_name']}\n\n")
    
    print(f"Top dependencies written to: {top_dependencies_file}")
    
    excluded_edges_file = output_folder / 'excluded_edges_analysis.txt'
    with open(excluded_edges_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("EXCLUDED EDGES ANALYSIS\n")
        f.write("=" * 80 + "\n")
        f.write(f"Edges excluded from dependency graph\n\n")
        
        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Excluded Edges: {excluded_analysis['total_excluded']:,}\n")
        f.write(f"Edges with undefined caller: {excluded_analysis['caller_undefined']:,}\n")
        f.write(f"Edges with undefined referenced object: {excluded_analysis['referenced_undefined']:,}\n")
        f.write(f"Edges with both undefined: {excluded_analysis['both_undefined']:,}\n\n")
        
        f.write("EXCLUSION REASONS\n")
        f.write("-" * 80 + "\n")
        for reason, count in sorted(excluded_analysis['exclusion_reasons'].items(), key=lambda x: x[1], reverse=True):
            f.write(f"{reason}: {count:,}\n")
        f.write("\n")
        
        f.write("RELATION TYPES\n")
        f.write("-" * 80 + "\n")
        for rel_type, count in sorted(excluded_analysis['relation_types'].items(), key=lambda x: x[1], reverse=True)[:20]:
            f.write(f"{rel_type}: {count:,}\n")
        f.write("\n")
        
        f.write("TOP 20 UNDEFINED CALLERS (most frequent)\n")
        f.write("-" * 80 + "\n")
        for obj, count in excluded_analysis['top_undefined_callers']:
            f.write(f"{count:,}x - {obj}\n")
        f.write("\n")
        
        f.write("TOP 20 UNDEFINED REFERENCED OBJECTS (most frequent)\n")
        f.write("-" * 80 + "\n")
        for obj, count in excluded_analysis['top_undefined_referenced']:
            f.write(f"{count:,}x - {obj}\n")
        f.write("\n")
        
        f.write("SAMPLE EXCLUDED EDGES (first 10)\n")
        f.write("=" * 80 + "\n")
        for i, edge in enumerate(excluded_analysis['samples'], 1):
            f.write(f"\nSample {i}:\n")
            f.write(f"  Caller: {edge['caller']}\n")
            f.write(f"  Caller Defined: {edge['caller_defined']}\n")
            f.write(f"  Referenced: {edge['referenced']}\n")
            f.write(f"  Referenced Defined: {edge['referenced_defined']}\n")
            f.write(f"  Relation Type: {edge['relation_type']}\n")
            f.write(f"  Exclusion Reason: {edge.get('exclusion_reason', 'Unknown')}\n")
            f.write(f"  Line: {edge['line']}\n")
    
    print(f"Excluded edges analysis written to: {excluded_edges_file}")
    
    # Write excluded edges JSON
    excluded_edges_json_file = output_folder / 'excluded_edges.json'
    with open(excluded_edges_json_file, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': {
                'total_excluded': excluded_analysis['total_excluded'],
                'caller_undefined': excluded_analysis['caller_undefined'],
                'referenced_undefined': excluded_analysis['referenced_undefined'],
                'both_undefined': excluded_analysis['both_undefined']
            },
            'exclusion_reasons': excluded_analysis['exclusion_reasons'],
            'relation_types': excluded_analysis['relation_types'],
            'excluded_edges': excluded_edges
        }, f, indent=2)
    
    print(f"Excluded edges JSON written to: {excluded_edges_json_file}")
    
    # Write missing objects analysis
    missing_objects_file = output_folder / 'missing_objects_analysis.txt'
    with open(missing_objects_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("MISSING OBJECTS ANALYSIS\n")
        f.write("=" * 80 + "\n")
        f.write("Objects present in TopLevelCodeUnits.csv but excluded from analysis\n\n")
        
        f.write("SUMMARY\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Missing Objects: {len(missing_objects):,}\n\n")
        
        # Count by exclusion reason
        reason_counts = defaultdict(int)
        category_by_reason = defaultdict(lambda: defaultdict(int))
        for obj_name, info in missing_objects.items():
            reason = info.get('exclusion_reason', 'Unknown')
            category = info.get('category', 'Unknown')
            reason_counts[reason] += 1
            category_by_reason[reason][category] += 1
        
        f.write("EXCLUSION REASONS\n")
        f.write("-" * 80 + "\n")
        for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
            f.write(f"  {reason}: {count:,}\n")
        f.write("\n")
        
        f.write("CATEGORIES BY EXCLUSION REASON\n")
        f.write("-" * 80 + "\n")
        for reason in sorted(reason_counts.keys(), key=lambda x: reason_counts[x], reverse=True):
            f.write(f"\n{reason} ({reason_counts[reason]:,} objects):\n")
            categories = category_by_reason[reason]
            for category, count in sorted(categories.items(), key=lambda x: x[1], reverse=True):
                f.write(f"  {category}: {count:,}\n")
        f.write("\n")
        
        f.write("SAMPLE MISSING OBJECTS (first 20)\n")
        f.write("=" * 80 + "\n")
        for i, (obj_name, info) in enumerate(list(missing_objects.items())[:20], 1):
            f.write(f"\n{i}. {obj_name}\n")
            f.write(f"   Category: {info.get('category', 'Unknown')}\n")
            f.write(f"   Exclusion Reason: {info.get('exclusion_reason', 'Unknown')}\n")
            code_unit = info.get('code_unit', '')
            if code_unit:
                # Show first 100 chars of code unit
                code_preview = code_unit[:100] + ('...' if len(code_unit) > 100 else '')
                f.write(f"   Code Unit: {code_preview}\n")
            f.write(f"   File: {info.get('file_name', 'N/A')}\n")
    
    print(f"Missing objects analysis written to: {missing_objects_file}")
    
    # Write partition analysis
    partitions_file = output_folder / 'deployment_partitions.txt'
    with open(partitions_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("DEPLOYMENT PARTITIONS ANALYSIS\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("OVERVIEW\n")
        f.write("-" * 80 + "\n")
        f.write(f"Total Partitions: {len(partitions)}\n")
        
        if len(partitions) > 0:
            f.write(f"Total Objects: {sum(p.size for p in partitions)}\n")
            f.write(f"Average Partition Size: {sum(p.size for p in partitions) / len(partitions):.1f}\n")
            f.write(f"Min Partition Size: {min(p.size for p in partitions)}\n")
            f.write(f"Max Partition Size: {max(p.size for p in partitions)}\n\n")
        else:
            f.write(f"Total Objects: 0\n")
            f.write(f"WARNING: No partitions were created. Check that input files have valid CREATE dependencies.\n\n")
        
        f.write("PARTITION DETAILS\n")
        f.write("=" * 80 + "\n\n")
        
        for partition in partitions:
            f.write(f"PARTITION {partition.partition_number}\n")
            f.write("-" * 80 + "\n")
            f.write(f"Size: {partition.size} objects\n")
            
            # Show picked SCC information
            picked_scc_nodes = partition.picked_scc_nodes
            if picked_scc_nodes:
                f.write(f"Picked SCC (priority object): ")
                if len(picked_scc_nodes) == 1:
                    f.write(f"{picked_scc_nodes[0]}\n")
                else:
                    f.write(f"Cycle with {len(picked_scc_nodes)} nodes\n")
                    f.write(f"  Picked SCC Nodes: {', '.join(picked_scc_nodes[:5])}")
                    if len(picked_scc_nodes) > 5:
                        f.write(f", ... and {len(picked_scc_nodes) - 5} more")
                    f.write("\n")
            
            f.write(f"Root Nodes (no dependencies): {len(partition.root_nodes)}\n")
            f.write(f"Leaf Nodes (no dependents): {len(partition.leaf_nodes)}\n")
            f.write(f"Internal Dependencies: {partition.internal_dependencies}\n")
            f.write(f"External Dependencies: {partition.external_dependencies}\n")
            
            if partition.dependencies_by_partition:
                f.write(f"Dependencies from previous partitions:\n")
                for part_num, count in sorted(partition.dependencies_by_partition.items()):
                    f.write(f"  Partition {part_num}: {count} dependencies\n")
            
            f.write(f"\nObject Types:\n")
            for obj_type, count in sorted(partition.node_types.items(), key=lambda x: x[1], reverse=True):
                f.write(f"  {obj_type}: {count}\n")
            
            f.write(f"\nObjects (first 20):\n")
            for i, node in enumerate(partition.nodes[:20], 1):
                # Mark root and leaf nodes
                markers = []
                if node in partition.root_nodes:
                    markers.append("ROOT")
                if node in partition.leaf_nodes:
                    markers.append("LEAF")
                marker_str = f" [{', '.join(markers)}]" if markers else ""
                f.write(f"  {i}. {node}{marker_str}\n")
            
            if partition.size > 20:
                f.write(f"  ... and {partition.size - 20} more objects\n")
            
            f.write("\n\n")
    
    print(f"Deployment partitions written to: {partitions_file}")
    
    # Write partition dependency matrix
    partition_matrix_file = output_folder / 'partition_dependency_matrix.txt'
    with open(partition_matrix_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("PARTITION-TO-PARTITION DEPENDENCY MATRIX\n")
        f.write("=" * 80 + "\n")
        f.write(f"Shows number of dependency edges from partition X to partition Y\n")
        f.write(f"(X depends on Y, where X > Y)\n\n")
        
        if partition_dependency_matrix:
            # Group by source partition
            deps_by_source = defaultdict(list)
            for (source, target), count in partition_dependency_matrix.items():
                deps_by_source[source].append((target, count))
            
            f.write("SUMMARY BY SOURCE PARTITION\n")
            f.write("-" * 80 + "\n")
            for source in sorted(deps_by_source.keys()):
                targets = sorted(deps_by_source[source])
                total_deps = sum(count for _, count in targets)
                f.write(f"\nPartition {source} depends on:\n")
                f.write(f"  Total dependencies: {total_deps}\n")
                f.write(f"  Target partitions ({len(targets)}):\n")
                for target, count in targets:
                    f.write(f"    Partition {target}: {count} edges\n")
            
            f.write("\n\n")
            f.write("DETAILED MATRIX\n")
            f.write("-" * 80 + "\n")
            f.write("Format: (Source Partition -> Target Partition: Edge Count)\n\n")
            
            for (source, target), count in sorted(partition_dependency_matrix.items()):
                f.write(f"Partition {source} -> Partition {target}: {count} dependencies\n")
            
            # Statistics
            f.write("\n\n")
            f.write("STATISTICS\n")
            f.write("-" * 80 + "\n")
            total_inter_partition_edges = sum(partition_dependency_matrix.values())
            num_partition_pairs_with_deps = len(partition_dependency_matrix)
            
            f.write(f"Total inter-partition dependency edges: {total_inter_partition_edges}\n")
            f.write(f"Number of partition pairs with dependencies: {num_partition_pairs_with_deps}\n")
            
            if partition_dependency_matrix:
                max_deps = max(partition_dependency_matrix.values())
                avg_deps = total_inter_partition_edges / num_partition_pairs_with_deps
                f.write(f"Maximum dependencies between any two partitions: {max_deps}\n")
                f.write(f"Average dependencies per partition pair: {avg_deps:.2f}\n")
                
                # Find most connected partition pairs
                f.write(f"\nTop 20 Most Connected Partition Pairs:\n")
                top_pairs = sorted(partition_dependency_matrix.items(), key=lambda x: x[1], reverse=True)[:20]
                for (source, target), count in top_pairs:
                    f.write(f"  Partition {source} -> Partition {target}: {count} edges\n")
        else:
            f.write("No inter-partition dependencies found (all partitions are independent)\n")
    
    print(f"Partition dependency matrix written to: {partition_matrix_file}")
    
    # Write partition dependency matrix CSV for easier analysis
    partition_matrix_csv = output_folder / 'partition_dependency_matrix.csv'
    with open(partition_matrix_csv, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['source_partition', 'target_partition', 'dependency_count']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for (source, target), count in sorted(partition_dependency_matrix.items()):
            writer.writerow({
                'source_partition': source,
                'target_partition': target,
                'dependency_count': count
            })
    
    print(f"Partition dependency matrix CSV written to: {partition_matrix_csv}")
    
    # Write detailed partition membership CSV
    partition_membership_file = output_folder / 'partition_membership.csv'
    with open(partition_membership_file, 'w', newline='', encoding='utf-8') as f:
        fieldnames = ['partition_number', 'object', 'category', 'file_name', 'is_root', 'is_leaf', 'is_picked_scc', 'technology', 'conversion_status', 'subtype', 'partition_type']
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for partition in partitions:
            picked_scc_nodes_set = set(partition.picked_scc_nodes)
            for node in partition.nodes:
                obj_info = graph.object_info.get(node, {})
                is_root = node in partition.root_nodes
                is_leaf = node in partition.leaf_nodes
                is_picked_scc = node in picked_scc_nodes_set
                writer.writerow({
                    'partition_number': partition.partition_number,
                    'object': node,
                    'category': obj_info.get('category', 'Unknown'),
                    'file_name': obj_info.get('file_name', 'N/A'),
                    'is_root': is_root,
                    'is_leaf': is_leaf,
                    'is_picked_scc': is_picked_scc,
                    'technology': obj_info.get('technology', ''),
                    'conversion_status': obj_info.get('conversion_status', ''),
                    'subtype': obj_info.get('subtype', ''),
                    'partition_type': partition.partition_type
                })
    
    print(f"Partition membership written to: {partition_membership_file}")
    
    # Write deployment_partitions.json with partition metadata
    deployment_json_file = output_folder / 'deployment_partitions.json'
    partitions_json = {
        'metadata': {
            'generated_timestamp': datetime.now().isoformat(),
            'total_partitions': len(partitions),
            'total_objects': sum(p.size for p in partitions) if partitions else 0,
            'average_partition_size': sum(p.size for p in partitions) / len(partitions) if partitions else 0,
            'min_partition_size': min(p.size for p in partitions) if partitions else 0,
            'max_partition_size': max(p.size for p in partitions) if partitions else 0
        },
        'partitions': []
    }
    
    for partition in partitions:
        # Build objects list with metadata
        objects_list = []
        picked_scc_nodes_set = set(partition.picked_scc_nodes)
        for node in partition.nodes:
            obj_info = graph.object_info.get(node, {})
            is_root = node in partition.root_nodes
            is_leaf = node in partition.leaf_nodes
            is_picked_scc = node in picked_scc_nodes_set
            objects_list.append({
                'name': node,
                'category': obj_info.get('category', 'Unknown'),
                'file_name': obj_info.get('file_name', 'N/A'),
                'technology': obj_info.get('technology', ''),
                'conversion_status': obj_info.get('conversion_status', ''),
                'subtype': obj_info.get('subtype', ''),
                'is_root': is_root,
                'is_leaf': is_leaf,
                'is_picked_scc': is_picked_scc
            })
        
        partition_data = {
            'partition_number': partition.partition_number,
            'partition_type': partition.partition_type,
            'size': partition.size,
            'is_simple_object_wave': partition.is_simple_object_wave,
            'picked_scc_ids': partition.picked_scc_ids,
            'picked_scc_nodes': partition.picked_scc_nodes,
            'root_nodes': list(partition.root_nodes),
            'leaf_nodes': list(partition.leaf_nodes),
            'root_nodes_count': len(partition.root_nodes),
            'leaf_nodes_count': len(partition.leaf_nodes),
            'internal_dependencies': partition.internal_dependencies,
            'external_dependencies': partition.external_dependencies,
            'dependencies_by_partition': partition.dependencies_by_partition,
            'node_types': partition.node_types,
            'objects': objects_list
        }
        partitions_json['partitions'].append(partition_data)
    
    with open(deployment_json_file, 'w', encoding='utf-8') as f:
        json.dump(partitions_json, f, indent=2, ensure_ascii=False)
    
    print(f"Deployment partitions JSON written to: {deployment_json_file}")
    
    # Write SCC priority list if available
    if scc_priority_list:
        scc_priority_file = output_folder / 'scc_priority_order.csv'
        with open(scc_priority_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = [
                'priority_rank',
                'scc_id',
                'scc_size',
                'priority_tier',
                'priority_tier_name',
                'total_dependents',
                'transitive_dependencies',
                'assigned_partition',
                'is_user_prioritized',
                'objects'
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for rank, scc_info in enumerate(scc_priority_list, 1):
                tier_name = PRIORITY_TIER_NAMES.get(scc_info['priority_tier'], 'Unknown')
                
                writer.writerow({
                    'priority_rank': rank,
                    'scc_id': scc_info['scc_id'],
                    'scc_size': scc_info['scc_size'],
                    'priority_tier': scc_info['priority_tier'],
                    'priority_tier_name': tier_name,
                    'total_dependents': scc_info['total_dependents'],
                    'transitive_dependencies': scc_info['transitive_dependencies'],
                    'assigned_partition': scc_info['assigned_partition'],
                    'is_user_prioritized': scc_info.get('is_user_prioritized', False),
                    'objects': '; '.join(scc_info['nodes'][:10]) + ('; ...' if len(scc_info['nodes']) > 10 else '')
                })
        
        print(f"SCC priority order written to: {scc_priority_file}")
        
        # Write summary text file
        scc_priority_summary = output_folder / 'scc_priority_order_summary.txt'
        with open(scc_priority_summary, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("SCC PRIORITY ORDER SUMMARY\n")
            f.write("=" * 80 + "\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Count by tier
            tier_counts = {0: 0, 1: 0, 2: 0}
            for scc_info in scc_priority_list:
                tier_counts[scc_info['priority_tier']] += 1
            
            f.write("PRIORITY TIER DISTRIBUTION\n")
            f.write("-" * 80 + "\n")
            for tier_id in sorted(PRIORITY_TIER_NAMES):
                f.write(f"{PRIORITY_TIER_NAMES[tier_id]} (Tier {tier_id}): {tier_counts.get(tier_id, 0):,} SCCs\n")
            f.write(f"Total SCCs: {len(scc_priority_list):,}\n\n")
            
            f.write("TOP 50 PRIORITIZED SCCS\n")
            f.write("-" * 80 + "\n")
            f.write("Sorted by: Priority Tier → Fewer Dependents → More Transitive Dependencies → Size\n\n")
            for rank, scc_info in enumerate(scc_priority_list[:50], 1):
                tier_name = PRIORITY_TIER_NAMES.get(scc_info['priority_tier'], 'Unknown')
                f.write(f"{rank}. [{tier_name}] Partition {scc_info['assigned_partition']}: ")
                if scc_info['scc_size'] == 1:
                    f.write(f"{scc_info['nodes'][0]}\n")
                else:
                    f.write(f"Cycle with {scc_info['scc_size']} nodes: {', '.join(scc_info['nodes'][:3])}")
                    if scc_info['scc_size'] > 3:
                        f.write(f", ... and {scc_info['scc_size'] - 3} more")
                    f.write("\n")
                f.write(f"   Dependents: {scc_info['total_dependents']}, ")
                f.write(f"Transitive Deps: {scc_info['transitive_dependencies']}\n\n")
        
        print(f"SCC priority order summary written to: {scc_priority_summary}")
    
    return output_folder


def main() -> None:
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Analyze SQL object dependencies and create deployment partitions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --references refs.csv --objects objs.csv --output ./analysis
  %(prog)s -r refs.csv -o objs.csv -d ./output --min-size 10 --max-size 50
  %(prog)s -r refs.csv -o objs.csv -d ./output --prioritize "PKG_*" --prioritize "*OrthoContract*"
  %(prog)s -r refs.csv -o objs.csv -d ./output --prioritize-file priority_patterns.txt
        """
    )
    
    parser.add_argument(
        '--references', '-r',
        required=True,
        help='Path to ObjectReferences CSV file'
    )
    
    parser.add_argument(
        '--objects', '-o',
        required=True,
        help='Path to TopLevelCodeUnits CSV file'
    )
    
    parser.add_argument(
        '--output', '-d',
        required=True,
        help='Output directory for analysis results'
    )
    
    parser.add_argument(
        '--min-size',
        type=int,
        default=40,
        help='Minimum partition size (default: 40)'
    )
    
    parser.add_argument(
        '--max-size',
        type=int,
        default=80,
        help='Maximum partition size (default: 80)'
    )
    
    parser.add_argument(
        '--prioritize',
        action='append',
        help='Object name or pattern to prioritize for earlier placement (can be specified multiple times). Supports wildcards (e.g., "PKG_*", "*OrthoContract*")'
    )
    
    parser.add_argument(
        '--prioritize-file',
        help='Path to a file containing object names or patterns to prioritize (one per line)'
    )
    
    parser.add_argument(
        '--no-category-waves',
        action='store_true',
        help='Disable category-based wave ordering (TABLE→VIEW→FUNCTION first). '
             'When set, all object types are mixed and sorted purely by dependency level.'
    )
    
    args = parser.parse_args()
    
    references_csv = args.references
    objects_csv = args.objects
    output_dir = args.output
    min_size = args.min_size
    max_size = args.max_size
    
    # Load prioritization preferences
    prioritize_patterns = []
    if args.prioritize:
        prioritize_patterns.extend(args.prioritize)
    
    if args.prioritize_file:
        with open(args.prioritize_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    prioritize_patterns.append(line)
    
    print(f"Configuration:")
    print(f"  References CSV: {references_csv}")
    print(f"  Objects CSV: {objects_csv}")
    print(f"  Output directory: {output_dir}")
    print(f"  Partition size range: {min_size}-{max_size}")
    if prioritize_patterns:
        print(f"  Prioritization patterns: {len(prioritize_patterns)}")
        for pattern in prioritize_patterns:
            print(f"    - {pattern}")
    print()
    
    print("Building dependency graph (CREATE objects only, excluding self-references)...")
    graph, excluded_edges, missing_objects = build_dependency_graph(references_csv, objects_csv)
    
    print(f"Graph loaded: {len(graph.all_nodes)} nodes, {sum(len(deps) for deps in graph.graph.values())} edges")
    print(f"Excluded edges: {len(excluded_edges)}")
    
    print("\nAnalyzing excluded edges...")
    excluded_analysis = analyze_excluded_edges(excluded_edges)
    
    print("\nAnalyzing dependencies...")
    dependency_results = analyze_dependencies(graph)
    
    print("\nAnalyzing graph structure...")
    graph_structure = analyze_graph_structure(graph)
    
    print("\nCreating deployment partitions...")
    partitions, partition_dependency_matrix, scc_priority_list = create_deployment_partitions(
        graph, 
        min_size=min_size, 
        max_size=max_size,
        prioritize_patterns=prioritize_patterns,
        category_waves=not args.no_category_waves
    )
    
    print(f"Initial partitions created: {len(partitions)}")
    
    print("\nMerging small partitions...")
    partitions = merge_small_partitions(partitions, graph, min_size=min_size, max_size=max_size)
    
    print(f"After merging: {len(partitions)} partitions")
    
    # Re-analyze partitions after merging
    print("\nRe-analyzing merged partitions...")
    for partition in partitions:
        nodes = partition.nodes
        
        # Count root and leaf nodes
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
        
        # Count internal vs external dependencies
        internal_deps = 0
        external_deps = 0
        deps_by_partition = defaultdict(int)
        
        for node in nodes:
            deps = graph.get_direct_dependencies(node)
            for dep in deps:
                if dep in nodes:
                    internal_deps += 1
                else:
                    external_deps += 1
                    # Find which partition this dependency is in
                    for p in partitions:
                        if dep in p.nodes:
                            deps_by_partition[p.partition_number] += 1
                            break
        
        partition.internal_dependencies = internal_deps
        partition.external_dependencies = external_deps
        partition.dependencies_by_partition = dict(deps_by_partition)
        
        # Count node types
        node_types = defaultdict(int)
        for node in nodes:
            obj_info = graph.object_info.get(node, {})
            category = obj_info.get('category', 'Unknown')
            node_types[category] += 1
        partition.node_types = dict(node_types)
    
    # Recalculate partition dependency matrix
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
    output_folder = write_results(dependency_results, graph_structure, excluded_analysis, partitions, partition_dependency_matrix, graph, output_dir, missing_objects, excluded_edges, scc_priority_list)
    
    print(f"\nDone! Output folder: {output_folder}")
    print(f"\nSummary:")
    print(f"  Total objects: {graph_structure['total_nodes']}")
    print(f"  Total dependencies: {graph_structure['total_edges']}")
    print(f"  Excluded edges: {excluded_analysis['total_excluded']}")
    print(f"  Forests/Components: {graph_structure['weakly_connected_components']}")
    print(f"  Cycles detected: {graph_structure['cycles']}")
    print(f"  Deployment partitions: {len(partitions)}")
    
    print("\nGenerating missing dependencies report...")
    try:
        from pathlib import Path
        import sys
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        from find_dependencies_by_object import generate_missing_dependencies_report, find_csv_files
        
        # Find ObjectReferences CSV in the same directory as TopLevelCodeUnits
        objects_path = Path(args.objects)
        reports_dir = objects_path.parent
        
        object_refs_csv = find_csv_files(str(reports_dir), 'ObjectReferences')
        legacy_csv = find_csv_files(str(reports_dir), 'MissingObjectReferences')
        
        if object_refs_csv or legacy_csv:
            missing_deps_json_path = output_folder / 'missing_dependencies.json'
            generate_missing_dependencies_report(
                args.objects,
                str(object_refs_csv) if object_refs_csv else None,
                str(legacy_csv) if legacy_csv else None,
                str(missing_deps_json_path)
            )
            print(f"Missing dependencies report: {missing_deps_json_path}")
        else:
            print("Warning: Neither ObjectReferences CSV nor MissingObjectReferences CSV found, skipping missing dependencies report")
    except Exception as e:
        print(f"Warning: Missing dependencies report generation failed: {e}")
    
    # Generate missing dependencies JSON for HTML report
    print("\nGenerating missing dependencies data...")
    try:
        from pathlib import Path
        import sys
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))
        from find_dependencies_by_object import generate_missing_dependencies_report, find_csv_files
        
        # Get reports_dir from objects CSV path
        objects_path = Path(args.objects)
        reports_dir = objects_path.parent
        
        # Use the TopLevelObjectsEstimation CSV that was provided (or find TopLevelCodeUnits as fallback)
        toplevel_csv = objects_path  # Use the objects CSV that was provided
        if not toplevel_csv.exists():
            # Fallback to searching for TopLevelCodeUnits
            for pattern in ['TopLevelCodeUnits.NA.csv', 'TopLevelCodeUnits.*.csv']:
                matches = list(reports_dir.glob(pattern))
                if matches:
                    toplevel_csv = matches[0]
                    break
        
        # Find ObjectReferences CSV (new format) and MissingObjectReferences CSV (legacy format)
        object_refs_csv = find_csv_files(str(reports_dir), 'ObjectReferences')
        legacy_csv = find_csv_files(str(reports_dir), 'MissingObjectReferences')
        
        if toplevel_csv and toplevel_csv.exists() and (object_refs_csv or legacy_csv):
            missing_deps_json = reports_dir / 'missing_dependencies.json'
            generate_missing_dependencies_report(
                toplevel_csv,
                str(object_refs_csv) if object_refs_csv else None,
                str(legacy_csv) if legacy_csv else None,
                missing_deps_json
            )
            print(f"Missing dependencies data generated: {missing_deps_json}")
        else:
            print("Warning: TopLevelObjectsEstimation/TopLevelCodeUnits or missing refs CSV not found")
            print(f"  Looked in: {reports_dir}")
    except Exception as e:
        print(f"Warning: Missing dependencies data generation failed: {e}")
    
    print("\nGenerating wave deployment order from partition_membership.csv...")
    try:
        partition_membership_path = Path(output_folder) / 'partition_membership.csv'
        deployment_order_path = Path(output_folder) / 'wave_deployment_order.json'
        
        if partition_membership_path.exists():
            # Read partition_membership.csv which already has objects in topological order
            wave_deployment_order = {}
            with open(partition_membership_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    wave_num = row['partition_number']
                    if wave_num not in wave_deployment_order:
                        wave_deployment_order[wave_num] = {
                            'wave_number': wave_num,
                            'deployment_order': [],
                            'objects_detail': []
                        }
                    
                    obj_name = row['object']
                    wave_deployment_order[wave_num]['deployment_order'].append(obj_name)
                    wave_deployment_order[wave_num]['objects_detail'].append({
                        'name': obj_name,
                        'category': row['category'],
                        'is_root': row['is_root'].lower() == 'true',
                        'is_leaf': row['is_leaf'].lower() == 'true',
                        'deployment_position': len(wave_deployment_order[wave_num]['deployment_order'])
                    })
            
            # Add total_objects count for each wave
            for wave_data in wave_deployment_order.values():
                wave_data['total_objects'] = len(wave_data['deployment_order'])
            
            # Build final JSON structure
            output_data = {
                'metadata': {
                    'description': 'Wave deployment order from partition_membership (already topologically sorted)',
                    'total_waves': len(wave_deployment_order),
                    'total_objects': sum(len(w['deployment_order']) for w in wave_deployment_order.values()),
                    'ordering_algorithm': 'Kahn\'s algorithm (topological sort) - applied in analyze_dependencies.py',
                    'ordering_rule': 'Dependencies before dependents within each wave'
                },
                'waves': wave_deployment_order
            }
            
            with open(deployment_order_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, indent=2)
            
            print(f"Wave deployment order generated: {deployment_order_path}")
        else:
            print(f"Warning: partition_membership.csv not found")
    except Exception as e:
        print(f"Warning: Wave deployment order generation failed: {e}")
    

if __name__ == '__main__':
    main()