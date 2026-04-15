import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .analyzer import ETLAssessmentAnalyzer
from .services import PackageTrackingService, ETLAnalysisReaderService, AnalysisValidatorService


def handle_etl_commands():
    """Handle ETL analysis JSON reading commands."""
    if len(sys.argv) < 4:
        print("Usage: python -m scai_assessment_analyzer.cli etl <json_file> <command> [args]")
        print("\nCommands:")
        print("  pending                      - List the first pending package found with PENDING status")
        print("  scan-package <pkg> <dtsx>    - Full package scan: info, DAGs, and extraction commands")
        print("  update <package_path> [opts] - Update package AI analysis")
        print("    --ai-status <status>       - Set AI analysis status (PENDING/DONE)")
        print("    --ai-analysis <text>       - Set AI analysis text")
        print("    --classification <type>    - Set classification (Ingestion/Data Transformation/Configuration & Control)")
        print("    --effort <hours>           - Set estimated effort hours")
        print("  ai-summary <relative_path>   - Set summary.ai_summary HTML path (relative to JSON)")
        print("  summary                      - Print consolidated summary for LLM")
        print("  stats                        - Show statistics")
        sys.exit(1)
    
    json_file = sys.argv[2]
    command = sys.argv[3]
    
    try:
        if command == 'pending':
            pending = PackageTrackingService.get_pending(json_file)
            
            if (pending is not None and len(pending) > 0):
                print(f"Name: {pending[0]['name']} | Relative Path: {pending[0]['path']}")
            else:
                print("No pending packages found")
                sys.exit(1)
            return
        elif command == 'scan-package' and len(sys.argv) > 5:
            package_path = sys.argv[4]
            dtsx_path = sys.argv[5]
            
            result = ETLAnalysisReaderService.get_package(json_file, package_path)
            if not result:
                print(f"Package not found: {package_path}", file=sys.stderr)
                sys.exit(1)
            
            if not Path(dtsx_path).exists():
                print(f"DTSX file not found: {dtsx_path}", file=sys.stderr)
                sys.exit(1)
            
            print("=" * 70)
            print("PACKAGE INFO")
            print("=" * 70)
            print(json.dumps(result, indent=2))
            
            print("\n" + "=" * 70)
            print("CONTROL FLOW DAG")
            print("=" * 70)
            dag_result = ETLAnalysisReaderService.get_control_flow_dag(json_file, package_path)
            if dag_result:
                print(dag_result)

            package_full = ETLAnalysisReaderService.get_package_full(json_file, package_path)
            if package_full:
                data_flows = package_full.get('data_flows', [])
                if data_flows:
                    for df in data_flows:
                        df_path = df.get('full_path', '')
                        print("\n" + "=" * 70)
                        print(f"DATA FLOW: {df_path}")
                        print("=" * 70)
                        df_dag = ETLAnalysisReaderService.get_data_flow_dag(json_file, package_path, df_path)
                        if df_dag:
                            print(df_dag)
            
            # Execute extraction commands
            # TODO: This is a temporary solution to extract the data from the DTSX file, we need to find a better way to do this
            import subprocess
            
            def run_grep(pattern, file_path, after=10, before=0, head=None):
                """Run grep and return output."""
                try:
                    cmd = ['grep']
                    if before > 0:
                        cmd.extend(['-B', str(before)])
                    if after > 0:
                        cmd.extend(['-A', str(after)])
                    cmd.extend([pattern, file_path])
                    
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    output = result.stdout
                    
                    if head and output:
                        lines = output.split('\n')[:head]
                        output = '\n'.join(lines)
                    
                    return output if output else "(No matches found)"
                except subprocess.TimeoutExpired:
                    return "(Command timed out)"
                except Exception as e:
                    return f"(Error: {e})"
            
            print("\n" + "=" * 70)
            print("VARIABLES")
            print("=" * 70)
            print(run_grep('<DTS:Variables>', dtsx_path, after=100, head=150))
            
            print("\n" + "=" * 70)
            print("SQL STATEMENTS")
            print("=" * 70)
            print(run_grep('SQLTask:SqlStatementSource=', dtsx_path, after=10, before=10, head=300))
            
            print("\n" + "=" * 70)
            print("CONNECTION MANAGERS")
            print("=" * 70)
            print(run_grep('<DTS:ConnectionManagers>', dtsx_path, after=50, head=200))
            
            print("\n" + "=" * 70)
            print("SCRIPT TASKS")
            print("=" * 70)
            print(run_grep('DTS:ExecutableType="Microsoft.ScriptTask"', dtsx_path, before=5, after=50))
            
            return
        elif command == 'update' and len(sys.argv) > 4:
            package_path = sys.argv[4]
            ai_status = None
            ai_analysis_text = None
            classification = None
            estimated_effort_hours = None
            
            i = 5
            while i < len(sys.argv):
                if sys.argv[i] == '--ai-status' and i + 1 < len(sys.argv):
                    ai_status = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == '--ai-analysis' and i + 1 < len(sys.argv):
                    ai_analysis_text = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == '--classification' and i + 1 < len(sys.argv):
                    classification = sys.argv[i + 1]
                    i += 2
                elif sys.argv[i] == '--effort' and i + 1 < len(sys.argv):
                    estimated_effort_hours = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1
            
            # Validate ai_analysis structure if provided and status is DONE
            if ai_analysis_text and ai_status == 'DONE':
                is_valid, error_message = AnalysisValidatorService.validate_and_report(
                    ai_analysis_text, package_path
                )
                if not is_valid:
                    print(error_message, file=sys.stderr)
                    sys.exit(1)
            
            if PackageTrackingService.update_package(json_file, package_path, ai_status, ai_analysis_text, 
                                                    classification, estimated_effort_hours):
                print(f"Updated: {package_path}")
            else:
                print(f"Package not found: {package_path}", file=sys.stderr)
                sys.exit(1)
            return
        elif command == 'ai-summary' and len(sys.argv) > 4:
            summary_path = sys.argv[4]
            PackageTrackingService.update_ai_summary(json_file, summary_path)
            print(f"Updated summary.ai_summary: {summary_path}")
            return
        elif command == 'summary':
            summary_payload = PackageTrackingService.get_summary_for_llm(json_file)
            print(summary_payload)
            return
        elif command == 'stats':
            stats = PackageTrackingService.get_statistics(json_file)
            print(f"Total Packages: {stats['total']}")
            print(f"AI Analysis - Pending: {stats['pending']}")
            print(f"AI Analysis - Done: {stats['reviewed']}")
            print(f"Packages with Scripts: {stats['with_scripts']}")
            print(f"\nClassifications:")
            for cls, count in stats.get('classifications', {}).items():
                print(f"  {cls}: {count}")
            return
        else:
            print(f"Unknown command: {command}", file=sys.stderr)
            sys.exit(1)
        
        print(json.dumps(result, indent=2))
    
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == 'etl':
        handle_etl_commands()
        return
    
    if len(sys.argv) < 5:
        print("Usage: python -m scai_assessment_analyzer <elements_csv> <issues_csv> <ssis_source_dir> <output_folder>")
        print("       python -m scai_assessment_analyzer etl <json_file> <command> [args]")
        print("\nAnalysis mode:")
        print("  python -m scai_assessment_analyzer ETL.Elements.csv ETL.Issues.csv ./ssis_packages ./output")
        print("\nETL Analysis mode:")
        print("  python -m scai_assessment_analyzer etl <json_file> pending")
        print("  python -m scai_assessment_analyzer etl <json_file> scan-package <package_path> <dtsx_file>")
        print("  python -m scai_assessment_analyzer etl <json_file> update <package_path> --ai-status DONE --classification 'Ingestion'")
        print("  python -m scai_assessment_analyzer etl <json_file> update <package_path> --ai-analysis 'Purpose: ...' --effort 8")
        print("  python -m scai_assessment_analyzer etl <json_file> ai-summary ai_ssis_summary.html")
        print("  python -m scai_assessment_analyzer etl <json_file> summary")
        print("  python -m scai_assessment_analyzer etl <json_file> stats")
        sys.exit(1)

    elements_file = sys.argv[1]
    issues_file = sys.argv[2]
    ssis_source_dir = sys.argv[3]
    output_folder = sys.argv[4]
    output_json = Path(f"{output_folder}/etl_assessment_analysis.json")

    try:
        analyzer = ETLAssessmentAnalyzer(elements_file, issues_file, ssis_source_dir)
        analyzer.analyze()
        analyzer.export_to_json(str(output_json))
        
        print(f"\nETL assessment analysis JSON export saved to: {output_json}")

    except FileNotFoundError as e:
        print(f"Error: File not found: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

