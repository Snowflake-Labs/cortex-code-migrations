"""Filename utility functions for sanitizing and handling file names."""

import re
from urllib.parse import unquote


def sanitize_filename(name: str) -> str:
    """Convert a name to a valid filename.
    
    Handles URL-encoded characters, special characters, and ensures
    clean filenames.
    
    Args:
        name: The original name (may contain special chars, URL encoding, etc.)
        
    Returns:
        A sanitized filename
        
    Examples:
        >>> sanitize_filename('Package%20With%20Spaces.dtsx')
        'Package_With_Spaces'
        >>> sanitize_filename('Package-With-Hyphens.dtsx')
        'Package_With_Hyphens'
    """
    sanitized = unquote(name)
    sanitized = re.sub(r'\.dtsx$', '', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'[^\w]', '_', sanitized)
    sanitized = re.sub(r'_+', '_', sanitized)
    sanitized = sanitized.strip('_')
    return sanitized


def format_display_name(name: str) -> str:
    """Convert a name to a readable display name.
    
    Args:
        name: The original name
        
    Returns:
        A readable display name
        
    Examples:
        >>> format_display_name('PBI%20Tables%20Data%20Loading.dtsx')
        'PBI Tables Data Loading'
        >>> format_display_name('QIS_Reporting_-_ETL_DB2%20to%20SQL.dtsx')
        'QIS_Reporting_-_ETL_DB2 to SQL'
    """
    name = unquote(name)
    name = re.sub(r'\.dtsx$', '', name, flags=re.IGNORECASE)
    return name
