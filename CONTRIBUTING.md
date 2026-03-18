# Contributing to BugHawk 🦅

Thank you for your interest in contributing to BugHawk! We welcome contributions from everyone.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [Code Style](#code-style)
- [Architecture Overview](#architecture-overview)

## Code of Conduct

By participating in this project, you agree to abide by our code of conduct:

- Be respectful and inclusive
- Be patient with new contributors
- Focus on constructive feedback
- Remember that everyone was new once

## Getting Started

### Finding Issues to Work On

1. Check our [GitHub Issues](https://github.com/kieutrungvtr/bughawk/issues) for open tasks
2. Look for issues labeled `good first issue` if you're new
3. Issues labeled `help wanted` are great for contributors
4. Feel free to ask questions on any issue

### Before You Start

1. **Check existing issues**: Make sure your idea isn't already being discussed
2. **Open an issue**: For significant changes, open an issue first to discuss your approach
3. **Assign yourself**: Comment on an issue to let others know you're working on it

## Development Setup

### Prerequisites

- Python 3.10 or higher
- Git
- Poetry (recommended) or pip

### Setup Steps

```bash
# 1. Fork and clone the repository
git clone https://github.com/YOUR-USERNAME/bughawk.git
cd bughawk

# 2. Install dependencies
poetry install

# Or using pip
pip install -e ".[dev]"

# 3. Install pre-commit hooks
pre-commit install

# 4. Verify setup
pytest
```

### Environment Setup

Create a `.env` file for local development:

```bash
# Optional: For testing with real APIs
BUGHAWK_SENTRY_AUTH_TOKEN=your-token
BUGHAWK_SENTRY_ORG=your-org
BUGHAWK_LLM_API_KEY=your-key
```

## Making Changes

### Branch Naming

Use descriptive branch names:

```
feature/add-gitlab-support
fix/sentry-rate-limiting
docs/improve-readme
refactor/cleanup-orchestrator
```

### Commit Messages

Follow conventional commits format:

```
type(scope): description

[optional body]

[optional footer]
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Code style (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding tests
- `chore`: Maintenance tasks

Examples:
```
feat(analyzer): add support for PHP error patterns
fix(sentry): handle rate limiting gracefully
docs(readme): add configuration examples
test(orchestrator): add integration tests for hunt workflow
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=bughawk --cov-report=html

# Run specific test file
pytest tests/test_code_locator.py

# Run tests matching a pattern
pytest -k "test_pattern"

# Run with verbose output
pytest -v
```

### Writing Tests

1. **Location**: Place tests in the `tests/` directory
2. **Naming**: Use `test_<module>.py` for test files
3. **Fixtures**: Use pytest fixtures from `conftest.py`
4. **Coverage**: Aim for high coverage on new code

Example test:

```python
"""Tests for the new module."""

import pytest
from bughawk.module import MyClass


class TestMyClass:
    """Tests for MyClass."""

    def test_initialization(self) -> None:
        """Test that MyClass initializes correctly."""
        obj = MyClass()
        assert obj is not None

    def test_method_with_fixture(self, temp_dir: Path) -> None:
        """Test method using a fixture."""
        obj = MyClass(work_dir=temp_dir)
        result = obj.do_something()
        assert result.success
```

### Test Categories

Tests are organized by feature groups for easy review:

| Test File | Tests | Feature Coverage |
|-----------|-------|------------------|
| `test_pr_creator.py` | 82 | GitHub, GitLab, Bitbucket PR creation |
| `test_llm_client.py` | 55 | LLM providers, caching, retry logic |
| `test_config.py` | 51 | Configuration models, env loading, validation |
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

- **Unit tests**: `tests/test_*.py` - Test individual components
- **Integration tests**: `tests/test_integration.py` - Test component interactions

## Pull Request Process

### Before Submitting

1. **Update tests**: Add or update tests for your changes
2. **Run all tests**: Ensure all tests pass locally
3. **Update documentation**: Add docstrings and update README if needed
4. **Format code**: Run `black` and `ruff` formatters

```bash
# Format code
black bughawk tests
ruff check --fix bughawk tests

# Type check
mypy bughawk
```

### PR Checklist

- [ ] Tests pass locally
- [ ] Code is formatted with black
- [ ] No ruff/mypy errors
- [ ] Documentation updated if needed
- [ ] Commit messages follow conventions
- [ ] PR description explains the changes

### PR Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactoring

## Testing
Describe how you tested these changes.

## Related Issues
Fixes #123
```

### Review Process

1. A maintainer will review your PR
2. Address any feedback or questions
3. Once approved, a maintainer will merge your PR

## Code Style

### Python Style

We follow PEP 8 with some modifications:

- Line length: 100 characters
- Use type hints for all functions
- Use docstrings for modules, classes, and functions

### Formatting Tools

```bash
# Auto-format code
black bughawk tests

# Sort imports
isort bughawk tests

# Lint code
ruff check bughawk tests

# Type checking
mypy bughawk
```

### Example Code Style

```python
"""Module docstring explaining purpose."""

from pathlib import Path
from typing import Optional

from bughawk.core.models import Issue


class MyAnalyzer:
    """Analyzer for processing issues.

    This class handles the analysis workflow for issues,
    including pattern matching and context building.

    Example:
        >>> analyzer = MyAnalyzer()
        >>> result = analyzer.analyze(issue)
    """

    def __init__(self, config: Optional[Config] = None) -> None:
        """Initialize the analyzer.

        Args:
            config: Optional configuration object.
        """
        self.config = config or Config()

    def analyze(self, issue: Issue) -> AnalysisResult:
        """Analyze an issue and return results.

        Args:
            issue: The issue to analyze.

        Returns:
            AnalysisResult containing findings.

        Raises:
            AnalysisError: If analysis fails.
        """
        # Implementation
        pass
```

## Architecture Overview

### Module Structure

```
bughawk/
├── analyzer/        # Code analysis (CodeLocator, ContextBuilder, PatternMatcher)
├── core/            # Core logic (Config, Models, Orchestrator)
├── fixer/           # Fix generation (FixGenerator, LLMClient, Validator)
├── git/             # Git operations (RepoManager, PRCreator)
├── monitors/        # Error monitoring integrations (Sentry, Datadog, Rollbar, Bugsnag)
├── sentry/          # Legacy Sentry API (deprecated, use monitors/)
└── utils/           # Utilities (Logger)
```

### Key Components

1. **Orchestrator** (`core/orchestrator.py`): Main workflow coordinator
2. **CodeLocator** (`analyzer/code_locator.py`): Finds and extracts code
3. **ContextBuilder** (`analyzer/context_builder.py`): Builds rich context
4. **PatternMatcher** (`analyzer/pattern_matcher.py`): Matches error patterns
5. **FixGenerator** (`fixer/fix_generator.py`): Generates code fixes
6. **RepoManager** (`git/repo_manager.py`): Git operations

### Data Flow

```
Sentry Issue
    ↓
CodeLocator (find source files)
    ↓
ContextBuilder (build context)
    ↓
PatternMatcher / LLM (analyze)
    ↓
FixGenerator (create fix)
    ↓
RepoManager (apply changes)
    ↓
PRCreator (create PR)
```

### Adding New Features

When adding new features:

1. **Error monitoring integrations**: Add to `monitors/` (implement `MonitorClient` interface)
2. **New error patterns**: Add to `analyzer/pattern_matcher.py`
3. **Git providers**: Add to `git/pr_creator.py` (implement `BasePRCreator` interface)
4. **LLM providers**: Add to `fixer/llm_client.py` (implement `BaseLLMProvider` interface)
5. **CLI commands**: Add to `cli.py`

Supported platforms:
- **Error monitors**: Sentry, Datadog, Rollbar, Bugsnag
- **Git providers**: GitHub, GitLab, Bitbucket
- **LLM providers**: OpenAI, Anthropic, Azure OpenAI, Gemini, Ollama, Groq, Mistral, Cohere

## Questions?

- Open a [GitHub Discussion](https://github.com/kieutrungvtr/bughawk/discussions)
- Join our community chat
- Email the maintainers

Thank you for contributing to BugHawk! 🦅
