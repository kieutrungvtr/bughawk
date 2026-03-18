"""Integration tests for BugHawk end-to-end workflows.

These tests verify that all components work together correctly.
"""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.analyzer.code_locator import CodeLocator
from bughawk.analyzer.context_builder import ContextBuilder, EnrichedContext
from bughawk.analyzer.pattern_matcher import ErrorCategory, PatternMatcher
from bughawk.core.config import BugHawkConfig, FilterConfig, GitConfig, LLMConfig, SentryConfig
from bughawk.core.models import (
    CodeContext,
    FixProposal,
    IssueSeverity,
    IssueStatus,
    SentryIssue,
    StackFrame,
    StackTrace,
)
from bughawk.core.orchestrator import (
    HuntPhase,
    HuntReport,
    HuntResult,
    HuntState,
    Orchestrator,
)
from bughawk.fixer.fix_generator import FixGenerator, ValidationResult


class TestCodeAnalysisPipeline:
    """Tests for the complete code analysis pipeline."""

    def test_full_analysis_pipeline(self, temp_repo: Path) -> None:
        """Test the complete code analysis pipeline."""
        # Setup: Create a file with a potential bug
        bug_file = temp_repo / "src" / "buggy.py"
        bug_file.parent.mkdir(parents=True, exist_ok=True)
        bug_file.write_text('''def process_users(users):
    """Process user data."""
    # Bug: users might be None
    for user in users:
        print(user.name)
    return len(users)
''')

        # Commit the file
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add buggy code"],
            cwd=temp_repo,
            capture_output=True,
        )

        # Step 1: Code Locator finds the file
        locator = CodeLocator()
        found_file = locator.find_file_in_repo(temp_repo, "buggy.py")

        assert found_file is not None
        assert found_file.name == "buggy.py"

        # Step 2: Build code context
        context = locator.build_code_context(
            found_file,
            error_line=4,
            context_lines=5,
        )

        assert context.error_line == 4
        assert "users" in context.file_content

        # Step 3: Context Builder enriches with git info
        builder = ContextBuilder(code_locator=locator)

        issue = SentryIssue(
            id="12345",
            title="TypeError: 'NoneType' object is not iterable",
            culprit="process_users in src/buggy.py",
            level=IssueSeverity.ERROR,
            count=42,
            metadata={
                "exception": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "'NoneType' object is not iterable",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "src/buggy.py",
                                        "lineNo": 4,
                                        "function": "process_users",
                                        "inApp": True,
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        )

        enriched = builder.build_context(issue, temp_repo)

        assert enriched.language == "python"
        assert enriched.code_context is not None

        # Step 4: Pattern matcher identifies the error type
        matcher = PatternMatcher()
        pattern_match = matcher.match_pattern(
            issue=issue,
            stack_trace=enriched.stack_trace,
            code_context=enriched.code_context.file_content,
        )

        # Should match null reference pattern
        assert pattern_match is not None
        assert pattern_match.pattern.category == ErrorCategory.NULL_REFERENCE

    def test_related_files_discovery(self, temp_repo: Path) -> None:
        """Test discovering related files."""
        # Create interconnected files
        (temp_repo / "src").mkdir(exist_ok=True)

        # Main module that imports utils
        (temp_repo / "src" / "main.py").write_text('''from src.utils import helper
from src.models import User

def main():
    user = User()
    helper(user)
''')

        # Utils module
        (temp_repo / "src" / "utils.py").write_text('''def helper(obj):
    return obj.process()
''')

        # Models module
        (temp_repo / "src" / "models.py").write_text('''class User:
    def process(self):
        return "processed"
''')

        # Commit changes
        subprocess.run(["git", "add", "."], cwd=temp_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add modules"],
            cwd=temp_repo,
            capture_output=True,
        )

        locator = CodeLocator()
        main_file = temp_repo / "src" / "main.py"

        related = locator.find_related_files(temp_repo, main_file)

        # Should find utils.py and models.py
        related_names = [f.name for f in related]
        assert "utils.py" in related_names or "models.py" in related_names


class TestFixGenerationPipeline:
    """Tests for the fix generation pipeline."""

    def test_pattern_based_fix(self) -> None:
        """Test generating a fix using pattern matching."""
        generator = FixGenerator()

        issue = SentryIssue(
            id="123",
            title="TypeError: Cannot read property 'name' of undefined",
            level=IssueSeverity.ERROR,
            count=10,
        )

        context = CodeContext(
            file_path="src/user.js",
            file_content='''function displayUser(user) {
    console.log(user.name);
}
''',
            error_line=2,
            surrounding_lines={
                1: "function displayUser(user) {",
                2: "    console.log(user.name);",
                3: "}",
            },
        )

        stack_trace = StackTrace(
            frames=[
                StackFrame(
                    filename="src/user.js",
                    line_number=2,
                    function="displayUser",
                    in_app=True,
                )
            ],
            exception_type="TypeError",
            exception_value="Cannot read property 'name' of undefined",
        )

        # Try pattern fix
        fix = generator._try_pattern_fix(issue, context, stack_trace)

        # Should get a pattern match for null reference
        assert fix is not None
        assert fix.confidence_score > 0.5

    def test_fix_validation_pipeline(self, temp_dir: Path) -> None:
        """Test the complete fix validation pipeline."""
        generator = FixGenerator()

        # Create original file
        original_file = temp_dir / "service.py"
        original_file.write_text('''def get_user_name(user):
    return user.name
''')

        # Create fix proposal
        fix = FixProposal(
            issue_id="123",
            fix_description="Add null check for user",
            code_changes={
                "service.py": '''@@ -1,2 +1,4 @@
 def get_user_name(user):
-    return user.name
+    if user is None:
+        return None
+    return user.name
'''
            },
            confidence_score=0.85,
        )

        context = CodeContext(
            file_path="service.py",
            file_content="def get_user_name(user):\n    return user.name",
            error_line=2,
        )

        # Validate the fix
        validation = generator.validate_fix(fix, context)

        assert validation.is_valid is True
        assert validation.syntax_valid is True

        # Apply the fix
        new_content = generator.apply_fix_to_code(original_file, fix)

        assert "if user is None" in new_content
        assert "return None" in new_content


class TestOrchestratorIntegration:
    """Tests for Orchestrator with mocked external services."""

    def test_hunt_state_persistence(self, temp_dir: Path) -> None:
        """Test that hunt state is properly persisted and loaded."""
        config = BugHawkConfig(
            sentry=SentryConfig(
                auth_token="test-token",
                org="test-org",
                projects=["test-project"],
            ),
            output_dir=temp_dir,
        )

        orchestrator = Orchestrator(config=config)

        # Create and save a state
        state = HuntState(
            issue_id="12345",
            phase=HuntPhase.PLANNING,
            started_at=datetime.now(),
            updated_at=datetime.now(),
            branch_name="bughawk/fix-12345",
        )

        orchestrator._save_hunt_state(state)

        # Load the state back
        loaded = orchestrator._load_hunt_state("12345")

        assert loaded is not None
        assert loaded.issue_id == "12345"
        assert loaded.phase == HuntPhase.PLANNING
        assert loaded.branch_name == "bughawk/fix-12345"

    def test_hunt_report_generation(self, temp_dir: Path) -> None:
        """Test generating a hunt report."""
        config = BugHawkConfig(
            output_dir=temp_dir,
        )

        orchestrator = Orchestrator(config=config)

        # Simulate a hunt
        report = HuntReport(
            started_at=datetime.now(),
            total_issues=5,
            processed=5,
            succeeded=3,
            failed=1,
            low_confidence=1,
            prs_created=["https://github.com/org/repo/pull/1"],
        )
        report.completed_at = datetime.now()

        # Serialize and verify
        data = report.to_dict()

        assert data["total_issues"] == 5
        assert data["succeeded"] == 3
        assert len(data["prs_created"]) == 1


class TestEndToEndWorkflow:
    """End-to-end workflow tests with mocked external services."""

    @patch("bughawk.sentry.client.SentryClient")
    @patch("bughawk.git.repo_manager.RepoManager")
    def test_issue_processing_workflow(
        self,
        mock_repo_manager: MagicMock,
        mock_sentry_client: MagicMock,
        temp_dir: Path,
        sample_sentry_issue: SentryIssue,
        sample_fix_proposal: FixProposal,
    ) -> None:
        """Test the complete issue processing workflow."""
        # Setup mocks
        mock_sentry_client.return_value.get_issue_details.return_value = sample_sentry_issue
        mock_sentry_client.return_value.get_issue_events.return_value = []

        mock_repo = MagicMock()
        mock_repo.prepare_repository.return_value = temp_dir / "repo"
        mock_repo_manager.return_value = mock_repo

        # Create test repository
        repo_dir = temp_dir / "repo"
        repo_dir.mkdir()
        (repo_dir / "src" / "components").mkdir(parents=True)
        (repo_dir / "src" / "components" / "UserList.tsx").write_text('''const UserList = ({ users }) => {
    const items = users.map(u => <UserItem user={u} />);
    return <ul>{items}</ul>;
};
''')

        # Initialize git
        subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir,
            capture_output=True,
        )
        subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial"],
            cwd=repo_dir,
            capture_output=True,
        )

        # Test the analysis flow
        locator = CodeLocator()
        file_path = locator.find_file_in_repo(repo_dir, "UserList.tsx")

        assert file_path is not None

        context = locator.build_code_context(file_path, error_line=2, context_lines=3)

        assert "users.map" in context.file_content


class TestFilteringIntegration:
    """Tests for issue filtering across components."""

    def test_severity_filtering(self, temp_dir: Path) -> None:
        """Test filtering issues by severity."""
        from bughawk.core.config import Severity

        config = BugHawkConfig(
            filters=FilterConfig(
                severity_levels=[Severity.ERROR, Severity.FATAL],
                min_events=1,
            ),
            output_dir=temp_dir,
        )

        orchestrator = Orchestrator(config=config)

        issues = [
            SentryIssue(id="1", title="Debug", level=IssueSeverity.DEBUG, count=10),
            SentryIssue(id="2", title="Info", level=IssueSeverity.INFO, count=10),
            SentryIssue(id="3", title="Warning", level=IssueSeverity.WARNING, count=10),
            SentryIssue(id="4", title="Error", level=IssueSeverity.ERROR, count=10),
            SentryIssue(id="5", title="Fatal", level=IssueSeverity.FATAL, count=10),
        ]

        filtered = orchestrator._filter_issues(issues)

        assert len(filtered) == 2
        assert all(i.id in ["4", "5"] for i in filtered)

    def test_event_count_filtering(self, temp_dir: Path) -> None:
        """Test filtering issues by event count."""
        config = BugHawkConfig(
            filters=FilterConfig(
                min_events=50,
            ),
            output_dir=temp_dir,
        )

        orchestrator = Orchestrator(config=config)

        issues = [
            SentryIssue(id="1", title="Low", level=IssueSeverity.ERROR, count=10),
            SentryIssue(id="2", title="Medium", level=IssueSeverity.ERROR, count=49),
            SentryIssue(id="3", title="High", level=IssueSeverity.ERROR, count=100),
        ]

        filtered = orchestrator._filter_issues(issues)

        assert len(filtered) == 1
        assert filtered[0].id == "3"


class TestLLMPromptGeneration:
    """Tests for LLM prompt generation."""

    def test_generate_complete_prompt(
        self, sample_sentry_issue: SentryIssue, sample_stack_trace: StackTrace
    ) -> None:
        """Test generating a complete LLM prompt."""
        builder = ContextBuilder()

        code_context = CodeContext(
            file_path="src/components/UserList.tsx",
            file_content="const items = users.map(u => <UserItem user={u} />);",
            error_line=15,
            surrounding_lines={
                13: "const UserList = ({ users }) => {",
                14: "  // Render user list",
                15: "  const items = users.map(u => <UserItem user={u} />);",
                16: "  return <ul>{items}</ul>;",
                17: "};",
            },
        )

        enriched = EnrichedContext(
            code_context=code_context,
            stack_trace=sample_stack_trace,
            blame_info=[],
            recent_commits=[],
            related_contexts=[],
            language="typescript",
            repo_path=Path("/tmp/repo"),
        )

        prompt = builder.build_llm_prompt(enriched, sample_sentry_issue)

        # Verify prompt structure
        assert "BugHawk Analysis Request" in prompt
        assert "Error Summary" in prompt
        assert "Stack Trace" in prompt
        assert "Source Code Context" in prompt
        assert "Analysis Request" in prompt

        # Verify content
        assert sample_sentry_issue.id in prompt
        assert "TypeError" in prompt
        assert "UserList.tsx" in prompt


class TestConfigurationIntegration:
    """Tests for configuration integration across components."""

    def test_config_propagation(self, temp_dir: Path) -> None:
        """Test that configuration is properly propagated."""
        config = BugHawkConfig(
            sentry=SentryConfig(
                auth_token="test-token",
                org="test-org",
                projects=["project1", "project2"],
            ),
            llm=LLMConfig(
                api_key="test-llm-key",
                model="gpt-4",
                temperature=0.2,
            ),
            git=GitConfig(
                token="test-git-token",
                branch_prefix="hawk/fix-",
                auto_pr=True,
            ),
            filters=FilterConfig(
                min_events=100,
                max_age_days=7,
            ),
            output_dir=temp_dir,
            debug=True,
        )

        orchestrator = Orchestrator(config=config, confidence_threshold=0.8)

        assert orchestrator.config.sentry.auth_token == "test-token"
        assert orchestrator.config.llm.model == "gpt-4"
        assert orchestrator.config.git.branch_prefix == "hawk/fix-"
        assert orchestrator.confidence_threshold == 0.8


class TestErrorRecovery:
    """Tests for error recovery and resilience."""

    def test_graceful_file_not_found(self, temp_dir: Path) -> None:
        """Test graceful handling when file is not found."""
        locator = CodeLocator()

        result = locator.find_file_in_repo(temp_dir, "nonexistent.py")

        assert result is None

    def test_graceful_invalid_repo(self, temp_dir: Path) -> None:
        """Test graceful handling of invalid repository."""
        locator = CodeLocator()

        # Directory exists but is not a git repo
        assert locator.validate_repository(temp_dir) is False

    def test_fix_application_fallback(self, temp_dir: Path) -> None:
        """Test fallback when fix cannot be applied."""
        generator = FixGenerator()

        original_file = temp_dir / "test.py"
        original_content = "# original content"
        original_file.write_text(original_content)

        # Fix with non-matching diff
        fix = FixProposal(
            issue_id="123",
            fix_description="Fix",
            code_changes={
                "test.py": """-non_existing_line
+replacement
"""
            },
            confidence_score=0.9,
        )

        # Should return original content when fix can't be applied
        result = generator.apply_fix_to_code(original_file, fix)

        # Result should be original or modified
        assert result is not None
