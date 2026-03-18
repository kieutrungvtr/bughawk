"""Tests for pattern matcher module."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from bughawk.analyzer.pattern_matcher import (
    ErrorCategory,
    ErrorPattern,
    FixTemplate,
    PatternMatch,
    PatternMatcher,
)


class TestErrorPattern:
    """Tests for ErrorPattern dataclass."""

    def test_error_pattern_creation(self) -> None:
        """Test creating an error pattern."""
        pattern = ErrorPattern(
            id="test-pattern",
            name="Test Pattern",
            category=ErrorCategory.NULL_REFERENCE,
            languages=["python", "javascript"],
            exception_types=["TypeError", "AttributeError"],
            message_patterns=[r".*undefined.*", r".*None.*"],
            common_causes=["Accessing undefined variable"],
            typical_fixes=["Add null check"],
        )

        assert pattern.id == "test-pattern"
        assert pattern.name == "Test Pattern"
        assert len(pattern.languages) == 2
        assert len(pattern.exception_types) == 2

    def test_error_pattern_with_fix_templates(self) -> None:
        """Test pattern with fix templates."""
        template = FixTemplate(
            id="fix-1",
            description="Add null check",
            before_pattern=r"(\w+)\.(\w+)",
            after_pattern=r"\1?.\2",
            languages=["typescript"],
        )

        pattern = ErrorPattern(
            id="test-pattern",
            name="Test Pattern",
            category=ErrorCategory.NULL_REFERENCE,
            languages=["typescript"],
            exception_types=["TypeError"],
            message_patterns=[r".*undefined.*"],
            common_causes=["Accessing undefined"],
            typical_fixes=["Add optional chaining"],
            fix_templates=[template],
        )

        assert len(pattern.fix_templates) == 1
        assert pattern.fix_templates[0].id == "fix-1"


class TestPatternMatcher:
    """Tests for PatternMatcher class."""

    @pytest.fixture
    def matcher(self) -> PatternMatcher:
        """Create a pattern matcher for testing."""
        return PatternMatcher()

    def test_matcher_initialization(self, matcher: PatternMatcher) -> None:
        """Test pattern matcher initializes correctly."""
        assert matcher is not None
        assert len(matcher.patterns) > 0

    def test_matcher_loads_patterns(self, matcher: PatternMatcher) -> None:
        """Test that patterns are loaded from JSON."""
        # Check that some expected patterns exist
        pattern_ids = [p.id for p in matcher.patterns]
        assert len(pattern_ids) > 0

    def test_match_null_pointer_javascript(self, matcher: PatternMatcher) -> None:
        """Test matching a JavaScript null pointer error."""
        match = matcher.match_pattern(
            exception_type="TypeError",
            message="Cannot read property 'map' of undefined",
            code_snippet="const items = data.map(x => x);",
        )

        assert match is not None
        assert match.confidence > 0.5
        assert "null" in match.pattern.name.lower() or "undefined" in match.pattern.name.lower()

    def test_match_python_key_error(self, matcher: PatternMatcher) -> None:
        """Test matching a Python KeyError."""
        match = matcher.match_pattern(
            exception_type="KeyError",
            message="KeyError: 'username'",
            code_snippet="user = data['username']",
        )

        assert match is not None
        assert match.confidence > 0.3

    def test_match_python_attribute_error(self, matcher: PatternMatcher) -> None:
        """Test matching a Python AttributeError."""
        match = matcher.match_pattern(
            exception_type="AttributeError",
            message="'NoneType' object has no attribute 'split'",
            code_snippet="parts = value.split(',')",
        )

        assert match is not None
        assert match.confidence > 0.5

    def test_no_match_unknown_error(self, matcher: PatternMatcher) -> None:
        """Test no match for unknown error types."""
        match = matcher.match_pattern(
            exception_type="CustomUnknownException",
            message="Some very specific error that doesn't match anything",
            code_snippet="# Unknown code",
        )

        # May or may not match, but if it does, confidence should be low
        if match:
            assert match.confidence < 0.5

    def test_match_with_code_snippet_boost(self, matcher: PatternMatcher) -> None:
        """Test that code snippet boosts confidence."""
        # Match without code snippet
        match1 = matcher.match_pattern(
            exception_type="TypeError",
            message="Cannot read property 'length' of undefined",
            code_snippet="",
        )

        # Match with relevant code snippet
        match2 = matcher.match_pattern(
            exception_type="TypeError",
            message="Cannot read property 'length' of undefined",
            code_snippet="const len = arr.length;",
        )

        if match1 and match2:
            # Code snippet should provide additional context
            assert match2.confidence >= match1.confidence

    def test_match_returns_pattern_match(self, matcher: PatternMatcher) -> None:
        """Test that match returns PatternMatch object."""
        match = matcher.match_pattern(
            exception_type="TypeError",
            message="Cannot read property 'x' of null",
            code_snippet="",
        )

        if match:
            assert isinstance(match, PatternMatch)
            assert isinstance(match.pattern, ErrorPattern)
            assert isinstance(match.confidence, float)
            assert 0.0 <= match.confidence <= 1.0


class TestPatternMatchConfidence:
    """Tests for confidence score calculation."""

    @pytest.fixture
    def matcher(self) -> PatternMatcher:
        """Create a pattern matcher for testing."""
        return PatternMatcher()

    def test_high_confidence_exact_match(self, matcher: PatternMatcher) -> None:
        """Test high confidence for exact exception type match."""
        match = matcher.match_pattern(
            exception_type="NullPointerException",
            message="null pointer exception occurred",
            code_snippet="Object obj = null; obj.toString();",
        )

        if match:
            # Exact exception type match should have higher confidence
            assert match.confidence > 0.6

    def test_confidence_within_bounds(self, matcher: PatternMatcher) -> None:
        """Test that confidence is always between 0 and 1."""
        test_cases = [
            ("TypeError", "undefined error", ""),
            ("KeyError", "missing key", ""),
            ("ValueError", "invalid value", ""),
            ("Exception", "generic error", ""),
        ]

        for exc_type, message, snippet in test_cases:
            match = matcher.match_pattern(
                exception_type=exc_type,
                message=message,
                code_snippet=snippet,
            )

            if match:
                assert 0.0 <= match.confidence <= 1.0


class TestPatternMatchSuggestions:
    """Tests for fix suggestions."""

    @pytest.fixture
    def matcher(self) -> PatternMatcher:
        """Create a pattern matcher for testing."""
        return PatternMatcher()

    def test_match_includes_suggested_fix(self, matcher: PatternMatcher) -> None:
        """Test that matches include suggested fixes."""
        match = matcher.match_pattern(
            exception_type="TypeError",
            message="Cannot read property 'map' of undefined",
            code_snippet="items.map(x => x)",
        )

        if match:
            # Should have typical fixes from pattern
            assert len(match.pattern.typical_fixes) > 0

    def test_match_includes_common_causes(self, matcher: PatternMatcher) -> None:
        """Test that matches include common causes."""
        match = matcher.match_pattern(
            exception_type="KeyError",
            message="KeyError: 'id'",
            code_snippet="data['id']",
        )

        if match:
            assert len(match.pattern.common_causes) > 0


class TestPatternMatcherEdgeCases:
    """Tests for edge cases in pattern matching."""

    @pytest.fixture
    def matcher(self) -> PatternMatcher:
        """Create a pattern matcher for testing."""
        return PatternMatcher()

    def test_empty_exception_type(self, matcher: PatternMatcher) -> None:
        """Test matching with empty exception type."""
        match = matcher.match_pattern(
            exception_type="",
            message="Some error message",
            code_snippet="",
        )

        # Should still try to match based on message
        # Result depends on message content

    def test_empty_message(self, matcher: PatternMatcher) -> None:
        """Test matching with empty message."""
        match = matcher.match_pattern(
            exception_type="TypeError",
            message="",
            code_snippet="",
        )

        # May match based on exception type alone

    def test_special_characters_in_message(self, matcher: PatternMatcher) -> None:
        """Test matching with special regex characters in message."""
        match = matcher.match_pattern(
            exception_type="Error",
            message="Error: [object Object] (undefined)",
            code_snippet="",
        )

        # Should not crash on special characters

    def test_very_long_message(self, matcher: PatternMatcher) -> None:
        """Test matching with very long error message."""
        long_message = "Error: " + "a" * 10000

        match = matcher.match_pattern(
            exception_type="Error",
            message=long_message,
            code_snippet="",
        )

        # Should handle long messages without crashing

    def test_unicode_in_message(self, matcher: PatternMatcher) -> None:
        """Test matching with unicode characters in message."""
        match = matcher.match_pattern(
            exception_type="Error",
            message="Error: 日本語のエラーメッセージ 🦅",
            code_snippet="",
        )

        # Should handle unicode without crashing


class TestPatternCategories:
    """Tests for error pattern categories."""

    def test_category_enum_values(self) -> None:
        """Test ErrorCategory enum has expected values."""
        assert ErrorCategory.NULL_REFERENCE.value == "null_reference"
        assert ErrorCategory.TYPE_ERROR.value == "type_error"
        assert ErrorCategory.KEY_ERROR.value == "key_error"

    def test_category_in_pattern(self) -> None:
        """Test patterns have valid categories."""
        matcher = PatternMatcher()

        for pattern in matcher.patterns:
            assert isinstance(pattern.category, ErrorCategory)
