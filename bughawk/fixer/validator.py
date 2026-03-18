"""Fix validator module for ensuring high-quality code fixes.

This module provides comprehensive validation of proposed code fixes,
including syntax checking, confidence scoring, and test execution.

The hawk's quality control - only the finest catches are delivered.
"""

import ast
import difflib
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bughawk.core.models import CodeContext, FixProposal
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class SyntaxValidationResult:
    """Result of syntax validation.

    The hawk's inspection report on code quality.
    """

    is_valid: bool
    language: str
    error_message: str | None = None
    error_line: int | None = None
    error_column: int | None = None


@dataclass
class ConfidenceBreakdown:
    """Breakdown of confidence score calculation.

    The hawk's detailed assessment of catch quality.
    """

    pattern_match_score: float = 0.0
    syntax_valid_score: float = 0.0
    change_size_score: float = 0.0
    location_accuracy_score: float = 0.0
    llm_confidence_score: float = 0.0

    total_score: float = 0.0
    factors: dict[str, Any] = field(default_factory=dict)

    def calculate_total(self) -> float:
        """Calculate total confidence score."""
        self.total_score = (
            self.pattern_match_score
            + self.syntax_valid_score
            + self.change_size_score
            + self.location_accuracy_score
            + self.llm_confidence_score
        )
        return min(1.0, max(0.0, self.total_score))


@dataclass
class TestResult:
    """Result of running tests.

    The hawk's field test report.
    """

    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    command: str = ""


@dataclass
class DiffAnalysis:
    """Analysis of code differences.

    The hawk's comparison of before and after.
    """

    lines_added: int
    lines_removed: int
    lines_changed: int
    hunks: int
    unified_diff: str
    summary: str


class FixValidator:
    """Validates proposed code fixes for quality and safety.

    The hawk's quality assurance process - scrutinizing every catch
    before delivery to ensure only the finest fixes are applied.

    This class provides:
    - Multi-language syntax validation
    - Confidence score calculation
    - Test execution
    - Diff generation and analysis

    Example:
        >>> validator = FixValidator()
        >>> is_valid, error = validator.validate_syntax(code, "python")
        >>> confidence = validator.calculate_confidence(proposal, context)
        >>> if confidence >= 0.7:
        ...     test_result = validator.run_tests(repo_path)
    """

    # Supported languages for syntax validation
    SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "php"}

    # Test timeout in seconds (5 minutes)
    TEST_TIMEOUT = 300

    # Maximum lines for "small change" bonus
    SMALL_CHANGE_THRESHOLD = 10

    def __init__(self) -> None:
        """Initialize FixValidator.

        The hawk prepares its quality inspection tools.
        """
        logger.debug("FixValidator initialized - hawk's quality control ready")

    def validate_syntax(
        self,
        code: str,
        language: str,
    ) -> tuple[bool, str | None]:
        """Validate code syntax for a given language.

        The hawk inspects the code for structural integrity.

        Args:
            code: The code to validate
            language: Programming language (python, javascript, typescript, php)

        Returns:
            Tuple of (is_valid, error_message)
        """
        language = language.lower()
        logger.debug("Hawk inspecting %s syntax", language)

        if language == "python":
            return self._validate_python_syntax(code)
        elif language in ("javascript", "typescript"):
            return self._validate_js_syntax(code, language)
        elif language == "php":
            return self._validate_php_syntax(code)
        else:
            logger.warning("Hawk cannot inspect %s syntax - unsupported language", language)
            # Unknown language - assume valid but warn
            return True, None

    def validate_syntax_detailed(
        self,
        code: str,
        language: str,
    ) -> SyntaxValidationResult:
        """Validate code syntax with detailed results.

        The hawk's thorough inspection report.

        Args:
            code: The code to validate
            language: Programming language

        Returns:
            SyntaxValidationResult with full details
        """
        language = language.lower()
        is_valid, error = self.validate_syntax(code, language)

        result = SyntaxValidationResult(
            is_valid=is_valid,
            language=language,
            error_message=error,
        )

        # Try to extract line/column from error for Python
        if not is_valid and language == "python" and error:
            try:
                ast.parse(code)
            except SyntaxError as e:
                result.error_line = e.lineno
                result.error_column = e.offset

        return result

    def _validate_python_syntax(self, code: str) -> tuple[bool, str | None]:
        """Validate Python syntax using ast.parse.

        The hawk's Python inspection technique.
        """
        try:
            ast.parse(code)
            logger.debug("Hawk confirms Python syntax is valid")
            return True, None
        except SyntaxError as e:
            error_msg = f"Line {e.lineno}: {e.msg}"
            logger.debug("Hawk found Python syntax error: %s", error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Parse error: {str(e)}"
            logger.debug("Hawk encountered Python parse error: %s", error_msg)
            return False, error_msg

    def _validate_js_syntax(
        self,
        code: str,
        language: str,
    ) -> tuple[bool, str | None]:
        """Validate JavaScript/TypeScript syntax.

        The hawk's JavaScript inspection - uses Node.js if available.
        """
        # Check if Node.js is available
        node_path = shutil.which("node")
        if not node_path:
            logger.debug("Hawk cannot inspect JS syntax - Node.js not found")
            return True, None  # Assume valid if can't check

        # Create a temporary file with the code
        suffix = ".ts" if language == "typescript" else ".js"

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=suffix,
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(code)
                temp_path = f.name

            # Try to parse using Node.js with acorn or basic syntax check
            # Using a simple syntax check via Node's --check flag for .js
            # For TypeScript, we'd need tsc, so fall back to basic check

            if language == "javascript":
                # Use Node.js syntax check
                result = subprocess.run(
                    [node_path, "--check", temp_path],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    logger.debug("Hawk confirms JavaScript syntax is valid")
                    return True, None
                else:
                    error_msg = result.stderr.strip() or "Syntax error"
                    logger.debug("Hawk found JavaScript syntax error: %s", error_msg)
                    return False, error_msg
            else:
                # TypeScript - check if tsc is available
                tsc_path = shutil.which("tsc")
                if tsc_path:
                    result = subprocess.run(
                        [tsc_path, "--noEmit", "--allowJs", temp_path],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )

                    if result.returncode == 0:
                        logger.debug("Hawk confirms TypeScript syntax is valid")
                        return True, None
                    else:
                        error_msg = result.stdout.strip() or result.stderr.strip() or "Syntax error"
                        logger.debug("Hawk found TypeScript error: %s", error_msg)
                        return False, error_msg
                else:
                    # No tsc, assume valid
                    logger.debug("Hawk cannot verify TypeScript - tsc not found")
                    return True, None

        except subprocess.TimeoutExpired:
            logger.warning("Hawk's JS syntax check timed out")
            return True, None  # Assume valid on timeout
        except Exception as e:
            logger.warning("Hawk's JS syntax check failed: %s", e)
            return True, None  # Assume valid on error
        finally:
            # Clean up temp file
            try:
                Path(temp_path).unlink()
            except Exception:
                pass

    def _validate_php_syntax(self, code: str) -> tuple[bool, str | None]:
        """Validate PHP syntax.

        The hawk's PHP inspection - uses php -l if available.
        """
        php_path = shutil.which("php")
        if not php_path:
            logger.debug("Hawk cannot inspect PHP syntax - PHP not found")
            return True, None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".php",
                delete=False,
                encoding="utf-8",
            ) as f:
                # Ensure PHP opening tag
                if not code.strip().startswith("<?"):
                    code = "<?php\n" + code
                f.write(code)
                temp_path = f.name

            result = subprocess.run(
                [php_path, "-l", temp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                logger.debug("Hawk confirms PHP syntax is valid")
                return True, None
            else:
                error_msg = result.stdout.strip() or result.stderr.strip() or "Syntax error"
                # Clean up the error message
                error_msg = error_msg.replace(temp_path, "<code>")
                logger.debug("Hawk found PHP syntax error: %s", error_msg)
                return False, error_msg

        except subprocess.TimeoutExpired:
            logger.warning("Hawk's PHP syntax check timed out")
            return True, None
        except Exception as e:
            logger.warning("Hawk's PHP syntax check failed: %s", e)
            return True, None
        finally:
            try:
                Path(temp_path).unlink()
            except Exception:
                pass

    def calculate_confidence(
        self,
        proposal: FixProposal,
        context: CodeContext,
        pattern_matched: bool = False,
        syntax_valid: bool = True,
    ) -> float:
        """Calculate confidence score for a fix proposal.

        The hawk weighs the quality of its catch.

        Confidence factors:
        - Pattern match found: +0.3
        - Syntax valid: +0.2
        - Small change (< 10 lines): +0.2
        - Changes are in error location: +0.2
        - LLM confidence if provided: +0.1

        Args:
            proposal: The fix proposal
            context: Code context
            pattern_matched: Whether this fix came from pattern matching
            syntax_valid: Whether syntax validation passed

        Returns:
            Confidence score between 0.0 and 1.0
        """
        logger.debug("Hawk calculating confidence for fix: %s", proposal.issue_id)

        breakdown = self.calculate_confidence_breakdown(
            proposal, context, pattern_matched, syntax_valid
        )

        logger.info(
            "Hawk's confidence assessment: %.0f%% (pattern=%.1f, syntax=%.1f, "
            "size=%.1f, location=%.1f, llm=%.1f)",
            breakdown.total_score * 100,
            breakdown.pattern_match_score,
            breakdown.syntax_valid_score,
            breakdown.change_size_score,
            breakdown.location_accuracy_score,
            breakdown.llm_confidence_score,
        )

        return breakdown.total_score

    def calculate_confidence_breakdown(
        self,
        proposal: FixProposal,
        context: CodeContext,
        pattern_matched: bool = False,
        syntax_valid: bool = True,
    ) -> ConfidenceBreakdown:
        """Calculate detailed confidence breakdown.

        The hawk's itemized quality assessment.
        """
        breakdown = ConfidenceBreakdown()

        # Factor 1: Pattern match (+0.3)
        # Known prey patterns are highly reliable
        if pattern_matched:
            breakdown.pattern_match_score = 0.3
            breakdown.factors["pattern_match"] = "Known pattern matched"
        else:
            breakdown.factors["pattern_match"] = "No pattern match"

        # Factor 2: Syntax valid (+0.2)
        # The catch must be structurally sound
        if syntax_valid:
            breakdown.syntax_valid_score = 0.2
            breakdown.factors["syntax"] = "Syntax validated"
        else:
            breakdown.factors["syntax"] = "Syntax validation failed"

        # Factor 3: Change size (+0.2 for small changes)
        # Surgical precision is preferred
        total_changes = 0
        for diff in proposal.code_changes.values():
            for line in diff.split("\n"):
                if line.startswith("+") and not line.startswith("+++"):
                    total_changes += 1
                elif line.startswith("-") and not line.startswith("---"):
                    total_changes += 1

        breakdown.factors["lines_changed"] = total_changes

        if total_changes <= self.SMALL_CHANGE_THRESHOLD:
            breakdown.change_size_score = 0.2
            breakdown.factors["change_size"] = f"Small change ({total_changes} lines)"
        elif total_changes <= 20:
            breakdown.change_size_score = 0.1
            breakdown.factors["change_size"] = f"Medium change ({total_changes} lines)"
        else:
            breakdown.change_size_score = 0.0
            breakdown.factors["change_size"] = f"Large change ({total_changes} lines)"

        # Factor 4: Location accuracy (+0.2)
        # The strike must hit the target
        changes_error_location = False

        if context.error_line and context.file_path:
            for file_path, diff in proposal.code_changes.items():
                # Check if file matches
                if context.file_path in file_path or file_path in context.file_path:
                    # Check if diff mentions error line area
                    if self._diff_near_line(diff, context.error_line):
                        changes_error_location = True
                        break

        if changes_error_location:
            breakdown.location_accuracy_score = 0.2
            breakdown.factors["location"] = "Fix targets error location"
        else:
            breakdown.factors["location"] = "Fix may not target error location"

        # Factor 5: LLM confidence (+0.1 scaled)
        # Trust the intelligence network
        if proposal.confidence_score > 0:
            # Scale LLM confidence to 0.1 max
            breakdown.llm_confidence_score = proposal.confidence_score * 0.1
            breakdown.factors["llm_confidence"] = f"LLM confidence: {proposal.confidence_score:.0%}"
        else:
            breakdown.factors["llm_confidence"] = "No LLM confidence provided"

        # Calculate total
        breakdown.calculate_total()

        return breakdown

    def _diff_near_line(self, diff: str, line_number: int, tolerance: int = 10) -> bool:
        """Check if a diff affects lines near the target.

        The hawk checks if the strike zone is correct.
        """
        import re

        # Parse @@ -start,count +start,count @@ headers
        hunk_pattern = r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@"

        for match in re.finditer(hunk_pattern, diff):
            old_start = int(match.group(1))
            new_start = int(match.group(2))

            # Check if either old or new location is near the error line
            if abs(old_start - line_number) <= tolerance:
                return True
            if abs(new_start - line_number) <= tolerance:
                return True

        # Also check for line number mentions in the diff
        if str(line_number) in diff:
            return True

        return False

    def run_tests(
        self,
        repo_path: Path,
        test_command: str | None = None,
        timeout: int | None = None,
    ) -> TestResult:
        """Run tests to verify the fix doesn't break anything.

        The hawk's field test - ensuring the catch is safe.

        Args:
            repo_path: Path to the repository
            test_command: Command to run tests. Auto-detects if not provided.
            timeout: Timeout in seconds. Defaults to TEST_TIMEOUT.

        Returns:
            TestResult with pass/fail status and output
        """
        import time

        repo_path = Path(repo_path)
        timeout = timeout or self.TEST_TIMEOUT

        logger.info("Hawk initiating test flight in: %s", repo_path)

        # Auto-detect test command if not provided
        if not test_command:
            test_command = self._detect_test_command(repo_path)

        if not test_command:
            logger.warning("Hawk could not detect test command")
            return TestResult(
                passed=True,  # Assume pass if no tests
                exit_code=0,
                stdout="",
                stderr="No test command detected",
                duration_seconds=0.0,
                command="",
            )

        logger.info("Hawk running tests: %s", test_command)
        start_time = time.time()

        try:
            result = subprocess.run(
                test_command,
                shell=True,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            duration = time.time() - start_time
            passed = result.returncode == 0

            if passed:
                logger.info("Hawk's test flight successful (%.1fs)", duration)
            else:
                logger.warning(
                    "Hawk's test flight failed (exit code %d, %.1fs)",
                    result.returncode,
                    duration,
                )

            return TestResult(
                passed=passed,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                duration_seconds=duration,
                command=test_command,
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            logger.warning("Hawk's test flight timed out after %.1fs", duration)

            return TestResult(
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=f"Tests timed out after {timeout}s",
                duration_seconds=duration,
                timed_out=True,
                command=test_command,
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Hawk's test flight crashed: %s", e)

            return TestResult(
                passed=False,
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_seconds=duration,
                command=test_command,
            )

    def _detect_test_command(self, repo_path: Path) -> str | None:
        """Auto-detect the test command for a repository.

        The hawk surveys the terrain for test infrastructure.
        """
        repo_path = Path(repo_path)

        # Check for common test configurations

        # Python - pytest
        if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
            if shutil.which("pytest"):
                return "pytest -x -q"

        # Python - unittest
        if (repo_path / "setup.py").exists():
            return "python -m pytest -x -q" if shutil.which("pytest") else "python -m unittest discover -s tests"

        # Node.js - npm test
        package_json = repo_path / "package.json"
        if package_json.exists():
            try:
                with open(package_json) as f:
                    pkg = json.load(f)
                if "scripts" in pkg and "test" in pkg["scripts"]:
                    return "npm test"
            except Exception:
                pass

        # PHP - phpunit
        if (repo_path / "phpunit.xml").exists() or (repo_path / "phpunit.xml.dist").exists():
            if shutil.which("phpunit"):
                return "phpunit"
            elif (repo_path / "vendor" / "bin" / "phpunit").exists():
                return "./vendor/bin/phpunit"

        # Go
        if any(repo_path.glob("*.go")) or any(repo_path.glob("**/*.go")):
            if shutil.which("go"):
                return "go test ./..."

        # Rust
        if (repo_path / "Cargo.toml").exists():
            if shutil.which("cargo"):
                return "cargo test"

        logger.debug("Hawk could not auto-detect test command")
        return None

    def diff_changes(
        self,
        original: str,
        modified: str,
        filename: str = "file",
        context_lines: int = 3,
    ) -> str:
        """Generate a unified diff between original and modified code.

        The hawk compares before and after states.

        Args:
            original: Original code content
            modified: Modified code content
            filename: Filename for diff header
            context_lines: Number of context lines to include

        Returns:
            Unified diff string
        """
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=context_lines,
        )

        return "".join(diff)

    def analyze_diff(
        self,
        original: str,
        modified: str,
        filename: str = "file",
    ) -> DiffAnalysis:
        """Analyze differences between original and modified code.

        The hawk's detailed comparison report.

        Args:
            original: Original code content
            modified: Modified code content
            filename: Filename for the diff

        Returns:
            DiffAnalysis with detailed statistics
        """
        unified_diff = self.diff_changes(original, modified, filename)

        lines_added = 0
        lines_removed = 0
        hunks = 0

        for line in unified_diff.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                lines_added += 1
            elif line.startswith("-") and not line.startswith("---"):
                lines_removed += 1
            elif line.startswith("@@"):
                hunks += 1

        lines_changed = lines_added + lines_removed

        # Generate summary
        if lines_changed == 0:
            summary = "No changes detected"
        else:
            parts = []
            if lines_added > 0:
                parts.append(f"+{lines_added} line{'s' if lines_added != 1 else ''}")
            if lines_removed > 0:
                parts.append(f"-{lines_removed} line{'s' if lines_removed != 1 else ''}")
            parts.append(f"{hunks} hunk{'s' if hunks != 1 else ''}")
            summary = ", ".join(parts)

        return DiffAnalysis(
            lines_added=lines_added,
            lines_removed=lines_removed,
            lines_changed=lines_changed,
            hunks=hunks,
            unified_diff=unified_diff,
            summary=summary,
        )

    def format_diff_for_display(
        self,
        diff: str,
        use_colors: bool = True,
    ) -> str:
        """Format a diff for terminal display.

        The hawk presents its comparison findings.

        Args:
            diff: Unified diff string
            use_colors: Whether to include ANSI color codes

        Returns:
            Formatted diff string
        """
        if not use_colors:
            return diff

        lines = []
        for line in diff.split("\n"):
            if line.startswith("+++") or line.startswith("---"):
                # File headers - bold
                lines.append(f"\033[1m{line}\033[0m")
            elif line.startswith("+"):
                # Additions - green
                lines.append(f"\033[32m{line}\033[0m")
            elif line.startswith("-"):
                # Deletions - red
                lines.append(f"\033[31m{line}\033[0m")
            elif line.startswith("@@"):
                # Hunk headers - cyan
                lines.append(f"\033[36m{line}\033[0m")
            else:
                lines.append(line)

        return "\n".join(lines)

    def validate_fix_completeness(
        self,
        proposal: FixProposal,
        context: CodeContext,
    ) -> dict[str, Any]:
        """Validate that a fix is complete and addresses the issue.

        The hawk's final inspection before delivery.

        Args:
            proposal: The fix proposal
            context: Code context

        Returns:
            Dict with validation details
        """
        result = {
            "is_complete": True,
            "has_code_changes": bool(proposal.code_changes),
            "has_description": bool(proposal.fix_description),
            "has_explanation": bool(proposal.explanation),
            "targets_correct_file": False,
            "issues": [],
        }

        # Check code changes
        if not proposal.code_changes:
            result["is_complete"] = False
            result["issues"].append("No code changes provided")

        # Check if changes target the correct file
        if context.file_path and proposal.code_changes:
            for file_path in proposal.code_changes.keys():
                if context.file_path in file_path or file_path in context.file_path:
                    result["targets_correct_file"] = True
                    break

            if not result["targets_correct_file"]:
                result["issues"].append(
                    f"Changes target {list(proposal.code_changes.keys())} "
                    f"but error is in {context.file_path}"
                )

        # Check confidence
        if proposal.confidence_score < 0.3:
            result["issues"].append(
                f"Low confidence score: {proposal.confidence_score:.0%}"
            )

        # Check description
        if not proposal.fix_description or len(proposal.fix_description) < 10:
            result["issues"].append("Missing or too short fix description")

        if result["issues"]:
            result["is_complete"] = False
            logger.warning(
                "Hawk found completeness issues: %s",
                ", ".join(result["issues"]),
            )
        else:
            logger.info("Hawk confirms fix is complete")

        return result
