"""DAG Service - Generates interactive HTML DAG visualizations for SSIS flows."""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from html import escape
from urllib.parse import unquote

from ..utils import sanitize_filename, format_display_name


class DataFlowDagService:
    """Service for generating interactive DAG visualizations from SSIS components."""
    
    # ==========================================================================
    # Component Type Categories
    # ==========================================================================
    
    SOURCE_TYPES = {
        'Microsoft.OLEDBSource', 'Microsoft.FlatFileSource', 'Microsoft.ExcelSource',
        'Microsoft.ADONETSource', 'Microsoft.XMLSource', 'Microsoft.RawFileSource',
        'Microsoft.ODBCSource', 'Microsoft.DataReaderSource'
    }
    
    DESTINATION_TYPES = {
        'Microsoft.OLEDBDestination', 'Microsoft.FlatFileDestination', 
        'Microsoft.ExcelDestination', 'Microsoft.ADONETDestination',
        'Microsoft.RawFileDestination', 'Microsoft.ODBCDestination',
        'Microsoft.DataReaderDestination', 'Microsoft.RecordsetDestination'
    }
    
    TRANSFORM_TYPES = {
        'Microsoft.Lookup', 'Microsoft.DerivedColumn', 'Microsoft.DataConvert',
        'Microsoft.ConditionalSplit', 'Microsoft.Merge', 'Microsoft.MergeJoin',
        'Microsoft.Multicast', 'Microsoft.UnionAll', 'Microsoft.Aggregate',
        'Microsoft.Sort', 'Microsoft.RowCount', 'Microsoft.ScriptComponent',
        'Microsoft.OLEDBCommand', 'Microsoft.SCD', 'Microsoft.Pivot',
        'Microsoft.Unpivot', 'Microsoft.PercentageSampling', 'Microsoft.RowSampling',
        'Microsoft.Cache', 'Microsoft.CharacterMap', 'Microsoft.CopyColumn',
        'Microsoft.DataMining', 'Microsoft.Export', 'Microsoft.FuzzyGrouping',
        'Microsoft.FuzzyLookup', 'Microsoft.Import', 'Microsoft.TermExtraction',
        'Microsoft.TermLookup', 'Microsoft.Audit', 'Microsoft.DataConversion'
    }
    
    CONTROL_FLOW_CONTAINER_TYPES = {
        'Microsoft.SequenceContainer', 'Microsoft.ForLoop', 'Microsoft.ForEachLoop',
        'Microsoft.ForLoopContainer', 'Microsoft.ForEachLoopContainer',
        'STOCK:SEQUENCE', 'STOCK:FOREACHLOOP', 'STOCK:FORLOOP'
    }
    
    # ==========================================================================
    # Utility Methods
    # ==========================================================================
    
    
    @staticmethod
    def extract_short_name(full_name: str) -> str:
        """Extract short display name from full path."""
        parts = full_name.split('\\')
        return parts[-1] if parts else full_name
    
    @staticmethod
    def parse_additional_info(additional_info_str: str) -> Dict[str, Any]:
        """Parse additional_info JSON string safely."""
        if not additional_info_str:
            return {}
        try:
            if isinstance(additional_info_str, dict):
                return additional_info_str
            return json.loads(additional_info_str)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    @staticmethod
    def get_node_color_by_status(status: str) -> Dict[str, str]:
        """Get node color based on conversion status."""
        status_upper = status.upper() if status else ''
        if status_upper == 'SUCCESS':
            return {'background': '#DCFCE7', 'border': '#22C55E'}
        elif status_upper == 'PARTIAL':
            return {'background': '#FEF3C7', 'border': '#F59E0B'}
        elif status_upper == 'NOTSUPPORTED':
            return {'background': '#FEE2E2', 'border': '#EF4444'}
        else:
            return {'background': '#F3F4F6', 'border': '#6B7280'}
    
    @classmethod
    def get_short_type_name(cls, subtype: str, dag_type: str = 'data_flow') -> str:
        """Get a short, readable type name for display."""

        type_map = {
            'Pipeline.3': 'Data Flow (Old Format)',
        }
        
        # Remove common prefixes first
        short = subtype
        if short.startswith('Microsoft.'):
            short = short[10:]
        if short.startswith('STOCK:'):
            short = short[6:]
        if short.startswith('SSIS.'):
            short = short[5:]
        
        # Check type map
        if short in type_map:
            return type_map[short]
        
        return short
    
    # ==========================================================================
    # DAG Building Methods
    # ==========================================================================
    
    @classmethod
    def build_dag_from_components(cls, components: List[Dict], dag_type: str = 'data_flow') -> Tuple[List[Dict], List[Dict]]:
        """
        Build DAG nodes and edges from components.
        
        Args:
            components: List of component dictionaries
            dag_type: 'data_flow' or 'control_flow'
            
        Returns:
            Tuple of (nodes, edges)
        """
        if dag_type == 'control_flow':
            return cls._build_control_flow_dag(components)
        else:
            return cls._build_data_flow_dag(components)
    
    @classmethod
    def _build_data_flow_dag(cls, components: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Build DAG for data flow components (no container hierarchy)."""
        nodes = []
        edges = []
        component_map = {c.get('full_name', ''): c for c in components}
        
        for comp in components:
            full_name = comp.get('full_name', '')
            subtype = comp.get('subtype', 'Unknown')
            status = comp.get('status', 'Unknown')
            short_name = cls.extract_short_name(full_name)
            short_type = cls.get_short_type_name(subtype, 'data_flow')
            
            label = f"{short_name}\n[{short_type}]"
            color = cls.get_node_color_by_status(status)
            
            node = {
                'id': full_name,
                'label': label,
                'subtype': subtype,
                'status': status,
                'color': color,
                'parent': None  # Data flows don't have container hierarchy
            }
            nodes.append(node)
            
            # Build edges from successors
            additional_info = cls.parse_additional_info(comp.get('additional_info', ''))
            for successor in additional_info.get('successors', []):
                if successor in component_map:
                    edges.append({'from': full_name, 'to': successor})
        
        return nodes, edges
    
    @classmethod
    def _build_control_flow_dag(cls, components: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """Build DAG for control flow components with container hierarchy."""
        nodes = []
        edges = []
        
        # Filter out Event Handlers
        main_components = []
        for comp in components:
            full_name = comp.get('full_name', '')
            subtype = comp.get('subtype', '')
            additional_info = cls.parse_additional_info(comp.get('additional_info', ''))
            container = additional_info.get('controlFlowContainer', '')
            
            is_event_handler = subtype == 'EventHandler'
            is_inside_event_handler = 'EventHandler' in container if container else False
            
            if not is_event_handler and not is_inside_event_handler:
                main_components.append(comp)
        
        component_map = {c.get('full_name', ''): c for c in main_components}
        
        for comp in main_components:
            full_name = comp.get('full_name', '')
            subtype = comp.get('subtype', 'Unknown')
            status = comp.get('status', 'Unknown')
            short_name = cls.extract_short_name(full_name)
            short_type = cls.get_short_type_name(subtype, 'control_flow')
            
            label = f"{short_name}\n[{short_type}]"
            color = cls.get_node_color_by_status(status)
            
            # Get container (parent) info
            additional_info = cls.parse_additional_info(comp.get('additional_info', ''))
            container = additional_info.get('controlFlowContainer', '')
            
            parent = None
            if container and container != 'Package' and container in component_map:
                parent = container
            
            # Extract SQL task details if this is an ExecuteSQLTask
            sql_info = None
            if 'ExecuteSQLTask' in subtype or subtype == 'Microsoft.ExecuteSQLTask':
                sql_task_details = comp.get('sql_task_details', {})
                if sql_task_details:
                    # Prefer resolved_sql (for variable references) over sql_statement
                    sql_statement = sql_task_details.get('resolved_sql') or sql_task_details.get('sql_statement', '')
                    source_type = sql_task_details.get('source_type', '')
                    task_name = sql_task_details.get('task_name', '')
                    
                    if sql_statement:
                        sql_info = {
                            'sql': sql_statement,
                            'source_type': source_type,
                            'task_name': task_name
                        }
            
            node = {
                'id': full_name,
                'label': label,
                'subtype': subtype,
                'status': status,
                'color': color,
                'parent': parent,
                'isContainer': subtype in cls.CONTROL_FLOW_CONTAINER_TYPES,
                'sqlInfo': sql_info
            }
            nodes.append(node)
            
            # Build edges from successors
            for successor in additional_info.get('successors', []):
                if successor in component_map:
                    edges.append({'from': full_name, 'to': successor})
        
        return nodes, edges
    
    # ==========================================================================
    # HTML Generation (Unified Cytoscape.js Template)
    # ==========================================================================
    
    @classmethod
    def generate_dag_html(cls, title: str, subtitle: str, nodes: List[Dict], 
                          edges: List[Dict], dag_type: str = 'data_flow',
                          clickable_links: Optional[Dict[str, str]] = None,
                          back_link: Optional[str] = None,
                          back_link_title: Optional[str] = None) -> str:
        """
        Generate HTML for DAG visualization using Cytoscape.js.
        
        Args:
            title: Main title for the DAG
            subtitle: Subtitle (e.g., package path)
            nodes: List of node dictionaries with id, label, status, color, parent
            edges: List of edge dictionaries with from, to
            dag_type: 'data_flow' or 'control_flow'
            clickable_links: Optional dict mapping node IDs to URLs for navigation
            back_link: Optional URL for back navigation button
            back_link_title: Optional title for back navigation button
        """
        # Sort nodes for better layout (start nodes first)
        sorted_nodes = cls._sort_nodes_for_layout(nodes, edges)
        
        # Prepare clickable links mapping
        clickable_links = clickable_links or {}
        
        # Convert to Cytoscape elements format
        cy_elements = []
        
        # Compute levels for better ordering in control flow
        level_map = {}
        order_map = {}
        if dag_type == 'control_flow':
            level_map, order_map = cls._compute_levels(nodes, edges)
            sorted_nodes = sorted(
                nodes,
                key=lambda n: (
                    level_map.get(n['id'], 0),
                    0 if n.get('isContainer') else 1,
                    order_map.get(n['id'], 0)
                )
            )
        
        for node in sorted_nodes:
            node_id = node['id']
            is_clickable = node_id in clickable_links
            link_url = clickable_links.get(node_id, '')
            sql_info = node.get('sqlInfo')
            
            cy_node = {
                'data': {
                    'id': node_id,
                    'label': node['label'],
                    'status': node.get('status', 'Unknown'),
                    'subtype': node.get('subtype', 'Unknown'),
                    'isContainer': node.get('isContainer', False),
                    'bgColor': node['color']['background'],
                    'borderColor': node['color']['border'],
                    'isClickable': is_clickable,
                    'linkUrl': link_url,
                    'hasSql': sql_info is not None,
                    'sqlStatement': sql_info.get('sql', '') if sql_info else '',
                    'sqlSourceType': sql_info.get('source_type', '') if sql_info else ''
                }
            }
            if dag_type == 'control_flow':
                cy_node['data']['rank'] = level_map.get(node_id, 0)
                cy_node['data']['order'] = order_map.get(node_id, 0)
            if node.get('parent'):
                cy_node['data']['parent'] = node['parent']
            cy_elements.append(cy_node)
        
        for edge in edges:
            edge_data = {
                'data': {
                    'id': f"{edge['from']}_to_{edge['to']}",
                    'source': edge['from'],
                    'target': edge['to']
                }
            }
            if dag_type == 'control_flow':
                source_level = level_map.get(edge['from'], 0)
                target_level = level_map.get(edge['to'], source_level + 1)
                edge_data['data']['minlen'] = max(1, target_level - source_level)
                edge_data['data']['weight'] = 1
            cy_elements.append(edge_data)
        
        elements_json = json.dumps(cy_elements)
        
        # Choose header color based on DAG type
        header_gradient = 'linear-gradient(135deg, #3B82F6, #2563EB)' if dag_type == 'data_flow' else 'linear-gradient(135deg, #8B5CF6, #7C3AED)'
        
        # Build back button HTML if back_link is provided
        back_button_html = ''
        if back_link:
            back_title = back_link_title or 'Back to Control Flow'
            back_button_html = f'''
    <a href="{back_link}" class="back-btn">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      {escape(back_title)}
    </a>'''
        
        return f'''<!DOCTYPE html>
<html>
<head>
  <title>{escape(title)}</title>
  <script src="https://unpkg.com/cytoscape@3.28.1/dist/cytoscape.min.js"></script>
  <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js"></script>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: system-ui, -apple-system, sans-serif; background: #F9FAFB; min-height: 100vh; }}
    .header {{
      background: {header_gradient};
      color: white;
      padding: 20px 24px;
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }}
    .header h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 4px; }}
    .header p {{ font-size: 0.875rem; opacity: 0.9; }}
    .controls {{
      padding: 12px 24px;
      background: white;
      border-bottom: 1px solid #E5E7EB;
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .controls button {{
      padding: 6px 16px;
      background: #6B7280;
      color: white;
      border: none;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.875rem;
    }}
    .controls button:hover {{ background: #4B5563; }}
    #cy {{
      height: calc(100vh - 180px);
      background: white;
      margin: 16px;
      border-radius: 8px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
    .legend {{
      display: flex;
      gap: 20px;
      padding: 12px 24px;
      background: white;
      justify-content: center;
      flex-wrap: wrap;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-size: 0.75rem;
      color: #4B5563;
    }}
    .legend-color {{
      width: 16px;
      height: 16px;
      border-radius: 4px;
      border: 2px solid;
    }}
    .legend-success {{ background: #DCFCE7; border-color: #22C55E; }}
    .legend-partial {{ background: #FEF3C7; border-color: #F59E0B; }}
    .legend-notsupported {{ background: #FEE2E2; border-color: #EF4444; }}
    .legend-unknown {{ background: #F3F4F6; border-color: #6B7280; }}
    .back-btn {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 8px 16px;
      background: rgba(255,255,255,0.2);
      color: white;
      text-decoration: none;
      border-radius: 6px;
      font-size: 0.875rem;
      font-weight: 500;
      transition: background 0.2s;
      margin-bottom: 8px;
    }}
    .back-btn:hover {{ background: rgba(255,255,255,0.3); }}
    .clickable-hint {{
      font-size: 0.75rem;
      color: #6B7280;
      margin-left: auto;
    }}
    #sqlTooltip {{
      position: fixed;
      display: none;
      background: #1E293B;
      color: #E2E8F0;
      padding: 12px 16px;
      border-radius: 8px;
      font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
      font-size: 12px;
      max-width: 600px;
      max-height: 400px;
      overflow: auto;
      z-index: 1000;
      box-shadow: 0 10px 25px rgba(0,0,0,0.3);
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
    }}
    #sqlTooltip .tooltip-header {{
      font-family: system-ui, sans-serif;
      font-weight: 600;
      color: #94A3B8;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 8px;
      padding-bottom: 8px;
      border-bottom: 1px solid #334155;
    }}
    #sqlTooltip .sql-content {{
      color: #A5F3FC;
    }}
    .sql-indicator {{
      display: inline-block;
      width: 8px;
      height: 8px;
      background: #3B82F6;
      border-radius: 50%;
      margin-left: 4px;
    }}
  </style>
</head>
<body>
  <div class="header">{back_button_html}
    <h1>{escape(title)}</h1>
    <p>{escape(subtitle)}</p>
  </div>
  
  <div class="controls">
    <button id="fitBtn">Fit to Screen</button>
    <button id="zoomInBtn">Zoom In</button>
    <button id="zoomOutBtn">Zoom Out</button>
    <button id="layoutLRBtn" style="background: #3B82F6;">← → Left to Right</button>
    <button id="layoutTBBtn">↓ Top to Bottom</button>
    <span class="clickable-hint" id="clickHint"></span>
  </div>
  
  <div id="cy"></div>
  
  <div class="legend">
    <div class="legend-item"><div class="legend-color legend-success"></div> Success (Supported)</div>
    <div class="legend-item"><div class="legend-color legend-partial"></div> Partial (Needs Review)</div>
    <div class="legend-item"><div class="legend-color legend-notsupported"></div> Not Supported</div>
    <div class="legend-item"><div class="legend-color legend-unknown"></div> Unknown</div>
  </div>

  <!-- SQL Tooltip for ExecuteSQLTask nodes -->
  <div id="sqlTooltip">
    <div class="tooltip-header">SQL Statement</div>
    <div class="sql-content" id="sqlContent"></div>
  </div>

  <script>
    const elements = {elements_json};
    
    const cy = cytoscape({{
      container: document.getElementById('cy'),
      elements: elements,
      style: [
        {{
          selector: 'node',
          style: {{
            'label': 'data(label)',
            'text-wrap': 'wrap',
            'text-valign': 'center',
            'text-halign': 'center',
            'font-size': '11px',
            'font-family': 'system-ui, sans-serif',
            'background-color': 'data(bgColor)',
            'border-color': 'data(borderColor)',
            'border-width': 2,
            'padding': '10px',
            'shape': 'roundrectangle',
            'width': 'label',
            'height': 'label'
          }}
        }},
        {{
          selector: 'node[?isContainer]',
          style: {{
            'background-opacity': 0.3,
            'border-width': 3,
            'border-style': 'dashed',
            'font-weight': 'bold',
            'font-size': '12px',
            'text-valign': 'top',
            'text-margin-y': 10,
            'padding': '25px'
          }}
        }},
        {{
          selector: ':parent',
          style: {{
            'background-color': '#F8FAFC',
            'background-opacity': 0.7,
            'border-width': 2,
            'border-color': '#94A3B8',
            'border-style': 'dashed',
            'text-valign': 'top',
            'text-margin-y': 8,
            'padding': '20px'
          }}
        }},
        {{
          selector: 'edge',
          style: {{
            'width': 2,
            'line-color': '#6B7280',
            'target-arrow-color': '#6B7280',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'arrow-scale': 1.2
          }}
        }},
        {{
          selector: 'node:selected',
          style: {{
            'border-width': 4,
            'border-color': '#3B82F6'
          }}
        }},
        {{
          selector: '.highlighted',
          style: {{
            'border-width': 4,
            'border-color': '#3B82F6',
            'line-color': '#3B82F6',
            'target-arrow-color': '#3B82F6'
          }}
        }},
        {{
          selector: 'node[?isClickable]',
          style: {{
            'border-width': 3,
            'border-style': 'solid',
            'cursor': 'pointer'
          }}
        }},
        {{
          selector: 'node[?isClickable]:hover',
          style: {{
            'border-color': '#2563EB',
            'overlay-color': '#3B82F6',
            'overlay-opacity': 0.1
          }}
        }},
        {{
          selector: 'node[?hasSql]',
          style: {{
            'border-style': 'double',
            'border-width': 4
          }}
        }},
        {{
          selector: 'node[?hasSql]:hover',
          style: {{
            'overlay-color': '#8B5CF6',
            'overlay-opacity': 0.15
          }}
        }}
      ],
      layout: {{ name: 'preset' }}
    }});

    // Compute levels based on topological order
    function computeLevels() {{
      const nodes = cy.nodes();
      const edges = cy.edges();
      
      // Build adjacency and reverse adjacency
      const successors = {{}};
      const predecessors = {{}};
      const indegree = {{}};
      
      nodes.forEach(n => {{
        const id = n.id();
        successors[id] = [];
        predecessors[id] = [];
        indegree[id] = 0;
      }});
      
      edges.forEach(e => {{
        const src = e.data('source');
        const tgt = e.data('target');
        if (successors[src] && predecessors[tgt]) {{
          successors[src].push(tgt);
          predecessors[tgt].push(src);
          indegree[tgt]++;
        }}
      }});
      
      // Compute levels using longest path (ensures proper ordering)
      const level = {{}};
      const order = {{}};
      
      // Initialize roots at level 0
      const queue = [];
      nodes.forEach(n => {{
        const id = n.id();
        if (indegree[id] === 0) {{
          level[id] = 0;
          queue.push(id);
        }}
      }});
      
      // BFS to compute levels
      let orderIdx = 0;
      const processed = new Set();
      
      while (queue.length > 0) {{
        // Sort queue by current level to process in order
        queue.sort((a, b) => (level[a] || 0) - (level[b] || 0));
        const current = queue.shift();
        
        if (processed.has(current)) continue;
        processed.add(current);
        
        order[current] = orderIdx++;
        
        for (const next of (successors[current] || [])) {{
          // Level is max of all predecessors + 1
          const newLevel = (level[current] || 0) + 1;
          level[next] = Math.max(level[next] || 0, newLevel);
          indegree[next]--;
          if (indegree[next] === 0) {{
            queue.push(next);
          }}
        }}
      }}
      
      // Handle any unprocessed nodes (cycles or disconnected)
      nodes.forEach(n => {{
        const id = n.id();
        if (!processed.has(id)) {{
          level[id] = 0;
          order[id] = orderIdx++;
        }}
      }});
      
      // Group nodes by level
      const levelGroups = {{}};
      nodes.forEach(n => {{
        const id = n.id();
        const lvl = level[id] || 0;
        if (!levelGroups[lvl]) levelGroups[lvl] = [];
        levelGroups[lvl].push({{ id, order: order[id], node: n }});
      }});
      
      // Sort each level group by order
      Object.keys(levelGroups).forEach(lvl => {{
        levelGroups[lvl].sort((a, b) => a.order - b.order);
      }});
      
      return {{ levelGroups, levels: Object.keys(levelGroups).map(Number).sort((a, b) => a - b) }};
    }}

    // Compute positions for Left-to-Right layout
    function computePositionsLR() {{
      const {{ levelGroups, levels }} = computeLevels();
      const levelWidth = 250;
      const nodeHeight = 120;
      const startX = 100;
      const startY = 100;
      
      const positions = {{}};
      
      levels.forEach(lvl => {{
        const group = levelGroups[lvl];
        const x = startX + lvl * levelWidth;
        
        group.forEach((item, idx) => {{
          const y = startY + idx * nodeHeight;
          positions[item.id] = {{ x, y }};
        }});
      }});
      
      return positions;
    }}

    // Compute positions for Top-to-Bottom layout
    function computePositionsTB() {{
      const {{ levelGroups, levels }} = computeLevels();
      const levelHeight = 150;
      const nodeWidth = 200;
      const startX = 100;
      const startY = 100;
      
      const positions = {{}};
      
      levels.forEach(lvl => {{
        const group = levelGroups[lvl];
        const y = startY + lvl * levelHeight;
        
        group.forEach((item, idx) => {{
          const x = startX + idx * nodeWidth;
          positions[item.id] = {{ x, y }};
        }});
      }});
      
      return positions;
    }}

    // Apply layout
    function runLayout(direction) {{
      const positions = direction === 'TB' ? computePositionsTB() : computePositionsLR();
      
      cy.nodes().forEach(n => {{
        const pos = positions[n.id()];
        if (pos) {{
          n.position(pos);
        }}
      }});
      
      cy.fit(50);
      
      // Update button styles
      const lrBtn = document.getElementById('layoutLRBtn');
      const tbBtn = document.getElementById('layoutTBBtn');
      if (direction === 'TB') {{
        tbBtn.style.background = '#3B82F6';
        lrBtn.style.background = '#6B7280';
      }} else {{
        lrBtn.style.background = '#3B82F6';
        tbBtn.style.background = '#6B7280';
      }}
    }}

    runLayout('LR');

    // Controls
    document.getElementById('fitBtn').addEventListener('click', () => cy.fit(50));
    document.getElementById('zoomInBtn').addEventListener('click', () => cy.zoom(cy.zoom() * 1.2));
    document.getElementById('zoomOutBtn').addEventListener('click', () => cy.zoom(cy.zoom() / 1.2));
    document.getElementById('layoutLRBtn').addEventListener('click', () => runLayout('LR'));
    document.getElementById('layoutTBBtn').addEventListener('click', () => runLayout('TB'));

    // Highlight on click (only for non-clickable nodes)
    cy.on('tap', 'node[!isClickable]', function(evt) {{
      cy.elements().removeClass('highlighted');
      evt.target.addClass('highlighted');
      evt.target.neighborhood().addClass('highlighted');
    }});

    // Single click to navigate to data flow DAG
    cy.on('tap', 'node[?isClickable]', function(evt) {{
      const linkUrl = evt.target.data('linkUrl');
      if (linkUrl) {{
        window.location.href = linkUrl;
      }}
    }});

    cy.on('tap', function(evt) {{
      if (evt.target === cy) cy.elements().removeClass('highlighted');
    }});

    // Show hints for interactive nodes
    const clickableNodes = cy.nodes('[?isClickable]');
    const sqlNodes = cy.nodes('[?hasSql]');
    const hints = [];
    
    if (clickableNodes.length > 0) {{
      hints.push('Click Data Flow nodes to view DAG');
    }}
    if (sqlNodes.length > 0) {{
      hints.push('Hover SQL Tasks to see query');
    }}
    
    const hint = document.getElementById('clickHint');
    if (hint && hints.length > 0) {{
      hint.textContent = hints.join(' | ');
    }}

    // Change cursor on hover for clickable nodes
    cy.on('mouseover', 'node[?isClickable]', function() {{
      document.body.style.cursor = 'pointer';
    }});
    cy.on('mouseout', 'node[?isClickable]', function() {{
      document.body.style.cursor = 'default';
    }});

    // SQL Tooltip for ExecuteSQLTask nodes
    const sqlTooltip = document.getElementById('sqlTooltip');
    const sqlContent = document.getElementById('sqlContent');
    let tooltipVisible = false;

    cy.on('mouseover', 'node[?hasSql]', function(evt) {{
      const node = evt.target;
      const sql = node.data('sqlStatement');
      const sourceType = node.data('sqlSourceType');
      
      if (sql) {{
        sqlContent.textContent = sql;
        
        // Position tooltip near mouse
        const renderedPos = node.renderedPosition();
        const container = document.getElementById('cy');
        const containerRect = container.getBoundingClientRect();
        
        let left = containerRect.left + renderedPos.x + 20;
        let top = containerRect.top + renderedPos.y;
        
        // Keep tooltip on screen
        const tooltipWidth = 500;
        const tooltipHeight = 300;
        if (left + tooltipWidth > window.innerWidth) {{
          left = window.innerWidth - tooltipWidth - 20;
        }}
        if (top + tooltipHeight > window.innerHeight) {{
          top = window.innerHeight - tooltipHeight - 20;
        }}
        if (top < 10) top = 10;
        if (left < 10) left = 10;
        
        sqlTooltip.style.left = left + 'px';
        sqlTooltip.style.top = top + 'px';
        sqlTooltip.style.display = 'block';
        tooltipVisible = true;
      }}
    }});

    cy.on('mouseout', 'node[?hasSql]', function() {{
      sqlTooltip.style.display = 'none';
      tooltipVisible = false;
    }});

    // Hide tooltip when clicking elsewhere
    cy.on('tap', function() {{
      if (tooltipVisible) {{
        sqlTooltip.style.display = 'none';
        tooltipVisible = false;
      }}
    }});
  </script>
</body>
</html>'''
    
    @classmethod
    def _sort_nodes_for_layout(cls, nodes: List[Dict], edges: List[Dict]) -> List[Dict]:
        """Sort nodes so start nodes come first for better layout."""
        targets = set(e['to'] for e in edges)
        sources = set(e['from'] for e in edges)
        node_ids = set(n['id'] for n in nodes)
        
        # Build parent -> children mapping
        parent_children = {}
        for n in nodes:
            parent = n.get('parent')
            if parent not in parent_children:
                parent_children[parent] = []
            parent_children[parent].append(n)
        
        def get_order(node):
            nid = node['id']
            label = node.get('label', '').lower()
            parent = node.get('parent')
            
            # Get siblings
            siblings = parent_children.get(parent, [])
            sibling_ids = set(s['id'] for s in siblings)
            
            has_pred = any(e['to'] == nid and e['from'] in sibling_ids for e in edges)
            has_succ = any(e['from'] == nid and e['to'] in sibling_ids for e in edges)
            
            if not has_pred and has_succ:
                return (0, 0 if 'start' in label else 1, label)
            elif has_pred and not has_succ:
                return (3, 1 if 'end' in label else 0, label)
            elif has_pred and has_succ:
                return (1, 0, label)
            else:
                return (2, 0, label)
        
        return sorted(nodes, key=lambda n: (n.get('parent') or '', get_order(n)))

    @classmethod
    def _compute_levels(cls, nodes: List[Dict], edges: List[Dict]) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Compute topological levels and order for DAG nodes."""
        node_ids = {n['id'] for n in nodes}
        successors = {nid: [] for nid in node_ids}
        indegree = {nid: 0 for nid in node_ids}
        
        for edge in edges:
            src = edge.get('from')
            tgt = edge.get('to')
            if src in node_ids and tgt in node_ids:
                successors[src].append(tgt)
                indegree[tgt] += 1
        
        # Kahn's algorithm for topological order + level assignment
        queue = [nid for nid, deg in indegree.items() if deg == 0]
        level = {nid: 0 for nid in queue}
        order = {}
        order_idx = 0
        
        while queue:
            current = queue.pop(0)
            order[current] = order_idx
            order_idx += 1
            
            for nxt in successors.get(current, []):
                # Assign level based on longest path
                level[nxt] = max(level.get(nxt, 0), level.get(current, 0) + 1)
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        
        # Ensure all nodes have a level/order
        for nid in node_ids:
            if nid not in level:
                level[nid] = 0
            if nid not in order:
                order[nid] = order_idx
                order_idx += 1
        
        return level, order
    
    # ==========================================================================
    # Public Generation Methods
    # ==========================================================================
    
    @classmethod
    def generate_dag_for_data_flow(cls, data_flow: Dict, package_name: str,
                                    control_flow_dag_link: Optional[str] = None) -> Optional[str]:
        """Generate DAG HTML for a single data flow."""
        components = data_flow.get('components', [])
        if not components:
            return None
        
        data_flow_name = data_flow.get('name', 'Unknown')
        data_flow_path = data_flow.get('full_path', '')
        
        display_package_name = format_display_name(package_name)
        display_data_flow_name = format_display_name(data_flow_name)
        display_data_flow_path = unquote(data_flow_path)
        
        nodes, edges = cls.build_dag_from_components(components, 'data_flow')
        if not nodes:
            return None
        
        return cls.generate_dag_html(
            title=f"Data Flow DAG - {display_data_flow_name}",
            subtitle=f"{display_package_name} - {display_data_flow_path}",
            nodes=nodes,
            edges=edges,
            dag_type='data_flow',
            back_link=control_flow_dag_link,
            back_link_title='Back to Control Flow'
        )
    
    @classmethod
    def _get_worst_status(cls, statuses: List[str]) -> str:
        """Get the worst status from a list of statuses.
        
        Priority (worst to best): NotSupported > Partial > Unknown > Success
        """
        status_priority = {
            'NOTSUPPORTED': 0,
            'PARTIAL': 1,
            'UNKNOWN': 2,
            'SUCCESS': 3
        }
        
        worst_priority = 3  # Start with best (Success)
        worst_status = 'Success'
        
        for status in statuses:
            status_upper = status.upper() if status else 'UNKNOWN'
            priority = status_priority.get(status_upper, 2)
            if priority < worst_priority:
                worst_priority = priority
                worst_status = status
        
        return worst_status
    
    @classmethod
    def _calculate_pipeline_statuses(cls, data_flows: List[Dict]) -> Dict[str, str]:
        """Calculate the effective status for each Pipeline based on its data flow components.
        
        Returns:
            Dict mapping data flow full_path to its worst-case status
        """
        pipeline_statuses = {}
        
        for df in data_flows:
            full_path = df.get('full_path', '')
            components = df.get('components', [])
            
            if not components:
                continue
            
            # Collect all component statuses
            component_statuses = [c.get('status', 'Unknown') for c in components]
            
            # Get worst status
            worst_status = cls._get_worst_status(component_statuses)
            pipeline_statuses[full_path] = worst_status
        
        return pipeline_statuses
    
    @classmethod
    def generate_dag_for_control_flow(cls, package: Dict,
                                       data_flow_links: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Generate DAG HTML for a package's control flow.
        
        Args:
            package: Package dictionary with control_flow_components
            data_flow_links: Optional dict mapping pipeline full_name to data flow DAG URLs
        """
        components = package.get('control_flow_components', [])
        if not components:
            return None
        
        package_name = package.get('name', 'Unknown')
        package_path = package.get('path', '')
        
        display_package_name = format_display_name(package_name)
        display_path = unquote(package_path)
        
        # Calculate Pipeline statuses from data flow components
        data_flows = package.get('data_flows', [])
        pipeline_statuses = cls._calculate_pipeline_statuses(data_flows)
        
        nodes, edges = cls.build_dag_from_components(components, 'control_flow')
        if not nodes:
            return None
        
        # Override Pipeline node statuses based on their data flow components
        for node in nodes:
            if node.get('subtype') == 'Microsoft.Pipeline':
                node_id = node.get('id', '')
                if node_id in pipeline_statuses:
                    effective_status = pipeline_statuses[node_id]
                    node['status'] = effective_status
                    node['color'] = cls.get_node_color_by_status(effective_status)
        
        return cls.generate_dag_html(
            title=f"Control Flow DAG",
            subtitle=f"{display_package_name} - {display_path}",
            nodes=nodes,
            edges=edges,
            dag_type='control_flow',
            clickable_links=data_flow_links
        )
    
    @classmethod
    def generate_dags_for_package(cls, package: Dict, output_dir: Path,
                                   control_flow_dag_filename: Optional[str] = None) -> Tuple[List[str], Dict[str, str]]:
        """Generate DAG HTML files for all data flows in a package.
        
        Args:
            package: Package dictionary
            output_dir: Output directory for DAG files
            control_flow_dag_filename: Optional filename of the control flow DAG for back link
            
        Returns:
            Tuple of (list of generated file paths, dict mapping data_flow full_path to filename)
        """
        generated_files = []
        data_flow_links = {}  # Maps full_path (pipeline node ID) to DAG filename
        package_name = package.get('name', 'Unknown')
        package_path_sanitized = sanitize_filename(package.get('path', 'unknown'))
        
        for data_flow in package.get('data_flows', []):
            data_flow_full_path = data_flow.get('full_path', data_flow.get('name', 'Unknown'))
            path_parts = data_flow_full_path.replace('\\', '/').split('/')
            path_parts = [p for p in path_parts if p and p != 'Package']
            unique_suffix = '_'.join(path_parts)
            filename = f"{package_path_sanitized}__{sanitize_filename(unique_suffix)}_data_flow.html"
            
            html_content = cls.generate_dag_for_data_flow(
                data_flow, 
                package_name,
                control_flow_dag_link=control_flow_dag_filename
            )
            
            if html_content:
                filepath = output_dir / filename
                
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                
                generated_files.append(str(filepath))
                # Map the full_path to the filename for clickable links
                data_flow_links[data_flow_full_path] = filename
        
        return generated_files, data_flow_links
    
    @classmethod
    def generate_control_flow_dag_for_package(cls, package: Dict, output_dir: Path,
                                               data_flow_links: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Generate control flow DAG HTML file for a package.
        
        Args:
            package: Package dictionary
            output_dir: Output directory for DAG files
            data_flow_links: Optional dict mapping data_flow full_path to DAG filename
            
        Returns:
            Path to generated file, or None if no content
        """
        html_content = cls.generate_dag_for_control_flow(package, data_flow_links)
        
        if not html_content:
            return None
        
        package_path_sanitized = sanitize_filename(package.get('path', 'unknown'))
        filename = f"{package_path_sanitized}__control_flow.html"
        filepath = output_dir / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        return str(filepath)
    
    @classmethod
    def generate_all_dags(cls, packages: List[Dict], output_dir: str) -> Dict[str, Dict[str, Any]]:
        """
        Generate DAG HTML files for all data flows and control flows in all packages.
        
        Data flow DAGs have a back link to the control flow DAG.
        Control flow DAGs have clickable links on Pipeline nodes to open data flow DAGs.
        
        Returns:
            Dictionary mapping package paths to dict with 'data_flows' and 'control_flow' keys
        """
        output_path = Path(output_dir) / 'dags'
        output_path.mkdir(parents=True, exist_ok=True)
        
        results = {}
        total_data_flow_dags = 0
        total_control_flow_dags = 0
        
        for package in packages:
            package_path = package.get('path', 'unknown')
            package_path_sanitized = sanitize_filename(package_path)
            
            # Pre-calculate the control flow DAG filename for back links
            control_flow_dag_filename = f"{package_path_sanitized}__control_flow.html"
            
            # Generate data flow DAGs first (with back link to control flow)
            data_flow_dags, data_flow_links = cls.generate_dags_for_package(
                package, 
                output_path,
                control_flow_dag_filename=control_flow_dag_filename
            )
            
            # Generate control flow DAG (with clickable links to data flow DAGs)
            control_flow_dag = cls.generate_control_flow_dag_for_package(
                package, 
                output_path,
                data_flow_links=data_flow_links
            )
            
            if data_flow_dags or control_flow_dag:
                results[package_path] = {
                    'data_flows': data_flow_dags,
                    'control_flow': control_flow_dag
                }
                total_data_flow_dags += len(data_flow_dags) if data_flow_dags else 0
                total_control_flow_dags += 1 if control_flow_dag else 0
        
        print(f"Generated {total_data_flow_dags} data flow DAG files and {total_control_flow_dags} control flow DAG files in {output_path}", flush=True)
        
        return results
