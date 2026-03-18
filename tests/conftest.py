"""Pytest configuration and shared fixtures for BugHawk tests."""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator
from unittest.mock import MagicMock, patch

import pytest

from bughawk.core.config import (
    BugHawkConfig,
    FilterConfig,
    GitConfig,
    GitProvider,
    LLMConfig,
    LLMProvider,
    SentryConfig,
    Settings,
    Severity,
)
from bughawk.core.models import (
    CodeContext,
    FixProposal,
    IssueSeverity,
    IssueStatus,
    SentryIssue,
    StackFrame,
    StackTrace,
)


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def mock_settings() -> Settings:
    """Create mock settings for SentryClient."""
    return Settings(
        sentry_auth_token="test-token-12345",
        sentry_org="test-org",
        sentry_project="test-project",
    )


@pytest.fixture
def mock_config() -> BugHawkConfig:
    """Create a complete mock configuration."""
    return BugHawkConfig(
        sentry=SentryConfig(
            auth_token="test-sentry-token",
            org="test-org",
            projects=["test-project"],
            base_url="https://sentry.io/api/0",
        ),
        filters=FilterConfig(
            min_events=1,
            severity_levels=[Severity.ERROR, Severity.FATAL],
            max_age_days=30,
            ignored_issues=[],
        ),
        llm=LLMConfig(
            provider=LLMProvider.OPENAI,
            api_key="test-openai-key",
            model="gpt-4",
            max_tokens=4096,
            temperature=0.1,
        ),
        git=GitConfig(
            provider=GitProvider.GITHUB,
            token="test-github-token",
            branch_prefix="bughawk/fix-",
            auto_pr=True,
            base_branch="main",
        ),
        debug=False,
        output_dir=Path(".bughawk"),
    )


# =============================================================================
# Model Fixtures
# =============================================================================


@pytest.fixture
def sample_sentry_issue() -> SentryIssue:
    """Create a sample Sentry issue for testing."""
    return SentryIssue(
        id="12345",
        title="TypeError: Cannot read property 'map' of undefined",
        culprit="src/components/UserList.tsx in UserList",
        level=IssueSeverity.ERROR,
        count=42,
        first_seen=datetime(2024, 1, 1, 10, 0, 0),
        last_seen=datetime(2024, 1, 15, 14, 30, 0),
        status=IssueStatus.UNRESOLVED,
        metadata={
            "url": "https://sentry.io/issues/12345/",
            "repository": "https://github.com/test-org/test-repo.git",
        },
        tags={
            "environment": "production",
            "browser": "Chrome",
        },
    )


@pytest.fixture
def sample_stack_trace() -> StackTrace:
    """Create a sample stack trace for testing."""
    return StackTrace(
        frames=[
            StackFrame(
                filename="node_modules/react/index.js",
                line_number=123,
                function="renderComponent",
                in_app=False,
            ),
            StackFrame(
                filename="src/components/UserList.tsx",
                line_number=45,
                function="UserList",
                context_line="    const items = users.map(u => <UserItem user={u} />);",
                pre_context=[
                    "  const UserList = ({ users }) => {",
                    "    // Render user list",
                ],
                post_context=[
                    "    return <ul>{items}</ul>;",
                    "  };",
                ],
                in_app=True,
            ),
        ],
        exception_type="TypeError",
        exception_value="Cannot read property 'map' of undefined",
    )


@pytest.fixture
def sample_code_context() -> CodeContext:
    """Create a sample code context for testing."""
    file_content = '''import React from 'react';
import { UserItem } from './UserItem';

interface User {
  id: string;
  name: string;
}

interface Props {
  users: User[];
}

const UserList = ({ users }) => {
  // Render user list
  const items = users.map(u => <UserItem user={u} />);
  return <ul>{items}</ul>;
};

export default UserList;
'''
    return CodeContext(
        file_path="src/components/UserList.tsx",
        file_content=file_content,
        error_line=15,
        surrounding_lines={
            13: "const UserList = ({ users }) => {",
            14: "  // Render user list",
            15: "  const items = users.map(u => <UserItem user={u} />);",
            16: "  return <ul>{items}</ul>;",
            17: "};",
        },
        related_files=["src/components/UserItem.tsx"],
    )


@pytest.fixture
def sample_fix_proposal() -> FixProposal:
    """Create a sample fix proposal for testing."""
    return FixProposal(
        issue_id="12345",
        fix_description="Add null check before calling map on users array",
        code_changes={
            "src/components/UserList.tsx": """--- a/src/components/UserList.tsx
+++ b/src/components/UserList.tsx
@@ -12,7 +12,7 @@ interface Props {

 const UserList = ({ users }) => {
   // Render user list
-  const items = users.map(u => <UserItem user={u} />);
+  const items = (users || []).map(u => <UserItem user={u} />);
   return <ul>{items}</ul>;
 };
""",
        },
        confidence_score=0.85,
        explanation="The error occurs because 'users' is undefined when the component renders. "
        "Adding a fallback empty array ensures map() is always called on a valid array.",
    )


# =============================================================================
# Temporary Directory Fixtures
# =============================================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_repo(temp_dir: Path) -> Generator[Path, None, None]:
    """Create a temporary Git repository for testing."""
    import subprocess

    repo_path = temp_dir / "test-repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        capture_output=True,
    )

    # Create initial files
    (repo_path / "src").mkdir()
    (repo_path / "src" / "app.py").write_text(
        '''def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
'''
    )

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        capture_output=True,
    )

    yield repo_path


# =============================================================================
# Mock API Response Fixtures
# =============================================================================


@pytest.fixture
def mock_sentry_issues_response() -> list:
    """Create mock Sentry API issues response."""
    return [
        {
            "id": "12345",
            "title": "TypeError: Cannot read property 'map' of undefined",
            "culprit": "src/components/UserList.tsx in UserList",
            "level": "error",
            "status": "unresolved",
            "count": 42,
            "firstSeen": "2024-01-01T10:00:00Z",
            "lastSeen": "2024-01-15T14:30:00Z",
            "metadata": {},
        },
        {
            "id": "12346",
            "title": "NullPointerException in UserService",
            "culprit": "com.app.UserService.getUser",
            "level": "error",
            "status": "unresolved",
            "count": 15,
            "firstSeen": "2024-01-10T08:00:00Z",
            "lastSeen": "2024-01-14T16:00:00Z",
            "metadata": {},
        },
    ]


@pytest.fixture
def mock_sentry_event_response() -> dict:
    """Create mock Sentry API event response."""
    return {
        "eventID": "event-abc123",
        "message": "TypeError: Cannot read property 'map' of undefined",
        "dateCreated": "2024-01-15T14:30:00Z",
        "tags": [
            {"key": "environment", "value": "production"},
            {"key": "browser", "value": "Chrome"},
        ],
        "entries": [
            {
                "type": "exception",
                "data": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "Cannot read property 'map' of undefined",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "src/components/UserList.tsx",
                                        "lineNo": 15,
                                        "function": "UserList",
                                        "inApp": True,
                                        "contextLine": "  const items = users.map(u => <UserItem user={u} />);",
                                        "preContext": [
                                            "const UserList = ({ users }) => {",
                                            "  // Render user list",
                                        ],
                                        "postContext": [
                                            "  return <ul>{items}</ul>;",
                                            "};",
                                        ],
                                    }
                                ]
                            },
                        }
                    ]
                },
            }
        ],
    }


@pytest.fixture
def mock_llm_response() -> str:
    """Create mock LLM fix response."""
    return """Based on the error analysis, the issue is that `users` is undefined when the component renders.

## Fix

Add a null check or default value for the users array:

```typescript
const items = (users || []).map(u => <UserItem user={u} />);
```

## Explanation

The TypeError occurs because `users.map()` is called when `users` is undefined.
By providing a fallback empty array `(users || [])`, we ensure that `map()` is
always called on a valid array, preventing the error.

## Confidence: 0.85

This is a common pattern for handling potentially undefined arrays in React components.
"""


# =============================================================================
# Environment Fixtures
# =============================================================================


@pytest.fixture
def clean_env() -> Generator[None, None, None]:
    """Temporarily clear BugHawk environment variables."""
    original_env = {}
    bughawk_vars = [key for key in os.environ if key.startswith("BUGHAWK_")]

    for var in bughawk_vars:
        original_env[var] = os.environ.pop(var)

    yield

    os.environ.update(original_env)


# =============================================================================
# Pattern Fixtures
# =============================================================================


@pytest.fixture
def sample_patterns() -> list:
    """Create sample error patterns for testing."""
    return [
        {
            "id": "null-pointer",
            "name": "Null Pointer / Undefined Access",
            "category": "null_reference",
            "languages": ["javascript", "typescript", "python", "java"],
            "exception_types": [
                "TypeError",
                "NullPointerException",
                "AttributeError",
            ],
            "message_patterns": [
                r"Cannot read propert.*of (undefined|null)",
                r"'NoneType' object has no attribute",
                r"null pointer",
            ],
            "common_causes": [
                "Accessing property on undefined/null variable",
                "Missing null check before method call",
                "Async data not loaded yet",
            ],
            "typical_fixes": [
                "Add null/undefined check before access",
                "Use optional chaining (?.) operator",
                "Provide default values",
            ],
        },
        {
            "id": "key-error",
            "name": "Dictionary Key Error",
            "category": "key_error",
            "languages": ["python"],
            "exception_types": ["KeyError"],
            "message_patterns": [r"KeyError: '.*'"],
            "common_causes": [
                "Accessing non-existent dictionary key",
                "Typo in key name",
            ],
            "typical_fixes": [
                "Use dict.get() with default value",
                "Check if key exists before access",
            ],
        },
    ]
