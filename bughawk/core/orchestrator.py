"""Orchestrator for BugHawk - The Hunt begins here.

This module ties together all components of BugHawk to execute
the full automated bug hunting and fixing workflow.

The Orchestrator is the master hawk, coordinating the hunt from
spotting prey to making the final strike.
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.table import Table

from bughawk.analyzer.code_locator import CodeLocator
from bughawk.analyzer.context_builder import ContextBuilder
from bughawk.analyzer.pattern_matcher import PatternMatcher
from bughawk.core.config import BugHawkConfig, validate_config_for_fix, create_monitor_client
from bughawk.core.models import CodeContext, FixProposal, SentryIssue, StackTrace
from bughawk.fixer.fix_generator import FixGenerator
from bughawk.fixer.llm_client import LLMClient, LLMProvider
from bughawk.fixer.validator import FixValidator
from bughawk.git.pr_creator import PRCreator, PRPlatform
from bughawk.git.repo_manager import RepoManager
from bughawk.monitors.base import MonitorClient
from bughawk.sentry.client import SentryClient, Settings  # Keep for backward compatibility
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)
console = Console()


class HuntPhase(str, Enum):
    """Phases of the hunt."""

    SPOTTING = "spotting"  # Fetching issue from monitor
    SURVEYING = "surveying"  # Cloning repository
    TRACKING = "tracking"  # Building code context
    RECOGNIZING = "recognizing"  # Pattern matching
    PLANNING = "planning"  # Generating fix
    VALIDATING = "validating"  # Validating fix
    STRIKING = "striking"  # Applying changes
    MARKING = "marking"  # Creating PR, updating monitor
    CLEANUP = "cleanup"  # Cleaning up


class HuntResult(str, Enum):
    """Result of a hunt."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    LOW_CONFIDENCE = "low_confidence"
    VALIDATION_FAILED = "validation_failed"
    ERROR = "error"


@dataclass
class HuntState:
    """State of a single issue hunt.

    Allows resuming interrupted hunts.
    """

    issue_id: str
    phase: HuntPhase
    started_at: datetime
    updated_at: datetime
    repo_path: Optional[Path] = None
    branch_name: Optional[str] = None
    fix_proposal: Optional[FixProposal] = None
    pr_url: Optional[str] = None
    result: Optional[HuntResult] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "issue_id": self.issue_id,
            "phase": self.phase.value,
            "started_at": self.started_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "repo_path": str(self.repo_path) if self.repo_path else None,
            "branch_name": self.branch_name,
            "fix_proposal": {
                "issue_id": self.fix_proposal.issue_id,
                "fix_description": self.fix_proposal.fix_description,
                "confidence_score": self.fix_proposal.confidence_score,
            } if self.fix_proposal else None,
            "pr_url": self.pr_url,
            "result": self.result.value if self.result else None,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HuntState":
        """Create from dictionary."""
        fix_data = data.get("fix_proposal")
        fix_proposal = None
        if fix_data:
            fix_proposal = FixProposal(
                issue_id=fix_data["issue_id"],
                fix_description=fix_data["fix_description"],
                confidence_score=fix_data["confidence_score"],
            )

        return cls(
            issue_id=data["issue_id"],
            phase=HuntPhase(data["phase"]),
            started_at=datetime.fromisoformat(data["started_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            repo_path=Path(data["repo_path"]) if data.get("repo_path") else None,
            branch_name=data.get("branch_name"),
            fix_proposal=fix_proposal,
            pr_url=data.get("pr_url"),
            result=HuntResult(data["result"]) if data.get("result") else None,
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class HuntReport:
    """Summary report of a hunt session."""

    started_at: datetime
    completed_at: Optional[datetime] = None
    total_issues: int = 0
    processed: int = 0
    succeeded: int = 0
    skipped: int = 0
    low_confidence: int = 0
    failed: int = 0
    prs_created: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_issues": self.total_issues,
            "processed": self.processed,
            "succeeded": self.succeeded,
            "skipped": self.skipped,
            "low_confidence": self.low_confidence,
            "failed": self.failed,
            "prs_created": self.prs_created,
            "errors": self.errors,
        }


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    pass


class Orchestrator:
    """Coordinates the full BugHawk workflow.

    The master hawk - overseeing the entire hunt from detection to capture.

    This class ties together:
    - Sentry client for issue fetching
    - Code locator for repository management
    - Context builder for understanding errors
    - Pattern matcher for known issues
    - Fix generator for creating solutions
    - Validator for ensuring fix quality
    - Repo manager for git operations
    - PR creator for submitting fixes

    Example:
        >>> orchestrator = Orchestrator(config)
        >>> pr_url = orchestrator.process_issue("SENTRY-123")
        >>> if pr_url:
        ...     print(f"Fix submitted: {pr_url}")

        >>> # Process all matching issues
        >>> report = orchestrator.process_all_issues()
        >>> print(f"Fixed {report.succeeded} issues")
    """

    # Default confidence threshold for creating PRs
    DEFAULT_CONFIDENCE_THRESHOLD = 0.6

    # Hawk-themed phase messages
    PHASE_MESSAGES = {
        HuntPhase.SPOTTING: "Spotting the prey...",
        HuntPhase.SURVEYING: "Surveying the territory...",
        HuntPhase.TRACKING: "Tracking the target...",
        HuntPhase.RECOGNIZING: "Recognizing familiar patterns...",
        HuntPhase.PLANNING: "Planning the strike...",
        HuntPhase.VALIDATING: "Ensuring clean capture...",
        HuntPhase.STRIKING: "Executing the strike...",
        HuntPhase.MARKING: "Marking territory...",
        HuntPhase.CLEANUP: "Returning to nest...",
    }

    def __init__(
        self,
        config: BugHawkConfig,
        confidence_threshold: Optional[float] = None,
        dry_run: bool = False,
        state_dir: Optional[Path] = None,
    ) -> None:
        """Initialize the Orchestrator.

        Args:
            config: BugHawk configuration.
            confidence_threshold: Minimum confidence to create PR.
            dry_run: If True, don't create PRs or push changes.
            state_dir: Directory for state persistence.
        """
        self.config = config
        self.confidence_threshold = confidence_threshold or self.DEFAULT_CONFIDENCE_THRESHOLD
        self.dry_run = dry_run

        # State directory for persistence
        self.state_dir = state_dir or config.output_dir / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components lazily
        self._monitor_client: Optional[MonitorClient] = None
        self._sentry_client: Optional[SentryClient] = None  # Keep for backward compatibility
        self._code_locator: Optional[CodeLocator] = None
        self._context_builder: Optional[ContextBuilder] = None
        self._pattern_matcher: Optional[PatternMatcher] = None
        self._fix_generator: Optional[FixGenerator] = None
        self._fix_validator: Optional[FixValidator] = None
        self._repo_manager: Optional[RepoManager] = None
        self._pr_creator: Optional[PRCreator] = None
        self._llm_client: Optional[LLMClient] = None

        # Current hunt states
        self._hunt_states: Dict[str, HuntState] = {}

        logger.info("Orchestrator initialized - the hawk awakens 🦅 (monitor: %s)", self.config.monitor.value)

    # Lazy initialization properties

    @property
    def monitor_client(self) -> MonitorClient:
        """Get or create monitor client based on configuration."""
        if self._monitor_client is None:
            self._monitor_client = create_monitor_client(self.config)
        return self._monitor_client

    @property
    def sentry_client(self) -> SentryClient:
        """Get or create Sentry client (backward compatibility).

        Deprecated: Use monitor_client instead.
        """
        if self._sentry_client is None:
            settings = Settings(
                sentry_auth_token=self.config.sentry.auth_token,
                sentry_org=self.config.sentry.org,
                sentry_project=self.config.sentry.projects[0] if self.config.sentry.projects else "",
            )
            self._sentry_client = SentryClient(
                settings=settings,
                base_url=self.config.sentry.base_url,
            )
        return self._sentry_client

    @property
    def code_locator(self) -> CodeLocator:
        """Get or create code locator."""
        if self._code_locator is None:
            self._code_locator = CodeLocator()
        return self._code_locator

    @property
    def context_builder(self) -> ContextBuilder:
        """Get or create context builder."""
        if self._context_builder is None:
            self._context_builder = ContextBuilder()
        return self._context_builder

    @property
    def pattern_matcher(self) -> PatternMatcher:
        """Get or create pattern matcher."""
        if self._pattern_matcher is None:
            self._pattern_matcher = PatternMatcher()
        return self._pattern_matcher

    @property
    def llm_client(self) -> LLMClient:
        """Get or create LLM client."""
        if self._llm_client is None:
            provider = LLMProvider(self.config.llm.provider.value)
            self._llm_client = LLMClient(
                provider=provider,
                api_key=self.config.llm.api_key,
                model=self.config.llm.model,
            )
        return self._llm_client

    @property
    def fix_generator(self) -> FixGenerator:
        """Get or create fix generator."""
        if self._fix_generator is None:
            self._fix_generator = FixGenerator(
                pattern_matcher=self.pattern_matcher,
                llm_client=self.llm_client,
                context_builder=self.context_builder,
                debug_dir=self.config.output_dir / "debug" if self.config.debug else None,
            )
        return self._fix_generator

    @property
    def fix_validator(self) -> FixValidator:
        """Get or create fix validator."""
        if self._fix_validator is None:
            self._fix_validator = FixValidator()
        return self._fix_validator

    @property
    def repo_manager(self) -> RepoManager:
        """Get or create repo manager."""
        if self._repo_manager is None:
            self._repo_manager = RepoManager(
                work_dir=str(self.config.output_dir / "repos"),
                github_token=self.config.git.token if self.config.git.provider.value == "github" else None,
                gitlab_token=self.config.git.token if self.config.git.provider.value == "gitlab" else None,
            )
        return self._repo_manager

    def _get_pr_creator(self, sentry_client: Optional[SentryClient] = None):
        """Get or create PR creator."""
        platform = PRPlatform(self.config.git.provider.value)
        return PRCreator.for_platform(
            platform,
            sentry_client=sentry_client or self.sentry_client,
            token=self.config.git.token,
        )

    # Main workflow methods

    def process_issue(
        self,
        issue_id: str,
        repo_url: Optional[str] = None,
    ) -> Optional[str]:
        """Process a single issue through the full workflow.

        The Hunt - from spotting to capture.

        Args:
            issue_id: Issue ID to process.
            repo_url: Repository URL (extracted from issue if not provided).

        Returns:
            PR URL if successful, None otherwise.
        """
        validate_config_for_fix(self.config)

        state = self._create_hunt_state(issue_id)

        try:
            # Phase 1: Spot the prey - Fetch issue from monitor
            state = self._update_phase(state, HuntPhase.SPOTTING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.SPOTTING]}[/]")

            issue = self.monitor_client.get_issue_details(issue_id)
            logger.info(f"Fetched issue: {issue.title}")
            console.print(f"   Issue: [cyan]{issue.title}[/]")
            console.print(f"   Occurrences: [yellow]{issue.count}[/]")

            # Extract repository URL from issue metadata or use provided
            if not repo_url:
                repo_url = self._extract_repo_url(issue)
            if not repo_url:
                raise OrchestratorError(
                    "Could not determine repository URL. "
                    "Provide repo_url or configure in your monitor."
                )

            # Phase 2: Survey the territory - Clone repository
            state = self._update_phase(state, HuntPhase.SURVEYING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.SURVEYING]}[/]")

            repo_path = self.repo_manager.prepare_repository(
                repo_url,
                base_branch=self.config.git.base_branch,
            )
            state.repo_path = repo_path
            logger.info(f"Repository cloned to: {repo_path}")
            console.print(f"   Cloned to: [dim]{repo_path}[/]")

            # Phase 3: Track the target - Build code context
            state = self._update_phase(state, HuntPhase.TRACKING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.TRACKING]}[/]")

            # Get latest event for stack trace
            events = self.monitor_client.get_issue_events(issue_id, limit=1, full=True)
            stack_trace = self._extract_stack_trace(events[0] if events else None)

            # Build code context
            code_context = self._build_code_context(issue, repo_path, stack_trace)
            logger.info(f"Built context for: {code_context.file_path}")
            console.print(f"   Target file: [cyan]{code_context.file_path}[/]")

            # Phase 4: Recognize familiar patterns
            state = self._update_phase(state, HuntPhase.RECOGNIZING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.RECOGNIZING]}[/]")

            pattern_match = self.pattern_matcher.match_pattern(
                exception_type=stack_trace.exception_type if stack_trace else "",
                message=issue.title,
                code_snippet=code_context.file_content[:1000] if code_context.file_content else "",
            )

            if pattern_match:
                console.print(f"   Pattern matched: [green]{pattern_match.pattern.name}[/] "
                             f"(confidence: {pattern_match.confidence:.2f})")
                state.metadata["pattern_name"] = pattern_match.pattern.name
            else:
                console.print("   No pattern match - proceeding with LLM analysis")

            # Phase 5: Plan the strike - Generate fix
            state = self._update_phase(state, HuntPhase.PLANNING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.PLANNING]}[/]")

            fix_proposal = self.fix_generator.generate_fix(
                issue=issue,
                context=code_context,
                repo_path=repo_path,
                stack_trace=stack_trace,
            )
            state.fix_proposal = fix_proposal
            logger.info(f"Generated fix with confidence: {fix_proposal.confidence_score}")
            console.print(f"   Confidence: [{'green' if fix_proposal.confidence_score >= self.confidence_threshold else 'yellow'}]"
                         f"{fix_proposal.confidence_score:.2f}[/]")

            # Phase 6: Ensure clean capture - Validate fix
            state = self._update_phase(state, HuntPhase.VALIDATING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.VALIDATING]}[/]")

            validation = self.fix_generator.validate_fix(fix_proposal, code_context)

            if not validation.is_valid:
                console.print(f"   [red]Validation failed:[/] {', '.join(validation.issues)}")
                state.result = HuntResult.VALIDATION_FAILED
                state.error = "; ".join(validation.issues)
                self._save_hunt_state(state)
                return None

            console.print("   [green]Validation passed[/]")

            # Check confidence threshold
            if fix_proposal.confidence_score < self.confidence_threshold:
                console.print(f"\n[yellow]Confidence {fix_proposal.confidence_score:.2f} below threshold "
                             f"{self.confidence_threshold}[/]")
                state.result = HuntResult.LOW_CONFIDENCE
                self._save_hunt_state(state)
                return None

            # Phase 7: Execute the strike - Apply changes
            state = self._update_phase(state, HuntPhase.STRIKING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.STRIKING]}[/]")

            if self.dry_run:
                console.print("   [yellow]Dry run - skipping changes[/]")
                state.result = HuntResult.SUCCESS
                self._save_hunt_state(state)
                return None

            # Create fix branch
            branch_name = self.repo_manager.create_fix_branch(repo_path, issue_id)
            state.branch_name = branch_name
            console.print(f"   Branch: [cyan]{branch_name}[/]")

            # Apply changes
            self.repo_manager.apply_changes(repo_path, fix_proposal.code_changes)
            console.print(f"   Applied changes to {len(fix_proposal.code_changes)} file(s)")

            # Commit changes
            commit_info = self.repo_manager.commit_changes(
                repo_path=repo_path,
                issue_id=issue_id,
                issue_title=issue.title,
                fix_explanation=fix_proposal.explanation,
                sentry_url=issue.metadata.get("url", f"https://sentry.io/issues/{issue_id}/"),
            )
            console.print(f"   Committed: [dim]{commit_info.sha[:8]}[/]")

            # Push branch
            self.repo_manager.push_branch(repo_path, branch_name)
            console.print("   Pushed to remote")

            # Phase 8: Mark territory - Create PR and update Sentry
            state = self._update_phase(state, HuntPhase.MARKING)
            console.print(f"\n🦅 [bold gold1]{self.PHASE_MESSAGES[HuntPhase.MARKING]}[/]")

            # Create PR
            pr_creator = self._get_pr_creator()
            repo_full_name = self._extract_repo_full_name(repo_url)

            pr_url = pr_creator.create_pull_request(
                repo_full_name=repo_full_name,
                head_branch=branch_name,
                base_branch=self.config.git.base_branch,
                fix_proposal=fix_proposal,
                issue=issue,
                pattern_name=state.metadata.get("pattern_name"),
            )
            state.pr_url = pr_url
            console.print(f"   PR created: [link={pr_url}]{pr_url}[/link]")

            state.result = HuntResult.SUCCESS
            self._save_hunt_state(state)

            return pr_url

        except Exception as e:
            logger.exception(f"Hunt failed for issue {issue_id}: {e}")
            state.result = HuntResult.ERROR
            state.error = str(e)
            self._save_hunt_state(state)
            console.print(f"\n[red]Hunt failed: {e}[/]")
            return None

        finally:
            # Phase 9: Return to nest - Cleanup
            state = self._update_phase(state, HuntPhase.CLEANUP)
            if state.repo_path and not self.config.debug:
                try:
                    self.repo_manager.cleanup(state.repo_path, force=True)
                except Exception as e:
                    logger.warning(f"Cleanup failed: {e}")

    def process_all_issues(
        self,
        repo_url: Optional[str] = None,
        max_issues: Optional[int] = None,
    ) -> HuntReport:
        """Process all matching issues from the configured monitor.

        The Great Hunt - systematically eliminating bugs across the territory.

        Args:
            repo_url: Repository URL (optional, extracted from issues).
            max_issues: Maximum number of issues to process.

        Returns:
            HuntReport with summary of results.
        """
        validate_config_for_fix(self.config)

        report = HuntReport(started_at=datetime.now())

        console.print(Panel(
            f"[bold gold1]🦅 The Great Hunt Begins[/bold gold1]\n"
            f"BugHawk is scanning {self.config.monitor.value} for prey...",
            border_style="gold1",
        ))

        try:
            # Fetch issues from all configured projects
            all_issues: List[SentryIssue] = []
            projects = self._get_configured_projects()

            for project in projects:
                issues = self.monitor_client.get_issues(
                    project=project,
                    filters=self._get_monitor_filters(),
                )

                # Apply filters
                filtered = self._filter_issues(issues)
                all_issues.extend(filtered)

            if max_issues:
                all_issues = all_issues[:max_issues]

            report.total_issues = len(all_issues)
            console.print(f"\nFound [cyan]{len(all_issues)}[/] issues to hunt\n")

            if not all_issues:
                console.print("[yellow]No issues found matching criteria[/]")
                report.completed_at = datetime.now()
                return report

            # Process each issue with progress bar
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("🦅"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "[gold1]Hunting bugs...",
                    total=len(all_issues),
                )

                for issue in all_issues:
                    progress.update(
                        task,
                        description=f"[gold1]Hunting: {issue.id}",
                    )

                    try:
                        # Check if already processed
                        if self._is_already_processed(issue.id):
                            report.skipped += 1
                            progress.advance(task)
                            continue

                        # Process the issue
                        pr_url = self.process_issue(issue.id, repo_url=repo_url)

                        report.processed += 1

                        if pr_url:
                            report.succeeded += 1
                            report.prs_created.append(pr_url)
                        else:
                            # Check state for reason
                            state = self._hunt_states.get(issue.id)
                            if state:
                                if state.result == HuntResult.LOW_CONFIDENCE:
                                    report.low_confidence += 1
                                elif state.result == HuntResult.VALIDATION_FAILED:
                                    report.failed += 1

                    except Exception as e:
                        logger.exception(f"Failed to process issue {issue.id}")
                        report.failed += 1
                        report.errors.append({
                            "issue_id": issue.id,
                            "error": str(e),
                        })

                    progress.advance(task)

                    # Small delay to avoid rate limiting
                    time.sleep(0.5)

        except Exception as e:
            logger.exception("Great Hunt failed")
            report.errors.append({
                "issue_id": "global",
                "error": str(e),
            })

        report.completed_at = datetime.now()

        # Display summary
        self._display_hunt_summary(report)

        # Save report
        self._save_hunt_report(report)

        return report

    def dry_run_issue(
        self,
        issue_id: str,
        repo_url: Optional[str] = None,
    ) -> Optional[FixProposal]:
        """Run through the workflow without creating PR.

        A reconnaissance flight - observe but don't strike.

        Args:
            issue_id: Sentry issue ID.
            repo_url: Repository URL.

        Returns:
            FixProposal if fix was generated, None otherwise.
        """
        original_dry_run = self.dry_run
        self.dry_run = True

        try:
            console.print(Panel(
                "[bold yellow]🦅 Dry Run Mode[/bold yellow]\n"
                "Observing only - no changes will be made",
                border_style="yellow",
            ))

            self.process_issue(issue_id, repo_url=repo_url)

            state = self._hunt_states.get(issue_id)
            if state and state.fix_proposal:
                self._display_fix_proposal(state.fix_proposal)
                return state.fix_proposal

            return None

        finally:
            self.dry_run = original_dry_run

    def resume_hunt(self, issue_id: str) -> Optional[str]:
        """Resume an interrupted hunt.

        Args:
            issue_id: Issue ID to resume.

        Returns:
            PR URL if successful, None otherwise.
        """
        state = self._load_hunt_state(issue_id)
        if not state:
            logger.warning(f"No saved state found for issue {issue_id}")
            return self.process_issue(issue_id)

        console.print(f"\n[yellow]Resuming hunt from phase: {state.phase.value}[/]")

        # For now, restart from beginning
        # TODO: Implement true resume from saved phase
        return self.process_issue(issue_id)

    # Helper methods

    def _create_hunt_state(self, issue_id: str) -> HuntState:
        """Create a new hunt state."""
        now = datetime.now()
        state = HuntState(
            issue_id=issue_id,
            phase=HuntPhase.SPOTTING,
            started_at=now,
            updated_at=now,
        )
        self._hunt_states[issue_id] = state
        return state

    def _update_phase(self, state: HuntState, phase: HuntPhase) -> HuntState:
        """Update hunt phase and persist state."""
        state.phase = phase
        state.updated_at = datetime.now()
        self._save_hunt_state(state)
        return state

    def _save_hunt_state(self, state: HuntState) -> None:
        """Save hunt state to disk."""
        state_file = self.state_dir / f"hunt_{state.issue_id}.json"
        with open(state_file, "w") as f:
            json.dump(state.to_dict(), f, indent=2)

    def _load_hunt_state(self, issue_id: str) -> Optional[HuntState]:
        """Load hunt state from disk."""
        state_file = self.state_dir / f"hunt_{issue_id}.json"
        if not state_file.exists():
            return None

        with open(state_file) as f:
            data = json.load(f)
        return HuntState.from_dict(data)

    def _is_already_processed(self, issue_id: str) -> bool:
        """Check if issue was already successfully processed."""
        state = self._load_hunt_state(issue_id)
        return state is not None and state.result == HuntResult.SUCCESS

    def _extract_repo_url(self, issue: SentryIssue) -> Optional[str]:
        """Extract repository URL from issue metadata."""
        # Check metadata for repo info
        if "repository" in issue.metadata:
            return issue.metadata["repository"]

        # Check tags
        if "repository" in issue.tags:
            return issue.tags["repository"]

        # Check for GitHub/GitLab integration data
        if "github" in issue.metadata:
            return issue.metadata["github"].get("url")

        return None

    def _extract_repo_full_name(self, repo_url: str) -> str:
        """Extract owner/repo from URL."""
        # Handle SSH URLs
        if repo_url.startswith("git@"):
            # git@github.com:owner/repo.git
            path = repo_url.split(":")[-1]
        else:
            # HTTPS URLs
            from urllib.parse import urlparse
            parsed = urlparse(repo_url)
            path = parsed.path

        # Remove .git suffix and leading slash
        name = path.lstrip("/").rstrip("/")
        if name.endswith(".git"):
            name = name[:-4]

        return name

    def _extract_stack_trace(self, event: Optional[Dict[str, Any]]) -> Optional[StackTrace]:
        """Extract stack trace from Sentry event."""
        if not event:
            return None

        try:
            from bughawk.core.models import StackFrame

            entries = event.get("entries", [])
            for entry in entries:
                if entry.get("type") == "exception":
                    values = entry.get("data", {}).get("values", [])
                    if values:
                        exc = values[0]
                        frames = []

                        stacktrace = exc.get("stacktrace", {})
                        for frame_data in stacktrace.get("frames", []):
                            frames.append(StackFrame(
                                filename=frame_data.get("filename", ""),
                                line_number=frame_data.get("lineNo", 1),
                                function=frame_data.get("function", "<unknown>"),
                                context_line=frame_data.get("contextLine"),
                                pre_context=frame_data.get("preContext", []),
                                post_context=frame_data.get("postContext", []),
                                in_app=frame_data.get("inApp", True),
                            ))

                        return StackTrace(
                            frames=frames,
                            exception_type=exc.get("type", "Exception"),
                            exception_value=exc.get("value", ""),
                        )

        except Exception as e:
            logger.warning(f"Failed to extract stack trace: {e}")

        return None

    def _build_code_context(
        self,
        issue: SentryIssue,
        repo_path: Path,
        stack_trace: Optional[StackTrace],
    ) -> CodeContext:
        """Build code context for the issue."""
        # Find the main file from stack trace or culprit
        target_file = None
        error_line = None

        if stack_trace and stack_trace.frames:
            # Get the last in-app frame
            for frame in reversed(stack_trace.frames):
                if frame.in_app:
                    target_file = frame.filename
                    error_line = frame.line_number
                    break

        if not target_file and issue.culprit:
            # Extract from culprit (e.g., "app.views.user_profile")
            parts = issue.culprit.split(".")
            if parts:
                target_file = "/".join(parts[:-1]) + ".py"

        if not target_file:
            raise OrchestratorError("Could not determine target file from issue")

        # Find actual file in repo
        found_file = self.code_locator.find_file_in_repo(repo_path, target_file)
        if not found_file:
            raise OrchestratorError(f"Could not find file in repository: {target_file}")

        # Read file content
        file_content = found_file.read_text(encoding="utf-8", errors="replace")

        # Build surrounding lines
        surrounding_lines: Dict[int, str] = {}
        if error_line:
            lines = file_content.split("\n")
            start = max(0, error_line - 10)
            end = min(len(lines), error_line + 10)
            for i in range(start, end):
                surrounding_lines[i + 1] = lines[i]

        return CodeContext(
            file_path=str(found_file.relative_to(repo_path)),
            file_content=file_content,
            error_line=error_line,
            surrounding_lines=surrounding_lines,
        )

    def _filter_issues(self, issues: List[SentryIssue]) -> List[SentryIssue]:
        """Filter issues based on configuration."""
        filtered = []

        for issue in issues:
            # Check minimum events
            if issue.count < self.config.filters.min_events:
                continue

            # Check severity
            if issue.level not in self.config.filters.severity_levels:
                continue

            # Check ignored list
            if issue.id in self.config.filters.ignored_issues:
                continue

            filtered.append(issue)

        return filtered

    def _get_configured_projects(self) -> List[str]:
        """Get the list of configured projects based on active monitor."""
        from bughawk.core.config import MonitorType

        if self.config.monitor == MonitorType.SENTRY:
            return self.config.sentry.projects
        elif self.config.monitor == MonitorType.DATADOG:
            # Datadog uses services; return service if configured
            return [self.config.datadog.service] if self.config.datadog.service else [""]
        elif self.config.monitor == MonitorType.ROLLBAR:
            return [self.config.rollbar.project_slug] if self.config.rollbar.project_slug else [""]
        elif self.config.monitor == MonitorType.BUGSNAG:
            return [self.config.bugsnag.project_id] if self.config.bugsnag.project_id else [""]
        else:
            return [""]

    def _get_monitor_filters(self) -> Dict[str, Any]:
        """Get monitor-specific filters based on configuration."""
        from bughawk.core.config import MonitorType

        base_filters: Dict[str, Any] = {}

        if self.config.monitor == MonitorType.SENTRY:
            base_filters = {
                "query": "is:unresolved",
                "statsPeriod": f"{self.config.filters.max_age_days}d",
            }
        elif self.config.monitor == MonitorType.DATADOG:
            base_filters = {
                "status": "open",
                "env": self.config.datadog.env,
            }
        elif self.config.monitor == MonitorType.ROLLBAR:
            base_filters = {
                "status": "active",
            }
        elif self.config.monitor == MonitorType.BUGSNAG:
            base_filters = {
                "status": "open",
            }

        return base_filters

    def _display_hunt_summary(self, report: HuntReport) -> None:
        """Display hunt summary in a table."""
        table = Table(title="🦅 Hunt Summary", border_style="gold1")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Total Issues", str(report.total_issues))
        table.add_row("Processed", str(report.processed))
        table.add_row("Successful Fixes", f"[green]{report.succeeded}[/]")
        table.add_row("Low Confidence", f"[yellow]{report.low_confidence}[/]")
        table.add_row("Failed", f"[red]{report.failed}[/]")
        table.add_row("Skipped", str(report.skipped))

        if report.prs_created:
            table.add_row("PRs Created", str(len(report.prs_created)))

        console.print(table)

        if report.prs_created:
            console.print("\n[bold]Pull Requests:[/]")
            for pr_url in report.prs_created:
                console.print(f"  • [link={pr_url}]{pr_url}[/link]")

    def _display_fix_proposal(self, proposal: FixProposal) -> None:
        """Display fix proposal details."""
        console.print(Panel(
            f"[bold]Fix Proposal[/bold]\n\n"
            f"[cyan]Description:[/] {proposal.fix_description}\n\n"
            f"[cyan]Confidence:[/] {proposal.confidence_score:.2f}\n\n"
            f"[cyan]Explanation:[/] {proposal.explanation}\n\n"
            f"[cyan]Files Changed:[/] {len(proposal.code_changes)}",
            title="🦅 Proposed Fix",
            border_style="green",
        ))

        # Show diff preview
        for file_path, diff in proposal.code_changes.items():
            console.print(f"\n[bold]{file_path}[/]")
            console.print(f"```diff\n{diff[:500]}{'...' if len(diff) > 500 else ''}\n```")

    def _save_hunt_report(self, report: HuntReport) -> None:
        """Save hunt report to disk."""
        report_file = self.config.output_dir / "reports" / f"hunt_{report.started_at.strftime('%Y%m%d_%H%M%S')}.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)

        with open(report_file, "w") as f:
            json.dump(report.to_dict(), f, indent=2)

        logger.info(f"Hunt report saved to: {report_file}")
