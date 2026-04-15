"""ETL Analysis Reader Service for ETL analysis JSON files."""

import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class ETLAnalysisReaderService:
    """Service for reading ETL analysis JSON files."""
    
    @staticmethod
    def _load_data(json_file_path: str) -> Dict:
        """Load the JSON data from file."""
        path = Path(json_file_path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {json_file_path}")
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def get_package(json_file_path: str, package_name: str) -> Optional[Dict[str, Any]]:
        """
        Get summarized information about a specific package.
        
        Args:
            json_file_path: Path to the ETL analysis JSON file
            package_name: Name of the package to retrieve
            
        Returns:
            Dictionary containing:
            - name: Package name
            - path: Package path
            - connection_managers: Array with full_name and creationName from additional_info
            - metrics: Component counts with percentages
            - control_flow_components: Count by type with percentages
            - data_flow_components: Count by type with percentages
            
            Returns None if package not found
        """
        data = ETLAnalysisReaderService._load_data(json_file_path)
        packages = data.get('packages', [])
        
        for pkg in packages:
            if pkg.get('path') == package_name:
                connection_managers = []
                for cm in pkg.get('connection_managers', []):
                    additional_info_str = cm.get('additional_info', '{}')
                    try:
                        additional_info = json.loads(additional_info_str) if isinstance(additional_info_str, str) else additional_info_str
                    except:
                        additional_info = {}
                    
                    connection_managers.append({
                        'full_name': cm.get('full_name'),
                        'creationName': additional_info.get('creationName')
                    })
                
                # Get metrics
                metrics_raw = pkg.get('metrics', {})
                total_control_flow = metrics_raw.get('total_control_flow_components', 0)
                total_data_flow_components = metrics_raw.get('total_data_flow_components', 0)
                total_execution_components = total_control_flow + total_data_flow_components
                
                # Calculate execution component percentages
                control_flow_percentage = "0.0%"
                data_flow_percentage = "0.0%"
                if total_execution_components > 0:
                    control_flow_percentage = f"{round((total_control_flow / total_execution_components) * 100, 1)}%"
                    data_flow_percentage = f"{round((total_data_flow_components / total_execution_components) * 100, 1)}%"
                
                # Get control flow component breakdown by type
                control_flow_breakdown = {}
                for comp in pkg.get('control_flow_components', []):
                    comp_type = comp.get('subtype', 'Unknown')
                    control_flow_breakdown[comp_type] = control_flow_breakdown.get(comp_type, 0) + 1
                
                # Add percentages to control flow breakdown
                control_flow_with_percentages = {}
                for comp_type, count in control_flow_breakdown.items():
                    percentage = f"{round((count / total_control_flow) * 100, 1)}%" if total_control_flow > 0 else "0.0%"
                    control_flow_with_percentages[comp_type] = {
                        'count': count,
                        'percentage': percentage
                    }
                
                # Get data flow component breakdown by type
                data_flow_breakdown = {}
                for df in pkg.get('data_flows', []):
                    for comp in df.get('components', []):
                        comp_type = comp.get('subtype', 'Unknown')
                        data_flow_breakdown[comp_type] = data_flow_breakdown.get(comp_type, 0) + 1
                
                # Add percentages to data flow breakdown
                data_flow_with_percentages = {}
                for comp_type, count in data_flow_breakdown.items():
                    percentage = f"{round((count / total_data_flow_components) * 100, 1)}%" if total_data_flow_components > 0 else "0.0%"
                    data_flow_with_percentages[comp_type] = {
                        'count': count,
                        'percentage': percentage
                    }
                
                return {
                    'name': pkg.get('name'),
                    'path': pkg.get('path'),
                    'connection_managers': connection_managers,
                    'metrics': {
                        'total_connection_managers': metrics_raw.get('total_connection_managers', 0),
                        'total_control_flow_components': total_control_flow,
                        'total_data_flows': metrics_raw.get('total_data_flows', 0),
                        'total_data_flow_components': total_data_flow_components,
                        'total_execution_components': total_execution_components,
                        'control_flow_percentage': control_flow_percentage,
                        'data_flow_percentage': data_flow_percentage
                    },
                    'control_flow_components': control_flow_with_percentages,
                    'data_flow_components': data_flow_with_percentages
                }
        
        return None
    
    @staticmethod
    def get_package_full(json_file_path: str, package_name: str) -> Optional[Dict[str, Any]]:
        """
        Get complete detailed information for a specific package.
        
        Args:
            json_file_path: Path to the ETL analysis JSON file
            package_name: Name of the package to retrieve
            
        Returns:
            Dictionary containing full package details, or None if not found
        """
        data = ETLAnalysisReaderService._load_data(json_file_path)
        packages = data.get('packages', [])
        
        for pkg in packages:
            if pkg.get('path') == package_name:
                return pkg
        
        return None
    
    @staticmethod
    def get_control_flow_dag(json_file_path: str, package_name: str) -> Optional[str]:
        """
        Get control flow DAG (execution order) for a specific package as formatted text.
        
        This shows the topological order of control flow components with visual tree structure.
        Data flows (Microsoft.Pipeline) are shown at top level only, without their internal components.
        Sequences, containers, and loops are shown with their nested components.
        
        Uses tree-style formatting with arrows to show execution flow:
        - Indentation shows containment
        - ↓ shows sequential flow
        - ├─→ shows branching to child tasks
        - └─→ shows last child in a branch
        
        Args:
            json_file_path: Path to the ETL analysis JSON file
            package_name: Name of the package
            
        Returns:
            Formatted text string showing the control flow DAG
            Returns None if package not found
        """
        package = ETLAnalysisReaderService.get_package_full(json_file_path, package_name)
        if not package:
            return None
        
        control_flow_components = package.get('control_flow_components', [])
        
        # Build component lookup by full_name
        components_by_name = {}
        for comp in control_flow_components:
            full_name = comp.get('full_name', '')
            components_by_name[full_name] = comp
        
        # Parse additional_info to extract successors and containers
        component_graph = {}
        predecessors = {}
        containers = {}
        
        for comp in control_flow_components:
            full_name = comp.get('full_name', '')
            additional_info_str = comp.get('additional_info', '{}')
            
            # Parse JSON from additional_info
            try:
                additional_info = json.loads(additional_info_str) if isinstance(additional_info_str, str) else additional_info_str
            except:
                additional_info = {}
            
            # Get successors
            successors = additional_info.get('successors', [])
            component_graph[full_name] = successors
            
            # Track predecessors
            for successor in successors:
                if successor not in predecessors:
                    predecessors[successor] = []
                predecessors[successor].append(full_name)
            
            # Get container information
            container = additional_info.get('controlFlowContainer', '')
            if container:
                containers[full_name] = container
        
        # Find starter tasks (no predecessors)
        starter_tasks = []
        for comp in control_flow_components:
            full_name = comp.get('full_name', '')
            if full_name not in predecessors:
                starter_tasks.append(full_name)
        
        # Find end tasks (no successors)
        end_tasks = []
        for comp in control_flow_components:
            full_name = comp.get('full_name', '')
            if not component_graph.get(full_name, []):
                end_tasks.append(full_name)
        
        # Group components by container
        container_children = {}
        for comp in control_flow_components:
            full_name = comp.get('full_name', '')
            container = containers.get(full_name, '')
            
            if container and container != 'Package':
                if container not in container_children:
                    container_children[container] = []
                container_children[container].append(full_name)
        
        # Build formatted text output
        output_lines = []
        output_lines.append(f"PACKAGE: {package.get('name')}")
        output_lines.append(f"PATH: {package.get('path')}")
        output_lines.append(f"TOTAL CONTROL FLOW COMPONENTS: {len(control_flow_components)}")
        output_lines.append("")
        
        # Show starter tasks
        if starter_tasks:
            output_lines.append(f"STARTER TASKS ({len(starter_tasks)}):")
            for task in starter_tasks:
                comp = components_by_name.get(task, {})
                subtype = comp.get('subtype', 'Unknown')
                output_lines.append(f"  • {task} ({subtype})")
            output_lines.append("")
        
        # Show end tasks
        if end_tasks:
            output_lines.append(f"END TASKS ({len(end_tasks)}):")
            for task in end_tasks:
                comp = components_by_name.get(task, {})
                subtype = comp.get('subtype', 'Unknown')
                output_lines.append(f"  • {task} ({subtype})")
            output_lines.append("")
        
        output_lines.append("EXECUTION FLOW:")
        output_lines.append("")
        
        # Build tree structure with indentation and arrows
        def format_tree(comp_name, indent="", is_last=False, visited=None):
            if visited is None:
                visited = set()
            
            if comp_name in visited:
                return
            
            visited.add(comp_name)
            comp = components_by_name.get(comp_name, {})
            subtype = comp.get('subtype', 'Unknown')
            
            # Format component line
            prefix = ""
            if indent:
                prefix = indent + ("└─→ " if is_last else "├─→ ")
            
            output_lines.append(f"{prefix}{comp_name} ({subtype})")
            
            # Get children
            children = container_children.get(comp_name, [])
            
            # Get successors
            successors = component_graph.get(comp_name, [])
            
            # Process children first
            if children:
                new_indent = indent + ("    " if is_last or not indent else "│   ")
                for i, child in enumerate(children):
                    is_last_child = (i == len(children) - 1)
                    format_tree(child, new_indent, is_last_child, visited)
            
            # Show flow to next component with arrow
            if successors and not children:
                # Only show arrow if no children (children already show hierarchy)
                next_indent = indent + ("    " if is_last or not indent else "│   ")
                for successor in successors:
                    if successor not in visited:
                        output_lines.append(f"{next_indent}↓")
                        format_tree(successor, indent, is_last, visited)
        
        # Process all starter tasks
        visited_global = set()
        for i, starter in enumerate(starter_tasks):
            if starter not in visited_global:
                format_tree(starter, "", i == len(starter_tasks) - 1, visited_global)
                if i < len(starter_tasks) - 1:
                    output_lines.append("")
        
        return "\n".join(output_lines)
    
    @staticmethod
    def get_data_flow_dag(json_file_path: str, package_name: str, data_flow_name: str) -> Optional[str]:
        """
        Get data flow DAG for a specific data flow task.
        
        Shows the data transformation pipeline within a Microsoft.Pipeline task.
        Displays sources, transformations, and destinations with their connections.
        
        Args:
            json_file_path: Path to the ETL analysis JSON file
            package_name: Name of the package
            data_flow_name: Full name of the data flow task
            
        Returns:
            Formatted text string showing the data flow pipeline
            Returns None if package or data flow not found
        """
        package = ETLAnalysisReaderService.get_package_full(json_file_path, package_name)
        if not package:
            return None
        
        # Find the specific data flow
        data_flows = package.get('data_flows', [])
        target_data_flow = None
        
        for df in data_flows:
            if df.get('full_path') == data_flow_name:
                target_data_flow = df
                break
        
        if not target_data_flow:
            return f"Data flow not found: {data_flow_name}"
        
        components = target_data_flow.get('components', [])
        
        if not components:
            return f"No components found in data flow: {data_flow_name}"
        
        # Build component lookup
        components_by_name = {}
        for comp in components:
            full_name = comp.get('full_name', '')
            components_by_name[full_name] = comp
        
        # Parse connections from additional_info
        component_graph = {}
        predecessors = {}
        
        for comp in components:
            full_name = comp.get('full_name', '')
            additional_info_str = comp.get('additional_info', '{}')
            
            try:
                additional_info = json.loads(additional_info_str) if isinstance(additional_info_str, str) else additional_info_str
            except:
                additional_info = {}
            
            # Get successors/outputs
            successors = additional_info.get('successors', [])
            component_graph[full_name] = successors
            
            # Track predecessors
            for successor in successors:
                if successor not in predecessors:
                    predecessors[successor] = []
                predecessors[successor].append(full_name)
        
        # Find source components
        source_components = []
        for comp in components:
            full_name = comp.get('full_name', '')
            if full_name not in predecessors:
                source_components.append(full_name)
        
        # Find destination components
        destination_components = []
        for comp in components:
            full_name = comp.get('full_name', '')
            if not component_graph.get(full_name, []):
                destination_components.append(full_name)
        
        # Build output
        output_lines = []
        output_lines.append(f"DATA FLOW: {target_data_flow.get('full_path')}")
        output_lines.append(f"TOTAL COMPONENTS: {len(components)}")
        output_lines.append("")
        
        # Show sources
        if source_components:
            output_lines.append(f"SOURCE COMPONENTS ({len(source_components)}):")
            for comp_name in source_components:
                comp = components_by_name.get(comp_name, {})
                subtype = comp.get('subtype', 'Unknown')
                output_lines.append(f"  • {comp_name} ({subtype})")
            output_lines.append("")
        
        # Show destinations
        if destination_components:
            output_lines.append(f"DESTINATION COMPONENTS ({len(destination_components)}):")
            for comp_name in destination_components:
                comp = components_by_name.get(comp_name, {})
                subtype = comp.get('subtype', 'Unknown')
                output_lines.append(f"  • {comp_name} ({subtype})")
            output_lines.append("")
        
        output_lines.append("DATA FLOW PIPELINE:")
        output_lines.append("")
        
        # Build tree structure
        def format_pipeline(comp_name, indent="", is_last=False, visited=None):
            if visited is None:
                visited = set()
            
            if comp_name in visited:
                return
            
            visited.add(comp_name)
            comp = components_by_name.get(comp_name, {})
            subtype = comp.get('subtype', 'Unknown')
            
            # Format component line
            prefix = ""
            if indent:
                prefix = indent + ("└─→ " if is_last else "├─→ ")
            
            output_lines.append(f"{prefix}{comp_name} ({subtype})")
            
            # Get successors
            successors = component_graph.get(comp_name, [])
            
            if successors:
                new_indent = indent + ("    " if is_last or not indent else "│   ")
                
                if len(successors) == 1:
                    # Single successor - show with arrow
                    output_lines.append(f"{new_indent}↓")
                    format_pipeline(successors[0], indent, is_last, visited)
                else:
                    # Multiple successors - show as branches
                    for i, successor in enumerate(successors):
                        is_last_successor = (i == len(successors) - 1)
                        if successor not in visited:
                            format_pipeline(successor, new_indent, is_last_successor, visited)
        
        # Process all source components
        visited_global = set()
        for i, source in enumerate(source_components):
            if source not in visited_global:
                format_pipeline(source, "", i == len(source_components) - 1, visited_global)
                if i < len(source_components) - 1:
                    output_lines.append("")
        
        return "\n".join(output_lines)

