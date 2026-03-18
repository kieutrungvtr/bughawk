"""Fix generator module for creating and validating code fixes.

This module orchestrates the fix generation process, combining pattern matching
for known issues with LLM-powered analysis for complex bugs.

The hawk's hunting strategy - quick strikes for familiar prey,
careful reconnaissance for unfamiliar targets.
"""

import ast
import difflib
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from bughawk.analyzer.context_builder import ContextBuilder, EnrichedContext
from bughawk.analyzer.pattern_matcher import PatternMatch, PatternMatcher
from bughawk.core.models import CodeContext, FixProposal, SentryIssue, StackTrace
from bughawk.fixer.llm_client import LLMClient, LLMError
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class FixAttempt:
    """Record of a fix generation attempt.

    The hawk's hunting log - documenting each approach.
    """

    timestamp: datetime
    issue_id: str
    method: str  # "pattern" or "llm"
    success: bool
    proposal: FixProposal | None
    error: str | None = None
    prompt: str | None = None
    response: str | None = None
    validation_result: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of fix validation.

    The hawk's quality control check.
    """

    is_valid: bool
    syntax_valid: bool
    changes_error_location: bool
    scope_appropriate: bool
    confidence_adjustment: float
    issues: list[str]
    warnings: list[str]


class FixGenerationError(Exception):
    """Raised when fix generation fails."""

    pass


class FixValidationError(Exception):
    """Raised when fix validation fails."""

    pass


class FixGenerator:
    """Generates and validates code fixes.

    The hawk's master hunting strategy - combining instinct (patterns)
    with intelligence (LLM) for precise bug elimination.

    This class orchestrates the fix generation process:
    1. Check pattern matcher for known issues (quick strike)
    2. Fall back to LLM for complex issues (careful reconnaissance)
    3. Validate proposed fixes for safety
    4. Apply fixes to code without modifying files

    Example:
        >>> generator = FixGenerator()
        >>> fix = generator.generate_fix(issue, context, repo_path)
        >>> if fix.confidence_score >= 0.7:
        ...     new_code = generator.apply_fix_to_code(file_path, fix)
    """

    # Maximum number of lines a fix should change
    MAX_CHANGED_LINES = 50

    # Minimum confidence to consider a fix valid
    MIN_CONFIDENCE = 0.3

    def __init__(
        self,
        pattern_matcher: PatternMatcher | None = None,
        llm_client: LLMClient | None = None,
        context_builder: ContextBuilder | None = None,
        debug_dir: Path | None = None,
    ) -> None:
        """Initialize FixGenerator.

        The hawk prepares its hunting arsenal.

        Args:
            pattern_matcher: Pattern matcher instance
            llm_client: LLM client instance
            context_builder: Context builder instance
            debug_dir: Directory to store debug information
        """
        self.pattern_matcher = pattern_matcher or PatternMatcher()
        self.llm_client = llm_client
        self.context_builder = context_builder or ContextBuilder()

        self.debug_dir = debug_dir
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)

        self.attempts: list[FixAttempt] = []

        logger.info("FixGenerator initialized - hawk ready for the hunt")

    def _get_llm_client(self) -> LLMClient:
        """Get or create LLM client (lazy initialization)."""
        if self.llm_client is None:
            self.llm_client = LLMClient()
        return self.llm_client

    def generate_fix(
        self,
        issue: SentryIssue,
        context: CodeContext,
        repo_path: Path,
        stack_trace: StackTrace | None = None,
        prefer_pattern: bool = True,
    ) -> FixProposal:
        """Generate a fix for the given issue.

        The hawk's hunting sequence:
        1. Direct strike - check for known patterns (fast, reliable)
        2. Reconnaissance - use LLM analysis (thorough, adaptive)

        Args:
            issue: The Sentry issue to fix
            context: Code context around the error
            repo_path: Path to the repository
            stack_trace: Optional stack trace for additional context
            prefer_pattern: Whether to try pattern matching first

        Returns:
            FixProposal with suggested changes

        Raises:
            FixGenerationError: If fix generation fails
        """
        logger.info("Hawk initiating hunt for issue: %s", issue.id)

        # Phase 1: Direct strike on known prey (pattern matching)
        if prefer_pattern:
            pattern_fix = self._try_pattern_fix(issue, context, stack_trace)
            if pattern_fix:
                logger.info(
                    "Hawk captured prey with direct strike (pattern match): %s",
                    pattern_fix.fix_description,
                )
                return pattern_fix

        # Phase 2: Careful reconnaissance (LLM analysis)
        logger.info("Hawk beginning careful reconnaissance (LLM analysis)")
        llm_fix = self._try_llm_fix(issue, context, repo_path, stack_trace)

        if llm_fix:
            logger.info(
                "Hawk captured prey after reconnaissance: %s (confidence: %.0f%%)",
                llm_fix.fix_description,
                llm_fix.confidence_score * 100,
            )
            return llm_fix

        # Failed to generate fix
        raise FixGenerationError(
            f"Hawk could not capture prey - failed to generate fix for issue {issue.id}"
        )

    def _try_pattern_fix(
        self,
        issue: SentryIssue,
        context: CodeContext,
        stack_trace: StackTrace | None,
    ) -> FixProposal | None:
        """Try to generate a fix using pattern matching.

        Direct strike on known prey - fast and reliable.
        """
        logger.debug("Hawk scanning for known prey patterns")

        code_context_str = None
        if context.surrounding_lines:
            code_context_str = "\n".join(
                f"{ln}: {code}" for ln, code in sorted(context.surrounding_lines.items())
            )

        match = self.pattern_matcher.match_pattern(
            issue=issue,
            stack_trace=stack_trace,
            code_context=code_context_str,
        )

        if not match or not match.is_confident_match:
            logger.debug("No confident pattern match found")
            return None

        # Convert pattern match to fix proposal
        fix = self._pattern_match_to_proposal(match, issue, context)

        # Record attempt
        self._record_attempt(
            issue_id=issue.id,
            method="pattern",
            success=True,
            proposal=fix,
        )

        return fix

    def _pattern_match_to_proposal(
        self,
        match: PatternMatch,
        issue: SentryIssue,
        context: CodeContext,
    ) -> FixProposal:
        """Convert a pattern match to a fix proposal.

        The hawk prepares its catch for delivery.
        """
        pattern = match.pattern
        suggested_fix = match.suggested_fix

        # Build fix description
        description = f"Pattern-based fix: {pattern.name}"
        if suggested_fix:
            description = suggested_fix.description

        # Build explanation
        explanation_parts = [
            f"This error matches the known pattern: **{pattern.name}**",
            "",
            f"**Category**: {pattern.category.value}",
            f"**Confidence**: {match.confidence:.0%}",
            "",
            "**Common causes**:",
        ]
        for cause in pattern.common_causes[:3]:
            explanation_parts.append(f"- {cause}")

        if suggested_fix:
            explanation_parts.extend([
                "",
                "**Suggested approach**:",
                suggested_fix.explanation,
            ])
            if suggested_fix.caveats:
                explanation_parts.extend(["", "**Caveats**:"])
                for caveat in suggested_fix.caveats:
                    explanation_parts.append(f"- {caveat}")

        explanation = "\n".join(explanation_parts)

        # Build code changes (template-based)
        code_changes: dict[str, str] = {}
        if suggested_fix and suggested_fix.code_template and context.file_path:
            # Create a placeholder diff showing the suggested pattern
            code_changes[context.file_path] = (
                f"# Suggested fix pattern:\n"
                f"# {suggested_fix.code_template.replace(chr(10), chr(10) + '# ')}"
            )

        return FixProposal(
            issue_id=issue.id,
            fix_description=description,
            code_changes=code_changes,
            confidence_score=match.confidence,
            explanation=explanation,
        )

    def _try_llm_fix(
        self,
        issue: SentryIssue,
        context: CodeContext,
        repo_path: Path,
        stack_trace: StackTrace | None,
    ) -> FixProposal | None:
        """Try to generate a fix using LLM.

        Careful reconnaissance before the strike.
        """
        try:
            client = self._get_llm_client()
        except LLMError as e:
            logger.warning("Could not initialize LLM client: %s", e)
            self._record_attempt(
                issue_id=issue.id,
                method="llm",
                success=False,
                proposal=None,
                error=str(e),
            )
            return None

        # Format stack trace
        stack_trace_str = None
        if stack_trace:
            stack_trace_str = self._format_stack_trace(stack_trace)

        try:
            # Get analysis and fix from LLM
            analysis, fix = client.analyze_and_fix(
                context=context,
                issue=issue,
                stack_trace=stack_trace_str,
            )

            # Validate the proposed fix
            validation = self.validate_fix(fix, context)

            # Adjust confidence based on validation
            adjusted_confidence = fix.confidence_score * validation.confidence_adjustment
            fix = FixProposal(
                issue_id=fix.issue_id,
                fix_description=fix.fix_description,
                code_changes=fix.code_changes,
                confidence_score=adjusted_confidence,
                explanation=fix.explanation,
            )

            # Record attempt
            self._record_attempt(
                issue_id=issue.id,
                method="llm",
                success=True,
                proposal=fix,
                response=analysis,
                validation_result=validation.__dict__ if hasattr(validation, "__dict__") else {},
            )

            return fix

        except LLMError as e:
            logger.error("LLM fix generation failed: %s", e)
            self._record_attempt(
                issue_id=issue.id,
                method="llm",
                success=False,
                proposal=None,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.error("Unexpected error in LLM fix generation: %s", e)
            self._record_attempt(
                issue_id=issue.id,
                method="llm",
                success=False,
                proposal=None,
                error=str(e),
            )
            return None

    def _format_stack_trace(self, stack_trace: StackTrace) -> str:
        """Format stack trace for LLM prompt."""
        lines = [f"{stack_trace.exception_type}: {stack_trace.exception_value}", ""]

        for frame in reversed(stack_trace.frames):
            marker = "[APP]" if frame.in_app else "[LIB]"
            lines.append(
                f'{marker} File "{frame.filename}", line {frame.line_number}, '
                f"in {frame.function}"
            )
            if frame.context_line:
                lines.append(f"    {frame.context_line.strip()}")

        return "\n".join(lines)

    def validate_fix(
        self,
        proposal: FixProposal,
        context: CodeContext,
    ) -> ValidationResult:
        """Validate a proposed fix for safety and correctness.

        The hawk inspects its catch before delivery.

        Args:
            proposal: The proposed fix
            context: Original code context

        Returns:
            ValidationResult with details
        """
        logger.debug("Hawk validating fix for issue: %s", proposal.issue_id)

        issues: list[str] = []
        warnings: list[str] = []
        confidence_adjustment = 1.0

        syntax_valid = True
        changes_error_location = False
        scope_appropriate = True

        # Check 1: Syntax validity
        for file_path, diff in proposal.code_changes.items():
            if file_path.endswith(".py"):
                syntax_result = self._check_python_syntax(diff, file_path)
                if not syntax_result["valid"]:
                    syntax_valid = False
                    issues.append(f"Syntax error in {file_path}: {syntax_result['error']}")
                    confidence_adjustment *= 0.5

        # Check 2: Changes target the error location
        if context.error_line and context.file_path:
            for file_path, diff in proposal.code_changes.items():
                if context.file_path in file_path or file_path in context.file_path:
                    # Check if diff mentions error line
                    if str(context.error_line) in diff or self._diff_affects_line(
                        diff, context.error_line
                    ):
                        changes_error_location = True
                        break

            if not changes_error_location:
                warnings.append(
                    f"Fix may not address error location (line {context.error_line})"
                )
                confidence_adjustment *= 0.8

        # Check 3: Scope is appropriate (not too broad)
        total_changed_lines = 0
        for diff in proposal.code_changes.values():
            changed = diff.count("\n+") + diff.count("\n-")
            total_changed_lines += changed

        if total_changed_lines > self.MAX_CHANGED_LINES:
            scope_appropriate = False
            warnings.append(
                f"Fix changes {total_changed_lines} lines (max: {self.MAX_CHANGED_LINES})"
            )
            confidence_adjustment *= 0.7

        # Check 4: Fix targets correct file
        if proposal.code_changes and context.file_path:
            target_files = list(proposal.code_changes.keys())
            if not any(
                context.file_path in f or f in context.file_path for f in target_files
            ):
                issues.append(
                    f"Fix targets {target_files} but error is in {context.file_path}"
                )
                confidence_adjustment *= 0.3

        # Check 5: Confidence threshold
        if proposal.confidence_score < self.MIN_CONFIDENCE:
            warnings.append(
                f"Low confidence score: {proposal.confidence_score:.0%}"
            )

        is_valid = len(issues) == 0 and syntax_valid

        result = ValidationResult(
            is_valid=is_valid,
            syntax_valid=syntax_valid,
            changes_error_location=changes_error_location,
            scope_appropriate=scope_appropriate,
            confidence_adjustment=confidence_adjustment,
            issues=issues,
            warnings=warnings,
        )

        if is_valid:
            logger.info("Hawk validated fix successfully")
        else:
            logger.warning("Hawk found issues with fix: %s", issues)

        return result

    def _check_python_syntax(self, diff_or_code: str, file_path: str) -> dict[str, Any]:
        """Check Python code for syntax errors.

        Args:
            diff_or_code: Diff string or code to check
            file_path: File path for error messages

        Returns:
            Dict with 'valid' bool and optional 'error' string
        """
        # Extract added lines from diff
        code_lines = []
        for line in diff_or_code.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                code_lines.append(line[1:])  # Remove + prefix
            elif not line.startswith("-") and not line.startswith("@@"):
                # Context line
                code_lines.append(line)

        # If no added lines, might be full code
        if not code_lines:
            code_lines = diff_or_code.split("\n")

        code = "\n".join(code_lines)

        try:
            ast.parse(code)
            return {"valid": True}
        except SyntaxError as e:
            return {"valid": False, "error": str(e)}
        except Exception:
            # Can't parse partial code - assume valid
            return {"valid": True}

    def _diff_affects_line(self, diff: str, line_number: int) -> bool:
        """Check if a diff affects a specific line number.

        Args:
            diff: Unified diff string
            line_number: Line number to check

        Returns:
            True if diff affects the line
        """
        # Parse @@ -start,count +start,count @@ headers
        hunk_pattern = r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"

        current_line = 0
        for match in re.finditer(hunk_pattern, diff):
            start_line = int(match.group(2))  # New file line number
            # Check if error line is near this hunk
            if abs(start_line - line_number) < 20:
                return True

        return False

    def apply_fix_to_code(
        self,
        file_path: Path,
        fix: FixProposal,
    ) -> str:
        """Apply a fix to code and return the result.

        Does NOT modify the file on disk.

        The hawk delivers its catch for inspection.

        Args:
            file_path: Path to the original file
            fix: The fix to apply

        Returns:
            New file content with fix applied

        Raises:
            FixValidationError: If fix cannot be applied
        """
        logger.debug("Hawk applying fix to: %s", file_path)

        file_path = Path(file_path)

        # Read original content
        try:
            original_content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise FixValidationError(f"Cannot read file {file_path}: {e}")

        # Find the relevant diff for this file
        diff_content = None
        file_path_str = str(file_path)

        for target, diff in fix.code_changes.items():
            if target in file_path_str or file_path_str in target or Path(target).name == file_path.name:
                diff_content = diff
                break

        if not diff_content:
            logger.warning("No diff found for file: %s", file_path)
            return original_content

        # Try to apply diff
        try:
            new_content = self._apply_unified_diff(original_content, diff_content)
            logger.info("Hawk successfully applied fix to %s", file_path)
            return new_content
        except Exception as e:
            logger.warning("Could not apply diff, trying alternative methods: %s", e)

        # Alternative: Try search/replace patterns in diff
        try:
            new_content = self._apply_search_replace(original_content, diff_content)
            if new_content != original_content:
                logger.info("Hawk applied fix using search/replace")
                return new_content
        except Exception as e:
            logger.warning("Search/replace failed: %s", e)

        # If all else fails, return original with comment
        logger.warning("Could not apply fix automatically to %s", file_path)
        return original_content

    def _apply_unified_diff(self, original: str, diff: str) -> str:
        """Apply a unified diff to original content.

        Args:
            original: Original file content
            diff: Unified diff string

        Returns:
            Patched content
        """
        # Parse the diff to extract hunks
        lines = original.split("\n")
        diff_lines = diff.split("\n")

        # Find hunk headers and apply changes
        hunk_pattern = r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"

        result_lines = lines.copy()
        offset = 0  # Track line number changes

        i = 0
        while i < len(diff_lines):
            line = diff_lines[i]
            match = re.match(hunk_pattern, line)

            if match:
                old_start = int(match.group(1)) - 1  # Convert to 0-indexed
                new_start = int(match.group(3)) - 1

                # Collect hunk changes
                additions = []
                deletions = []
                j = i + 1

                while j < len(diff_lines) and not diff_lines[j].startswith("@@"):
                    hunk_line = diff_lines[j]
                    if hunk_line.startswith("+") and not hunk_line.startswith("+++"):
                        additions.append(hunk_line[1:])
                    elif hunk_line.startswith("-") and not hunk_line.startswith("---"):
                        deletions.append(hunk_line[1:])
                    j += 1

                # Apply the hunk
                if deletions or additions:
                    # Find where to apply in result
                    apply_pos = old_start + offset

                    # Remove deleted lines
                    for _ in deletions:
                        if apply_pos < len(result_lines):
                            result_lines.pop(apply_pos)

                    # Add new lines
                    for idx, add_line in enumerate(additions):
                        result_lines.insert(apply_pos + idx, add_line)

                    # Update offset
                    offset += len(additions) - len(deletions)

                i = j
            else:
                i += 1

        return "\n".join(result_lines)

    def _apply_search_replace(self, original: str, diff: str) -> str:
        """Try to apply diff as search/replace patterns.

        Args:
            original: Original content
            diff: Diff content with - and + lines

        Returns:
            Modified content
        """
        result = original

        # Extract search (- lines) and replace (+ lines) pairs
        diff_lines = diff.split("\n")
        search_lines = []
        replace_lines = []

        for line in diff_lines:
            if line.startswith("-") and not line.startswith("---"):
                search_lines.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                replace_lines.append(line[1:])

        # Try to find and replace the search pattern
        if search_lines:
            search_text = "\n".join(search_lines)
            replace_text = "\n".join(replace_lines)

            if search_text in result:
                result = result.replace(search_text, replace_text, 1)

        return result

    def _record_attempt(
        self,
        issue_id: str,
        method: str,
        success: bool,
        proposal: FixProposal | None,
        error: str | None = None,
        prompt: str | None = None,
        response: str | None = None,
        validation_result: dict[str, Any] | None = None,
    ) -> None:
        """Record a fix generation attempt.

        The hawk logs its hunting activity.
        """
        attempt = FixAttempt(
            timestamp=datetime.now(),
            issue_id=issue_id,
            method=method,
            success=success,
            proposal=proposal,
            error=error,
            prompt=prompt,
            response=response,
            validation_result=validation_result or {},
        )

        self.attempts.append(attempt)

        # Save to debug directory if configured
        if self.debug_dir:
            self._save_debug_info(attempt)

    def _save_debug_info(self, attempt: FixAttempt) -> None:
        """Save debug information for an attempt.

        The hawk's detailed hunting journal.
        """
        timestamp = attempt.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{attempt.issue_id}_{attempt.method}.json"
        filepath = self.debug_dir / filename

        debug_data = {
            "timestamp": attempt.timestamp.isoformat(),
            "issue_id": attempt.issue_id,
            "method": attempt.method,
            "success": attempt.success,
            "error": attempt.error,
            "prompt": attempt.prompt,
            "response": attempt.response,
            "validation_result": attempt.validation_result,
        }

        if attempt.proposal:
            debug_data["proposal"] = {
                "fix_description": attempt.proposal.fix_description,
                "confidence_score": attempt.proposal.confidence_score,
                "explanation": attempt.proposal.explanation,
                "code_changes": attempt.proposal.code_changes,
            }

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(debug_data, f, indent=2, default=str)
            logger.debug("Debug info saved to: %s", filepath)
        except OSError as e:
            logger.warning("Failed to save debug info: %s", e)

    def get_attempt_history(self, issue_id: str | None = None) -> list[FixAttempt]:
        """Get fix attempt history.

        Args:
            issue_id: Filter by issue ID if provided

        Returns:
            List of FixAttempt records
        """
        if issue_id:
            return [a for a in self.attempts if a.issue_id == issue_id]
        return self.attempts.copy()

    def generate_diff_preview(
        self,
        original_content: str,
        new_content: str,
        file_path: str,
    ) -> str:
        """Generate a unified diff preview.

        Args:
            original_content: Original file content
            new_content: New file content with fix
            file_path: File path for diff header

        Returns:
            Unified diff string
        """
        original_lines = original_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
        )

        return "".join(diff)

    def estimate_fix_impact(
        self,
        fix: FixProposal,
        context: CodeContext,
    ) -> dict[str, Any]:
        """Estimate the impact of applying a fix.

        The hawk assesses the aftermath of the strike.

        Args:
            fix: The proposed fix
            context: Code context

        Returns:
            Impact assessment dict
        """
        impact = {
            "files_affected": len(fix.code_changes),
            "lines_changed": 0,
            "lines_added": 0,
            "lines_removed": 0,
            "risk_level": "low",
            "requires_review": fix.confidence_score < 0.7,
        }

        for diff in fix.code_changes.values():
            for line in diff.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    impact["lines_added"] += 1
                elif line.startswith("-") and not line.startswith("---"):
                    impact["lines_removed"] += 1

        impact["lines_changed"] = impact["lines_added"] + impact["lines_removed"]

        # Assess risk level
        if impact["lines_changed"] > 30:
            impact["risk_level"] = "high"
        elif impact["lines_changed"] > 10:
            impact["risk_level"] = "medium"

        if fix.confidence_score < 0.5:
            impact["risk_level"] = "high"

        return impact
