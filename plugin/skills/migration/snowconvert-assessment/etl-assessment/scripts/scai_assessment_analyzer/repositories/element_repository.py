import sys
from pathlib import Path
from typing import Dict, Tuple, Set

# Add shared scripts to path for snowconvert_reports
_scripts_dir = str(Path(__file__).resolve().parents[4] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from snowconvert_reports import load_elements, Element
from ..models import Component


class ElementRepository:
    def __init__(self, file_path: str, excluded_subtypes: Set[str]):
        self.file_path = Path(file_path)
        self.excluded_subtypes = excluded_subtypes

    def load_components(self) -> Tuple[Dict[Tuple[str, str], Component], int]:
        elements = load_elements(self.file_path)

        components_by_key = {}
        excluded_count = 0

        for elem in elements:
            if not elem.full_name or not elem.file_name:
                continue
            if elem.subtype in self.excluded_subtypes:
                excluded_count += 1
                continue

            component = Component(
                full_name=elem.full_name,
                file_name=elem.file_name,
                technology=elem.technology,
                category=elem.category,
                subtype=elem.subtype,
                status=elem.status,
                entry_kind=elem.entry_kind,
                additional_info=elem.additional_info,
            )
            component_key = (elem.file_name, elem.full_name)
            components_by_key[component_key] = component

        return components_by_key, excluded_count
