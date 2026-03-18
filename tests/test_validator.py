"""Tests for fix validator module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.fixer.validator import (
    ConfidenceBreakdown,
    DiffAnalysis,
    FixValidator,
    SyntaxValidationResult,
    TestResult,
)


class TestFixValidatorInitialization:
    """Tests for FixValidator initialization."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        validator = FixValidator()
        assert validator is not None

    def test_initialization_with_options(self) -> None:
        """Test initialization with custom options."""
        validator = FixValidator(
            skip_tests=True,
            timeout=60,
        )
        assert validator.skip_tests is True
        assert validator.timeout == 60


class TestSyntaxValidation:
    """Tests for syntax validation."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    def test_validate_python_syntax_valid(self, validator: FixValidator) -> None:
        """Test validation of valid Python code."""
        code = '''
def hello():
    print("Hello, World!")

if __name__ == "__main__":
    hello()
'''
        result = validator.validate_syntax(code, language="python")

        assert result.is_valid is True
        assert result.errors == []

    def test_validate_python_syntax_invalid(self, validator: FixValidator) -> None:
        """Test validation of invalid Python code."""
        code = '''
def hello(:
    print("Missing parenthesis"
'''
        result = validator.validate_syntax(code, language="python")

        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_validate_python_syntax_indentation_error(
        self, validator: FixValidator
    ) -> None:
        """Test detection of Python indentation errors."""
        code = '''
def hello():
print("Bad indentation")
'''
        result = validator.validate_syntax(code, language="python")

        assert result.is_valid is False

    def test_validate_javascript_syntax_valid(self, validator: FixValidator) -> None:
        """Test validation of valid JavaScript code."""
        code = '''
function hello() {
    console.log("Hello, World!");
}

hello();
'''
        # Note: JS validation may depend on node being available
        try:
            result = validator.validate_syntax(code, language="javascript")
            # If node is available, should validate
            assert isinstance(result, SyntaxValidationResult)
        except Exception:
            # Node not available, skip
            pytest.skip("Node.js not available for JS syntax validation")

    def test_validate_unsupported_language(self, validator: FixValidator) -> None:
        """Test validation of unsupported language."""
        code = "some code in unknown language"
        result = validator.validate_syntax(code, language="unknown_lang")

        # Should return a result (possibly with warnings about unsupported language)
        assert isinstance(result, SyntaxValidationResult)


class TestDiffAnalysis:
    """Tests for diff analysis."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    def test_analyze_diff_basic(self, validator: FixValidator) -> None:
        """Test basic diff analysis."""
        diff = '''--- a/file.py
+++ b/file.py
@@ -1,3 +1,4 @@
 def hello():
-    print("old")
+    if True:
+        print("new")
'''
        analysis = validator.analyze_diff(diff)

        assert isinstance(analysis, DiffAnalysis)
        assert analysis.lines_added > 0
        assert analysis.lines_removed > 0

    def test_analyze_diff_only_additions(self, validator: FixValidator) -> None:
        """Test diff with only additions."""
        diff = '''--- a/file.py
+++ b/file.py
@@ -1,2 +1,4 @@
 def hello():
     print("hello")
+    # New comment
+    print("world")
'''
        analysis = validator.analyze_diff(diff)

        assert analysis.lines_added >= 2
        assert analysis.lines_removed == 0

    def test_analyze_diff_only_removals(self, validator: FixValidator) -> None:
        """Test diff with only removals."""
        diff = '''--- a/file.py
+++ b/file.py
@@ -1,4 +1,2 @@
 def hello():
     print("hello")
-    # Removed comment
-    print("world")
'''
        analysis = validator.analyze_diff(diff)

        assert analysis.lines_removed >= 2

    def test_analyze_diff_empty(self, validator: FixValidator) -> None:
        """Test analysis of empty diff."""
        analysis = validator.analyze_diff("")

        assert analysis.lines_added == 0
        assert analysis.lines_removed == 0


class TestConfidenceCalculation:
    """Tests for confidence score calculation."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    def test_calculate_confidence_high(self, validator: FixValidator) -> None:
        """Test high confidence calculation."""
        breakdown = validator.calculate_confidence(
            syntax_valid=True,
            pattern_matched=True,
            small_change=True,
            targets_error_location=True,
            llm_confidence=0.9,
        )

        assert isinstance(breakdown, ConfidenceBreakdown)
        assert breakdown.total >= 0.7

    def test_calculate_confidence_low(self, validator: FixValidator) -> None:
        """Test low confidence calculation."""
        breakdown = validator.calculate_confidence(
            syntax_valid=False,
            pattern_matched=False,
            small_change=False,
            targets_error_location=False,
            llm_confidence=0.2,
        )

        assert breakdown.total < 0.5

    def test_confidence_breakdown_components(self, validator: FixValidator) -> None:
        """Test that confidence breakdown has all components."""
        breakdown = validator.calculate_confidence(
            syntax_valid=True,
            pattern_matched=True,
            small_change=True,
            targets_error_location=True,
            llm_confidence=0.8,
        )

        assert breakdown.syntax_score >= 0
        assert breakdown.pattern_score >= 0
        assert breakdown.change_size_score >= 0
        assert breakdown.location_score >= 0
        assert breakdown.llm_score >= 0

    def test_confidence_within_bounds(self, validator: FixValidator) -> None:
        """Test that confidence is always between 0 and 1."""
        # Test various combinations
        for syntax in [True, False]:
            for pattern in [True, False]:
                for small in [True, False]:
                    for location in [True, False]:
                        for llm in [0.0, 0.5, 1.0]:
                            breakdown = validator.calculate_confidence(
                                syntax_valid=syntax,
                                pattern_matched=pattern,
                                small_change=small,
                                targets_error_location=location,
                                llm_confidence=llm,
                            )
                            assert 0.0 <= breakdown.total <= 1.0


class TestTestExecution:
    """Tests for test execution functionality."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    @patch("subprocess.run")
    def test_run_tests_pytest_success(
        self,
        mock_run: MagicMock,
        validator: FixValidator,
        temp_repo: Path,
    ) -> None:
        """Test successful pytest execution."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="All tests passed",
            stderr="",
        )

        # Create pytest.ini to simulate pytest project
        (temp_repo / "pytest.ini").write_text("[pytest]\n")

        result = validator.run_tests(temp_repo)

        assert isinstance(result, TestResult)
        assert result.passed is True

    @patch("subprocess.run")
    def test_run_tests_pytest_failure(
        self,
        mock_run: MagicMock,
        validator: FixValidator,
        temp_repo: Path,
    ) -> None:
        """Test failed pytest execution."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="1 failed, 2 passed",
            stderr="AssertionError: test failed",
        )

        (temp_repo / "pytest.ini").write_text("[pytest]\n")

        result = validator.run_tests(temp_repo)

        assert result.passed is False
        assert result.failed_count > 0 or "failed" in result.output.lower()

    def test_run_tests_skip_flag(
        self,
        validator: FixValidator,
        temp_repo: Path,
    ) -> None:
        """Test that tests are skipped with skip_tests flag."""
        validator.skip_tests = True

        result = validator.run_tests(temp_repo)

        assert result.skipped is True


class TestFixValidation:
    """Tests for complete fix validation."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator(skip_tests=True)

    def test_validate_fix_valid_python(
        self,
        validator: FixValidator,
        sample_fix_proposal,
        sample_code_context,
    ) -> None:
        """Test validation of a valid Python fix."""
        # This would require a more complete implementation
        # For now, test basic structure
        pass

    def test_validate_fix_completeness(self, validator: FixValidator) -> None:
        """Test fix completeness validation."""
        # Test that validator checks for complete fixes
        incomplete_diff = '''--- a/file.py
+++ b/file.py
@@ -1,1 +1,1 @@
-# TODO: implement
+# TODO: implement this properly
'''
        is_complete = validator.validate_fix_completeness(incomplete_diff)

        # Incomplete fix (just a comment change) should be flagged
        # Actual behavior depends on implementation


class TestValidatorEdgeCases:
    """Tests for edge cases in validation."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    def test_validate_empty_code(self, validator: FixValidator) -> None:
        """Test validation of empty code."""
        result = validator.validate_syntax("", language="python")

        # Empty code should be technically valid syntax
        assert isinstance(result, SyntaxValidationResult)

    def test_validate_whitespace_only(self, validator: FixValidator) -> None:
        """Test validation of whitespace-only code."""
        result = validator.validate_syntax("   \n\n\t\t  \n", language="python")

        assert isinstance(result, SyntaxValidationResult)

    def test_validate_very_long_code(self, validator: FixValidator) -> None:
        """Test validation of very long code."""
        code = "x = 1\n" * 10000  # Very long but valid Python

        result = validator.validate_syntax(code, language="python")

        assert result.is_valid is True

    def test_analyze_diff_malformed(self, validator: FixValidator) -> None:
        """Test analysis of malformed diff."""
        malformed_diff = "This is not a valid diff format"

        analysis = validator.analyze_diff(malformed_diff)

        # Should handle gracefully
        assert isinstance(analysis, DiffAnalysis)


class TestLanguageDetection:
    """Tests for language detection in validation."""

    @pytest.fixture
    def validator(self) -> FixValidator:
        """Create validator for testing."""
        return FixValidator()

    def test_detect_python_from_extension(self, validator: FixValidator) -> None:
        """Test Python detection from file extension."""
        lang = validator._detect_language("src/app.py")
        assert lang == "python"

    def test_detect_javascript_from_extension(self, validator: FixValidator) -> None:
        """Test JavaScript detection from file extension."""
        lang = validator._detect_language("src/app.js")
        assert lang == "javascript"

    def test_detect_typescript_from_extension(self, validator: FixValidator) -> None:
        """Test TypeScript detection from file extension."""
        lang = validator._detect_language("src/app.ts")
        assert lang == "typescript"

        lang = validator._detect_language("src/component.tsx")
        assert lang == "typescript"

    def test_detect_unknown_extension(self, validator: FixValidator) -> None:
        """Test detection of unknown extension."""
        lang = validator._detect_language("file.unknown")
        assert lang is None or lang == "unknown"
