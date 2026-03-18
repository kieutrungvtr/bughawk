"""Unit tests for the FixGenerator module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.analyzer.pattern_matcher import ErrorCategory, ErrorPattern, PatternMatch
from bughawk.core.models import (
    CodeContext,
    FixProposal,
    IssueSeverity,
    SentryIssue,
    StackFrame,
    StackTrace,
)
from bughawk.fixer.fix_generator import (
    FixAttempt,
    FixGenerationError,
    FixGenerator,
    FixValidationError,
    ValidationResult,
)


class TestFixAttempt:
    """Tests for FixAttempt dataclass."""

    def test_fix_attempt_creation(self) -> None:
        """Test creating a FixAttempt."""
        now = datetime.now()
        proposal = FixProposal(
            issue_id="12345",
            fix_description="Fix null pointer",
            code_changes={"main.py": "# fix"},
            confidence_score=0.85,
        )

        attempt = FixAttempt(
            timestamp=now,
            issue_id="12345",
            method="pattern",
            success=True,
            proposal=proposal,
        )

        assert attempt.issue_id == "12345"
        assert attempt.method == "pattern"
        assert attempt.success is True
        assert attempt.proposal is not None

    def test_fix_attempt_with_error(self) -> None:
        """Test creating a failed FixAttempt."""
        now = datetime.now()

        attempt = FixAttempt(
            timestamp=now,
            issue_id="12345",
            method="llm",
            success=False,
            proposal=None,
            error="LLM API error",
        )

        assert attempt.success is False
        assert attempt.error == "LLM API error"
        assert attempt.proposal is None


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_validation_result_valid(self) -> None:
        """Test creating a valid ValidationResult."""
        result = ValidationResult(
            is_valid=True,
            syntax_valid=True,
            changes_error_location=True,
            scope_appropriate=True,
            confidence_adjustment=1.0,
            issues=[],
            warnings=[],
        )

        assert result.is_valid is True
        assert result.confidence_adjustment == 1.0

    def test_validation_result_with_issues(self) -> None:
        """Test ValidationResult with issues."""
        result = ValidationResult(
            is_valid=False,
            syntax_valid=False,
            changes_error_location=False,
            scope_appropriate=True,
            confidence_adjustment=0.5,
            issues=["Syntax error at line 10"],
            warnings=["Fix may be too broad"],
        )

        assert result.is_valid is False
        assert len(result.issues) == 1
        assert len(result.warnings) == 1


class TestFixGeneratorInitialization:
    """Tests for FixGenerator initialization."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        generator = FixGenerator()

        assert generator.pattern_matcher is not None
        assert generator.context_builder is not None
        assert generator.attempts == []

    def test_initialization_with_debug_dir(self, temp_dir: Path) -> None:
        """Test initialization with debug directory."""
        debug_dir = temp_dir / "debug"
        generator = FixGenerator(debug_dir=debug_dir)

        assert generator.debug_dir == debug_dir
        assert debug_dir.exists()


class TestValidateFix:
    """Tests for fix validation."""

    def test_validate_valid_fix(self) -> None:
        """Test validating a valid fix."""
        generator = FixGenerator()

        proposal = FixProposal(
            issue_id="12345",
            fix_description="Add null check",
            code_changes={
                "src/main.py": """@@ -10,3 +10,4 @@
 def process(data):
-    return data.process()
+    if data is None:
+        return None
+    return data.process()
"""
            },
            confidence_score=0.85,
        )

        context = CodeContext(
            file_path="src/main.py",
            file_content="def process(data):\n    return data.process()",
            error_line=11,
        )

        result = generator.validate_fix(proposal, context)

        assert result.is_valid is True
        assert result.syntax_valid is True

    def test_validate_fix_wrong_file(self) -> None:
        """Test validating fix that targets wrong file."""
        generator = FixGenerator()

        proposal = FixProposal(
            issue_id="12345",
            fix_description="Fix in wrong file",
            code_changes={"other.py": "# fix"},
            confidence_score=0.7,
        )

        context = CodeContext(
            file_path="main.py",
            file_content="# main",
            error_line=5,
        )

        result = generator.validate_fix(proposal, context)

        assert len(result.issues) > 0
        assert result.confidence_adjustment < 1.0

    def test_validate_fix_too_many_changes(self) -> None:
        """Test validating fix with too many changes."""
        generator = FixGenerator()

        # Create a diff with many changes
        many_changes = "\n".join([f"+line {i}" for i in range(60)])
        proposal = FixProposal(
            issue_id="12345",
            fix_description="Large fix",
            code_changes={"main.py": many_changes},
            confidence_score=0.7,
        )

        context = CodeContext(
            file_path="main.py",
            file_content="# original",
        )

        result = generator.validate_fix(proposal, context)

        assert result.scope_appropriate is False
        assert len(result.warnings) > 0

    def test_validate_fix_low_confidence(self) -> None:
        """Test validating fix with low confidence."""
        generator = FixGenerator()

        proposal = FixProposal(
            issue_id="12345",
            fix_description="Uncertain fix",
            code_changes={"main.py": "+# maybe this helps"},
            confidence_score=0.2,
        )

        context = CodeContext(
            file_path="main.py",
            file_content="# original",
        )

        result = generator.validate_fix(proposal, context)

        assert any("confidence" in w.lower() for w in result.warnings)


class TestCheckPythonSyntax:
    """Tests for Python syntax checking."""

    def test_valid_python_code(self) -> None:
        """Test checking valid Python code."""
        generator = FixGenerator()

        code = """def hello():
    print("Hello, World!")
    return True
"""
        result = generator._check_python_syntax(code, "test.py")

        assert result["valid"] is True

    def test_invalid_python_syntax(self) -> None:
        """Test checking invalid Python code."""
        generator = FixGenerator()

        code = """def hello()
    print("Missing colon")
"""
        result = generator._check_python_syntax(code, "test.py")

        assert result["valid"] is False
        assert "error" in result

    def test_diff_with_valid_additions(self) -> None:
        """Test checking diff with valid Python additions."""
        generator = FixGenerator()

        diff = """+def new_function():
+    return "new"
"""
        result = generator._check_python_syntax(diff, "test.py")

        assert result["valid"] is True


class TestDiffAffectsLine:
    """Tests for diff line detection."""

    def test_diff_affects_target_line(self) -> None:
        """Test detecting diff affects target line."""
        generator = FixGenerator()

        diff = """@@ -10,3 +10,4 @@
 def process():
-    return None
+    if check:
+        return None
"""
        assert generator._diff_affects_line(diff, 11) is True

    def test_diff_does_not_affect_distant_line(self) -> None:
        """Test diff doesn't affect distant line."""
        generator = FixGenerator()

        diff = """@@ -10,3 +10,4 @@
 def process():
-    return None
+    return True
"""
        # Line 100 is far from the hunk
        assert generator._diff_affects_line(diff, 100) is False


class TestApplyUnifiedDiff:
    """Tests for applying unified diffs."""

    def test_apply_simple_diff(self) -> None:
        """Test applying a simple unified diff."""
        generator = FixGenerator()

        original = """line 1
line 2
line 3
line 4
"""
        diff = """@@ -2,2 +2,3 @@
 line 1
-line 2
+line 2 modified
+line 2.5
 line 3
"""
        result = generator._apply_unified_diff(original, diff)

        assert "line 2 modified" in result
        assert "line 2.5" in result


class TestApplySearchReplace:
    """Tests for search/replace application."""

    def test_simple_search_replace(self) -> None:
        """Test simple search and replace."""
        generator = FixGenerator()

        original = """def process(data):
    return data.value
"""
        diff = """-    return data.value
+    return data.value if data else None
"""
        result = generator._apply_search_replace(original, diff)

        assert "data.value if data else None" in result

    def test_multiline_search_replace(self) -> None:
        """Test multiline search and replace."""
        generator = FixGenerator()

        original = """if condition:
    do_something()
    do_more()
"""
        diff = """-if condition:
-    do_something()
+if condition and extra:
+    do_something_else()
"""
        result = generator._apply_search_replace(original, diff)

        assert "condition and extra" in result


class TestApplyFixToCode:
    """Tests for apply_fix_to_code method."""

    def test_apply_fix_success(self, temp_dir: Path) -> None:
        """Test successfully applying a fix."""
        generator = FixGenerator()

        # Create test file
        test_file = temp_dir / "test.py"
        test_file.write_text("""def process(data):
    return data.value
""")

        fix = FixProposal(
            issue_id="123",
            fix_description="Add null check",
            code_changes={
                "test.py": """-    return data.value
+    return data.value if data else None
"""
            },
            confidence_score=0.9,
        )

        result = generator.apply_fix_to_code(test_file, fix)

        assert "data.value if data else None" in result

    def test_apply_fix_file_not_found(self, temp_dir: Path) -> None:
        """Test applying fix to non-existent file."""
        generator = FixGenerator()

        fix = FixProposal(
            issue_id="123",
            fix_description="Fix",
            code_changes={"test.py": "+# fix"},
            confidence_score=0.9,
        )

        with pytest.raises(FixValidationError):
            generator.apply_fix_to_code(temp_dir / "nonexistent.py", fix)

    def test_apply_fix_no_matching_diff(self, temp_dir: Path) -> None:
        """Test applying fix when no diff matches file."""
        generator = FixGenerator()

        test_file = temp_dir / "test.py"
        test_file.write_text("# original content")

        fix = FixProposal(
            issue_id="123",
            fix_description="Fix",
            code_changes={"other.py": "+# fix"},
            confidence_score=0.9,
        )

        # Should return original content when no diff matches
        result = generator.apply_fix_to_code(test_file, fix)
        assert result == "# original content"


class TestGenerateDiffPreview:
    """Tests for diff preview generation."""

    def test_generate_diff_preview(self) -> None:
        """Test generating diff preview."""
        generator = FixGenerator()

        original = "line 1\nline 2\nline 3\n"
        new = "line 1\nmodified line 2\nline 3\n"

        diff = generator.generate_diff_preview(original, new, "test.py")

        assert "---" in diff
        assert "+++" in diff
        assert "-line 2" in diff
        assert "+modified line 2" in diff


class TestEstimateFixImpact:
    """Tests for fix impact estimation."""

    def test_estimate_low_impact(self) -> None:
        """Test estimating low impact fix."""
        generator = FixGenerator()

        fix = FixProposal(
            issue_id="123",
            fix_description="Small fix",
            code_changes={"test.py": "+# one line\n-# removed"},
            confidence_score=0.9,
        )

        context = CodeContext(file_path="test.py", file_content="")

        impact = generator.estimate_fix_impact(fix, context)

        assert impact["risk_level"] == "low"
        assert impact["lines_added"] == 1
        assert impact["lines_removed"] == 1

    def test_estimate_high_impact(self) -> None:
        """Test estimating high impact fix."""
        generator = FixGenerator()

        # Many changes
        changes = "\n".join([f"+line {i}" for i in range(40)])
        fix = FixProposal(
            issue_id="123",
            fix_description="Large fix",
            code_changes={"test.py": changes},
            confidence_score=0.4,  # Low confidence
        )

        context = CodeContext(file_path="test.py", file_content="")

        impact = generator.estimate_fix_impact(fix, context)

        assert impact["risk_level"] == "high"
        assert impact["requires_review"] is True


class TestRecordAttempt:
    """Tests for attempt recording."""

    def test_record_attempt(self) -> None:
        """Test recording a fix attempt."""
        generator = FixGenerator()

        proposal = FixProposal(
            issue_id="123",
            fix_description="Test fix",
            code_changes={},
            confidence_score=0.8,
        )

        generator._record_attempt(
            issue_id="123",
            method="pattern",
            success=True,
            proposal=proposal,
        )

        assert len(generator.attempts) == 1
        assert generator.attempts[0].issue_id == "123"
        assert generator.attempts[0].method == "pattern"

    def test_get_attempt_history(self) -> None:
        """Test getting attempt history."""
        generator = FixGenerator()

        # Record multiple attempts
        for i in range(3):
            generator._record_attempt(
                issue_id=f"issue_{i}",
                method="llm",
                success=True,
                proposal=None,
            )

        # Get all
        all_attempts = generator.get_attempt_history()
        assert len(all_attempts) == 3

        # Get filtered
        filtered = generator.get_attempt_history("issue_1")
        assert len(filtered) == 1
        assert filtered[0].issue_id == "issue_1"

    def test_save_debug_info(self, temp_dir: Path) -> None:
        """Test saving debug information."""
        debug_dir = temp_dir / "debug"
        generator = FixGenerator(debug_dir=debug_dir)

        proposal = FixProposal(
            issue_id="123",
            fix_description="Test",
            code_changes={"test.py": "+# fix"},
            confidence_score=0.8,
            explanation="Test explanation",
        )

        generator._record_attempt(
            issue_id="123",
            method="llm",
            success=True,
            proposal=proposal,
            response="LLM response",
        )

        # Check debug file was created
        debug_files = list(debug_dir.glob("*.json"))
        assert len(debug_files) == 1

        # Verify content
        with open(debug_files[0]) as f:
            data = json.load(f)

        assert data["issue_id"] == "123"
        assert data["method"] == "llm"
        assert data["success"] is True


class TestPatternMatchToProposal:
    """Tests for converting pattern matches to proposals."""

    def test_convert_pattern_match(self) -> None:
        """Test converting PatternMatch to FixProposal."""
        generator = FixGenerator()

        pattern = ErrorPattern(
            id="null-check",
            name="Null Reference Check",
            category=ErrorCategory.NULL_REFERENCE,
            languages=["python"],
            exception_types=["TypeError", "AttributeError"],
            message_patterns=[r"'NoneType' object"],
            common_causes=["Accessing attribute on None"],
            typical_fixes=["Add null check before access"],
        )

        match = PatternMatch(
            pattern=pattern,
            confidence=0.85,
            matched_by=["exception_type", "message"],
            suggested_fix=None,
        )

        issue = SentryIssue(
            id="123",
            title="AttributeError: 'NoneType' object has no attribute 'value'",
            level=IssueSeverity.ERROR,
            count=10,
        )

        context = CodeContext(
            file_path="main.py",
            file_content="return obj.value",
            error_line=5,
        )

        proposal = generator._pattern_match_to_proposal(match, issue, context)

        assert proposal.issue_id == "123"
        assert "Null Reference" in proposal.fix_description
        assert proposal.confidence_score == 0.85
        assert "NULL_REFERENCE" in proposal.explanation


class TestTryPatternFix:
    """Tests for pattern-based fix generation."""

    @patch.object(FixGenerator, "pattern_matcher")
    def test_pattern_fix_found(self, mock_matcher: MagicMock) -> None:
        """Test finding a pattern-based fix."""
        generator = FixGenerator()

        pattern = ErrorPattern(
            id="test",
            name="Test Pattern",
            category=ErrorCategory.NULL_REFERENCE,
            languages=["python"],
            exception_types=["Error"],
            message_patterns=[],
            common_causes=["Test"],
            typical_fixes=["Fix"],
        )

        mock_matcher.match_pattern.return_value = PatternMatch(
            pattern=pattern,
            confidence=0.9,
            matched_by=["exception_type"],
            suggested_fix=None,
        )

        issue = SentryIssue(
            id="123",
            title="Error",
            level=IssueSeverity.ERROR,
            count=1,
        )

        context = CodeContext(
            file_path="test.py",
            file_content="# code",
        )

        result = generator._try_pattern_fix(issue, context, None)

        assert result is not None
        assert result.confidence_score >= 0.9

    @patch.object(FixGenerator, "pattern_matcher")
    def test_no_pattern_match(self, mock_matcher: MagicMock) -> None:
        """Test when no pattern matches."""
        generator = FixGenerator()
        mock_matcher.match_pattern.return_value = None

        issue = SentryIssue(
            id="123",
            title="Unknown Error",
            level=IssueSeverity.ERROR,
            count=1,
        )

        context = CodeContext(
            file_path="test.py",
            file_content="# code",
        )

        result = generator._try_pattern_fix(issue, context, None)

        assert result is None


class TestFormatStackTrace:
    """Tests for stack trace formatting."""

    def test_format_stack_trace(self) -> None:
        """Test formatting stack trace for LLM."""
        generator = FixGenerator()

        stack_trace = StackTrace(
            frames=[
                StackFrame(
                    filename="lib/module.py",
                    line_number=10,
                    function="helper",
                    in_app=False,
                ),
                StackFrame(
                    filename="src/main.py",
                    line_number=42,
                    function="process",
                    context_line="    return data.value",
                    in_app=True,
                ),
            ],
            exception_type="AttributeError",
            exception_value="'NoneType' object has no attribute 'value'",
        )

        formatted = generator._format_stack_trace(stack_trace)

        assert "AttributeError" in formatted
        assert "'NoneType' object" in formatted
        assert "[APP]" in formatted
        assert "[LIB]" in formatted
        assert "src/main.py" in formatted


class TestGenerateFix:
    """Tests for the main generate_fix method."""

    @patch.object(FixGenerator, "_try_pattern_fix")
    def test_generate_fix_pattern_success(
        self, mock_pattern_fix: MagicMock
    ) -> None:
        """Test generate_fix with successful pattern match."""
        generator = FixGenerator()

        mock_pattern_fix.return_value = FixProposal(
            issue_id="123",
            fix_description="Pattern fix",
            code_changes={"test.py": "+# fix"},
            confidence_score=0.9,
        )

        issue = SentryIssue(
            id="123",
            title="Error",
            level=IssueSeverity.ERROR,
            count=1,
        )

        context = CodeContext(
            file_path="test.py",
            file_content="# code",
        )

        result = generator.generate_fix(issue, context, Path("/repo"))

        assert result is not None
        assert result.fix_description == "Pattern fix"

    @patch.object(FixGenerator, "_try_pattern_fix")
    @patch.object(FixGenerator, "_try_llm_fix")
    def test_generate_fix_fallback_to_llm(
        self,
        mock_llm_fix: MagicMock,
        mock_pattern_fix: MagicMock,
    ) -> None:
        """Test generate_fix falls back to LLM when pattern fails."""
        generator = FixGenerator()

        mock_pattern_fix.return_value = None
        mock_llm_fix.return_value = FixProposal(
            issue_id="123",
            fix_description="LLM fix",
            code_changes={"test.py": "+# llm fix"},
            confidence_score=0.75,
        )

        issue = SentryIssue(
            id="123",
            title="Complex Error",
            level=IssueSeverity.ERROR,
            count=1,
        )

        context = CodeContext(
            file_path="test.py",
            file_content="# code",
        )

        result = generator.generate_fix(issue, context, Path("/repo"))

        assert result is not None
        assert result.fix_description == "LLM fix"

    @patch.object(FixGenerator, "_try_pattern_fix")
    @patch.object(FixGenerator, "_try_llm_fix")
    def test_generate_fix_both_fail(
        self,
        mock_llm_fix: MagicMock,
        mock_pattern_fix: MagicMock,
    ) -> None:
        """Test generate_fix raises when both methods fail."""
        generator = FixGenerator()

        mock_pattern_fix.return_value = None
        mock_llm_fix.return_value = None

        issue = SentryIssue(
            id="123",
            title="Unfixable Error",
            level=IssueSeverity.ERROR,
            count=1,
        )

        context = CodeContext(
            file_path="test.py",
            file_content="# code",
        )

        with pytest.raises(FixGenerationError):
            generator.generate_fix(issue, context, Path("/repo"))
