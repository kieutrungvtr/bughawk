# BugHawk API Reference

This document provides detailed API documentation for BugHawk's core modules.

## Core Module

### `bughawk.core.orchestrator`

#### `Orchestrator`

Main workflow coordinator for bug hunting and fixing.

```python
class Orchestrator:
    def __init__(
        self,
        config: BugHawkConfig,
        confidence_threshold: float = 0.6,
        dry_run: bool = False,
    ) -> None:
        """Initialize the Orchestrator.

        Args:
            config: BugHawk configuration object
            confidence_threshold: Minimum confidence for applying fixes (0.0-1.0)
            dry_run: If True, don't make actual changes
        """
```

**Methods:**

```python
def process_issue(
    self,
    issue_id: str,
    repo_url: str,
    branch: str = "main",
) -> HuntState | None:
    """Process a single Sentry issue.

    Args:
        issue_id: Sentry issue ID
        repo_url: Git repository URL
        branch: Branch to work on

    Returns:
        HuntState with results, or None if processing failed
    """

def process_all_issues(
    self,
    repo_url: str,
    project: str | None = None,
    limit: int = 10,
    auto_pr: bool = False,
) -> HuntReport:
    """Process multiple issues from Sentry.

    Args:
        repo_url: Git repository URL
        project: Sentry project slug (uses config if None)
        limit: Maximum issues to process
        auto_pr: Create PRs automatically

    Returns:
        HuntReport with summary statistics
    """

def dry_run_issue(
    self,
    issue_id: str,
    repo_url: str,
) -> FixProposal | None:
    """Analyze issue without applying changes.

    Args:
        issue_id: Sentry issue ID
        repo_url: Git repository URL

    Returns:
        FixProposal if fix generated, None otherwise
    """

def resume_hunt(
    self,
    issue_id: str,
    repo_url: str,
) -> HuntState | None:
    """Resume a previously interrupted hunt.

    Args:
        issue_id: Sentry issue ID to resume
        repo_url: Git repository URL

    Returns:
        Updated HuntState
    """
```

#### `HuntState`

```python
@dataclass
class HuntState:
    issue_id: str
    phase: HuntPhase
    started_at: datetime
    updated_at: datetime
    branch_name: str | None = None
    fix_proposal: FixProposal | None = None
    result: HuntResult | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialize to dictionary."""

    @classmethod
    def from_dict(cls, data: dict) -> "HuntState":
        """Deserialize from dictionary."""
```

#### `HuntPhase`

```python
class HuntPhase(Enum):
    SPOTTING = "spotting"      # Fetching issue from Sentry
    SURVEYING = "surveying"    # Locating code in repository
    TRACKING = "tracking"      # Building code context
    RECOGNIZING = "recognizing" # Pattern matching / analysis
    PLANNING = "planning"      # Generating fix proposal
    VALIDATING = "validating"  # Validating proposed fix
    STRIKING = "striking"      # Applying fix to code
    MARKING = "marking"        # Creating PR
    CLEANUP = "cleanup"        # Cleaning up resources
```

#### `HuntResult`

```python
class HuntResult(Enum):
    SUCCESS = "success"                    # Fix applied successfully
    SKIPPED = "skipped"                    # Issue skipped (filtered out)
    LOW_CONFIDENCE = "low_confidence"      # Fix below confidence threshold
    VALIDATION_FAILED = "validation_failed" # Fix failed validation
    ERROR = "error"                        # Error during processing
```

---

### `bughawk.core.models`

#### `SentryIssue`

```python
@dataclass
class SentryIssue:
    id: str
    title: str
    culprit: str | None = None
    level: IssueSeverity = IssueSeverity.ERROR
    count: int = 0
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    status: IssueStatus = IssueStatus.UNRESOLVED
    metadata: dict = field(default_factory=dict)
    tags: dict = field(default_factory=dict)
```

#### `StackTrace`

```python
@dataclass
class StackTrace:
    frames: list[StackFrame]
    exception_type: str = "Exception"
    exception_value: str = ""
```

#### `StackFrame`

```python
@dataclass
class StackFrame:
    filename: str
    line_number: int
    function: str = "<unknown>"
    context_line: str | None = None
    pre_context: list[str] = field(default_factory=list)
    post_context: list[str] = field(default_factory=list)
    in_app: bool = True
```

#### `CodeContext`

```python
@dataclass
class CodeContext:
    file_path: str
    file_content: str
    error_line: int | None = None
    error_column: int | None = None
    surrounding_lines: dict[int, str] = field(default_factory=dict)
    related_files: list[str] = field(default_factory=list)
```

#### `FixProposal`

```python
@dataclass
class FixProposal:
    issue_id: str
    fix_description: str
    code_changes: dict[str, str]  # file_path -> diff/new_content
    confidence_score: float = 0.0
    explanation: str = ""
```

---

## Analyzer Module

### `bughawk.analyzer.code_locator`

#### `CodeLocator`

```python
class CodeLocator:
    def __init__(self, temp_dir: Path | None = None) -> None:
        """Initialize CodeLocator.

        Args:
            temp_dir: Directory for temporary files
        """

    def clone_repository(
        self,
        repo_url: str,
        branch: str = "main",
        target_dir: Path | None = None,
        depth: int | None = 1,
    ) -> Path:
        """Clone a Git repository.

        Args:
            repo_url: Repository URL
            branch: Branch to checkout
            target_dir: Target directory
            depth: Clone depth (None for full)

        Returns:
            Path to cloned repository

        Raises:
            RepositoryCloneError: If cloning fails
        """

    def find_file_in_repo(
        self,
        repo_path: Path,
        filename: str,
        use_fuzzy: bool = True,
    ) -> Path | None:
        """Find a file in repository.

        Args:
            repo_path: Repository root path
            filename: File to find (can be partial path)
            use_fuzzy: Enable fuzzy matching

        Returns:
            Path to file, or None if not found
        """

    def get_file_content(
        self,
        file_path: Path,
        line_start: int = 1,
        line_end: int | None = None,
    ) -> str:
        """Get file content.

        Args:
            file_path: Path to file
            line_start: Starting line (1-indexed)
            line_end: Ending line (None for EOF)

        Returns:
            File content

        Raises:
            FileAccessError: If file cannot be read
            BinaryFileError: If file is binary
        """

    def get_surrounding_context(
        self,
        file_path: Path,
        target_line: int,
        context_lines: int = 50,
    ) -> dict[int, str]:
        """Get code context around a line.

        Args:
            file_path: Path to file
            target_line: Center line number
            context_lines: Lines before/after

        Returns:
            Dict mapping line numbers to content
        """

    def build_code_context(
        self,
        file_path: Path,
        error_line: int,
        error_column: int | None = None,
        context_lines: int = 50,
        related_files: list[str] | None = None,
    ) -> CodeContext:
        """Build complete code context.

        Args:
            file_path: Source file path
            error_line: Error line number
            error_column: Error column (optional)
            context_lines: Context size
            related_files: Related file paths

        Returns:
            CodeContext object
        """

    def cleanup(self, path: Path | None = None) -> None:
        """Clean up temporary files.

        Args:
            path: Specific path to clean (None for all)
        """
```

---

### `bughawk.analyzer.context_builder`

#### `ContextBuilder`

```python
class ContextBuilder:
    def __init__(self, code_locator: CodeLocator | None = None) -> None:
        """Initialize ContextBuilder.

        Args:
            code_locator: CodeLocator instance
        """

    def build_context(
        self,
        issue: SentryIssue,
        repo_path: Path,
        context_lines: int = 50,
        include_git_info: bool = True,
    ) -> EnrichedContext:
        """Build enriched context for an issue.

        Args:
            issue: Sentry issue
            repo_path: Repository path
            context_lines: Context size
            include_git_info: Include git blame/history

        Returns:
            EnrichedContext with all gathered info
        """

    def build_llm_prompt(
        self,
        context: EnrichedContext,
        issue: SentryIssue,
        include_fix_request: bool = True,
    ) -> str:
        """Build LLM analysis prompt.

        Args:
            context: Enriched context
            issue: Sentry issue
            include_fix_request: Request fix in prompt

        Returns:
            Formatted prompt string
        """
```

#### `EnrichedContext`

```python
@dataclass
class EnrichedContext:
    code_context: CodeContext
    stack_trace: StackTrace | None
    blame_info: list[GitBlameInfo]
    recent_commits: list[GitCommitInfo]
    related_contexts: list[CodeContext]
    language: str
    repo_path: Path | None
```

---

### `bughawk.analyzer.pattern_matcher`

#### `PatternMatcher`

```python
class PatternMatcher:
    def __init__(self) -> None:
        """Initialize with built-in patterns."""

    def match_pattern(
        self,
        issue: SentryIssue,
        stack_trace: StackTrace | None = None,
        code_context: str | None = None,
    ) -> PatternMatch | None:
        """Match issue against known patterns.

        Args:
            issue: Sentry issue
            stack_trace: Stack trace
            code_context: Code context string

        Returns:
            PatternMatch if found, None otherwise
        """

    def register_pattern(self, pattern: ErrorPattern) -> None:
        """Register a custom error pattern."""

    def register_fix_template(self, template: FixTemplate) -> None:
        """Register a custom fix template."""
```

#### `PatternMatch`

```python
@dataclass
class PatternMatch:
    pattern: ErrorPattern
    confidence: float  # 0.0 to 1.0
    matched_by: list[str]  # What triggered the match
    suggested_fix: FixTemplate | None

    @property
    def is_confident_match(self) -> bool:
        """True if confidence >= 0.7"""
```

---

## Fixer Module

### `bughawk.fixer.fix_generator`

#### `FixGenerator`

```python
class FixGenerator:
    def __init__(
        self,
        pattern_matcher: PatternMatcher | None = None,
        llm_client: LLMClient | None = None,
        context_builder: ContextBuilder | None = None,
        debug_dir: Path | None = None,
    ) -> None:
        """Initialize FixGenerator."""

    def generate_fix(
        self,
        issue: SentryIssue,
        context: CodeContext,
        repo_path: Path,
        stack_trace: StackTrace | None = None,
        prefer_pattern: bool = True,
    ) -> FixProposal:
        """Generate a fix for the issue.

        Args:
            issue: Sentry issue
            context: Code context
            repo_path: Repository path
            stack_trace: Stack trace
            prefer_pattern: Try patterns first

        Returns:
            FixProposal

        Raises:
            FixGenerationError: If generation fails
        """

    def validate_fix(
        self,
        proposal: FixProposal,
        context: CodeContext,
    ) -> ValidationResult:
        """Validate a proposed fix.

        Args:
            proposal: Fix proposal
            context: Original code context

        Returns:
            ValidationResult with details
        """

    def apply_fix_to_code(
        self,
        file_path: Path,
        fix: FixProposal,
    ) -> str:
        """Apply fix and return new content.

        Does NOT modify file on disk.

        Args:
            file_path: Original file path
            fix: Fix to apply

        Returns:
            New file content
        """
```

#### `ValidationResult`

```python
@dataclass
class ValidationResult:
    is_valid: bool
    syntax_valid: bool
    changes_error_location: bool
    scope_appropriate: bool
    confidence_adjustment: float  # Multiplier for confidence
    issues: list[str]  # Critical issues
    warnings: list[str]  # Non-critical warnings
```

---

## Git Module

### `bughawk.git.repo_manager`

#### `RepoManager`

```python
class RepoManager:
    def __init__(
        self,
        work_dir: Path | None = None,
        git_token: str | None = None,
    ) -> None:
        """Initialize RepoManager."""

    def prepare_repository(
        self,
        repo_url: str,
        branch: str = "main",
    ) -> Path:
        """Clone/prepare a repository.

        Returns:
            Path to repository
        """

    def create_fix_branch(
        self,
        repo_path: Path,
        issue_id: str,
        branch_prefix: str = "bughawk/fix-",
    ) -> str:
        """Create a branch for the fix.

        Returns:
            Branch name
        """

    def apply_changes(
        self,
        repo_path: Path,
        code_changes: dict[str, str],
    ) -> list[Path]:
        """Apply code changes to files.

        Returns:
            List of modified file paths
        """

    def commit_changes(
        self,
        repo_path: Path,
        issue_id: str,
        issue_title: str,
        fix_explanation: str,
        sentry_url: str | None = None,
    ) -> str:
        """Commit changes.

        Returns:
            Commit hash
        """

    def push_branch(
        self,
        repo_path: Path,
        branch_name: str,
    ) -> None:
        """Push branch to remote."""

    def cleanup(self, repo_path: Path) -> None:
        """Clean up repository."""
```

---

### `bughawk.git.pr_creator`

#### `PRCreator`

```python
class PRCreator:
    @staticmethod
    def for_platform(
        platform: str,
        token: str,
    ) -> BasePRCreator:
        """Get PR creator for platform.

        Args:
            platform: "github", "gitlab", or "bitbucket"
            token: API token

        Returns:
            Platform-specific PR creator
        """

    @staticmethod
    def from_repo_url(
        repo_url: str,
        token: str,
    ) -> BasePRCreator:
        """Detect platform from URL and get creator."""
```

#### `BasePRCreator`

```python
class BasePRCreator(ABC):
    @abstractmethod
    def create_pull_request(
        self,
        repo_full_name: str,
        head_branch: str,
        base_branch: str,
        title: str,
        body: str,
        issue_id: str | None = None,
        sentry_issue_url: str | None = None,
    ) -> PRInfo:
        """Create a pull request.

        Returns:
            PRInfo with PR details including URL
        """

    @abstractmethod
    def add_comment_to_pr(
        self,
        repo_full_name: str,
        pr_number: int,
        comment: str,
    ) -> bool:
        """Add a comment to an existing PR.

        Returns:
            True if comment was added successfully
        """

    @abstractmethod
    def get_pr_info(
        self,
        repo_full_name: str,
        pr_number: int,
    ) -> PRInfo:
        """Get information about a PR.

        Returns:
            PRInfo with PR details
        """
```

#### `PRInfo`

```python
@dataclass
class PRInfo:
    number: int
    url: str
    title: str
    state: str
    head_branch: str
    base_branch: str
    created_at: str | None = None
    merged_at: str | None = None
```

#### Platform-Specific Implementations

**GitHubPRCreator**: Uses PyGithub library for GitHub API integration.

**GitLabPRCreator**: Uses python-gitlab library for GitLab API integration.
- Supports both gitlab.com and self-hosted GitLab instances
- Creates Merge Requests (MR) instead of Pull Requests

**BitbucketPRCreator**: Uses Bitbucket REST API v2.0.
- Supports Bitbucket Cloud
- Full PR lifecycle management

---

## Sentry Module

### `bughawk.sentry.client`

#### `SentryClient`

```python
class SentryClient:
    def __init__(
        self,
        auth_token: str,
        org: str,
        base_url: str = "https://sentry.io/api/0",
    ) -> None:
        """Initialize Sentry client."""

    def get_project_issues(
        self,
        project: str,
        status: str = "unresolved",
        limit: int = 25,
    ) -> list[SentryIssue]:
        """Get issues from a project.

        Args:
            project: Project slug
            status: Issue status filter
            limit: Maximum issues

        Returns:
            List of SentryIssue objects
        """

    def get_issue_details(
        self,
        issue_id: str,
    ) -> SentryIssue:
        """Get detailed issue information.

        Raises:
            SentryNotFoundError: If issue not found
        """

    def get_issue_events(
        self,
        issue_id: str,
        limit: int = 10,
    ) -> list[dict]:
        """Get events for an issue."""
```

---

## Configuration

### `bughawk.core.config`

#### `load_config`

```python
def load_config(
    config_path: Path | None = None,
    cli_overrides: CLIOverrides | None = None,
) -> BugHawkConfig:
    """Load configuration from all sources.

    Priority (highest to lowest):
    1. CLI overrides
    2. Environment variables
    3. YAML config file
    4. Default values

    Args:
        config_path: Explicit config file path
        cli_overrides: CLI argument overrides

    Returns:
        Validated BugHawkConfig

    Raises:
        ConfigurationError: If config is invalid
    """
```

#### `BugHawkConfig`

```python
class BugHawkConfig(BaseModel):
    sentry: SentryConfig
    filters: FilterConfig
    llm: LLMConfig
    git: GitConfig
    debug: bool = False
    output_dir: Path = Path(".bughawk")
```

---

## Exceptions

```python
# Base exception
class BugHawkError(Exception): pass

# Configuration
class ConfigurationError(BugHawkError): pass

# Orchestrator
class OrchestratorError(BugHawkError): pass

# Code Locator
class CodeLocatorError(BugHawkError): pass
class RepositoryCloneError(CodeLocatorError): pass
class FileNotFoundInRepoError(CodeLocatorError): pass
class BinaryFileError(CodeLocatorError): pass
class FileAccessError(CodeLocatorError): pass

# Fix Generator
class FixGenerationError(BugHawkError): pass
class FixValidationError(BugHawkError): pass

# Sentry
class SentryError(BugHawkError): pass
class SentryAPIError(SentryError): pass
class SentryNotFoundError(SentryError): pass
class SentryRateLimitError(SentryError): pass

# Git
class RepoManagerError(BugHawkError): pass
class CloneError(RepoManagerError): pass
class BranchError(RepoManagerError): pass
class CommitError(RepoManagerError): pass
class PushError(RepoManagerError): pass
```
