# Copyright 2026 Snowflake Inc.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Object Relocation Tool for Wave Deployment - Labeled Reconstruction Approach

This module provides functionality to relocate objects between deployment waves
by REBUILDING the wave assignments from scratch with labeled constraints.

KEY APPROACH:
-------------
Instead of patching existing wave assignments, this tool:
1. Loads the dependency graph from the existing analysis output
2. Accepts user labels (objects + target waves)
3. Rebuilds ALL wave assignments using the wave construction algorithm
4. The topological sort naturally handles transitive dependencies
5. Generates new analysis reports

This ensures:
- All dependencies are correctly ordered (deps before dependents)
- Transitive dependencies are handled automatically
- No manual cascade logic needed - the algorithm does it

USAGE:
    # Relocate single object to specific wave (rebuilds all waves)
    python relocate_object.py relocate <analysis_dir> --object "ObjectName" --to-wave 3
    
    # Relocate multiple objects
    python relocate_object.py relocate <analysis_dir> --object "Obj1" --to-wave 3 --object "Obj2" --to-wave 5
    
    # Preview changes without applying (dry-run)
    python relocate_object.py relocate <analysis_dir> --object "ObjectName" --to-wave 2 --dry-run
    
    # Show object info and dependencies
    python relocate_object.py info <analysis_dir> --object "ObjectName"
    
    # Validate current wave assignments
    python relocate_object.py validate <analysis_dir>

ALGORITHM:
---------
1. Load the dependency graph from existing analysis (graph_analysis.json, deployment_partitions.json)
2. Load object info from partition_membership.csv
3. Apply user-specified labels: "Object X must be in wave <= N"
4. Rebuild waves using topological sort with constraints:
   a. Dependencies of labeled objects inherit the same or earlier constraint
   b. Create waves respecting: dependencies first, then labeled objects, then dependents
5. Output new partition_membership.csv and regenerate reports

DEPENDENCY RULES:
- An object can only be deployed AFTER all its dependencies are deployed
- When user labels object X for wave N:
  - All dependencies of X must be in wave <= N
  - The algorithm naturally pulls dependencies earlier
"""

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Set, List, Tuple, Optional, Any


@dataclass
class ObjectInfo:
    """Information about a single object in the deployment"""
    name: str
    wave: int
    category: str
    file_name: str
    is_root: bool
    is_leaf: bool
    technology: str = ""
    conversion_status: str = ""
    subtype: str = ""
    partition_type: str = "regular"


@dataclass
class WaveConstraint:
    """A constraint specifying that an object must be in a specific wave"""
    object_name: str
    target_wave: int
    original_wave: int


class DependencyGraph:
    """Dependency graph built from existing analysis output"""
    
    def __init__(self):
        self.dependencies: Dict[str, Set[str]] = defaultdict(set)  # object -> dependencies
        self.dependents: Dict[str, Set[str]] = defaultdict(set)    # object -> dependents
        self.all_objects: Set[str] = set()
        self.object_info: Dict[str, Dict[str, Any]] = {}
    
    def add_edge(self, obj: str, depends_on: str) -> None:
        """Add dependency edge: obj depends on depends_on"""
        if obj != depends_on:
            self.dependencies[obj].add(depends_on)
            self.dependents[depends_on].add(obj)
        self.all_objects.add(obj)
        self.all_objects.add(depends_on)
    
    def add_object(self, obj: str, info: Dict[str, Any] = None) -> None:
        """Add an object to the graph"""
        self.all_objects.add(obj)
        if info:
            self.object_info[obj] = info
    
    def get_dependencies(self, obj: str) -> Set[str]:
        """Get direct dependencies of an object"""
        return self.dependencies.get(obj, set())
    
    def get_dependents(self, obj: str) -> Set[str]:
        """Get direct dependents of an object"""
        return self.dependents.get(obj, set())
    
    def get_transitive_dependencies(self, obj: str) -> Set[str]:
        """Get all transitive dependencies using BFS"""
        visited = set()
        queue = deque([obj])
        visited.add(obj)
        
        while queue:
            current = queue.popleft()
            for dep in self.dependencies.get(current, set()):
                if dep not in visited:
                    visited.add(dep)
                    queue.append(dep)
        
        visited.discard(obj)
        return visited
    
    def get_transitive_dependents(self, obj: str) -> Set[str]:
        """Get all transitive dependents using BFS"""
        visited = set()
        queue = deque([obj])
        visited.add(obj)
        
        while queue:
            current = queue.popleft()
            for dependent in self.dependents.get(current, set()):
                if dependent not in visited:
                    visited.add(dependent)
                    queue.append(dependent)
        
        visited.discard(obj)
        return visited


class LabeledWaveBuilder:
    """
    Builds wave assignments with labeled constraints.
    
    This approach PRESERVES the original wave structure and only moves
    objects that NEED to move to satisfy the constraints.
    
    When moving an object to an earlier wave:
    - All its dependencies must also be in that wave or earlier
    - The algorithm pulls dependencies earlier as needed
    - Other objects stay in their original waves
    """
    
    def __init__(self, graph: DependencyGraph, original_waves: Dict[str, int]):
        self.graph = graph
        self.original_waves = original_waves
        self.labels: Dict[str, int] = {}  # object -> target_wave constraint
    
    def add_label(self, obj_name: str, target_wave: int) -> None:
        """
        Add a constraint that object must be in wave <= target_wave.
        """
        self.labels[obj_name] = target_wave
    
    def build_waves(self, min_size: int = 40, max_size: int = 80) -> Dict[str, int]:
        """
        Build wave assignments respecting labels while preserving original structure.
        
        Algorithm:
        1. Start with original wave assignments
        2. For each labeled object, if it needs to move earlier:
           a. Move it to target wave
           b. Recursively pull all its dependencies to target wave or earlier
        3. Return the modified assignments
        
        Returns:
            Dict mapping object names to wave numbers
        """
        # Start with original assignments
        new_assignments = dict(self.original_waves)
        
        # Process each labeled object
        for obj_name, target_wave in self.labels.items():
            current_wave = new_assignments.get(obj_name)
            if current_wave is None:
                continue
            
            if target_wave < current_wave:
                # Moving earlier - need to pull dependencies
                self._move_earlier_with_deps(obj_name, target_wave, new_assignments)
            elif target_wave > current_wave:
                # Moving later - need to push dependents
                self._move_later_with_dependents(obj_name, target_wave, new_assignments)
        
        # Compact waves to remove gaps
        return self._compact_waves(new_assignments)
    
    def _move_earlier_with_deps(self, obj_name: str, target_wave: int, 
                                 assignments: Dict[str, int]) -> None:
        """
        Move an object to an earlier wave, pulling all its dependencies along.
        
        Uses BFS to ensure all transitive dependencies are moved.
        """
        # Queue of objects to process: (object_name, max_allowed_wave)
        queue = deque([(obj_name, target_wave)])
        processed = set()
        
        while queue:
            current_obj, max_wave = queue.popleft()
            
            if current_obj in processed:
                continue
            processed.add(current_obj)
            
            current_wave = assignments.get(current_obj)
            if current_wave is None:
                continue
            
            # Move this object if needed
            if current_wave > max_wave:
                assignments[current_obj] = max_wave
            
            # Get the wave this object ended up in
            final_wave = assignments[current_obj]
            
            # All dependencies must be in an earlier or same wave
            for dep in self.graph.get_dependencies(current_obj):
                dep_wave = assignments.get(dep)
                if dep_wave is not None and dep_wave > final_wave:
                    # Dependency is in a later wave - needs to move
                    queue.append((dep, final_wave))
    
    def _move_later_with_dependents(self, obj_name: str, target_wave: int,
                                     assignments: Dict[str, int]) -> None:
        """
        Move an object to a later wave, pushing all its dependents along.
        
        Uses BFS to ensure all transitive dependents are moved.
        """
        queue = deque([(obj_name, target_wave)])
        processed = set()
        
        while queue:
            current_obj, min_wave = queue.popleft()
            
            if current_obj in processed:
                continue
            processed.add(current_obj)
            
            current_wave = assignments.get(current_obj)
            if current_wave is None:
                continue
            
            # Move this object if needed
            if current_wave < min_wave:
                assignments[current_obj] = min_wave
            
            # Get the wave this object ended up in
            final_wave = assignments[current_obj]
            
            # All dependents must be in a later or same wave
            for dependent in self.graph.get_dependents(current_obj):
                dep_wave = assignments.get(dependent)
                if dep_wave is not None and dep_wave < final_wave:
                    # Dependent is in an earlier wave - needs to move
                    queue.append((dependent, final_wave))
    
    def _compact_waves(self, assignments: Dict[str, int]) -> Dict[str, int]:
        """
        Compact waves to remove any gaps in wave numbering.
        
        This renumbers waves consecutively while preserving relative order.
        """
        if not assignments:
            return assignments
        
        # Get all unique waves and sort them
        unique_waves = sorted(set(assignments.values()))
        
        # Create mapping from old wave to new wave
        wave_mapping = {old_wave: new_wave + 1 for new_wave, old_wave in enumerate(unique_waves)}
        
        # Apply mapping
        return {obj: wave_mapping[wave] for obj, wave in assignments.items()}


class WaveRelocator:
    """
    Main class for relocating objects using labeled reconstruction.
    """
    
    def __init__(self, analysis_dir: str, reports_dir: str = None):
        self.analysis_dir = Path(analysis_dir)
        self.reports_dir = Path(reports_dir) if reports_dir else None
        self.graph = DependencyGraph()
        self.objects: Dict[str, ObjectInfo] = {}
        self.original_waves: Dict[str, int] = {}
        self.wave_count = 0
        self._load_data()
    
    def _load_data(self) -> None:
        """Load dependency graph and object info from analysis output"""
        # Load partition membership (objects and their current waves)
        membership_file = self.analysis_dir / 'partition_membership.csv'
        if not membership_file.exists():
            raise FileNotFoundError(f"partition_membership.csv not found in {self.analysis_dir}")
        
        print(f"Loading objects from: {membership_file}")
        
        with open(membership_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                obj_name = row['object']
                wave = int(row['partition_number'])
                self.wave_count = max(self.wave_count, wave)
                
                self.objects[obj_name] = ObjectInfo(
                    name=obj_name,
                    wave=wave,
                    category=row.get('category', 'Unknown'),
                    file_name=row.get('file_name', 'N/A'),
                    is_root=row.get('is_root', 'False').lower() == 'true',
                    is_leaf=row.get('is_leaf', 'False').lower() == 'true',
                    technology=row.get('technology', ''),
                    conversion_status=row.get('conversion_status', ''),
                    subtype=row.get('subtype', ''),
                    partition_type=row.get('partition_type', 'regular')
                )
                self.original_waves[obj_name] = wave
                self.graph.add_object(obj_name, {
                    'category': row.get('category', 'Unknown'),
                    'file_name': row.get('file_name', 'N/A'),
                })
        
        print(f"Loaded {len(self.objects)} objects across {self.wave_count} waves")
        
        # Load dependencies - try multiple sources
        self._load_dependencies()
    
    def _load_dependencies(self) -> None:
        """Load dependency edges from available sources"""
        deps_loaded = False
        
        # Try 1: Load from graph_analysis.json if it has edge data
        graph_file = self.analysis_dir / 'graph_analysis.json'
        if graph_file.exists():
            try:
                with open(graph_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Check if this file has dependency info we can use
            except:
                pass
        
        # Try 2: Load from deployment_partitions.json
        partitions_file = self.analysis_dir / 'deployment_partitions.json'
        if partitions_file.exists() and not deps_loaded:
            try:
                with open(partitions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except:
                pass
        
        # Try 3: Load from ObjectReferences CSV (most reliable)
        refs_file = self._find_object_references()
        if refs_file:
            print(f"Loading dependencies from: {refs_file}")
            self._load_from_object_references(refs_file)
            deps_loaded = True
        
        if not deps_loaded:
            print("Warning: Could not load full dependency data. Relocation may be incomplete.")
    
    def _find_object_references(self) -> Optional[Path]:
        """Find ObjectReferences CSV file"""
        search_paths = []
        
        # If reports_dir was provided, prioritize it
        if self.reports_dir and self.reports_dir.exists():
            search_paths.append(self.reports_dir / 'ObjectReferences.NA.csv')
            # Also check for timestamped versions
            matches = list(self.reports_dir.glob('ObjectReferences.*.csv'))
            search_paths.extend(matches)
        
        # Standard search paths
        search_paths.extend([
            self.analysis_dir / 'ObjectReferences.NA.csv',
            self.analysis_dir.parent / 'ObjectReferences.NA.csv',
            self.analysis_dir.parent.parent / 'ObjectReferences.NA.csv',
        ])
        
        # Also try glob patterns
        for pattern in ['ObjectReferences.*.csv']:
            for search_dir in [self.analysis_dir, self.analysis_dir.parent, self.analysis_dir.parent.parent]:
                matches = list(search_dir.glob(pattern))
                search_paths.extend(matches)
        
        for path in search_paths:
            if path and path.exists():
                return path
        
        return None
    
    def _load_from_object_references(self, refs_file: Path) -> None:
        """Load dependencies from ObjectReferences CSV"""
        edge_count = 0
        with open(refs_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                caller = row.get('Caller_CodeUnit_FullName', '').strip()
                referenced = row.get('Referenced_Element_FullName', '').strip()
                relation_type = row.get('Relation_Type', '').strip()
                
                # Skip FOREIGN KEY relationships (same as analyze_dependencies.py)
                if relation_type == 'FOREIGN KEY':
                    continue
                
                # Only add edges for objects we know about
                if caller in self.objects and referenced in self.objects:
                    if caller != referenced:
                        self.graph.add_edge(caller, referenced)
                        edge_count += 1
        
        print(f"Loaded {edge_count} dependency edges")
    
    def get_object_info(self, obj_name: str) -> Optional[ObjectInfo]:
        """Get information about a specific object"""
        return self.objects.get(obj_name)
    
    def find_object(self, search_term: str) -> List[str]:
        """Find objects matching a search term"""
        search_lower = search_term.lower()
        return sorted([
            name for name in self.objects.keys()
            if search_lower in name.lower()
        ])
    
    def show_object_dependencies(self, obj_name: str) -> Dict[str, Any]:
        """Show dependencies and dependents of an object"""
        if obj_name not in self.objects:
            return {'error': f"Object '{obj_name}' not found"}
        
        obj = self.objects[obj_name]
        direct_deps = self.graph.get_dependencies(obj_name)
        direct_dependents = self.graph.get_dependents(obj_name)
        trans_deps = self.graph.get_transitive_dependencies(obj_name)
        trans_dependents = self.graph.get_transitive_dependents(obj_name)
        
        # Get wave info for dependencies
        deps_info = []
        for dep in sorted(direct_deps):
            dep_obj = self.objects.get(dep)
            if dep_obj:
                deps_info.append({
                    'name': dep,
                    'wave': dep_obj.wave,
                    'category': dep_obj.category
                })
        
        dependents_info = []
        for dependent in sorted(direct_dependents):
            dep_obj = self.objects.get(dependent)
            if dep_obj:
                dependents_info.append({
                    'name': dependent,
                    'wave': dep_obj.wave,
                    'category': dep_obj.category
                })
        
        return {
            'object': obj_name,
            'current_wave': obj.wave,
            'category': obj.category,
            'is_root': obj.is_root,
            'is_leaf': obj.is_leaf,
            'direct_dependencies': deps_info,
            'direct_dependents': dependents_info,
            'transitive_dependency_count': len(trans_deps),
            'transitive_dependent_count': len(trans_dependents)
        }
    
    def relocate(self, relocations: List[Tuple[str, int]], 
                 min_size: int = 40, max_size: int = 80,
                 dry_run: bool = False) -> Dict[str, Any]:
        """
        Relocate objects by rebuilding waves with labeled constraints.
        
        Args:
            relocations: List of (object_name, target_wave) tuples
            min_size: Minimum wave size
            max_size: Maximum wave size
            dry_run: If True, don't write changes
            
        Returns:
            Summary of relocation results
        """
        # Validate relocations
        errors = []
        for obj_name, target_wave in relocations:
            if obj_name not in self.objects:
                errors.append(f"Object '{obj_name}' not found")
            if target_wave < 1:
                errors.append(f"Target wave must be >= 1, got {target_wave}")
        
        if errors:
            return {'success': False, 'errors': errors}
        
        # Create wave builder with labeled constraints
        builder = LabeledWaveBuilder(self.graph, self.original_waves)
        
        # Add user-specified labels
        for obj_name, target_wave in relocations:
            builder.add_label(obj_name, target_wave)
            print(f"Label: {obj_name} -> wave <= {target_wave}")
        
        # Build new wave assignments
        print("\nRebuilding waves with constraints...")
        new_assignments = builder.build_waves(min_size, max_size)
        
        # Calculate changes
        changes = []
        for obj_name, new_wave in new_assignments.items():
            old_wave = self.original_waves.get(obj_name, 0)
            if old_wave != new_wave:
                changes.append({
                    'object': obj_name,
                    'old_wave': old_wave,
                    'new_wave': new_wave,
                    'category': self.objects[obj_name].category if obj_name in self.objects else 'Unknown'
                })
        
        # Sort changes by object name for readability
        changes.sort(key=lambda x: x['object'])
        
        result = {
            'success': True,
            'total_objects': len(new_assignments),
            'total_changes': len(changes),
            'relocations_requested': len(relocations),
            'changes': changes,
            'dry_run': dry_run
        }
        
        # Show summary of changes
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Relocation Summary:")
        print(f"  Total objects: {len(new_assignments)}")
        print(f"  Total changes: {len(changes)}")
        
        # Group changes by direction
        moved_earlier = [c for c in changes if c['new_wave'] < c['old_wave']]
        moved_later = [c for c in changes if c['new_wave'] > c['old_wave']]
        
        if moved_earlier:
            print(f"\n  Objects moved EARLIER ({len(moved_earlier)}):")
            for c in moved_earlier[:20]:  # Show first 20
                print(f"    {c['object']}: wave {c['old_wave']} -> {c['new_wave']}")
            if len(moved_earlier) > 20:
                print(f"    ... and {len(moved_earlier) - 20} more")
        
        if moved_later:
            print(f"\n  Objects moved LATER ({len(moved_later)}):")
            for c in moved_later[:20]:
                print(f"    {c['object']}: wave {c['old_wave']} -> {c['new_wave']}")
            if len(moved_later) > 20:
                print(f"    ... and {len(moved_later) - 20} more")
        
        if not dry_run:
            # Apply changes
            self._apply_changes(new_assignments)
            result['output_files'] = self._write_output()
        
        return result
    
    def _apply_changes(self, new_assignments: Dict[str, int]) -> None:
        """Apply new wave assignments to internal state"""
        for obj_name, new_wave in new_assignments.items():
            if obj_name in self.objects:
                self.objects[obj_name].wave = new_wave
        
        # Update wave count
        self.wave_count = max(new_assignments.values()) if new_assignments else 0
    
    def _write_output(self) -> List[str]:
        """Write updated partition_membership.csv and related files"""
        output_files = []
        
        # Backup original
        membership_file = self.analysis_dir / 'partition_membership.csv'
        backup_file = self.analysis_dir / f'partition_membership.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        if membership_file.exists():
            shutil.copy(membership_file, backup_file)
            output_files.append(str(backup_file))
            print(f"Backed up original to: {backup_file}")
        
        # Write new partition_membership.csv
        self._write_partition_membership(membership_file)
        output_files.append(str(membership_file))
        print(f"Updated: {membership_file}")
        
        # Write relocation log
        log_file = self.analysis_dir / f'relocation_log.{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        self._write_relocation_log(log_file)
        output_files.append(str(log_file))
        print(f"Relocation log: {log_file}")
        
        # Update wave_deployment_order.json
        deployment_order_file = self.analysis_dir / 'wave_deployment_order.json'
        self._write_deployment_order(deployment_order_file)
        output_files.append(str(deployment_order_file))
        print(f"Updated: {deployment_order_file}")
        
        return output_files
    
    def _write_partition_membership(self, output_file: Path) -> None:
        """Write partition_membership.csv with new wave assignments"""
        # Group objects by wave and sort within each wave
        wave_objects: Dict[int, List[str]] = defaultdict(list)
        for obj_name, obj_info in self.objects.items():
            wave_objects[obj_info.wave].append(obj_name)
        
        # Topologically sort objects within each wave
        for wave in wave_objects:
            objects = wave_objects[wave]
            wave_objects[wave] = self._topological_sort_objects(objects)
        
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['object', 'partition_number', 'category', 'file_name', 
                         'is_root', 'is_leaf', 'technology', 'conversion_status',
                         'subtype', 'partition_type']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for wave in sorted(wave_objects.keys()):
                for obj_name in wave_objects[wave]:
                    obj = self.objects[obj_name]
                    writer.writerow({
                        'object': obj_name,
                        'partition_number': obj.wave,
                        'category': obj.category,
                        'file_name': obj.file_name,
                        'is_root': str(obj.is_root),
                        'is_leaf': str(obj.is_leaf),
                        'technology': obj.technology,
                        'conversion_status': obj.conversion_status,
                        'subtype': obj.subtype,
                        'partition_type': obj.partition_type
                    })
    
    def _topological_sort_objects(self, objects: List[str]) -> List[str]:
        """Sort objects topologically (dependencies first)"""
        if not objects:
            return []
        
        obj_set = set(objects)
        in_degree = {obj: 0 for obj in objects}
        
        for obj in objects:
            for dep in self.graph.get_dependencies(obj):
                if dep in obj_set:
                    in_degree[obj] += 1
        
        queue = deque(sorted([obj for obj in objects if in_degree[obj] == 0]))
        result = []
        
        while queue:
            current = queue.popleft()
            result.append(current)
            
            for dependent in sorted(self.graph.get_dependents(current)):
                if dependent in obj_set and dependent in in_degree:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        queue.append(dependent)
            queue = deque(sorted(queue))
        
        # Add any remaining (cycles)
        remaining = [obj for obj in objects if obj not in result]
        result.extend(sorted(remaining))
        
        return result
    
    def _write_relocation_log(self, output_file: Path) -> None:
        """Write relocation log JSON"""
        log = {
            'timestamp': datetime.now().isoformat(),
            'analysis_dir': str(self.analysis_dir),
            'total_objects': len(self.objects),
            'wave_count': self.wave_count,
            'objects': {
                name: {
                    'wave': obj.wave,
                    'category': obj.category,
                    'original_wave': self.original_waves.get(name, obj.wave)
                }
                for name, obj in self.objects.items()
            }
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=2)
    
    def _write_deployment_order(self, output_file: Path) -> None:
        """Write wave_deployment_order.json with new assignments"""
        wave_data = {}
        
        for wave in range(1, self.wave_count + 1):
            wave_objects = [
                name for name, obj in self.objects.items()
                if obj.wave == wave
            ]
            wave_objects = self._topological_sort_objects(wave_objects)
            
            wave_data[str(wave)] = {
                'wave_number': str(wave),
                'total_objects': len(wave_objects),
                'deployment_order': wave_objects,
                'objects_detail': [
                    {
                        'name': name,
                        'category': self.objects[name].category,
                        'is_root': self.objects[name].is_root,
                        'is_leaf': self.objects[name].is_leaf,
                        'deployment_position': i + 1
                    }
                    for i, name in enumerate(wave_objects)
                ]
            }
        
        output_data = {
            'metadata': {
                'description': 'Wave deployment order after relocation',
                'total_waves': self.wave_count,
                'total_objects': len(self.objects),
                'generated_at': datetime.now().isoformat()
            },
            'waves': wave_data
        }
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
    
    def validate_assignments(self) -> List[str]:
        """Validate that all wave assignments respect dependencies"""
        errors = []
        
        for obj_name, obj_info in self.objects.items():
            obj_wave = obj_info.wave
            deps = self.graph.get_dependencies(obj_name)
            
            for dep in deps:
                dep_info = self.objects.get(dep)
                if dep_info:
                    if dep_info.wave > obj_wave:
                        errors.append(
                            f"VIOLATION: {obj_name} (wave {obj_wave}) depends on "
                            f"{dep} (wave {dep_info.wave}) - dependency in later wave!"
                        )
        
        return errors


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Relocate objects between deployment waves using labeled reconstruction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s relocate ./analysis --object "MyProc" --to-wave 5
  %(prog)s relocate ./analysis --object "Obj1" --to-wave 3 --object "Obj2" --to-wave 5
  %(prog)s relocate ./analysis --object "MyProc" --to-wave 5 --dry-run
  %(prog)s info ./analysis --object "MyProc"
  %(prog)s validate ./analysis
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Relocate command
    relocate_parser = subparsers.add_parser('relocate', help='Relocate objects to different waves')
    relocate_parser.add_argument('analysis_dir', help='Path to analysis output directory')
    relocate_parser.add_argument('--reports-dir', '-r', help='Path to Reports directory containing ObjectReferences.csv')
    relocate_parser.add_argument('--object', '-o', action='append', dest='objects',
                                 help='Object name to relocate (can be specified multiple times)')
    relocate_parser.add_argument('--to-wave', '-w', action='append', dest='waves', type=int,
                                 help='Target wave for each object (must match --object count)')
    relocate_parser.add_argument('--dry-run', action='store_true',
                                 help='Preview changes without applying')
    relocate_parser.add_argument('--min-size', type=int, default=40,
                                 help='Minimum wave size (default: 40)')
    relocate_parser.add_argument('--max-size', type=int, default=80,
                                 help='Maximum wave size (default: 80)')
    
    # Info command
    info_parser = subparsers.add_parser('info', help='Show object information and dependencies')
    info_parser.add_argument('analysis_dir', help='Path to analysis output directory')
    info_parser.add_argument('--reports-dir', '-r', help='Path to Reports directory containing ObjectReferences.csv')
    info_parser.add_argument('--object', '-o', required=True, help='Object name to show info for')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate wave assignments')
    validate_parser.add_argument('analysis_dir', help='Path to analysis output directory')
    validate_parser.add_argument('--reports-dir', '-r', help='Path to Reports directory containing ObjectReferences.csv')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    try:
        reports_dir = getattr(args, 'reports_dir', None)
        relocator = WaveRelocator(args.analysis_dir, reports_dir=reports_dir)
        
        if args.command == 'relocate':
            if not args.objects or not args.waves:
                print("Error: Both --object and --to-wave are required")
                return
            
            if len(args.objects) != len(args.waves):
                print(f"Error: Number of --object ({len(args.objects)}) must match --to-wave ({len(args.waves)})")
                return
            
            relocations = list(zip(args.objects, args.waves))
            result = relocator.relocate(
                relocations,
                min_size=args.min_size,
                max_size=args.max_size,
                dry_run=args.dry_run
            )
            
            if result['success']:
                print("\nRelocation completed successfully!")
            else:
                print("\nRelocation failed:")
                for error in result.get('errors', []):
                    print(f"  - {error}")
        
        elif args.command == 'info':
            # Try exact match first
            if args.object in relocator.objects:
                info = relocator.show_object_dependencies(args.object)
            else:
                # Try partial match
                matches = relocator.find_object(args.object)
                if len(matches) == 0:
                    print(f"Object '{args.object}' not found")
                    return
                elif len(matches) == 1:
                    info = relocator.show_object_dependencies(matches[0])
                else:
                    print(f"Multiple matches found for '{args.object}':")
                    for m in matches[:20]:
                        wave = relocator.objects[m].wave
                        print(f"  [{wave:3d}] {m}")
                    if len(matches) > 20:
                        print(f"  ... and {len(matches) - 20} more")
                    return
            
            print(f"\nObject: {info['object']}")
            print(f"Current Wave: {info['current_wave']}")
            print(f"Category: {info['category']}")
            print(f"Is Root: {info['is_root']}")
            print(f"Is Leaf: {info['is_leaf']}")
            
            print(f"\nDirect Dependencies ({len(info['direct_dependencies'])}):")
            for dep in info['direct_dependencies']:
                print(f"  [{dep['wave']:3d}] {dep['name']} ({dep['category']})")
            
            print(f"\nDirect Dependents ({len(info['direct_dependents'])}):")
            for dep in info['direct_dependents']:
                print(f"  [{dep['wave']:3d}] {dep['name']} ({dep['category']})")
            
            print(f"\nTransitive Dependencies: {info['transitive_dependency_count']}")
            print(f"Transitive Dependents: {info['transitive_dependent_count']}")
        
        elif args.command == 'validate':
            errors = relocator.validate_assignments()
            if errors:
                print(f"\nValidation found {len(errors)} issues:")
                for error in errors[:50]:
                    print(f"  - {error}")
                if len(errors) > 50:
                    print(f"  ... and {len(errors) - 50} more")
            else:
                print("\nAll wave assignments are valid!")
    
    except FileNotFoundError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == '__main__':
    main()