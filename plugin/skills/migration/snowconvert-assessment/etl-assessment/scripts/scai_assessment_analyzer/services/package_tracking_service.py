import json
from typing import List, Dict, Optional


class PackageTrackingService:
    
    @staticmethod
    def read_json(json_path: str) -> Dict:
        """Read full JSON data"""
        with open(json_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @staticmethod
    def write_json(json_path: str, data: Dict) -> None:
        """Write complete JSON data back to file"""
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    @staticmethod
    def get_pending(json_path: str) -> List[Dict[str, str]]:
        """Get packages where ai_analysis.status is PENDING"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        return [p for p in packages if p.get('ai_analysis', {}).get('status', 'PENDING') == 'PENDING']
    
    @staticmethod
    def get_package(json_path: str, package_path: str) -> Optional[Dict]:
        """Get a specific package by path"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        for package in packages:
            if package.get('path') == package_path:
                return package
        return None
    
    @staticmethod
    def update_package(json_path: str, package_path: str, 
                      ai_status: Optional[str] = None, 
                      ai_analysis_text: Optional[str] = None,
                      classification: Optional[str] = None,
                      estimated_effort_hours: Optional[str] = None) -> bool:
        """Update package AI analysis information within ai_analysis property"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        found = False
        
        for package in packages:
            if package.get('path') == package_path:
                if 'ai_analysis' not in package:
                    package['ai_analysis'] = {}
                
                if ai_status is not None:
                    package['ai_analysis']['status'] = ai_status
                if ai_analysis_text is not None:
                    package['ai_analysis']['analysis'] = ai_analysis_text
                if classification is not None:
                    package['ai_analysis']['classification'] = classification
                if estimated_effort_hours is not None:
                    package['ai_analysis']['estimated_effort_hours'] = estimated_effort_hours
                found = True
                break
        
        if found:
            PackageTrackingService.write_json(json_path, data)
        
        return found

    @staticmethod
    def update_ai_summary(json_path: str, ai_summary_path: str) -> None:
        """Update summary.ai_summary with a relative HTML path."""
        data = PackageTrackingService.read_json(json_path)
        if 'summary' not in data or not isinstance(data['summary'], dict):
            data['summary'] = {}
        data['summary']['ai_summary'] = ai_summary_path
        PackageTrackingService.write_json(json_path, data)
    
    @staticmethod
    def get_statistics(json_path: str) -> Dict[str, int]:
        """Get statistics about package analysis status and classifications"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        
        classifications = {}
        for package in packages:
            ai_analysis = package.get('ai_analysis', {})
            cls = ai_analysis.get('classification', 'Unclassified')
            if not cls:  # Handle empty string
                cls = 'Unclassified'
            classifications[cls] = classifications.get(cls, 0) + 1
        
        return {
            'total': len(packages),
            'pending': sum(1 for p in packages if p.get('ai_analysis', {}).get('status', 'PENDING') == 'PENDING'),
            'reviewed': sum(1 for p in packages if p.get('ai_analysis', {}).get('status', '') == 'DONE'),
            'with_scripts': sum(1 for p in packages if p.get('flags', {}).get('has_scripts', False)),
            'classifications': classifications
        }

    @staticmethod
    def get_summary_for_llm(json_path: str) -> str:
        """Get a consolidated summary for LLM consumption."""
        data = PackageTrackingService.read_json(json_path)
        summary = data.get('summary', {})
        packages = data.get('packages', [])

        classifications = {}
        connection_managers = []

        def parse_additional_info(value):
            if isinstance(value, dict):
                return value
            if isinstance(value, str) and value.strip().startswith('{'):
                try:
                    return json.loads(value)
                except Exception:
                    return {}
            return {}

        # AI analysis per package + classifications + connection managers
        ai_lines = []
        for package in packages:
            name = package.get('name') or package.get('path') or 'Unknown'
            ai_analysis = package.get('ai_analysis', {})
            ai_text = (ai_analysis.get('analysis') or '').strip()
            ai_lines.append(f"- {name}: {ai_text or 'No AI analysis provided'}")

            cls = ai_analysis.get('classification', 'Unclassified') or 'Unclassified'
            classifications[cls] = classifications.get(cls, 0) + 1

            for cm in package.get('connection_managers', []):
                info = parse_additional_info(cm.get('additional_info'))
                creation = info.get('creationName', 'Unknown')
                cm_name = cm.get('full_name') or cm.get('name') or 'Unknown'
                connection_managers.append(f"- {cm_name} (type: {creation})")

        # Summary top-level fields
        summary_fields = {
            'packages': summary.get('packages', 0),
            'connection managers': summary.get('connection managers', 0),
            'control flow components': summary.get('control flow components', 0),
            'data flow components': summary.get('data flow components', 0),
            'not supported elements': summary.get('not supported elements', {})
        }

        not_supported = summary_fields['not supported elements']
        not_supported_count = not_supported.get('total_count', 0) if isinstance(not_supported, dict) else 0
        not_supported_types = not_supported.get('component_types', []) if isinstance(not_supported, dict) else []

        lines = []
        lines.append("AI Analysis per Package:")
        lines.extend(ai_lines)
        lines.append("")
        lines.append("Classification Counts:")
        for cls, count in sorted(classifications.items()):
            lines.append(f"- {cls}: {count}")
        lines.append("")
        lines.append("Summary (Top-Level):")
        lines.append(f"- packages: {summary_fields['packages']}")
        lines.append(f"- connection managers: {summary_fields['connection managers']}")
        lines.append(f"- control flow components: {summary_fields['control flow components']}")
        lines.append(f"- data flow components: {summary_fields['data flow components']}")
        lines.append(f"- not supported elements: {not_supported_count}")
        if not_supported_types:
            lines.append(f"  types: {', '.join(not_supported_types)}")
        lines.append("")
        lines.append("Connection Managers (name + creationName):")
        lines.extend(connection_managers)

        return "\n".join(lines)
    
    @staticmethod
    def get_by_classification(json_path: str, classification: str) -> List[Dict]:
        """Get packages by classification type (Ingestion, Data Transformation, Configuration & Control)"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        return [p for p in packages if p.get('ai_analysis', {}).get('classification', '') == classification]
    
    @staticmethod
    def get_packages_with_scripts(json_path: str) -> List[Dict]:
        """Get packages that contain script tasks (red flag packages)"""
        data = PackageTrackingService.read_json(json_path)
        packages = data.get('packages', [])
        return [p for p in packages if p.get('flags', {}).get('has_scripts', False)]

