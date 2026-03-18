# 🦅 BugHawk

> **Hunt down bugs with precision and speed**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

BugHawk is an intelligent, automated bug hunting and fixing CLI tool that integrates with your team's error monitoring platforms to identify, analyze, and fix bugs in your codebase. Like a hawk spotting prey from above, BugHawk swoops in on errors with precision, analyzes their root cause, and proposes targeted fixes.

```
    ,_   _,
    |'\_/'|
   / (o o) \
  | "====" |    BugHawk
   \ ____ /     Automated Bug Hunting & Fixing
    |    |
    |    |
```

## ✨ Features

- **🔍 Multi-Platform Monitoring**: Integrates with Sentry, Datadog, Rollbar, Bugsnag, and other error tracking platforms
- **🧠 Intelligent Analysis**: Uses pattern matching and LLM-powered analysis to understand bug root causes
- **🔧 Automated Fixes**: Generates code fixes with confidence scores
- **📊 Rich CLI**: Beautiful terminal output with progress tracking and detailed reports
- **🔀 Git Integration**: Creates branches, commits, and pull requests automatically
- **⚡ Multi-Platform**: Supports GitHub, GitLab, and Bitbucket
- **🛡️ Safe Mode**: Dry-run capability to preview changes before applying

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/bughawk.git
cd bughawk

# Install dependencies
pip install -e .

# Or using poetry
poetry install
```

## 📦 Integrating BugHawk into Your Existing Project

Follow these steps to integrate BugHawk into your existing project and start fixing bugs automatically.

### Step 1: Install BugHawk

```bash
# Option A: Install from source (recommended for development)
git clone https://github.com/your-org/bughawk.git
cd bughawk
pip install -e .

# Option B: Install as a dependency in your project
pip install bughawk

# Option C: Using Poetry
poetry add bughawk
```

### Step 2: Set Up Error Monitoring Platform

Make sure your project is already connected to an error monitoring platform. BugHawk supports:

| Platform | Required Setup |
|----------|---------------|
| **Sentry** | Create an Auth Token at Settings → API Keys |
| **Datadog** | Create API Key + Application Key |
| **Rollbar** | Get Access Token from project settings |
| **Bugsnag** | Generate Personal Auth Token |

### Step 3: Get API Tokens

#### For Sentry:
1. Go to [Sentry](https://sentry.io) → Settings → Auth Tokens
2. Create a new token with scopes: `project:read`, `event:read`, `org:read`
3. Note your organization slug and project slug

#### For GitHub/GitLab/Bitbucket:
1. **GitHub**: Settings → Developer Settings → Personal Access Tokens → Generate with `repo` scope
2. **GitLab**: Preferences → Access Tokens → Create with `api` scope
3. **Bitbucket**: Settings → App Passwords → Create with repository read/write

#### For LLM Provider:
- **OpenAI**: Get API key from [platform.openai.com](https://platform.openai.com)
- **Anthropic**: Get API key from [console.anthropic.com](https://console.anthropic.com)
- **Other providers**: See Configuration Reference below

### Step 4: Configure Your Project

Navigate to your project root and initialize BugHawk:

```bash
cd /path/to/your/project

# Initialize configuration (creates .bughawk.yml)
bughawk config init
```

Or create `.bughawk.yml` manually:

```yaml
# .bughawk.yml - Place this in your project root
monitor: sentry  # or datadog, rollbar, bugsnag

sentry:
  org: your-org-slug
  projects:
    - your-project-slug

llm:
  provider: openai  # or anthropic, azure, gemini, ollama, groq, mistral, cohere
  model: gpt-4

git:
  provider: github  # or gitlab, bitbucket
  branch_prefix: bughawk/fix-
  auto_pr: true
  base_branch: main

filters:
  min_events: 5        # Only fix bugs with 5+ occurrences
  severity_levels:
    - error
    - fatal
  max_age_days: 30     # Focus on recent bugs
```

### Step 5: Set Environment Variables

```bash
# Add to your .env or export directly
export BUGHAWK_SENTRY_AUTH_TOKEN="your-sentry-token"
export BUGHAWK_LLM_API_KEY="your-openai-key"
export BUGHAWK_GIT_TOKEN="your-github-token"
```

**Important**: Add `.bughawk.yml` and `.env` to your `.gitignore` if they contain sensitive tokens.

### Step 6: Test Your Setup

```bash
# Verify all connections work
bughawk config test

# List recent issues from your error monitor
bughawk list-issues
```

Expected output:
```
✓ Sentry connection: OK
✓ LLM provider: OK
✓ Git provider: OK

Found 15 issues in project 'your-project':
  #12345  TypeError: Cannot read property 'x' of undefined  (523 events)
  #12346  KeyError: 'user_id'                                (156 events)
  ...
```

### Step 7: Fix Your First Bug

```bash
# Analyze an issue first (dry run)
bughawk analyze 12345

# Fix with dry-run to preview changes
bughawk fix 12345 --repo https://github.com/org/repo.git --dry-run

# Apply fix and create PR
bughawk fix 12345 --repo https://github.com/org/repo.git --auto-pr
```

### Step 8: Automate with Hunt Mode

For processing multiple bugs automatically:

```bash
# Hunt mode: process up to 10 issues
bughawk hunt --limit 10 --auto-pr

# Only fix high-confidence bugs
bughawk hunt --limit 5 --confidence 0.8 --auto-pr
```

### Workflow Example

```
Your Project
    │
    ├── .bughawk.yml        ← BugHawk configuration
    ├── .env                ← API tokens (gitignored)
    ├── src/
    │   └── your_code.py    ← Where bugs live
    └── ...

Workflow:
1. Errors occur in production → Logged to Sentry/Datadog
2. Run: bughawk hunt --auto-pr
3. BugHawk analyzes errors, generates fixes
4. PRs created automatically
5. Review and merge PRs
```

### Tips for Best Results

1. **Start with dry-run**: Always use `--dry-run` first to preview changes
2. **Set confidence threshold**: Use `--confidence 0.8` to only apply high-confidence fixes
3. **Filter by severity**: Focus on `error` and `fatal` level issues first
4. **Review PRs**: Always review auto-generated PRs before merging
5. **Use in CI/CD**: Run `bughawk hunt --dry-run` in CI to get fix suggestions

### Configuration

Create a `.bughawk.yml` configuration file in your project root. BugHawk supports multiple error monitoring platforms:

#### Sentry Configuration

```yaml
monitor: sentry  # sentry, datadog, rollbar, or bugsnag

sentry:
  org: your-sentry-org
  projects:
    - your-project-name

llm:
  provider: openai
  model: gpt-4

git:
  provider: github
  branch_prefix: bughawk/fix-
  auto_pr: true
  base_branch: main

filters:
  min_events: 10
  severity_levels:
    - error
    - fatal
  max_age_days: 30
```

#### Datadog Configuration

```yaml
monitor: datadog

datadog:
  api_key: ""      # Or use BUGHAWK_DATADOG_API_KEY
  app_key: ""      # Or use BUGHAWK_DATADOG_APP_KEY
  site: datadoghq.com  # datadoghq.eu for EU
  service: my-service
  env: production
```

#### Rollbar Configuration

```yaml
monitor: rollbar

rollbar:
  access_token: ""  # Or use BUGHAWK_ROLLBAR_ACCESS_TOKEN
  project_slug: my-project
```

#### Bugsnag Configuration

```yaml
monitor: bugsnag

bugsnag:
  auth_token: ""   # Or use BUGHAWK_BUGSNAG_AUTH_TOKEN
  org_id: your-org-id
  project_id: your-project-id
```

#### Environment Variables

```bash
# Select your monitor platform
export BUGHAWK_MONITOR="sentry"  # sentry, datadog, rollbar, bugsnag

# Sentry configuration
export BUGHAWK_SENTRY_AUTH_TOKEN="your-sentry-token"
export BUGHAWK_SENTRY_ORG="your-org"
export BUGHAWK_SENTRY_PROJECTS="project1,project2"

# Datadog configuration
export BUGHAWK_DATADOG_API_KEY="your-api-key"
export BUGHAWK_DATADOG_APP_KEY="your-app-key"
export BUGHAWK_DATADOG_SITE="datadoghq.com"

# Rollbar configuration
export BUGHAWK_ROLLBAR_ACCESS_TOKEN="your-token"

# Bugsnag configuration
export BUGHAWK_BUGSNAG_AUTH_TOKEN="your-token"
export BUGHAWK_BUGSNAG_ORG_ID="your-org-id"

# Common configuration
export BUGHAWK_LLM_API_KEY="your-openai-key"
export BUGHAWK_GIT_TOKEN="your-github-token"
```

### Basic Usage

```bash
# Initialize configuration
bughawk config init

# List recent issues from your configured monitor
bughawk list-issues

# Fix a specific issue
bughawk fix ISSUE_ID --repo https://github.com/org/repo.git

# Hunt mode: process multiple issues automatically
bughawk hunt --limit 10 --auto-pr

# Analyze an issue without fixing
bughawk analyze ISSUE_ID

# Check the status of ongoing hunts
bughawk status
```

## 🎯 How It Works

BugHawk follows a hawk's hunting strategy - methodical, precise, and efficient:

### 1. **Spotting** 🔭
Fetches issues from your error monitoring platform (Sentry, Datadog, Rollbar, or Bugsnag), filtering by severity, event count, and age.

### 2. **Surveying** 📍
Locates the error in your codebase by analyzing stack traces and file paths.

### 3. **Tracking** 🐾
Builds comprehensive context including surrounding code, git history, and related files.

### 4. **Recognizing** 🎯
Matches the error against known patterns or uses LLM analysis for complex bugs.

### 5. **Planning** 📋
Generates a fix proposal with code changes and confidence scores.

### 6. **Validating** ✅
Validates the fix for syntax errors, scope appropriateness, and safety.

### 7. **Striking** ⚡
Applies the fix to the codebase and creates a feature branch.

### 8. **Marking** 🏷️
Creates a pull request with detailed documentation of the fix.

## 📖 Commands

### `bughawk fix <issue-id>`

Fix a specific Sentry issue.

```bash
# Basic fix
bughawk fix 12345 --repo https://github.com/org/repo.git

# Dry run (preview without making changes)
bughawk fix 12345 --repo https://github.com/org/repo.git --dry-run

# Auto-create PR after fixing
bughawk fix 12345 --repo https://github.com/org/repo.git --auto-pr

# Set minimum confidence threshold
bughawk fix 12345 --repo https://github.com/org/repo.git --confidence 0.8
```

### `bughawk hunt`

Automatically hunt and fix multiple issues.

```bash
# Hunt with default settings
bughawk hunt

# Limit number of issues
bughawk hunt --limit 5

# Filter by project
bughawk hunt --project my-project

# Hunt and create PRs automatically
bughawk hunt --auto-pr

# Dry run mode
bughawk hunt --dry-run
```

### `bughawk analyze <issue-id>`

Analyze an issue without applying fixes.

```bash
# Basic analysis
bughawk analyze 12345

# Include detailed code context
bughawk analyze 12345 --verbose

# Output as JSON
bughawk analyze 12345 --json
```

### `bughawk list-issues`

List issues from Sentry.

```bash
# List recent issues
bughawk list-issues

# Filter by severity
bughawk list-issues --severity error,fatal

# Limit results
bughawk list-issues --limit 20

# Output as JSON
bughawk list-issues --json
```

### `bughawk status`

Check status of ongoing hunts.

```bash
bughawk status
```

### `bughawk config`

Manage configuration.

```bash
# Initialize configuration file
bughawk config init

# Show current configuration
bughawk config show

# Test API connections
bughawk config test

# Edit configuration
bughawk config edit
```

## ⚙️ Configuration Reference

### Configuration Priority

BugHawk loads configuration from multiple sources (highest to lowest priority):

1. **Command-line arguments**
2. **Environment variables** (prefixed with `BUGHAWK_`)
3. **`.bughawk.yml`** file
4. **Default values**

### Full Configuration Options

```yaml
# Monitor selection (sentry, datadog, rollbar, bugsnag)
monitor: sentry

# Sentry configuration
sentry:
  auth_token: ""          # Sentry API token
  org: ""                 # Organization slug
  projects: []            # List of project slugs
  base_url: "https://sentry.io/api/0"  # API base URL

# Datadog configuration
datadog:
  api_key: ""             # Datadog API key
  app_key: ""             # Datadog Application key
  site: "datadoghq.com"   # Datadog site (datadoghq.com, datadoghq.eu, etc.)
  service: ""             # Default service name
  env: ""                 # Default environment

# Rollbar configuration
rollbar:
  access_token: ""        # Rollbar access token
  account_slug: ""        # Account slug
  project_slug: ""        # Project slug

# Bugsnag configuration
bugsnag:
  auth_token: ""          # Bugsnag Personal Auth Token
  org_id: ""              # Organization ID
  project_id: ""          # Project ID

# Issue filters
filters:
  min_events: 1           # Minimum event count
  severity_levels:        # Severity levels to include
    - error
    - fatal
  max_age_days: 30        # Maximum issue age in days
  ignored_issues: []      # Issue IDs to ignore

# LLM configuration
llm:
  provider: openai        # openai, anthropic, azure, gemini, ollama, groq, mistral, cohere
  api_key: ""             # API key
  model: gpt-4            # Model name (auto-selected if not specified)
  max_tokens: 4096        # Maximum response tokens
  temperature: 0.1        # Temperature (0.0-2.0)

  # Azure OpenAI specific
  azure_endpoint: ""      # Azure OpenAI endpoint URL
  azure_deployment: ""    # Azure deployment name
  azure_api_version: "2024-02-15-preview"

  # Ollama specific (local models)
  ollama_base_url: "http://localhost:11434"

# Git configuration
git:
  provider: github        # github, gitlab, or bitbucket
  token: ""               # API token
  branch_prefix: "bughawk/fix-"  # Branch prefix
  auto_pr: false          # Auto-create PRs
  base_branch: main       # Base branch for PRs

# General settings
debug: false              # Enable debug logging
output_dir: .bughawk      # Output directory
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BUGHAWK_MONITOR` | Monitor platform (sentry/datadog/rollbar/bugsnag) |
| `BUGHAWK_SENTRY_AUTH_TOKEN` | Sentry API authentication token |
| `BUGHAWK_SENTRY_ORG` | Sentry organization slug |
| `BUGHAWK_SENTRY_PROJECTS` | Comma-separated project slugs |
| `BUGHAWK_DATADOG_API_KEY` | Datadog API key |
| `BUGHAWK_DATADOG_APP_KEY` | Datadog Application key |
| `BUGHAWK_DATADOG_SITE` | Datadog site (datadoghq.com, etc.) |
| `BUGHAWK_ROLLBAR_ACCESS_TOKEN` | Rollbar access token |
| `BUGHAWK_BUGSNAG_AUTH_TOKEN` | Bugsnag Personal Auth Token |
| `BUGHAWK_BUGSNAG_ORG_ID` | Bugsnag organization ID |
| `BUGHAWK_LLM_PROVIDER` | LLM provider (openai/anthropic/azure/gemini/ollama/groq/mistral/cohere) |
| `BUGHAWK_LLM_API_KEY` | LLM API key |
| `BUGHAWK_LLM_MODEL` | LLM model name |
| `BUGHAWK_GIT_PROVIDER` | Git provider (github/gitlab/bitbucket) |
| `BUGHAWK_GIT_TOKEN` | Git API token |
| `BUGHAWK_DEBUG` | Enable debug mode (true/false) |

## 🧪 Testing

BugHawk has comprehensive test coverage with **468+ tests** organized by feature groups:

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=bughawk --cov-report=html

# Run specific test file
pytest tests/test_orchestrator.py

# Run integration tests only
pytest tests/test_integration.py

# Run tests by feature
pytest tests/test_pr_creator.py      # GitHub, GitLab, Bitbucket PR tests
pytest tests/test_llm_client.py      # LLM provider tests
pytest tests/test_monitors.py        # Datadog, Rollbar, Bugsnag tests
pytest tests/test_config.py          # Configuration tests
```

### Test Coverage by Module

| Module | Test File | Tests |
|--------|-----------|-------|
| PR Creator | `test_pr_creator.py` | 82 |
| LLM Client | `test_llm_client.py` | 55 |
| Configuration | `test_config.py` | 51 |
| Error Monitors | `test_monitors.py` | 49 |
| Code Locator | `test_code_locator.py` | 38 |
| Fix Generator | `test_fix_generator.py` | 34 |
| Context Builder | `test_context_builder.py` | 28 |
| Validator | `test_validator.py` | 28 |
| Repo Manager | `test_repo_manager.py` | 27 |
| Orchestrator | `test_orchestrator.py` | 22 |
| Pattern Matcher | `test_pattern_matcher.py` | 21 |
| Sentry Client | `test_sentry_client.py` | 19 |
| Integration | `test_integration.py` | 14 |

## 📁 Project Structure

```
bughawk/
├── bughawk/
│   ├── analyzer/           # Code analysis modules
│   │   ├── code_locator.py     # File finding and context extraction
│   │   ├── context_builder.py  # Rich context building
│   │   └── pattern_matcher.py  # Error pattern matching
│   ├── core/              # Core functionality
│   │   ├── config.py          # Configuration management
│   │   ├── models.py          # Data models
│   │   └── orchestrator.py    # Main workflow orchestration
│   ├── fixer/             # Fix generation
│   │   ├── fix_generator.py   # Fix proposal generation
│   │   ├── llm_client.py      # LLM integration
│   │   └── validator.py       # Fix validation
│   ├── git/               # Git operations
│   │   ├── repo_manager.py    # Repository management
│   │   └── pr_creator.py      # PR creation
│   ├── monitors/          # Error monitoring integrations
│   │   ├── base.py            # Base monitor client interface
│   │   ├── sentry_monitor.py  # Sentry API client
│   │   ├── datadog_monitor.py # Datadog API client
│   │   ├── rollbar_monitor.py # Rollbar API client
│   │   └── bugsnag_monitor.py # Bugsnag API client
│   ├── sentry/            # Legacy Sentry integration
│   │   └── client.py          # Sentry API client (deprecated)
│   ├── utils/             # Utilities
│   │   └── logger.py          # Logging configuration
│   └── cli.py             # CLI entry point
├── tests/                 # Test suite
├── docs/                  # Documentation
├── .bughawk.yml           # Example configuration
└── pyproject.toml         # Project metadata
```

## 🔒 Security

- **Never commit credentials**: Use environment variables or secure secret management
- **Token permissions**: Use minimal required permissions for API tokens
- **Review before merge**: Always review auto-generated PRs before merging
- **Dry run first**: Use `--dry-run` to preview changes before applying

## 🤝 Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Sentry](https://sentry.io/), [Datadog](https://www.datadoghq.com/), [Rollbar](https://rollbar.com/), [Bugsnag](https://www.bugsnag.com/) for error tracking
- [OpenAI](https://openai.com/) for LLM capabilities
- [Click](https://click.palletsprojects.com/) for CLI framework
- [Rich](https://rich.readthedocs.io/) for beautiful terminal output
- [GitPython](https://gitpython.readthedocs.io/) for Git operations

---

**Built with 🦅 by developers who hate bugs as much as you do.**
