from dataclasses import dataclass


@dataclass(frozen=True)
class Element:
    """A single row from SnowConvert Elements.csv."""

    full_name: str
    file_name: str
    technology: str
    category: str
    subtype: str
    status: str
    entry_kind: str
    additional_info: str

    @staticmethod
    def from_csv_row(row: dict[str, str]) -> "Element":
        return Element(
            full_name=row.get("FullName", "").strip(),
            file_name=row.get("FileName", "").strip(),
            technology=row.get("Technology", "").strip(),
            category=row.get("Category", "").strip(),
            subtype=row.get("Subtype", "").strip(),
            status=row.get("Status", "").strip(),
            entry_kind=row.get("Entry Kind", "").strip(),
            additional_info=row.get("Additional Info", "").strip(),
        )
