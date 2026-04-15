"""
AI Analysis Structure Validator

Validates that ai_analysis text follows the mandatory format:
- Classification: [text]
- Sources & Destinations: [text]  (or "Sources and Destinations:")
- Purpose: [text]
- Conversion: [text]

Each section must be a separate paragraph (separated by blank lines).
Each section must have sufficient content to ensure quality analysis.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple, Optional


@dataclass
class ValidationResult:
    """Result of validating an ai_analysis entry."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]


@dataclass
class SectionContent:
    """Extracted content for a section."""
    name: str
    content: str
    char_count: int
    word_count: int


class AnalysisValidatorService:
    """Validates ai_analysis structure for ETL assessment packages."""
    
    REQUIRED_SECTIONS = {
        "Classification": r"(?:^|\n\n)Classification:",
        "Sources & Destinations": r"(?:^|\n\n)Sources\s*(?:&|and)\s*Destinations:",
        "Purpose": r"(?:^|\n\n)Purpose:",
        "Conversion": r"(?:^|\n\n)Conversion:",
    }
    
    SECTION_MIN_CHARS = {
        "Classification": 100,
        "Sources & Destinations": 50,
        "Purpose": 50,
        "Conversion": 50,
    }
    
    SECTION_MIN_WORDS = {
        "Classification": 30,
        "Sources & Destinations": 10,
        "Purpose": 10,
        "Conversion": 10,
    }
    
    SECTION_EXTRACT_PATTERNS = {
        "Classification": r"Classification:\s*(.*?)(?=\n\n(?:Sources\s*(?:&|and)\s*Destinations:|Purpose:|Conversion:)|$)",
        "Sources & Destinations": r"Sources\s*(?:&|and)\s*Destinations:\s*(.*?)(?=\n\n(?:Purpose:|Conversion:)|$)",
        "Purpose": r"Purpose:\s*(.*?)(?=\n\nConversion:|$)",
        "Conversion": r"Conversion:\s*(.*?)$",
    }

    
    INLINE_SECTION_PATTERNS = {
        "Sources & Destinations inline": r"[^\n][ \t]{2,}Sources\s*(?:&|and)\s*Destinations:",
        "Purpose inline": r"[^\n][ \t]{2,}Purpose:",
        "Conversion inline": r"[^\n][ \t]{2,}Conversion:",
    }
    
    WRITING_GUIDE_PATH = "/references/writing_analysis.md"
    EXAMPLE_PATH = "/references/analysis_example.md"
    
    @classmethod
    def extract_section_content(cls, analysis_text: str, section_name: str) -> Optional[SectionContent]:
        """
        Extract the content of a specific section from the analysis text.
        
        Args:
            analysis_text: The full analysis text
            section_name: Name of the section to extract
            
        Returns:
            SectionContent with the extracted text and metrics, or None if not found
        """
        pattern = cls.SECTION_EXTRACT_PATTERNS.get(section_name)
        if not pattern:
            return None
            
        match = re.search(pattern, analysis_text, re.IGNORECASE | re.DOTALL)
        if not match:
            return None
            
        content = match.group(1).strip()
        words = [w for w in content.split() if w]
        
        return SectionContent(
            name=section_name,
            content=content,
            char_count=len(content),
            word_count=len(words)
        )
    
    @classmethod
    def validate_section_quality(cls, analysis_text: str) -> Tuple[List[str], List[str]]:
        """
        Validate that each section has sufficient content.
        
        Args:
            analysis_text: The analysis text to validate
            
        Returns:
            Tuple of (errors, warnings) lists
        """
        errors = []
        warnings = []
        
        for section_name in cls.REQUIRED_SECTIONS.keys():
            section = cls.extract_section_content(analysis_text, section_name)
            
            if not section:
                continue
            
            min_chars = cls.SECTION_MIN_CHARS.get(section_name, 50)
            min_words = cls.SECTION_MIN_WORDS.get(section_name, 10)
            
            if section.char_count < min_chars // 2 or section.word_count < min_words // 2:
                errors.append(
                    f"'{section_name}' section is too brief ({section.word_count} words, "
                    f"{section.char_count} chars). Minimum required: {min_words} words, "
                    f"{min_chars} chars. Provide substantive content with reasoning."
                )

            elif section.char_count < min_chars or section.word_count < min_words:
                errors.append(
                    f"'{section_name}' section lacks sufficient detail ({section.word_count} words, "
                    f"{section.char_count} chars). Minimum required: {min_words} words, "
                    f"{min_chars} chars."
                )
        
        return errors, warnings
    
    @classmethod
    def validate(cls, analysis_text: str) -> ValidationResult:
        """
        Validate an ai_analysis text string.
        
        Args:
            analysis_text: The analysis text to validate
            
        Returns:
            ValidationResult with is_valid, errors, and warnings
        """
        if not analysis_text or not analysis_text.strip():
            return ValidationResult(
                is_valid=False,
                errors=["Analysis text is empty"],
                warnings=[]
            )
        
        errors = []
        warnings = []
        
        missing_sections = []
        for section_name, pattern in cls.REQUIRED_SECTIONS.items():
            if not re.search(pattern, analysis_text, re.IGNORECASE):
                missing_sections.append(section_name)
        
        if missing_sections:
            errors.append(f"Missing required sections: {', '.join(missing_sections)}")

        inline_found = []
        for pattern_name, pattern in cls.INLINE_SECTION_PATTERNS.items():
            if re.search(pattern, analysis_text, re.IGNORECASE):
                inline_found.append(pattern_name.replace(" inline", ""))
        
        if inline_found:
            errors.append(
                f"Sections appear inline (newlines stripped): {', '.join(inline_found)}. "
                "Use $'...\\n\\n...' syntax in bash or ensure proper paragraph breaks."
            )

        paragraph_breaks = analysis_text.count("\n\n")
        if paragraph_breaks < 2:
            errors.append(
                f"Insufficient paragraph separation (found {paragraph_breaks}, need at least 3 paragraphs). "
                "Sections must be separated by blank lines."
            )
        
        classification_match = re.search(r"Classification:", analysis_text, re.IGNORECASE)
        if classification_match and classification_match.start() > 50:
            warnings.append("Classification section should appear at the beginning of the analysis")
        
        quality_errors, quality_warnings = cls.validate_section_quality(analysis_text)
        errors.extend(quality_errors)
        warnings.extend(quality_warnings)
        
        is_valid = len(errors) == 0
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings
        )
    
    @classmethod
    def get_validation_error_message(cls, result: ValidationResult, package_path: str) -> str:
        """
        Generate a helpful error message for the LLM when validation fails.
        
        Args:
            result: The ValidationResult from validate()
            package_path: The package path being updated
            
        Returns:
            Formatted error message with guidance
        """
        lines = [
            "",
            "=" * 70,
            "AI ANALYSIS VALIDATION FAILED",
            "=" * 70,
            f"Package: {package_path}",
            "",
            "ERRORS:",
        ]
        
        for error in result.errors:
            lines.append(f"  - {error}")
        
        if result.warnings:
            lines.append("")
            lines.append("WARNINGS:")
            for warning in result.warnings:
                lines.append(f"  - {warning}")
        
        lines.extend([
            "",
            "-" * 70,
            "REQUIRED FORMAT:",
            "-" * 70,
            "",
            "The analysis MUST contain exactly these four sections as separate paragraphs.",
            "",
            "BASH SYNTAX - Use $'...' with literal \\n\\n for newlines:",
            "",
            "  --ai-analysis $'Classification: [text]\\n\\nSources & Destinations: [text]\\n\\nPurpose: [text]\\n\\nConversion: [text]'",
            "",
            "RULES:",
            "  1. Each section header must start at the beginning of a paragraph",
            "  2. Use exact labels: 'Classification:', 'Sources & Destinations:', 'Purpose:', 'Conversion:'",
            "  3. Sections must be separated by \\n\\n (blank lines)",
            "",
            "-" * 70,
            "MINIMUM CONTENT REQUIREMENTS:",
            "-" * 70,
            "",
            "Each section MUST have sufficient content. Brief one-liners are NOT acceptable.",
            "",
            "  Classification:           min 100 chars, 30 words (category + reasoning + evidence, why this classification applies)",
            "  Sources & Destinations:   min 50 chars, 10 words (list with INTERNAL/EXTERNAL labels), if it does not have sources and/or destinations add a note to the analysis in this section",
            "  Purpose:                  min 100 chars, 30 words (business context, why this package exists, how relate to the business needs)",
            "  Conversion:               min 100 chars, 30 words (assessment + explanation)",
            "",
            "QUALITY EXPECTATIONS:",
            "  - Classification: State category + 2-3 sentences explaining WHY, why this classification applies",
            "  - Sources & Destinations: List each source/destination with INTERNAL/EXTERNAL label, if it does not have sources and/or destinations add a note to the analysis in this section",
            "  - Purpose: Describe business value, not just 'loads data', why this package exists, how relate to the business needs",
            "  - Conversion: Assessment rating + what converts + any concerns, why this conversion is suitable or not suitable for SnowConvert",
            "",
            "-" * 70,
            f"READ THE GUIDE provided in the snowconvert-assessment skill for ETL-SSIS: {cls.WRITING_GUIDE_PATH}",
            f"READ THE EXAMPLEs provided in the snowconvert-assessment skill for ETL-SSIS: {cls.EXAMPLE_PATH}",
            "-" * 70,
            "",
        ])
        
        return "\n".join(lines)
    
    @classmethod
    def validate_and_report(cls, analysis_text: str, package_path: str) -> Tuple[bool, str]:
        """
        Validate analysis and return tuple of (is_valid, error_message).
        
        Args:
            analysis_text: The analysis text to validate
            package_path: The package path for error reporting
            
        Returns:
            Tuple of (is_valid: bool, error_message: str)
            If valid, error_message will be empty.
        """
        result = cls.validate(analysis_text)
        
        if result.is_valid:
            return True, ""
        
        error_message = cls.get_validation_error_message(result, package_path)
        return False, error_message
