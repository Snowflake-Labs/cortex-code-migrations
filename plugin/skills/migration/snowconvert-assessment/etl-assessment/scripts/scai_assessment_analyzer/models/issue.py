from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    code: str
    name: str
    description: str
    component_full_name: str
    effort_hours: float
    severity: str

    @property
    def issue_type(self) -> str:
        if 'EWI' in self.code:
            return 'EWI'
        elif 'FDM' in self.code:
            return 'FDM'
        elif 'PRF' in self.code:
            return 'PRF'
        return 'UNKNOWN'

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'type': self.issue_type,
            'description': self.description,
            'severity': self.severity
        }

