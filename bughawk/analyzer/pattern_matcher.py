"""Pattern matcher for common error patterns.

This module implements pattern matching for well-known error types,
allowing BugHawk to quickly identify and suggest fixes for common bugs
without always needing to call an LLM.

The hawk has catalogued its most common prey - these patterns represent
bugs that are frequently spotted in the wild and have known remedies.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from bughawk.core.models import SentryIssue, StackTrace
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


class ErrorCategory(str, Enum):
    """Categories of common errors.

    These represent the different hunting grounds where the hawk
    typically finds its prey.
    """

    NULL_REFERENCE = "null_reference"
    INDEX_OUT_OF_BOUNDS = "index_out_of_bounds"
    KEY_NOT_FOUND = "key_not_found"
    TYPE_ERROR = "type_error"
    DIVISION_BY_ZERO = "division_by_zero"
    IMPORT_ERROR = "import_error"
    ASYNC_ERROR = "async_error"
    ATTRIBUTE_ERROR = "attribute_error"
    VALUE_ERROR = "value_error"
    IO_ERROR = "io_error"
    PERMISSION_ERROR = "permission_error"
    TIMEOUT_ERROR = "timeout_error"
    CONNECTION_ERROR = "connection_error"
    SYNTAX_ERROR = "syntax_error"
    MEMORY_ERROR = "memory_error"
    UNKNOWN = "unknown"


@dataclass
class FixTemplate:
    """Template for a suggested fix.

    The hawk's tried-and-true hunting technique for this type of prey.
    """

    description: str
    code_template: str
    explanation: str
    caveats: list[str] = field(default_factory=list)


@dataclass
class ErrorPattern:
    """Represents a known error pattern.

    This is a profile of prey that the hawk has successfully hunted before.
    Each pattern contains everything needed to identify and address the error.
    """

    id: str
    name: str
    category: ErrorCategory
    description: str

    # Pattern matching criteria
    exception_types: list[str]
    message_patterns: list[str]  # Regex patterns for error messages
    code_patterns: list[str]  # Regex patterns for code snippets

    # Knowledge about this error
    common_causes: list[str]
    typical_fixes: list[FixTemplate]
    examples: list[dict[str, str]]

    # Metadata
    languages: list[str]  # Languages where this pattern applies
    severity: str  # low, medium, high, critical
    documentation_links: list[str] = field(default_factory=list)

    # Runtime matching data
    confidence: float = 0.0
    matched_by: str = ""


@dataclass
class PatternMatch:
    """Result of pattern matching.

    The hawk's assessment of the prey it has spotted.
    """

    pattern: ErrorPattern
    confidence: float
    matched_exception: bool
    matched_message: bool
    matched_code: bool
    match_details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_confident_match(self) -> bool:
        """Check if this is a high-confidence match (hawk is certain of its prey)."""
        return self.confidence >= 0.7

    @property
    def suggested_fix(self) -> FixTemplate | None:
        """Get the most relevant fix template."""
        if self.pattern.typical_fixes:
            return self.pattern.typical_fixes[0]
        return None


class PatternMatcher:
    """Matches errors against known patterns.

    The hawk's pattern recognition system - trained to spot common prey
    from afar and swoop in with precision.

    This class loads patterns from a JSON file and matches incoming
    errors against them, providing quick suggestions for common issues.

    Example:
        >>> matcher = PatternMatcher()
        >>> match = matcher.match_pattern(issue)
        >>> if match and match.is_confident_match:
        ...     print(f"Found: {match.pattern.name}")
        ...     print(f"Fix: {match.suggested_fix.description}")
    """

    # Default patterns file location
    DEFAULT_PATTERNS_FILE = Path(__file__).parent / "patterns.json"

    def __init__(self, patterns_file: Path | None = None) -> None:
        """Initialize PatternMatcher.

        The hawk sharpens its talons and reviews its prey catalog.

        Args:
            patterns_file: Path to JSON file with pattern definitions.
                          Uses default patterns.json if not provided.
        """
        self.patterns_file = patterns_file or self.DEFAULT_PATTERNS_FILE
        self.patterns: list[ErrorPattern] = []

        self._load_patterns()
        logger.info(
            "Hawk's pattern recognition loaded: %d prey profiles catalogued",
            len(self.patterns),
        )

    def _load_patterns(self) -> None:
        """Load patterns from JSON file.

        The hawk reviews its hunting journal, loading knowledge of past prey.
        """
        if not self.patterns_file.exists():
            logger.warning(
                "Hawk's prey catalog not found at %s, using built-in patterns",
                self.patterns_file,
            )
            self._load_builtin_patterns()
            return

        try:
            with open(self.patterns_file, encoding="utf-8") as f:
                data = json.load(f)

            for pattern_data in data.get("patterns", []):
                pattern = self._parse_pattern(pattern_data)
                if pattern:
                    self.patterns.append(pattern)

            logger.debug("Loaded %d patterns from %s", len(self.patterns), self.patterns_file)

        except json.JSONDecodeError as e:
            logger.error("Failed to parse patterns file: %s", e)
            self._load_builtin_patterns()
        except OSError as e:
            logger.error("Failed to read patterns file: %s", e)
            self._load_builtin_patterns()

    def _parse_pattern(self, data: dict[str, Any]) -> ErrorPattern | None:
        """Parse a pattern from JSON data.

        Args:
            data: Pattern dictionary from JSON

        Returns:
            ErrorPattern or None if parsing fails
        """
        try:
            # Parse fix templates
            fixes = []
            for fix_data in data.get("typical_fixes", []):
                fixes.append(
                    FixTemplate(
                        description=fix_data.get("description", ""),
                        code_template=fix_data.get("code_template", ""),
                        explanation=fix_data.get("explanation", ""),
                        caveats=fix_data.get("caveats", []),
                    )
                )

            return ErrorPattern(
                id=data["id"],
                name=data["name"],
                category=ErrorCategory(data.get("category", "unknown")),
                description=data.get("description", ""),
                exception_types=data.get("exception_types", []),
                message_patterns=data.get("message_patterns", []),
                code_patterns=data.get("code_patterns", []),
                common_causes=data.get("common_causes", []),
                typical_fixes=fixes,
                examples=data.get("examples", []),
                languages=data.get("languages", []),
                severity=data.get("severity", "medium"),
                documentation_links=data.get("documentation_links", []),
            )
        except (KeyError, ValueError) as e:
            logger.warning("Failed to parse pattern: %s", e)
            return None

    def _load_builtin_patterns(self) -> None:
        """Load built-in patterns when JSON file is not available.

        The hawk's instinctive knowledge - prey patterns etched in its DNA.
        """
        # This provides a minimal set of patterns as fallback
        self.patterns = [
            ErrorPattern(
                id="py_attribute_none",
                name="NoneType AttributeError",
                category=ErrorCategory.NULL_REFERENCE,
                description="Attempting to access an attribute on None",
                exception_types=["AttributeError"],
                message_patterns=[
                    r"'NoneType' object has no attribute",
                    r"None has no attribute",
                ],
                code_patterns=[r"\w+\.\w+"],
                common_causes=[
                    "Function returned None unexpectedly",
                    "Variable not initialized",
                    "Failed API call or database query",
                ],
                typical_fixes=[
                    FixTemplate(
                        description="Add None check before accessing attribute",
                        code_template="if obj is not None:\n    obj.attribute",
                        explanation="Guard against None by checking before access",
                        caveats=["Consider why the value is None in the first place"],
                    )
                ],
                examples=[
                    {
                        "error": "'NoneType' object has no attribute 'name'",
                        "code": "user.name",
                        "fix": "if user is not None: user.name",
                    }
                ],
                languages=["python"],
                severity="high",
            ),
            ErrorPattern(
                id="py_key_error",
                name="Dictionary KeyError",
                category=ErrorCategory.KEY_NOT_FOUND,
                description="Accessing a dictionary with a key that doesn't exist",
                exception_types=["KeyError"],
                message_patterns=[r"KeyError:", r"KeyError\(['\"](\w+)['\"]\)"],
                code_patterns=[r"\w+\[['\"]?\w+['\"]?\]"],
                common_causes=[
                    "Key typo or case mismatch",
                    "Missing data in dictionary",
                    "Unexpected API response structure",
                ],
                typical_fixes=[
                    FixTemplate(
                        description="Use .get() with default value",
                        code_template='value = data.get("key", default_value)',
                        explanation="The .get() method returns None or default if key missing",
                        caveats=["Choose an appropriate default value"],
                    )
                ],
                examples=[
                    {
                        "error": "KeyError: 'username'",
                        "code": "data['username']",
                        "fix": "data.get('username', '')",
                    }
                ],
                languages=["python"],
                severity="medium",
            ),
            ErrorPattern(
                id="py_index_error",
                name="List IndexError",
                category=ErrorCategory.INDEX_OUT_OF_BOUNDS,
                description="Accessing a list with an out-of-bounds index",
                exception_types=["IndexError"],
                message_patterns=[r"list index out of range", r"IndexError:"],
                code_patterns=[r"\w+\[\d+\]", r"\w+\[-?\d+\]"],
                common_causes=[
                    "Empty list not checked",
                    "Off-by-one error in loop",
                    "Hardcoded index assumption",
                ],
                typical_fixes=[
                    FixTemplate(
                        description="Check list length before accessing",
                        code_template="if len(items) > index:\n    items[index]",
                        explanation="Validate index is within bounds before access",
                        caveats=["Consider if empty list is a valid state"],
                    )
                ],
                examples=[
                    {
                        "error": "IndexError: list index out of range",
                        "code": "items[0]",
                        "fix": "items[0] if items else None",
                    }
                ],
                languages=["python"],
                severity="medium",
            ),
        ]

    def match_pattern(
        self,
        issue: SentryIssue,
        stack_trace: StackTrace | None = None,
        code_context: str | None = None,
    ) -> PatternMatch | None:
        """Match an issue against known patterns.

        The hawk circles overhead, scanning for familiar prey patterns.
        When a match is found, it swoops in with confidence.

        Args:
            issue: The Sentry issue to analyze
            stack_trace: Optional stack trace for deeper analysis
            code_context: Optional code snippet where error occurred

        Returns:
            PatternMatch if a pattern is found, None otherwise
        """
        logger.debug("Hawk scanning issue %s for known patterns", issue.id)

        # Extract error information from issue
        error_title = issue.title
        error_message = self._extract_error_message(issue)
        exception_type = self._extract_exception_type(issue)

        best_match: PatternMatch | None = None
        best_confidence = 0.0

        for pattern in self.patterns:
            match_result = self._evaluate_pattern(
                pattern,
                exception_type=exception_type,
                error_message=error_message,
                error_title=error_title,
                code_context=code_context,
            )

            if match_result and match_result.confidence > best_confidence:
                best_match = match_result
                best_confidence = match_result.confidence

        if best_match:
            logger.info(
                "Hawk spotted prey: %s (confidence: %.2f)",
                best_match.pattern.name,
                best_match.confidence,
            )
        else:
            logger.debug("Hawk found no matching patterns for issue %s", issue.id)

        return best_match

    def _evaluate_pattern(
        self,
        pattern: ErrorPattern,
        exception_type: str,
        error_message: str,
        error_title: str,
        code_context: str | None,
    ) -> PatternMatch | None:
        """Evaluate how well an error matches a pattern.

        The hawk's keen eyes assess the prey, checking all identifying marks.

        Args:
            pattern: The pattern to evaluate
            exception_type: The exception type from the error
            error_message: The error message
            error_title: The issue title
            code_context: Optional code context

        Returns:
            PatternMatch with confidence score, or None if no match
        """
        confidence = 0.0
        matched_exception = False
        matched_message = False
        matched_code = False
        match_details: dict[str, Any] = {}

        # Check exception type match (40% weight)
        # The prey's species - most reliable identifier
        if exception_type:
            for exc_pattern in pattern.exception_types:
                if exc_pattern.lower() in exception_type.lower():
                    matched_exception = True
                    confidence += 0.4
                    match_details["exception_match"] = exc_pattern
                    break

        # Check message patterns (40% weight)
        # The prey's distinctive markings
        combined_message = f"{error_title} {error_message}"
        for msg_pattern in pattern.message_patterns:
            try:
                if re.search(msg_pattern, combined_message, re.IGNORECASE):
                    matched_message = True
                    confidence += 0.4
                    match_details["message_pattern"] = msg_pattern
                    break
            except re.error:
                continue

        # Check code patterns (20% weight)
        # The prey's behavior patterns in code
        if code_context:
            for code_pattern in pattern.code_patterns:
                try:
                    if re.search(code_pattern, code_context):
                        matched_code = True
                        confidence += 0.2
                        match_details["code_pattern"] = code_pattern
                        break
                except re.error:
                    continue

        # Must match at least exception or message to be valid
        if not matched_exception and not matched_message:
            return None

        # Bonus confidence for multiple matches
        # The hawk is more certain when multiple signs align
        match_count = sum([matched_exception, matched_message, matched_code])
        if match_count >= 2:
            confidence = min(1.0, confidence * 1.1)  # 10% bonus for multiple matches

        return PatternMatch(
            pattern=pattern,
            confidence=confidence,
            matched_exception=matched_exception,
            matched_message=matched_message,
            matched_code=matched_code,
            match_details=match_details,
        )

    def _extract_error_message(self, issue: SentryIssue) -> str:
        """Extract error message from issue.

        The hawk listens for the prey's distress call.

        Args:
            issue: The Sentry issue

        Returns:
            Error message string
        """
        # Try metadata first
        metadata = issue.metadata
        if "value" in metadata:
            return str(metadata["value"])

        # Try to parse from title
        if ": " in issue.title:
            parts = issue.title.split(": ", 1)
            if len(parts) > 1:
                return parts[1]

        return issue.title

    def _extract_exception_type(self, issue: SentryIssue) -> str:
        """Extract exception type from issue.

        Identifying the prey's species from its tracks.

        Args:
            issue: The Sentry issue

        Returns:
            Exception type string
        """
        # Try metadata
        metadata = issue.metadata
        if "type" in metadata:
            return str(metadata["type"])

        # Parse from title
        if ": " in issue.title:
            return issue.title.split(": ")[0]

        # Check for known exception patterns
        exception_patterns = [
            r"(\w+Error)",
            r"(\w+Exception)",
            r"(\w+Fault)",
            r"(\w+Warning)",
        ]

        for pattern in exception_patterns:
            match = re.search(pattern, issue.title)
            if match:
                return match.group(1)

        return ""

    def get_patterns_by_category(self, category: ErrorCategory) -> list[ErrorPattern]:
        """Get all patterns in a category.

        The hawk reviews its hunting strategies for a specific type of prey.

        Args:
            category: The error category

        Returns:
            List of patterns in that category
        """
        return [p for p in self.patterns if p.category == category]

    def get_patterns_by_language(self, language: str) -> list[ErrorPattern]:
        """Get all patterns for a language.

        The hawk knows different terrains (languages) have different prey.

        Args:
            language: Programming language (e.g., 'python', 'javascript')

        Returns:
            List of patterns for that language
        """
        language = language.lower()
        return [p for p in self.patterns if language in [l.lower() for l in p.languages]]

    def add_pattern(self, pattern: ErrorPattern) -> None:
        """Add a new pattern to the matcher.

        The hawk learns to recognize new prey.

        Args:
            pattern: The pattern to add
        """
        self.patterns.append(pattern)
        logger.info("Hawk learned new pattern: %s", pattern.name)

    def save_patterns(self, file_path: Path | None = None) -> None:
        """Save patterns to JSON file.

        The hawk records its hunting knowledge for future reference.

        Args:
            file_path: Path to save to. Uses default if not provided.
        """
        target = file_path or self.patterns_file

        patterns_data = []
        for pattern in self.patterns:
            fixes_data = []
            for fix in pattern.typical_fixes:
                fixes_data.append(
                    {
                        "description": fix.description,
                        "code_template": fix.code_template,
                        "explanation": fix.explanation,
                        "caveats": fix.caveats,
                    }
                )

            patterns_data.append(
                {
                    "id": pattern.id,
                    "name": pattern.name,
                    "category": pattern.category.value,
                    "description": pattern.description,
                    "exception_types": pattern.exception_types,
                    "message_patterns": pattern.message_patterns,
                    "code_patterns": pattern.code_patterns,
                    "common_causes": pattern.common_causes,
                    "typical_fixes": fixes_data,
                    "examples": pattern.examples,
                    "languages": pattern.languages,
                    "severity": pattern.severity,
                    "documentation_links": pattern.documentation_links,
                }
            )

        data = {
            "version": "1.0",
            "description": "BugHawk error pattern catalog - the hawk's prey profiles",
            "patterns": patterns_data,
        }

        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info("Hawk's hunting knowledge saved to %s", target)
        except OSError as e:
            logger.error("Failed to save patterns: %s", e)

    def get_fix_suggestion(
        self,
        match: PatternMatch,
        language: str | None = None,
    ) -> str:
        """Generate a fix suggestion based on pattern match.

        The hawk prepares its attack strategy based on the identified prey.

        Args:
            match: The pattern match result
            language: Target language for code formatting

        Returns:
            Formatted fix suggestion string
        """
        pattern = match.pattern
        lines: list[str] = []

        lines.append(f"## {pattern.name}")
        lines.append("")
        lines.append(f"**Category**: {pattern.category.value}")
        lines.append(f"**Confidence**: {match.confidence:.0%}")
        lines.append(f"**Severity**: {pattern.severity}")
        lines.append("")

        lines.append("### Description")
        lines.append(pattern.description)
        lines.append("")

        lines.append("### Common Causes")
        for cause in pattern.common_causes:
            lines.append(f"- {cause}")
        lines.append("")

        if pattern.typical_fixes:
            lines.append("### Suggested Fixes")
            for i, fix in enumerate(pattern.typical_fixes, 1):
                lines.append(f"#### Option {i}: {fix.description}")
                lines.append("")
                lines.append(fix.explanation)
                lines.append("")
                if fix.code_template:
                    lang = language or (pattern.languages[0] if pattern.languages else "")
                    lines.append(f"```{lang}")
                    lines.append(fix.code_template)
                    lines.append("```")
                    lines.append("")
                if fix.caveats:
                    lines.append("**Caveats:**")
                    for caveat in fix.caveats:
                        lines.append(f"- {caveat}")
                    lines.append("")

        if pattern.examples:
            lines.append("### Examples")
            for example in pattern.examples[:2]:  # Limit to 2 examples
                lines.append("")
                if "error" in example:
                    lines.append(f"**Error**: `{example['error']}`")
                if "code" in example:
                    lines.append(f"**Problematic code**: `{example['code']}`")
                if "fix" in example:
                    lines.append(f"**Fixed code**: `{example['fix']}`")

        return "\n".join(lines)
