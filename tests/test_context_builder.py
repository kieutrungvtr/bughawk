"""Unit tests for the ContextBuilder module."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.analyzer.code_locator import CodeLocator
from bughawk.analyzer.context_builder import (
    ContextBuilder,
    EnrichedContext,
    GitBlameInfo,
    GitCommitInfo,
)
from bughawk.core.models import (
    CodeContext,
    IssueSeverity,
    IssueStatus,
    SentryIssue,
    StackFrame,
    StackTrace,
)


class TestGitBlameInfo:
    """Tests for GitBlameInfo dataclass."""

    def test_blame_info_creation(self) -> None:
        """Test creating GitBlameInfo."""
        now = datetime.now()
        blame = GitBlameInfo(
            line_number=42,
            commit_hash="abc123def456",
            author="Test Author",
            author_email="test@example.com",
            timestamp=now,
            commit_message="Fix bug in handler",
            original_line_number=42,
        )

        assert blame.line_number == 42
        assert blame.author == "Test Author"
        assert blame.commit_hash == "abc123def456"


class TestGitCommitInfo:
    """Tests for GitCommitInfo dataclass."""

    def test_commit_info_creation(self) -> None:
        """Test creating GitCommitInfo."""
        now = datetime.now()
        commit = GitCommitInfo(
            hash="abc123def456789",
            short_hash="abc123d",
            author="Test Author",
            author_email="test@example.com",
            timestamp=now,
            message="Add new feature\n\nDetailed description here.",
            files_changed=["src/main.py", "tests/test_main.py"],
        )

        assert commit.hash == "abc123def456789"
        assert commit.short_hash == "abc123d"
        assert len(commit.files_changed) == 2


class TestEnrichedContext:
    """Tests for EnrichedContext dataclass."""

    def test_enriched_context_creation(self) -> None:
        """Test creating EnrichedContext."""
        code_context = CodeContext(
            file_path="src/main.py",
            file_content="print('hello')",
            error_line=1,
        )

        context = EnrichedContext(
            code_context=code_context,
            stack_trace=None,
            blame_info=[],
            recent_commits=[],
            related_contexts=[],
            language="python",
            repo_path=Path("/tmp/repo"),
        )

        assert context.language == "python"
        assert context.code_context.file_path == "src/main.py"


class TestContextBuilderInitialization:
    """Tests for ContextBuilder initialization."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        builder = ContextBuilder()

        assert builder.locator is not None
        assert isinstance(builder.locator, CodeLocator)

    def test_custom_locator(self) -> None:
        """Test initialization with custom CodeLocator."""
        custom_locator = CodeLocator()
        builder = ContextBuilder(code_locator=custom_locator)

        assert builder.locator is custom_locator


class TestLanguageDetection:
    """Tests for language detection."""

    def test_detect_python(self) -> None:
        """Test detecting Python language."""
        builder = ContextBuilder()
        assert builder._detect_language(Path("test.py")) == "python"

    def test_detect_javascript(self) -> None:
        """Test detecting JavaScript language."""
        builder = ContextBuilder()
        assert builder._detect_language(Path("app.js")) == "javascript"
        assert builder._detect_language(Path("component.jsx")) == "javascript"

    def test_detect_typescript(self) -> None:
        """Test detecting TypeScript language."""
        builder = ContextBuilder()
        assert builder._detect_language(Path("service.ts")) == "typescript"
        assert builder._detect_language(Path("Component.tsx")) == "typescript"

    def test_detect_unknown(self) -> None:
        """Test detecting unknown language."""
        builder = ContextBuilder()
        assert builder._detect_language(Path("file.xyz")) == "unknown"


class TestExtractStackTrace:
    """Tests for stack trace extraction."""

    def test_extract_from_metadata(self) -> None:
        """Test extracting stack trace from issue metadata."""
        issue = SentryIssue(
            id="12345",
            title="TypeError: Cannot read property 'map' of undefined",
            level=IssueSeverity.ERROR,
            count=10,
            metadata={
                "exception": {
                    "values": [
                        {
                            "type": "TypeError",
                            "value": "Cannot read property 'map' of undefined",
                            "stacktrace": {
                                "frames": [
                                    {
                                        "filename": "src/components/List.tsx",
                                        "lineNo": 42,
                                        "function": "List",
                                        "inApp": True,
                                        "contextLine": "  items.map(item => ...)",
                                    }
                                ]
                            },
                        }
                    ]
                }
            },
        )

        builder = ContextBuilder()
        stack_trace = builder._extract_stack_trace(issue)

        assert stack_trace is not None
        assert stack_trace.exception_type == "TypeError"
        assert len(stack_trace.frames) == 1
        assert stack_trace.frames[0].filename == "src/components/List.tsx"

    def test_extract_from_culprit(self) -> None:
        """Test extracting stack trace from culprit when no metadata."""
        issue = SentryIssue(
            id="12345",
            title="ValueError: Invalid input",
            culprit="process_data in src/handlers/data.py",
            level=IssueSeverity.ERROR,
            count=10,
            metadata={},
        )

        builder = ContextBuilder()
        stack_trace = builder._extract_stack_trace(issue)

        assert stack_trace is not None
        assert len(stack_trace.frames) == 1
        assert stack_trace.frames[0].function == "process_data"

    def test_extract_empty_metadata(self) -> None:
        """Test extraction with empty metadata."""
        issue = SentryIssue(
            id="12345",
            title="Unknown Error",
            level=IssueSeverity.ERROR,
            count=10,
            metadata={},
        )

        builder = ContextBuilder()
        stack_trace = builder._extract_stack_trace(issue)

        assert stack_trace is None


class TestGetPrimaryFrame:
    """Tests for get_primary_frame method."""

    def test_get_in_app_frame(self) -> None:
        """Test getting in-app frame as primary."""
        stack_trace = StackTrace(
            frames=[
                StackFrame(
                    filename="node_modules/react/index.js",
                    line_number=100,
                    function="render",
                    in_app=False,
                ),
                StackFrame(
                    filename="src/App.tsx",
                    line_number=42,
                    function="App",
                    in_app=True,
                ),
            ],
            exception_type="Error",
            exception_value="Something went wrong",
        )

        builder = ContextBuilder()
        primary = builder._get_primary_frame(stack_trace)

        assert primary is not None
        assert primary.filename == "src/App.tsx"
        assert primary.in_app is True

    def test_get_last_frame_when_no_in_app(self) -> None:
        """Test falling back to last frame when no in-app frames."""
        stack_trace = StackTrace(
            frames=[
                StackFrame(
                    filename="lib/module.py",
                    line_number=10,
                    function="func1",
                    in_app=False,
                ),
                StackFrame(
                    filename="lib/other.py",
                    line_number=20,
                    function="func2",
                    in_app=False,
                ),
            ],
            exception_type="Error",
            exception_value="Error",
        )

        builder = ContextBuilder()
        primary = builder._get_primary_frame(stack_trace)

        assert primary is not None
        assert primary.filename == "lib/other.py"

    def test_get_none_for_empty_trace(self) -> None:
        """Test returning None for empty stack trace."""
        builder = ContextBuilder()

        assert builder._get_primary_frame(None) is None
        assert builder._get_primary_frame(StackTrace(frames=[])) is None


class TestExtractImports:
    """Tests for import extraction methods."""

    def test_extract_python_imports_ast(self) -> None:
        """Test Python import extraction using AST."""
        content = """import os
import sys
from pathlib import Path
from typing import Dict, List
from mymodule.submodule import MyClass
"""

        builder = ContextBuilder()
        imports = builder._extract_python_imports_ast(content)

        assert "os" in imports
        assert "sys" in imports
        assert "pathlib" in imports
        assert "typing" in imports
        assert "mymodule.submodule" in imports

    def test_extract_python_imports_regex_fallback(self) -> None:
        """Test Python import extraction with regex fallback."""
        # Intentionally invalid syntax that would fail AST parsing
        content = """import os
from pathlib import Path
# This is valid but let's test regex
import json
"""

        builder = ContextBuilder()
        imports = builder._extract_python_imports_regex(content)

        assert "os" in imports
        assert "pathlib" in imports
        assert "json" in imports

    def test_extract_js_imports(self) -> None:
        """Test JavaScript/TypeScript import extraction."""
        content = """import React from 'react';
import { useState, useEffect } from 'react';
import MyComponent from './components/MyComponent';
const utils = require('./utils');
import('./dynamic-module').then(mod => {});
export { something } from './other';
"""

        builder = ContextBuilder()
        imports = builder._extract_js_imports(content)

        assert "react" in imports
        assert "./components/MyComponent" in imports
        assert "./utils" in imports
        assert "./dynamic-module" in imports
        assert "./other" in imports

    def test_extract_php_imports(self) -> None:
        """Test PHP import extraction."""
        content = """<?php
use App\\Services\\UserService;
use App\\Models\\User as UserModel;
require_once 'vendor/autoload.php';
include 'config.php';
"""

        builder = ContextBuilder()
        imports = builder._extract_php_imports(content)

        assert "App\\Services\\UserService" in imports
        assert "vendor/autoload.php" in imports
        assert "config.php" in imports


class TestBuildContext:
    """Tests for build_context method."""

    @patch.object(CodeLocator, "find_file_in_repo")
    @patch.object(CodeLocator, "build_code_context")
    @patch.object(CodeLocator, "get_file_content")
    def test_build_context_success(
        self,
        mock_get_content: MagicMock,
        mock_build_context: MagicMock,
        mock_find_file: MagicMock,
        temp_dir: Path,
        sample_sentry_issue: SentryIssue,
    ) -> None:
        """Test successful context building."""
        # Setup mocks
        mock_find_file.return_value = temp_dir / "src" / "UserList.tsx"
        mock_build_context.return_value = CodeContext(
            file_path="src/UserList.tsx",
            file_content="const items = users.map(...)",
            error_line=45,
            surrounding_lines={44: "// comment", 45: "const items = users.map(...)", 46: "return items;"},
        )
        mock_get_content.return_value = "// related file content"

        builder = ContextBuilder()

        # Update issue with stack trace metadata
        sample_sentry_issue.metadata = {
            "exception": {
                "values": [
                    {
                        "type": "TypeError",
                        "value": "Cannot read property 'map' of undefined",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "src/UserList.tsx",
                                    "lineNo": 45,
                                    "function": "UserList",
                                    "inApp": True,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        context = builder.build_context(
            sample_sentry_issue,
            temp_dir,
            include_git_info=False,
        )

        assert isinstance(context, EnrichedContext)
        assert context.code_context.error_line == 45
        assert context.language == "typescript"

    def test_build_context_file_not_found(
        self,
        temp_dir: Path,
        sample_sentry_issue: SentryIssue,
    ) -> None:
        """Test context building when file not found."""
        builder = ContextBuilder()

        # Issue with stack trace but file won't be found
        sample_sentry_issue.metadata = {
            "exception": {
                "values": [
                    {
                        "type": "Error",
                        "value": "Error",
                        "stacktrace": {
                            "frames": [
                                {
                                    "filename": "nonexistent.py",
                                    "lineNo": 1,
                                    "function": "func",
                                    "inApp": True,
                                }
                            ]
                        },
                    }
                ]
            }
        }

        context = builder.build_context(
            sample_sentry_issue,
            temp_dir,
            include_git_info=False,
        )

        # Should return context with empty file content
        assert context.code_context.file_content == ""


class TestBuildLLMPrompt:
    """Tests for build_llm_prompt method."""

    def test_build_prompt_with_all_sections(
        self, sample_sentry_issue: SentryIssue
    ) -> None:
        """Test building prompt with all sections."""
        code_context = CodeContext(
            file_path="src/UserList.tsx",
            file_content="const items = users.map(u => <Item user={u} />);",
            error_line=15,
            surrounding_lines={
                14: "const UserList = ({ users }) => {",
                15: "  const items = users.map(u => <Item user={u} />);",
                16: "  return <ul>{items}</ul>;",
            },
        )

        stack_trace = StackTrace(
            frames=[
                StackFrame(
                    filename="src/UserList.tsx",
                    line_number=15,
                    function="UserList",
                    context_line="const items = users.map(u => <Item user={u} />);",
                    in_app=True,
                )
            ],
            exception_type="TypeError",
            exception_value="Cannot read property 'map' of undefined",
        )

        context = EnrichedContext(
            code_context=code_context,
            stack_trace=stack_trace,
            blame_info=[],
            recent_commits=[],
            related_contexts=[],
            language="typescript",
            repo_path=Path("/tmp/repo"),
        )

        builder = ContextBuilder()
        prompt = builder.build_llm_prompt(context, sample_sentry_issue)

        # Check key sections exist
        assert "BugHawk Analysis Request" in prompt
        assert "Error Summary" in prompt
        assert "Stack Trace" in prompt
        assert "Source Code Context" in prompt
        assert "Analysis Request" in prompt
        assert "TypeError" in prompt
        assert "UserList.tsx" in prompt

    def test_build_prompt_without_fix_request(
        self, sample_sentry_issue: SentryIssue
    ) -> None:
        """Test building prompt without fix request."""
        code_context = CodeContext(
            file_path="main.py",
            file_content="print('hello')",
        )

        context = EnrichedContext(
            code_context=code_context,
            stack_trace=None,
            blame_info=[],
            recent_commits=[],
            related_contexts=[],
            language="python",
            repo_path=None,
        )

        builder = ContextBuilder()
        prompt = builder.build_llm_prompt(
            context, sample_sentry_issue, include_fix_request=False
        )

        assert "Proposed Fix" not in prompt
        assert "Confidence Score" not in prompt

    def test_build_prompt_with_git_info(
        self, sample_sentry_issue: SentryIssue
    ) -> None:
        """Test building prompt with git information."""
        code_context = CodeContext(
            file_path="service.py",
            file_content="def process(): pass",
            error_line=1,
        )

        now = datetime.now()
        blame_info = [
            GitBlameInfo(
                line_number=1,
                commit_hash="abc123def",
                author="Developer",
                author_email="dev@example.com",
                timestamp=now,
                commit_message="Add process function",
                original_line_number=1,
            )
        ]

        recent_commits = [
            GitCommitInfo(
                hash="abc123def456",
                short_hash="abc123d",
                author="Developer",
                author_email="dev@example.com",
                timestamp=now,
                message="Add process function",
                files_changed=["service.py"],
            )
        ]

        context = EnrichedContext(
            code_context=code_context,
            stack_trace=None,
            blame_info=blame_info,
            recent_commits=recent_commits,
            related_contexts=[],
            language="python",
            repo_path=Path("/tmp/repo"),
        )

        builder = ContextBuilder()
        prompt = builder.build_llm_prompt(context, sample_sentry_issue)

        assert "Git History" in prompt
        assert "Developer" in prompt
        assert "abc123d" in prompt


class TestResolveImport:
    """Tests for import resolution."""

    def test_resolve_python_module(self, temp_dir: Path) -> None:
        """Test resolving Python module imports."""
        # Create module file
        (temp_dir / "mypackage").mkdir()
        (temp_dir / "mypackage" / "module.py").write_text("# module")

        builder = ContextBuilder()
        result = builder._resolve_import(
            "mypackage.module",
            temp_dir / "main.py",
            temp_dir,
            "python",
        )

        assert result is not None
        assert result.name == "module.py"

    def test_resolve_python_package(self, temp_dir: Path) -> None:
        """Test resolving Python package imports."""
        # Create package with __init__.py
        (temp_dir / "mypackage").mkdir()
        (temp_dir / "mypackage" / "__init__.py").write_text("# init")

        builder = ContextBuilder()
        result = builder._resolve_import(
            "mypackage",
            temp_dir / "main.py",
            temp_dir,
            "python",
        )

        assert result is not None
        assert result.name == "__init__.py"

    def test_resolve_js_relative_import(self, temp_dir: Path) -> None:
        """Test resolving JavaScript relative imports."""
        # Create files
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "utils.ts").write_text("// utils")
        (temp_dir / "src" / "main.ts").write_text("// main")

        builder = ContextBuilder()
        result = builder._resolve_import(
            "./utils",
            temp_dir / "src" / "main.ts",
            temp_dir,
            "typescript",
        )

        assert result is not None
        assert result.name == "utils.ts"


class TestFindReverseImports:
    """Tests for finding files that import a given file."""

    def test_find_python_reverse_imports(self, temp_dir: Path) -> None:
        """Test finding Python files that import target."""
        (temp_dir / "mymodule.py").write_text("def func(): pass")
        (temp_dir / "main.py").write_text("from mymodule import func\nfunc()")
        (temp_dir / "other.py").write_text("import mymodule\nmymodule.func()")
        (temp_dir / "unrelated.py").write_text("print('hello')")

        builder = ContextBuilder()
        reverse = builder._find_reverse_imports(
            temp_dir / "mymodule.py",
            temp_dir,
            "python",
        )

        names = [f.name for f in reverse]
        assert "main.py" in names
        assert "other.py" in names
        assert "unrelated.py" not in names
