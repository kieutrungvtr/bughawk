"""Unit tests for the CodeLocator module."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.analyzer.code_locator import (
    BinaryFileError,
    CodeLocator,
    CodeLocatorError,
    FileAccessError,
    FileNotFoundInRepoError,
    RepositoryCloneError,
)
from bughawk.core.models import CodeContext


class TestCodeLocatorInitialization:
    """Tests for CodeLocator initialization."""

    def test_default_initialization(self) -> None:
        """Test default initialization."""
        locator = CodeLocator()

        assert locator.temp_dir.exists()
        assert "bughawk" in str(locator.temp_dir)

    def test_custom_temp_dir(self, temp_dir: Path) -> None:
        """Test initialization with custom temp directory."""
        custom_dir = temp_dir / "custom_temp"
        locator = CodeLocator(temp_dir=custom_dir)

        assert locator.temp_dir == custom_dir
        assert locator.temp_dir.exists()


class TestCodeLocatorExceptions:
    """Tests for CodeLocator custom exceptions."""

    def test_repository_clone_error(self) -> None:
        """Test RepositoryCloneError exception."""
        error = RepositoryCloneError("https://github.com/test/repo.git", "Access denied")

        assert "test/repo" in str(error)
        assert "Access denied" in str(error)
        assert error.repo_url == "https://github.com/test/repo.git"

    def test_file_not_found_error(self, temp_dir: Path) -> None:
        """Test FileNotFoundInRepoError exception."""
        error = FileNotFoundInRepoError("missing.py", temp_dir)

        assert "missing.py" in str(error)
        assert error.filename == "missing.py"
        assert error.repo_path == temp_dir

    def test_binary_file_error(self, temp_dir: Path) -> None:
        """Test BinaryFileError exception."""
        binary_path = temp_dir / "image.png"
        error = BinaryFileError(binary_path)

        assert "image.png" in str(error)
        assert error.file_path == binary_path


class TestFindFileInRepo:
    """Tests for find_file_in_repo method."""

    def test_find_exact_match(self, temp_dir: Path) -> None:
        """Test finding file with exact path match."""
        # Create directory structure
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "utils.py").write_text("# utils")

        locator = CodeLocator()
        result = locator.find_file_in_repo(temp_dir, "src/utils.py")

        assert result is not None
        assert result.name == "utils.py"

    def test_find_by_filename_only(self, temp_dir: Path) -> None:
        """Test finding file by filename only."""
        # Create nested structure
        (temp_dir / "deep" / "nested" / "path").mkdir(parents=True)
        (temp_dir / "deep" / "nested" / "path" / "target.py").write_text("# target")

        locator = CodeLocator()
        result = locator.find_file_in_repo(temp_dir, "target.py")

        assert result is not None
        assert result.name == "target.py"

    def test_find_by_partial_path(self, temp_dir: Path) -> None:
        """Test finding file by partial path suffix."""
        # Create structure
        (temp_dir / "project" / "src" / "components").mkdir(parents=True)
        (temp_dir / "project" / "src" / "components" / "Button.tsx").write_text("// button")

        locator = CodeLocator()
        result = locator.find_file_in_repo(temp_dir, "components/Button.tsx")

        assert result is not None
        assert result.name == "Button.tsx"

    def test_find_with_fuzzy_matching(self, temp_dir: Path) -> None:
        """Test finding file with fuzzy matching."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "UserService.py").write_text("# service")

        locator = CodeLocator()
        # Typo in filename
        result = locator.find_file_in_repo(temp_dir, "src/userservice.py", use_fuzzy=True)

        # Fuzzy match should find it (case insensitive partial match)
        assert result is not None

    def test_find_nonexistent_file(self, temp_dir: Path) -> None:
        """Test finding file that doesn't exist."""
        locator = CodeLocator()
        result = locator.find_file_in_repo(temp_dir, "nonexistent.py")

        assert result is None

    def test_find_in_nonexistent_repo(self) -> None:
        """Test finding file in non-existent repository."""
        locator = CodeLocator()
        result = locator.find_file_in_repo(Path("/nonexistent/repo"), "file.py")

        assert result is None

    def test_skip_node_modules(self, temp_dir: Path) -> None:
        """Test that node_modules is skipped during search."""
        # Create file in node_modules
        (temp_dir / "node_modules" / "package").mkdir(parents=True)
        (temp_dir / "node_modules" / "package" / "index.js").write_text("// module")

        # Create same-named file in src
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "index.js").write_text("// app")

        locator = CodeLocator()
        result = locator.find_file_in_repo(temp_dir, "index.js")

        # Should find src version, not node_modules
        assert result is not None
        assert "node_modules" not in str(result)


class TestGetFileContent:
    """Tests for get_file_content method."""

    def test_get_full_content(self, temp_dir: Path) -> None:
        """Test getting full file content."""
        test_file = temp_dir / "test.py"
        content = "line 1\nline 2\nline 3\nline 4\nline 5"
        test_file.write_text(content)

        locator = CodeLocator()
        result = locator.get_file_content(test_file)

        assert result == content

    def test_get_line_range(self, temp_dir: Path) -> None:
        """Test getting specific line range."""
        test_file = temp_dir / "test.py"
        test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")

        locator = CodeLocator()
        result = locator.get_file_content(test_file, line_start=2, line_end=4)

        assert "line 2" in result
        assert "line 3" in result
        assert "line 4" in result
        assert "line 1" not in result
        assert "line 5" not in result

    def test_get_content_nonexistent_file(self, temp_dir: Path) -> None:
        """Test getting content from non-existent file."""
        locator = CodeLocator()

        with pytest.raises(FileAccessError):
            locator.get_file_content(temp_dir / "nonexistent.py")

    def test_get_content_binary_file(self, temp_dir: Path) -> None:
        """Test getting content from binary file."""
        binary_file = temp_dir / "binary.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\x04")

        locator = CodeLocator()

        with pytest.raises(BinaryFileError):
            locator.get_file_content(binary_file)


class TestGetSurroundingContext:
    """Tests for get_surrounding_context method."""

    def test_get_context_middle_of_file(self, temp_dir: Path) -> None:
        """Test getting context from middle of file."""
        test_file = temp_dir / "test.py"
        lines = [f"line {i}" for i in range(1, 101)]
        test_file.write_text("\n".join(lines))

        locator = CodeLocator()
        context = locator.get_surrounding_context(test_file, target_line=50, context_lines=5)

        assert 45 in context
        assert 50 in context
        assert 55 in context
        assert 40 not in context
        assert 60 not in context

    def test_get_context_start_of_file(self, temp_dir: Path) -> None:
        """Test getting context at start of file."""
        test_file = temp_dir / "test.py"
        lines = [f"line {i}" for i in range(1, 21)]
        test_file.write_text("\n".join(lines))

        locator = CodeLocator()
        context = locator.get_surrounding_context(test_file, target_line=1, context_lines=5)

        assert 1 in context
        assert 6 in context
        # Should not have negative line numbers
        assert all(k >= 1 for k in context.keys())

    def test_get_context_end_of_file(self, temp_dir: Path) -> None:
        """Test getting context at end of file."""
        test_file = temp_dir / "test.py"
        lines = [f"line {i}" for i in range(1, 21)]
        test_file.write_text("\n".join(lines))

        locator = CodeLocator()
        context = locator.get_surrounding_context(test_file, target_line=20, context_lines=5)

        assert 20 in context
        assert 15 in context
        # Should not exceed file length
        assert all(k <= 20 for k in context.keys())

    def test_get_context_empty_file(self, temp_dir: Path) -> None:
        """Test getting context from empty file."""
        test_file = temp_dir / "empty.py"
        test_file.write_text("")

        locator = CodeLocator()
        context = locator.get_surrounding_context(test_file, target_line=1, context_lines=5)

        assert context == {}


class TestBuildCodeContext:
    """Tests for build_code_context method."""

    def test_build_complete_context(self, temp_dir: Path) -> None:
        """Test building complete code context."""
        test_file = temp_dir / "service.py"
        content = '''def process_data(data):
    if data is None:
        raise ValueError("Data cannot be None")
    return data.process()

def main():
    process_data(None)
'''
        test_file.write_text(content)

        locator = CodeLocator()
        context = locator.build_code_context(
            test_file,
            error_line=3,
            context_lines=2,
        )

        assert isinstance(context, CodeContext)
        assert context.error_line == 3
        assert "ValueError" in context.file_content
        assert 3 in context.surrounding_lines


class TestFindRelatedFiles:
    """Tests for find_related_files method."""

    def test_find_files_in_same_directory(self, temp_dir: Path) -> None:
        """Test finding related files in same directory."""
        (temp_dir / "src").mkdir()
        (temp_dir / "src" / "main.py").write_text("# main")
        (temp_dir / "src" / "utils.py").write_text("# utils")
        (temp_dir / "src" / "helpers.py").write_text("# helpers")

        locator = CodeLocator()
        main_file = temp_dir / "src" / "main.py"
        related = locator.find_related_files(temp_dir, main_file)

        assert len(related) >= 2
        names = [f.name for f in related]
        assert "utils.py" in names
        assert "helpers.py" in names

    def test_max_files_limit(self, temp_dir: Path) -> None:
        """Test max files limit is respected."""
        (temp_dir / "src").mkdir()
        main_file = temp_dir / "src" / "main.py"
        main_file.write_text("# main")

        # Create many files
        for i in range(20):
            (temp_dir / "src" / f"file_{i}.py").write_text(f"# file {i}")

        locator = CodeLocator()
        related = locator.find_related_files(temp_dir, main_file, max_files=5)

        assert len(related) <= 5


class TestBinaryFileDetection:
    """Tests for binary file detection."""

    def test_detect_python_as_text(self, temp_dir: Path) -> None:
        """Test that Python files are detected as text."""
        py_file = temp_dir / "script.py"
        py_file.write_text("print('hello')")

        locator = CodeLocator()
        assert locator._is_binary_file(py_file) is False

    def test_detect_binary_with_null_bytes(self, temp_dir: Path) -> None:
        """Test that files with null bytes are detected as binary."""
        bin_file = temp_dir / "data.dat"
        bin_file.write_bytes(b"some\x00binary\x00data")

        locator = CodeLocator()
        assert locator._is_binary_file(bin_file) is True

    def test_detect_known_text_extensions(self, temp_dir: Path) -> None:
        """Test that known text extensions are detected correctly."""
        locator = CodeLocator()

        for ext in [".py", ".js", ".ts", ".json", ".yml", ".md"]:
            test_file = temp_dir / f"test{ext}"
            test_file.write_text("content")
            assert locator._is_binary_file(test_file) is False


class TestCleanup:
    """Tests for cleanup method."""

    def test_cleanup_specific_path(self, temp_dir: Path) -> None:
        """Test cleaning up a specific path."""
        target = temp_dir / "to_clean"
        target.mkdir()
        (target / "file.txt").write_text("content")

        locator = CodeLocator()
        locator.cleanup(target)

        assert not target.exists()

    def test_cleanup_file(self, temp_dir: Path) -> None:
        """Test cleaning up a single file."""
        target_file = temp_dir / "to_clean.txt"
        target_file.write_text("content")

        locator = CodeLocator()
        locator.cleanup(target_file)

        assert not target_file.exists()

    def test_cleanup_nonexistent_path(self, temp_dir: Path) -> None:
        """Test cleanup of non-existent path doesn't raise."""
        locator = CodeLocator()
        # Should not raise
        locator.cleanup(temp_dir / "nonexistent")


class TestValidateRepository:
    """Tests for validate_repository method."""

    def test_validate_git_repo(self, temp_repo: Path) -> None:
        """Test validating a git repository."""
        locator = CodeLocator()
        assert locator.validate_repository(temp_repo) is True

    def test_validate_non_git_directory(self, temp_dir: Path) -> None:
        """Test validating a non-git directory."""
        locator = CodeLocator()
        assert locator.validate_repository(temp_dir) is False

    def test_validate_nonexistent_path(self) -> None:
        """Test validating non-existent path."""
        locator = CodeLocator()
        assert locator.validate_repository(Path("/nonexistent")) is False


class TestCloneRepository:
    """Tests for clone_repository method."""

    @patch("bughawk.analyzer.code_locator.Repo")
    def test_clone_success(self, mock_repo_class: MagicMock, temp_dir: Path) -> None:
        """Test successful repository clone."""
        locator = CodeLocator(temp_dir=temp_dir)

        result = locator.clone_repository(
            "https://github.com/test/repo.git",
            branch="main",
        )

        assert result is not None
        mock_repo_class.clone_from.assert_called_once()

    @patch("bughawk.analyzer.code_locator.Repo")
    def test_clone_with_custom_target(
        self, mock_repo_class: MagicMock, temp_dir: Path
    ) -> None:
        """Test clone with custom target directory."""
        locator = CodeLocator(temp_dir=temp_dir)
        target = temp_dir / "custom_target"

        result = locator.clone_repository(
            "https://github.com/test/repo.git",
            target_dir=target,
        )

        assert result == target

    @patch("bughawk.analyzer.code_locator.Repo")
    def test_clone_failure(self, mock_repo_class: MagicMock, temp_dir: Path) -> None:
        """Test clone failure handling."""
        from git import GitCommandError

        mock_repo_class.clone_from.side_effect = GitCommandError(
            "clone", "Authentication failed"
        )

        locator = CodeLocator(temp_dir=temp_dir)

        with pytest.raises(RepositoryCloneError):
            locator.clone_repository("https://github.com/test/repo.git")


class TestExtractPythonImports:
    """Tests for Python import extraction."""

    def test_extract_simple_imports(self, temp_dir: Path) -> None:
        """Test extracting simple import statements."""
        py_file = temp_dir / "test.py"
        py_file.write_text("""import os
import sys
import json
""")

        locator = CodeLocator()
        imports = locator._extract_python_imports(py_file)

        assert "os" in imports
        assert "sys" in imports
        assert "json" in imports

    def test_extract_from_imports(self, temp_dir: Path) -> None:
        """Test extracting from...import statements."""
        py_file = temp_dir / "test.py"
        py_file.write_text("""from pathlib import Path
from typing import Dict, List
from mymodule import MyClass
""")

        locator = CodeLocator()
        imports = locator._extract_python_imports(py_file)

        assert "pathlib" in imports
        assert "typing" in imports
        assert "mymodule" in imports

    def test_extract_aliased_imports(self, temp_dir: Path) -> None:
        """Test extracting aliased imports."""
        py_file = temp_dir / "test.py"
        py_file.write_text("""import numpy as np
import pandas as pd
""")

        locator = CodeLocator()
        imports = locator._extract_python_imports(py_file)

        assert "numpy" in imports
        assert "pandas" in imports
