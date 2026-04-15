from pathlib import Path
from typing import Dict

from .models import PackageAnalysis
from .repositories import ElementRepository, IssueRepository
from .services import IssueLookupService, ComponentOrganizerService, AnalysisService, DataFlowDagService, SqlTaskExtractorService
from .utils import Config


class ETLAssessmentAnalyzer:
    def __init__(self, elements_file: str, issues_file: str, ssis_source_dir: str):
        self.elements_file = elements_file
        self.issues_file = issues_file
        self.ssis_source_dir = ssis_source_dir
        self.packages: Dict[str, PackageAnalysis] = {}

        self.issue_lookup_service = IssueLookupService()
        self.organizer_service = ComponentOrganizerService()
        self.analysis_service = AnalysisService()
        self.dag_service = DataFlowDagService()
        self.sql_task_extractor = SqlTaskExtractorService()

    def analyze(self):
        components_by_key, excluded_count = self._load_elements()
        print(f"Total components loaded: {len(components_by_key)} (excluded: {excluded_count})")

        matched, not_matched = self._load_issues(components_by_key)
        print(f"Issues matched: {matched}, not matched: {not_matched}")

        self.packages = self._organize_by_packages(components_by_key)
        
        # Enrich ExecuteSQLTask components with SQL details from DTSX files
        self._enrich_sql_task_components()

    def _load_elements(self):
        repository = ElementRepository(
            self.elements_file,
            Config.EXCLUDED_COMPONENT_SUBTYPES
        )
        return repository.load_components()

    def _load_issues(self, components_by_key):
        repository = IssueRepository(
            self.issues_file,
            self.issue_lookup_service
        )
        return repository.load_and_attach_issues(components_by_key)

    def _organize_by_packages(self, components_by_key):
        return self.organizer_service.organize_by_packages(components_by_key)

    def _enrich_sql_task_components(self):
        """Enrich ExecuteSQLTask components with SQL details from DTSX source files."""
        # Extract SQL tasks from all DTSX files
        all_sql_tasks = self.sql_task_extractor.extract_all_sql_tasks(self.ssis_source_dir)
        
        if not all_sql_tasks:
            print("Warning: No SQL task details extracted from DTSX files")
            return
        
        enriched_count = 0
        
        for package_path, package in self.packages.items():
            # Find matching DTSX file - try different path variations
            sql_tasks = self._find_sql_tasks_for_package(package_path, all_sql_tasks)
            
            if not sql_tasks:
                continue
            
            # Enrich control flow components
            for component in package.control_flow_components:
                if component.subtype == 'Microsoft.ExecuteSQLTask':
                    sql_details = self.sql_task_extractor.match_component_to_sql_task(
                        component.full_name, sql_tasks
                    )
                    if sql_details:
                        component.sql_task_details = sql_details
                        enriched_count += 1
        
        print(f"Enriched {enriched_count} ExecuteSQLTask components with SQL details")
    
    def _find_sql_tasks_for_package(self, package_path: str, all_sql_tasks: dict) -> dict:
        """Find SQL tasks for a package, trying different path variations."""
        # Normalize package path
        normalized_path = package_path.replace('\\', '/')
        
        # Direct match
        if normalized_path in all_sql_tasks:
            return all_sql_tasks[normalized_path]
        
        # Try matching by filename only
        package_filename = normalized_path.split('/')[-1]
        for dtsx_path, sql_tasks in all_sql_tasks.items():
            dtsx_filename = dtsx_path.replace('\\', '/').split('/')[-1]
            if dtsx_filename == package_filename:
                return sql_tasks
        
        # Try matching by partial path (last 2-3 segments)
        path_parts = normalized_path.split('/')
        for num_parts in [3, 2]:
            if len(path_parts) >= num_parts:
                partial_path = '/'.join(path_parts[-num_parts:])
                for dtsx_path, sql_tasks in all_sql_tasks.items():
                    normalized_dtsx = dtsx_path.replace('\\', '/')
                    if normalized_dtsx.endswith(partial_path):
                        return sql_tasks
        
        return {}

    def export_to_json(self, output_path: str, generate_dags: bool = True):
        self.analysis_service.export_to_json(self.packages, output_path)
        
        if generate_dags:
            self.generate_data_flow_dags(output_path)
    
    def generate_data_flow_dags(self, output_path: str):
        """Generate HTML DAG visualizations for all data flows."""
        output_dir = str(Path(output_path).parent)
        packages_data = [pkg.to_dict() for pkg in self.packages.values()]
        self.dag_service.generate_all_dags(packages_data, output_dir)

