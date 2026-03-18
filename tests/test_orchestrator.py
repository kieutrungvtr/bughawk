"""Integration tests for the Orchestrator module."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.core.config import BugHawkConfig
from bughawk.core.models import FixProposal, SentryIssue
from bughawk.core.orchestrator import (
    HuntPhase,
    HuntReport,
    HuntResult,
    HuntState,
    Orchestrator,
    OrchestratorError,
)


class TestOrchestratorInitialization:
    """Tests for Orchestrator initialization."""

    def test_default_initialization(self, mock_config: BugHawkConfig) -> None:
        """Test default initialization."""
        orchestrator = Orchestrator(config=mock_config)

        assert orchestrator.config == mock_config
        assert orchestrator.confidence_threshold == 0.6
        assert orchestrator.dry_run is False

    def test_initialization_with_options(self, mock_config: BugHawkConfig) -> None:
        """Test initialization with custom options."""
        orchestrator = Orchestrator(
            config=mock_config,
            confidence_threshold=0.8,
            dry_run=True,
        )

        assert orchestrator.confidence_threshold == 0.8
        assert orchestrator.dry_run is True

    def test_state_directory_creation(
        self, mock_config: BugHawkConfig, temp_dir: Path
    ) -> None:
        """Test that state directory is created."""
        mock_config.output_dir = temp_dir / "bughawk_output"

        orchestrator = Orchestrator(config=mock_config)

        assert orchestrator.state_dir.exists()


class TestHuntState:
    """Tests for HuntState dataclass."""

    def test_hunt_state_creation(self) -> None:
        """Test creating a hunt state."""
        now = datetime.now()
        state = HuntState(
            issue_id="12345",
            phase=HuntPhase.SPOTTING,
            started_at=now,
            updated_at=now,
        )

        assert state.issue_id == "12345"
        assert state.phase == HuntPhase.SPOTTING

    def test_hunt_state_serialization(self) -> None:
        """Test serializing hunt state to dict."""
        now = datetime.now()
        state = HuntState(
            issue_id="12345",
            phase=HuntPhase.PLANNING,
            started_at=now,
            updated_at=now,
            branch_name="bughawk-fix/12345",
            result=HuntResult.SUCCESS,
        )

        data = state.to_dict()

        assert data["issue_id"] == "12345"
        assert data["phase"] == "planning"
        assert data["branch_name"] == "bughawk-fix/12345"
        assert data["result"] == "success"

    def test_hunt_state_deserialization(self) -> None:
        """Test deserializing hunt state from dict."""
        data = {
            "issue_id": "12345",
            "phase": "validating",
            "started_at": "2024-01-15T10:00:00",
            "updated_at": "2024-01-15T10:30:00",
            "result": "low_confidence",
        }

        state = HuntState.from_dict(data)

        assert state.issue_id == "12345"
        assert state.phase == HuntPhase.VALIDATING
        assert state.result == HuntResult.LOW_CONFIDENCE


class TestHuntReport:
    """Tests for HuntReport dataclass."""

    def test_hunt_report_creation(self) -> None:
        """Test creating a hunt report."""
        report = HuntReport(
            started_at=datetime.now(),
            total_issues=10,
            succeeded=5,
            failed=2,
        )

        assert report.total_issues == 10
        assert report.succeeded == 5
        assert report.failed == 2

    def test_hunt_report_serialization(self) -> None:
        """Test serializing hunt report to dict."""
        report = HuntReport(
            started_at=datetime(2024, 1, 15, 10, 0, 0),
            completed_at=datetime(2024, 1, 15, 11, 0, 0),
            total_issues=5,
            processed=5,
            succeeded=3,
            failed=1,
            low_confidence=1,
            prs_created=["https://github.com/test/repo/pull/1"],
        )

        data = report.to_dict()

        assert data["total_issues"] == 5
        assert data["succeeded"] == 3
        assert len(data["prs_created"]) == 1


class TestOrchestratorProcessIssue:
    """Tests for process_issue method."""

    @patch.object(Orchestrator, "sentry_client", new_callable=lambda: MagicMock())
    @patch.object(Orchestrator, "repo_manager", new_callable=lambda: MagicMock())
    @patch.object(Orchestrator, "fix_generator", new_callable=lambda: MagicMock())
    def test_process_issue_success(
        self,
        mock_fix_gen,
        mock_repo,
        mock_sentry,
        mock_config: BugHawkConfig,
        sample_sentry_issue: SentryIssue,
        sample_fix_proposal: FixProposal,
        temp_dir: Path,
    ) -> None:
        """Test successful issue processing."""
        mock_config.output_dir = temp_dir

        # Setup mocks
        mock_sentry.get_issue_details.return_value = sample_sentry_issue
        mock_sentry.get_issue_events.return_value = []
        mock_repo.prepare_repository.return_value = temp_dir / "repo"
        mock_repo.create_fix_branch.return_value = "bughawk-fix/12345"
        mock_fix_gen.generate_fix.return_value = sample_fix_proposal
        mock_fix_gen.validate_fix.return_value = MagicMock(is_valid=True, issues=[])

        orchestrator = Orchestrator(
            config=mock_config,
            dry_run=True,  # Dry run to avoid actual git operations
        )

        # Process should complete without errors in dry run mode
        result = orchestrator.dry_run_issue("12345", repo_url="https://github.com/test/repo.git")

        # Verify issue was fetched
        mock_sentry.get_issue_details.assert_called()

    @patch.object(Orchestrator, "sentry_client", new_callable=lambda: MagicMock())
    def test_process_issue_not_found(
        self,
        mock_sentry,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test processing non-existent issue."""
        from bughawk.sentry.client import SentryNotFoundError

        mock_config.output_dir = temp_dir
        mock_sentry.get_issue_details.side_effect = SentryNotFoundError("Not found", 404)

        orchestrator = Orchestrator(config=mock_config)

        result = orchestrator.process_issue("99999", repo_url="https://github.com/test/repo.git")

        assert result is None


class TestOrchestratorDryRun:
    """Tests for dry run functionality."""

    def test_dry_run_does_not_create_pr(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test that dry run doesn't create actual PRs."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(
            config=mock_config,
            dry_run=True,
        )

        assert orchestrator.dry_run is True


class TestOrchestratorStatePersistence:
    """Tests for state persistence."""

    def test_save_hunt_state(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test saving hunt state to disk."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        state = HuntState(
            issue_id="12345",
            phase=HuntPhase.PLANNING,
            started_at=datetime.now(),
            updated_at=datetime.now(),
        )

        orchestrator._save_hunt_state(state)

        state_file = orchestrator.state_dir / "hunt_12345.json"
        assert state_file.exists()

        # Verify content
        with open(state_file) as f:
            data = json.load(f)
        assert data["issue_id"] == "12345"

    def test_load_hunt_state(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test loading hunt state from disk."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        # Save a state first
        state = HuntState(
            issue_id="12345",
            phase=HuntPhase.VALIDATING,
            started_at=datetime.now(),
            updated_at=datetime.now(),
            result=HuntResult.SUCCESS,
        )
        orchestrator._save_hunt_state(state)

        # Load it back
        loaded = orchestrator._load_hunt_state("12345")

        assert loaded is not None
        assert loaded.issue_id == "12345"
        assert loaded.result == HuntResult.SUCCESS

    def test_load_nonexistent_state(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test loading non-existent state returns None."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        loaded = orchestrator._load_hunt_state("nonexistent")

        assert loaded is None


class TestOrchestratorHelpers:
    """Tests for helper methods."""

    def test_extract_repo_url_from_metadata(
        self,
        mock_config: BugHawkConfig,
        sample_sentry_issue: SentryIssue,
        temp_dir: Path,
    ) -> None:
        """Test extracting repo URL from issue metadata."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        url = orchestrator._extract_repo_url(sample_sentry_issue)

        assert url == "https://github.com/test-org/test-repo.git"

    def test_extract_repo_full_name_https(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test extracting repo full name from HTTPS URL."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        name = orchestrator._extract_repo_full_name("https://github.com/owner/repo.git")

        assert name == "owner/repo"

    def test_extract_repo_full_name_ssh(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test extracting repo full name from SSH URL."""
        mock_config.output_dir = temp_dir

        orchestrator = Orchestrator(config=mock_config)

        name = orchestrator._extract_repo_full_name("git@github.com:owner/repo.git")

        assert name == "owner/repo"


class TestHuntPhases:
    """Tests for hunt phase transitions."""

    def test_phase_enum_values(self) -> None:
        """Test HuntPhase enum has expected values."""
        assert HuntPhase.SPOTTING.value == "spotting"
        assert HuntPhase.SURVEYING.value == "surveying"
        assert HuntPhase.TRACKING.value == "tracking"
        assert HuntPhase.RECOGNIZING.value == "recognizing"
        assert HuntPhase.PLANNING.value == "planning"
        assert HuntPhase.VALIDATING.value == "validating"
        assert HuntPhase.STRIKING.value == "striking"
        assert HuntPhase.MARKING.value == "marking"
        assert HuntPhase.CLEANUP.value == "cleanup"

    def test_result_enum_values(self) -> None:
        """Test HuntResult enum has expected values."""
        assert HuntResult.SUCCESS.value == "success"
        assert HuntResult.SKIPPED.value == "skipped"
        assert HuntResult.LOW_CONFIDENCE.value == "low_confidence"
        assert HuntResult.VALIDATION_FAILED.value == "validation_failed"
        assert HuntResult.ERROR.value == "error"


class TestOrchestratorFiltering:
    """Tests for issue filtering."""

    def test_filter_by_min_events(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test filtering issues by minimum events."""
        mock_config.output_dir = temp_dir
        mock_config.filters.min_events = 10

        orchestrator = Orchestrator(config=mock_config)

        issues = [
            SentryIssue(id="1", title="Low count", count=5, level="error"),
            SentryIssue(id="2", title="High count", count=20, level="error"),
        ]

        filtered = orchestrator._filter_issues(issues)

        assert len(filtered) == 1
        assert filtered[0].id == "2"

    def test_filter_by_severity(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test filtering issues by severity level."""
        from bughawk.core.config import Severity
        from bughawk.core.models import IssueSeverity

        mock_config.output_dir = temp_dir
        mock_config.filters.severity_levels = [Severity.ERROR, Severity.FATAL]

        orchestrator = Orchestrator(config=mock_config)

        issues = [
            SentryIssue(id="1", title="Warning", count=10, level=IssueSeverity.WARNING),
            SentryIssue(id="2", title="Error", count=10, level=IssueSeverity.ERROR),
            SentryIssue(id="3", title="Fatal", count=10, level=IssueSeverity.FATAL),
        ]

        filtered = orchestrator._filter_issues(issues)

        assert len(filtered) == 2
        assert all(i.id in ["2", "3"] for i in filtered)

    def test_filter_ignored_issues(
        self,
        mock_config: BugHawkConfig,
        temp_dir: Path,
    ) -> None:
        """Test filtering ignored issues."""
        mock_config.output_dir = temp_dir
        mock_config.filters.ignored_issues = ["ignored-1", "ignored-2"]

        orchestrator = Orchestrator(config=mock_config)

        issues = [
            SentryIssue(id="ignored-1", title="Ignored", count=10, level="error"),
            SentryIssue(id="keep-1", title="Keep", count=10, level="error"),
        ]

        filtered = orchestrator._filter_issues(issues)

        assert len(filtered) == 1
        assert filtered[0].id == "keep-1"
