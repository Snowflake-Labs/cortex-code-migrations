"""SQL Task Extractor Service - Extracts SQL details from SSIS ExecuteSQLTask components."""

import re
import html
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from xml.etree import ElementTree as ET


class SqlTaskExtractorService:
    """Service for extracting SQL task details from DTSX files."""
    
    # SSIS namespaces used in DTSX files
    NAMESPACES = {
        'DTS': 'www.microsoft.com/SqlServer/Dts',
        'SQLTask': 'www.microsoft.com/sqlserver/dts/tasks/sqltask'
    }
    
    @classmethod
    def extract_sql_tasks_from_package(cls, dtsx_path: str) -> Dict[str, Dict[str, Any]]:
        """
        Extract SQL task details from a DTSX package file.
        
        Args:
            dtsx_path: Path to the .dtsx file
            
        Returns:
            Dictionary mapping component full_name (refId) to SQL task details
        """
        try:
            tree = ET.parse(dtsx_path)
            root = tree.getroot()
        except ET.ParseError as e:
            print(f"Warning: Failed to parse {dtsx_path}: {e}")
            return {}
        except Exception as e:
            print(f"Warning: Error reading {dtsx_path}: {e}")
            return {}
        
        # Extract package-level variables for resolution
        package_variables = cls._extract_variables(root)
        
        # Find all ExecuteSQLTask executables
        sql_tasks = {}
        
        # Handle namespaced and non-namespaced XML
        for executable in cls._find_all_executables(root):
            creation_name = cls._get_attribute(executable, 'CreationName')
            
            if creation_name == 'Microsoft.ExecuteSQLTask':
                ref_id = cls._get_attribute(executable, 'refId')
                if ref_id:
                    task_details = cls._extract_sql_task_details(executable, package_variables)
                    if task_details:
                        sql_tasks[ref_id] = task_details
        
        return sql_tasks
    
    @classmethod
    def _find_all_executables(cls, root: ET.Element) -> List[ET.Element]:
        """Find all Executable elements in the document, handling namespaces."""
        executables = []
        
        # Try with namespace
        for ns_prefix in ['', '{www.microsoft.com/SqlServer/Dts}']:
            for elem in root.iter(f'{ns_prefix}Executable'):
                executables.append(elem)
        
        return executables
    
    @classmethod
    def _get_attribute(cls, element: ET.Element, attr_name: str) -> Optional[str]:
        """Get attribute value, handling DTS namespace prefix."""
        # Try with DTS namespace prefix
        value = element.get(f'{{www.microsoft.com/SqlServer/Dts}}{attr_name}')
        if value:
            return value
        
        # Try with DTS: prefix (common in DTSX files)
        value = element.get(f'DTS:{attr_name}')
        if value:
            return value
        
        # Try without namespace
        return element.get(attr_name)
    
    @classmethod
    def _extract_variables(cls, root: ET.Element) -> Dict[str, Dict[str, Any]]:
        """Extract all package-level variables."""
        variables = {}
        
        # Find all Variable elements
        for ns_prefix in ['', '{www.microsoft.com/SqlServer/Dts}']:
            for var_elem in root.iter(f'{ns_prefix}Variable'):
                var_name = cls._get_attribute(var_elem, 'ObjectName')
                namespace = cls._get_attribute(var_elem, 'Namespace') or 'User'
                
                if var_name:
                    full_var_name = f"{namespace}::{var_name}"
                    
                    # Get the expression if it's an expression-based variable
                    expression = cls._get_attribute(var_elem, 'Expression')
                    evaluate_as_expression = cls._get_attribute(var_elem, 'EvaluateAsExpression')
                    
                    # Get the variable value
                    value = None
                    for val_ns in ['', '{www.microsoft.com/SqlServer/Dts}']:
                        for value_elem in var_elem.iter(f'{val_ns}VariableValue'):
                            value = value_elem.text
                            break
                    
                    variables[full_var_name] = {
                        'name': var_name,
                        'namespace': namespace,
                        'value': cls._decode_xml_entities(value) if value else None,
                        'expression': cls._decode_xml_entities(expression) if expression else None,
                        'is_expression': evaluate_as_expression == 'True'
                    }
        
        return variables
    
    @classmethod
    def _extract_sql_task_details(cls, executable: ET.Element, 
                                   package_variables: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Extract SQL task details from an ExecuteSQLTask executable element."""
        result = {}
        
        # Get the task name
        result['task_name'] = cls._get_attribute(executable, 'ObjectName')
        
        # Look for PropertyExpression (dynamic SQL)
        property_expression = None
        for ns_prefix in ['', '{www.microsoft.com/SqlServer/Dts}']:
            for prop_expr in executable.iter(f'{ns_prefix}PropertyExpression'):
                prop_name = cls._get_attribute(prop_expr, 'Name')
                if prop_name == 'SqlStatementSource':
                    property_expression = prop_expr.text
                    break
        
        if property_expression:
            result['sql_expression'] = cls._decode_xml_entities(property_expression)
        
        # Find SQLTask:SqlTaskData element
        sql_task_data = None
        for elem in executable.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_name == 'SqlTaskData':
                sql_task_data = elem
                break
        
        if sql_task_data is None:
            return None
        
        # Extract attributes from SqlTaskData
        # Handle both namespaced and non-namespaced attributes
        def get_sql_attr(attr_name: str) -> Optional[str]:
            # Try with SQLTask namespace
            val = sql_task_data.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}{attr_name}')
            if val:
                return val
            val = sql_task_data.get(f'SQLTask:{attr_name}')
            if val:
                return val
            return sql_task_data.get(attr_name)
        
        # Get SQL statement source type
        source_type = get_sql_attr('SqlStmtSourceType')
        result['source_type'] = source_type if source_type else 'DirectInput'
        
        # Get the SQL statement source
        sql_statement = get_sql_attr('SqlStatementSource')
        if sql_statement:
            result['sql_statement'] = cls._decode_xml_entities(sql_statement)
        
        # Get result type
        result_type = get_sql_attr('ResultType')
        if result_type:
            result['result_type'] = result_type
        
        # If source type is Variable, resolve the variable
        if source_type == 'Variable' and sql_statement:
            var_ref = sql_statement
            # Normalize variable reference format
            if '::' not in var_ref:
                var_ref = f"User::{var_ref}"
            
            if var_ref in package_variables:
                var_info = package_variables[var_ref]
                result['variable_reference'] = var_ref
                result['resolved_sql'] = var_info.get('value')
                if var_info.get('is_expression'):
                    result['variable_expression'] = var_info.get('expression')
        
        # Extract result bindings
        result_bindings = []
        for elem in sql_task_data.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_name == 'ResultBinding':
                binding = {}
                result_name = elem.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}ResultName')
                if not result_name:
                    result_name = elem.get('SQLTask:ResultName') or elem.get('ResultName')
                dts_var = elem.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}DtsVariableName')
                if not dts_var:
                    dts_var = elem.get('SQLTask:DtsVariableName') or elem.get('DtsVariableName')
                
                if result_name is not None:
                    binding['result_name'] = result_name
                if dts_var:
                    binding['variable'] = dts_var
                
                if binding:
                    result_bindings.append(binding)
        
        if result_bindings:
            result['result_bindings'] = result_bindings
        
        # Extract parameter bindings
        param_bindings = []
        for elem in sql_task_data.iter():
            tag_name = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
            if tag_name == 'ParameterBinding':
                binding = {}
                param_name = elem.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}ParameterName')
                if not param_name:
                    param_name = elem.get('SQLTask:ParameterName') or elem.get('ParameterName')
                dts_var = elem.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}DtsVariableName')
                if not dts_var:
                    dts_var = elem.get('SQLTask:DtsVariableName') or elem.get('DtsVariableName')
                direction = elem.get(f'{{www.microsoft.com/sqlserver/dts/tasks/sqltask}}ParameterDirection')
                if not direction:
                    direction = elem.get('SQLTask:ParameterDirection') or elem.get('ParameterDirection')
                
                if param_name:
                    binding['parameter_name'] = param_name
                if dts_var:
                    binding['variable'] = dts_var
                if direction:
                    binding['direction'] = direction
                
                if binding:
                    param_bindings.append(binding)
        
        if param_bindings:
            result['parameter_bindings'] = param_bindings
        
        return result if result else None
    
    @classmethod
    def _decode_xml_entities(cls, text: str) -> str:
        """Decode XML entities in text."""
        if not text:
            return text
        
        # Decode standard XML entities
        text = html.unescape(text)
        
        # Handle SSIS-specific encoded characters
        text = text.replace('&#xA;', '\n')
        text = text.replace('&#xD;', '\r')
        text = text.replace('&#x9;', '\t')
        
        return text
    
    @classmethod
    def extract_all_sql_tasks(cls, ssis_source_dir: str) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """
        Extract SQL task details from all DTSX files in a directory.
        
        Args:
            ssis_source_dir: Root directory containing DTSX files
            
        Returns:
            Dictionary mapping package relative path to dict of component refId to SQL task details
        """
        source_path = Path(ssis_source_dir)
        if not source_path.exists():
            print(f"Warning: SSIS source directory not found: {ssis_source_dir}")
            return {}
        
        all_sql_tasks = {}
        dtsx_files = list(source_path.rglob('*.dtsx'))
        
        print(f"Extracting SQL task details from {len(dtsx_files)} DTSX files...")
        
        for dtsx_file in dtsx_files:
            relative_path = str(dtsx_file.relative_to(source_path))
            # Normalize path separators
            relative_path = relative_path.replace('\\', '/')
            
            sql_tasks = cls.extract_sql_tasks_from_package(str(dtsx_file))
            if sql_tasks:
                all_sql_tasks[relative_path] = sql_tasks
        
        total_tasks = sum(len(tasks) for tasks in all_sql_tasks.values())
        print(f"Extracted SQL details for {total_tasks} ExecuteSQLTask components across {len(all_sql_tasks)} packages")
        
        return all_sql_tasks
    
    @classmethod
    def match_component_to_sql_task(cls, component_full_name: str, 
                                     sql_tasks: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        r"""
        Match a component's full_name to its SQL task details.
        
        Component full_name format: Package\Container\TaskName
        SQL task refId format: Package\Container\TaskName
        
        Args:
            component_full_name: The component's full_name from SnowConvert
            sql_tasks: Dictionary of refId to SQL task details for the package
            
        Returns:
            SQL task details if found, None otherwise
        """
        if not sql_tasks or not component_full_name:
            return None
        
        # Direct match
        if component_full_name in sql_tasks:
            return sql_tasks[component_full_name]
        
        # Try with normalized separators
        normalized = component_full_name.replace('/', '\\')
        if normalized in sql_tasks:
            return sql_tasks[normalized]
        
        # Try matching by task name (last part of path)
        component_parts = component_full_name.replace('/', '\\').split('\\')
        component_task_name = component_parts[-1] if component_parts else ''
        
        for ref_id, details in sql_tasks.items():
            ref_parts = ref_id.replace('/', '\\').split('\\')
            ref_task_name = ref_parts[-1] if ref_parts else ''
            
            if component_task_name == ref_task_name:
                # Verify parent path matches too if possible
                if len(component_parts) >= 2 and len(ref_parts) >= 2:
                    if component_parts[-2] == ref_parts[-2]:
                        return details
                else:
                    return details
        
        return None
