# BugHawk Architecture

This document describes the high-level architecture of BugHawk and how its components work together.

## Overview

BugHawk follows a modular, pipeline-based architecture inspired by a hawk's hunting behavior. Each phase of the "hunt" is handled by specialized components that work together through the Orchestrator.

```
┌─────────────────────────────────────────────────────────────────────┐
│                          BugHawk CLI                                 │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Orchestrator                                 │
│  Coordinates the entire bug hunting workflow                         │
└─────────────────────────────────────────────────────────────────────┘
        │           │           │           │           │
        ▼           ▼           ▼           ▼           ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ Sentry  │ │Analyzer │ │  Fixer  │ │   Git   │ │  Utils  │
   │ Client  │ │ Module  │ │ Module  │ │ Module  │ │         │
   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

## Core Components

### 1. CLI (`cli.py`)

The entry point for all BugHawk commands. Built with Click and Rich for a beautiful terminal experience.

**Responsibilities:**
- Parse command-line arguments
- Load and validate configuration
- Display progress and results
- Handle user interactions

### 2. Orchestrator (`core/orchestrator.py`)

The central coordinator that manages the entire bug hunting workflow.

**Responsibilities:**
- Coordinate all components
- Manage hunt phases (spotting → marking)
- Track state and enable resume capability
- Generate hunt reports

**Hunt Phases:**
```python
class HuntPhase(Enum):
    SPOTTING = "spotting"      # Fetching issues
    SURVEYING = "surveying"    # Locating code
    TRACKING = "tracking"      # Building context
    RECOGNIZING = "recognizing" # Pattern matching
    PLANNING = "planning"      # Generating fix
    VALIDATING = "validating"  # Validating fix
    STRIKING = "striking"      # Applying fix
    MARKING = "marking"        # Creating PR
    CLEANUP = "cleanup"        # Cleaning up
```

### 3. Analyzer Module (`analyzer/`)

Handles code analysis and context building.

#### CodeLocator (`code_locator.py`)
- Clone repositories
- Find files by name/path
- Extract code context
- Detect binary files
- Handle fuzzy matching

#### ContextBuilder (`context_builder.py`)
- Build rich context from issues
- Extract stack traces
- Get git blame/history
- Find related files
- Generate LLM prompts

#### PatternMatcher (`pattern_matcher.py`)
- Match errors against known patterns
- Categorize errors (null reference, key error, etc.)
- Provide pattern-based fix suggestions

### 4. Fixer Module (`fixer/`)

Handles fix generation and validation.

#### FixGenerator (`fix_generator.py`)
- Generate fixes using patterns or LLM
- Validate proposed fixes
- Apply fixes to code
- Track fix attempts

#### LLMClient (`llm_client.py`)
- Interface with LLM providers (OpenAI, Anthropic, Azure, Gemini, Ollama, Groq, Mistral, Cohere)
- Response caching to reduce API costs
- Retry logic with exponential backoff
- Send analysis requests
- Parse fix proposals from responses

#### Validator (`validator.py`)
- Validate fix safety
- Check syntax correctness
- Verify scope appropriateness

### 5. Git Module (`git/`)

Handles all Git operations.

#### RepoManager (`repo_manager.py`)
- Clone/prepare repositories
- Create fix branches
- Apply changes
- Commit and push

#### PRCreator (`pr_creator.py`)
- Create pull requests on GitHub, GitLab, and Bitbucket
- Full implementation for all three platforms:
  - **GitHub**: Uses PyGithub library
  - **GitLab**: Uses python-gitlab library
  - **Bitbucket**: Uses REST API v2.0 with requests
- Add comments to existing PRs/MRs
- Get PR/MR information
- Link issues to Sentry for traceability
- Format PR descriptions with fix details

### 6. Sentry Module (`sentry/`)

Handles Sentry API integration.

#### SentryClient (`client.py`)
- Fetch issues from projects
- Get issue details and events
- Extract stack traces
- Handle pagination

## Data Flow

### Issue Processing Flow

```
1. SPOTTING
   SentryClient.fetch_issues() → List[SentryIssue]
                                        │
2. SURVEYING                            ▼
   CodeLocator.find_file_in_repo() → Path
                                        │
3. TRACKING                             ▼
   ContextBuilder.build_context() → EnrichedContext
                                        │
4. RECOGNIZING                          ▼
   PatternMatcher.match_pattern() → PatternMatch | None
                                        │
5. PLANNING                             ▼
   FixGenerator.generate_fix() → FixProposal
                                        │
6. VALIDATING                           ▼
   FixGenerator.validate_fix() → ValidationResult
                                        │
7. STRIKING                             ▼
   RepoManager.apply_changes() → Modified Files
                                        │
8. MARKING                              ▼
   PRCreator.create_pr() → PR URL
```

### Data Models

```python
# Core Models (core/models.py)

@dataclass
class SentryIssue:
    id: str
    title: str
    culprit: str | None
    level: IssueSeverity
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    status: IssueStatus
    metadata: dict
    tags: dict

@dataclass
class CodeContext:
    file_path: str
    file_content: str
    error_line: int | None
    error_column: int | None
    surrounding_lines: dict[int, str]
    related_files: list[str]

@dataclass
class FixProposal:
    issue_id: str
    fix_description: str
    code_changes: dict[str, str]  # file_path -> diff
    confidence_score: float
    explanation: str
```

## Configuration

Configuration is loaded from multiple sources with priority:

```
1. CLI Arguments (highest priority)
         │
         ▼
2. Environment Variables (BUGHAWK_*)
         │
         ▼
3. .bughawk.yml File
         │
         ▼
4. Default Values (lowest priority)
```

### Configuration Classes

```python
# core/config.py

class BugHawkConfig:
    sentry: SentryConfig
    filters: FilterConfig
    llm: LLMConfig
    git: GitConfig
    debug: bool
    output_dir: Path
```

## State Management

### Hunt State Persistence

BugHawk persists hunt state to enable resuming interrupted hunts:

```
.bughawk/
├── state/
│   ├── hunt_12345.json    # Individual hunt state
│   ├── hunt_12346.json
│   └── ...
└── reports/
    └── hunt_20240115_100000.json  # Hunt reports
```

### State Structure

```python
@dataclass
class HuntState:
    issue_id: str
    phase: HuntPhase
    started_at: datetime
    updated_at: datetime
    branch_name: str | None
    fix_proposal: FixProposal | None
    result: HuntResult | None
    error: str | None
```

## Error Handling

### Exception Hierarchy

```
BugHawkError (base)
├── ConfigurationError
├── OrchestratorError
├── CodeLocatorError
│   ├── RepositoryCloneError
│   ├── FileNotFoundInRepoError
│   └── BinaryFileError
├── FixGenerationError
├── FixValidationError
├── SentryError
│   ├── SentryAPIError
│   ├── SentryNotFoundError
│   └── SentryRateLimitError
└── GitError
    ├── CloneError
    ├── BranchError
    └── PushError
```

## Testing Strategy

### Test Layers

1. **Unit Tests**: Test individual components in isolation
2. **Integration Tests**: Test component interactions
3. **Fixtures**: Shared test data and mocks in `conftest.py`

### Test Files by Feature Group

| Test File | Tests | Feature Coverage |
|-----------|-------|------------------|
| `test_pr_creator.py` | 82 | GitHub, GitLab, Bitbucket PR creation |
| `test_llm_client.py` | 55 | LLM providers, caching, retry, parsing |
| `test_config.py` | 51 | Config models, env loading, validation |
| `test_monitors.py` | 49 | Datadog, Rollbar, Bugsnag monitors |
| `test_code_locator.py` | 38 | File finding and context extraction |
| `test_fix_generator.py` | 34 | Fix generation and application |
| `test_context_builder.py` | 28 | Context building and enrichment |
| `test_validator.py` | 28 | Fix validation and safety checks |
| `test_repo_manager.py` | 27 | Git repository operations |
| `test_orchestrator.py` | 22 | Workflow orchestration |
| `test_pattern_matcher.py` | 21 | Error pattern matching |
| `test_sentry_client.py` | 19 | Sentry API client |
| `test_integration.py` | 14 | End-to-end integration tests |

**Total: 468+ tests**

### Mock Strategy

External services are mocked for testing:
- Sentry/Datadog/Rollbar/Bugsnag API → Mock responses
- Git operations → Temp repositories
- LLM calls → Mock responses
- GitHub/GitLab/Bitbucket API → Mock client

## Extension Points

### Adding New Error Patterns

```python
# analyzer/pattern_matcher.py

new_pattern = ErrorPattern(
    id="new-pattern",
    name="New Error Pattern",
    category=ErrorCategory.CUSTOM,
    languages=["python"],
    exception_types=["NewException"],
    message_patterns=[r"specific.*pattern"],
    common_causes=["Cause 1", "Cause 2"],
    typical_fixes=["Fix 1", "Fix 2"],
)
```

### Adding New Git Providers

```python
# git/pr_creator.py

class NewProviderPRCreator(BasePRCreator):
    def create_pr(self, repo_full_name, ...) -> str:
        # Implementation
        pass
```

### Adding New LLM Providers

BugHawk supports multiple LLM providers through a base class pattern:

```python
# fixer/llm_client.py

class NewLLMProvider(BaseLLMProvider):
    """New LLM provider implementation."""

    DEFAULT_MODEL = "model-name"

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key
        self.provider = LLMProvider.NEW_PROVIDER

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 60.0,
    ) -> LLMResponse:
        # Implementation
        pass

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL
```

Currently supported providers:
- **OpenAI** (GPT-4, GPT-3.5)
- **Anthropic** (Claude 3.5, Claude 3)
- **Azure OpenAI** (Custom deployments)
- **Google Gemini** (Gemini Pro, Gemini Flash)
- **Ollama** (Local models: Llama, Mistral, etc.)
- **Groq** (Fast inference: Llama, Mixtral)
- **Mistral** (Mistral Large, Mistral Small)
- **Cohere** (Command R+)

## Performance Considerations

### Optimizations

1. **Shallow clones**: Clone with `depth=1` for faster operations
2. **Lazy LLM init**: LLM client created only when needed
3. **Parallel processing**: Hunt mode can process multiple issues
4. **Caching**: Code context cached during analysis

### Resource Management

- Temporary directories cleaned up after use
- Repository clones managed in temp directory
- State files periodically cleaned

## Security

### Sensitive Data

- API tokens stored in environment variables
- Never logged or exposed in errors
- Configuration file should be gitignored

### Code Safety

- Fixes validated before application
- Dry-run mode for previewing
- Confidence thresholds prevent low-quality fixes
- Human review encouraged via PR workflow
