class Config:
    EXCLUDED_COMPONENT_SUBTYPES = {
        'Path',
        'Package',
        'PrecedenceConstraint',
    }

    DEFAULT_SEVERITY_EFFORT = {
        'Critical': 120,
        'High': 45,
        'Medium': 16.5,
        'Low': 3.5,
        'None': 0
    }

