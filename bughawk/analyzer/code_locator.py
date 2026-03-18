"""Code locator module for finding and extracting code context.

This module provides functionality to locate source code files in repositories,
clone repositories, and extract relevant code context for error analysis.
"""

import mimetypes
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from git import GitCommandError, InvalidGitRepositoryError, Repo
from git.exc import GitError
from thefuzz import fuzz, process

from bughawk.core.models import CodeContext
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


# Custom Exceptions


class CodeLocatorError(Exception):
    """Base exception for code locator errors."""

    pass


class RepositoryCloneError(CodeLocatorError):
    """Raised when repository cloning fails."""

    def __init__(self, repo_url: str, message: str) -> None:
        self.repo_url = repo_url
        super().__init__(f"Failed to clone '{repo_url}': {message}")


class FileNotFoundInRepoError(CodeLocatorError):
    """Raised when a file cannot be found in the repository."""

    def __init__(self, filename: str, repo_path: Path) -> None:
        self.filename = filename
        self.repo_path = repo_path
        super().__init__(f"File '{filename}' not found in repository '{repo_path}'")


class FileAccessError(CodeLocatorError):
    """Raised when file access fails due to permissions or other issues."""

    pass


class BinaryFileError(CodeLocatorError):
    """Raised when attempting to read a binary file as text."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        super().__init__(f"Cannot read binary file as text: {file_path}")


class CodeLocator:
    """Locates and extracts code context from repositories.

    This class provides methods for cloning repositories, finding files,
    and extracting code context with surrounding lines for error analysis.

    Example:
        >>> locator = CodeLocator()
        >>> repo_path = locator.clone_repository(
        ...     "https://github.com/user/repo.git",
        ...     branch="main"
        ... )
        >>> file_path = locator.find_file_in_repo(repo_path, "utils.py")
        >>> context = locator.get_surrounding_context(file_path, 42, context_lines=10)
    """

    # File extensions that are typically text-based source code
    TEXT_EXTENSIONS = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".r",
        ".R",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".yml",
        ".yaml",
        ".json",
        ".xml",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".md",
        ".txt",
        ".rst",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".gitignore",
        ".dockerignore",
        "Dockerfile",
        "Makefile",
        ".vue",
        ".svelte",
    }

    # Directories to skip when searching for files
    SKIP_DIRECTORIES = {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "env",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".idea",
        ".vscode",
        "vendor",
        "bower_components",
    }

    # Minimum fuzzy match score to consider a match valid
    FUZZY_MATCH_THRESHOLD = 60

    def __init__(self, temp_dir: Path | None = None) -> None:
        """Initialize CodeLocator.

        Args:
            temp_dir: Directory for temporary files. Uses system temp if not provided.
        """
        self.temp_dir = temp_dir or Path(tempfile.gettempdir()) / "bughawk"
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("CodeLocator initialized with temp_dir: %s", self.temp_dir)

    def clone_repository(
        self,
        repo_url: str,
        branch: str = "main",
        target_dir: Path | None = None,
        depth: int | None = 1,
    ) -> Path:
        """Clone a Git repository.

        Args:
            repo_url: URL of the repository to clone
            branch: Branch to checkout (default: "main")
            target_dir: Directory to clone into. Creates temp dir if not provided.
            depth: Clone depth for shallow clones. None for full clone.

        Returns:
            Path to the cloned repository

        Raises:
            RepositoryCloneError: If cloning fails
        """
        logger.info("Hawk swooping on repository: %s (branch: %s)", repo_url, branch)

        # Determine target directory
        if target_dir is None:
            # Create a unique directory name based on repo URL
            repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
            target_dir = self.temp_dir / f"{repo_name}_{os.urandom(4).hex()}"

        target_dir = Path(target_dir)

        # Clean up if directory exists
        if target_dir.exists():
            logger.debug("Cleaning existing directory: %s", target_dir)
            try:
                shutil.rmtree(target_dir)
            except PermissionError as e:
                logger.error("Permission denied cleaning directory: %s", e)
                raise RepositoryCloneError(repo_url, f"Permission denied: {e}") from e

        try:
            logger.debug("Cloning to: %s", target_dir)

            clone_kwargs: dict[str, Any] = {
                "branch": branch,
            }
            if depth is not None:
                clone_kwargs["depth"] = depth

            Repo.clone_from(repo_url, target_dir, **clone_kwargs)

            logger.info("Hawk captured repository successfully at: %s", target_dir)
            return target_dir

        except GitCommandError as e:
            logger.error("Git command failed during clone: %s", e.stderr)
            raise RepositoryCloneError(repo_url, str(e.stderr)) from e
        except GitError as e:
            logger.error("Git error during clone: %s", str(e))
            raise RepositoryCloneError(repo_url, str(e)) from e
        except PermissionError as e:
            logger.error("Permission denied during clone: %s", e)
            raise RepositoryCloneError(repo_url, f"Permission denied: {e}") from e
        except OSError as e:
            logger.error("OS error during clone: %s", e)
            raise RepositoryCloneError(repo_url, str(e)) from e

    def find_file_in_repo(
        self,
        repo_path: Path,
        filename: str,
        use_fuzzy: bool = True,
    ) -> Path | None:
        """Find a file in a repository.

        This method handles various cases:
        - Exact filename matches
        - Partial path matches (e.g., "src/utils.py" matches "myproject/src/utils.py")
        - Fuzzy matching for close matches

        Args:
            repo_path: Path to the repository root
            filename: Filename or partial path to find
            use_fuzzy: Whether to use fuzzy matching if exact match not found

        Returns:
            Path to the found file, or None if not found

        Raises:
            FileNotFoundInRepoError: If file cannot be found (when use_fuzzy is False)
        """
        logger.debug("Hawk hunting for file: %s in %s", filename, repo_path)

        repo_path = Path(repo_path)
        if not repo_path.exists():
            logger.error("Repository path does not exist: %s", repo_path)
            return None

        # Normalize the search filename
        search_name = filename.replace("\\", "/")

        # Collect all files in repository
        all_files: list[Path] = []
        for root, dirs, files in os.walk(repo_path):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in self.SKIP_DIRECTORIES]

            for file in files:
                file_path = Path(root) / file
                all_files.append(file_path)

        if not all_files:
            logger.warning("No files found in repository: %s", repo_path)
            return None

        # Create relative paths for matching
        relative_paths = {
            str(f.relative_to(repo_path)).replace("\\", "/"): f for f in all_files
        }

        # Strategy 1: Exact match on relative path
        if search_name in relative_paths:
            match = relative_paths[search_name]
            logger.info("Hawk found exact match: %s", match)
            return match

        # Strategy 2: Match by filename only
        base_name = Path(search_name).name
        name_matches = [
            (rel_path, abs_path)
            for rel_path, abs_path in relative_paths.items()
            if Path(rel_path).name == base_name
        ]

        if len(name_matches) == 1:
            match = name_matches[0][1]
            logger.info("Hawk found unique filename match: %s", match)
            return match

        # Strategy 3: Match by path suffix
        suffix_matches = [
            (rel_path, abs_path)
            for rel_path, abs_path in relative_paths.items()
            if rel_path.endswith(search_name)
        ]

        if len(suffix_matches) == 1:
            match = suffix_matches[0][1]
            logger.info("Hawk found suffix match: %s", match)
            return match
        elif suffix_matches:
            # Multiple suffix matches - pick the shortest path (most specific)
            match = min(suffix_matches, key=lambda x: len(x[0]))[1]
            logger.info(
                "Hawk found best suffix match among %d candidates: %s",
                len(suffix_matches),
                match,
            )
            return match

        # Strategy 4: If multiple filename matches, prefer in-app paths
        if name_matches:
            # Sort by path depth (shallower = more likely in-app)
            sorted_matches = sorted(name_matches, key=lambda x: x[0].count("/"))
            match = sorted_matches[0][1]
            logger.info(
                "Hawk selected from %d filename matches: %s",
                len(name_matches),
                match,
            )
            return match

        # Strategy 5: Fuzzy matching
        if use_fuzzy and relative_paths:
            logger.debug("Attempting fuzzy match for: %s", search_name)

            # Try fuzzy matching on full paths
            fuzzy_result = process.extractOne(
                search_name,
                list(relative_paths.keys()),
                scorer=fuzz.partial_ratio,
            )

            if fuzzy_result and fuzzy_result[1] >= self.FUZZY_MATCH_THRESHOLD:
                matched_path = fuzzy_result[0]
                match = relative_paths[matched_path]
                logger.info(
                    "Hawk found fuzzy match (score=%d): %s -> %s",
                    fuzzy_result[1],
                    search_name,
                    match,
                )
                return match

            # Try fuzzy matching on basenames only
            basename_map = {Path(p).name: p for p in relative_paths.keys()}
            fuzzy_basename = process.extractOne(
                base_name,
                list(basename_map.keys()),
                scorer=fuzz.ratio,
            )

            if fuzzy_basename and fuzzy_basename[1] >= self.FUZZY_MATCH_THRESHOLD:
                matched_basename = fuzzy_basename[0]
                matched_rel_path = basename_map[matched_basename]
                match = relative_paths[matched_rel_path]
                logger.info(
                    "Hawk found fuzzy basename match (score=%d): %s -> %s",
                    fuzzy_basename[1],
                    base_name,
                    match,
                )
                return match

        logger.warning("Hawk could not locate file: %s", filename)
        return None

    def get_file_content(
        self,
        file_path: Path,
        line_start: int = 1,
        line_end: int | None = None,
    ) -> str:
        """Get content from a file within a line range.

        Args:
            file_path: Path to the file
            line_start: Starting line number (1-indexed)
            line_end: Ending line number (inclusive). None for end of file.

        Returns:
            File content within the specified range

        Raises:
            FileAccessError: If file cannot be read
            BinaryFileError: If file is binary
        """
        file_path = Path(file_path)
        logger.debug(
            "Hawk extracting content from %s (lines %d-%s)",
            file_path,
            line_start,
            line_end or "end",
        )

        if not file_path.exists():
            logger.error("File does not exist: %s", file_path)
            raise FileAccessError(f"File not found: {file_path}")

        # Check if file is binary
        if self._is_binary_file(file_path):
            raise BinaryFileError(file_path)

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except PermissionError as e:
            logger.error("Permission denied reading file: %s", file_path)
            raise FileAccessError(f"Permission denied: {file_path}") from e
        except OSError as e:
            logger.error("OS error reading file: %s - %s", file_path, e)
            raise FileAccessError(f"Cannot read file: {file_path}") from e

        # Adjust to 0-indexed
        start_idx = max(0, line_start - 1)
        end_idx = line_end if line_end else len(lines)

        selected_lines = lines[start_idx:end_idx]
        content = "".join(selected_lines)

        logger.debug(
            "Hawk extracted %d lines (%d chars) from %s",
            len(selected_lines),
            len(content),
            file_path,
        )
        return content

    def get_surrounding_context(
        self,
        file_path: Path,
        target_line: int,
        context_lines: int = 50,
    ) -> dict[int, str]:
        """Get code context surrounding a target line.

        Args:
            file_path: Path to the file
            target_line: The line number to center context around (1-indexed)
            context_lines: Number of lines to include before and after target

        Returns:
            Dictionary mapping line numbers to their content.
            The target line is included with surrounding context.

        Raises:
            FileAccessError: If file cannot be read
            BinaryFileError: If file is binary
        """
        file_path = Path(file_path)
        logger.debug(
            "Hawk gathering context around line %d in %s (context=%d)",
            target_line,
            file_path,
            context_lines,
        )

        if not file_path.exists():
            logger.error("File does not exist: %s", file_path)
            raise FileAccessError(f"File not found: {file_path}")

        if self._is_binary_file(file_path):
            raise BinaryFileError(file_path)

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except PermissionError as e:
            logger.error("Permission denied reading file: %s", file_path)
            raise FileAccessError(f"Permission denied: {file_path}") from e
        except OSError as e:
            logger.error("OS error reading file: %s - %s", file_path, e)
            raise FileAccessError(f"Cannot read file: {file_path}") from e

        total_lines = len(lines)
        if total_lines == 0:
            logger.warning("File is empty: %s", file_path)
            return {}

        # Calculate context range
        start_line = max(1, target_line - context_lines)
        end_line = min(total_lines, target_line + context_lines)

        # Build context dictionary
        context: dict[int, str] = {}
        for line_num in range(start_line, end_line + 1):
            idx = line_num - 1  # Convert to 0-indexed
            if 0 <= idx < len(lines):
                # Remove trailing newline but preserve other whitespace
                context[line_num] = lines[idx].rstrip("\n\r")

        logger.info(
            "Hawk collected context: lines %d-%d (%d lines) from %s",
            start_line,
            end_line,
            len(context),
            file_path,
        )
        return context

    def build_code_context(
        self,
        file_path: Path,
        error_line: int,
        error_column: int | None = None,
        context_lines: int = 50,
        related_files: list[str] | None = None,
    ) -> CodeContext:
        """Build a complete CodeContext object for analysis.

        Args:
            file_path: Path to the source file
            error_line: Line number where the error occurred
            error_column: Column number where the error occurred (optional)
            context_lines: Number of lines of context to include
            related_files: List of related file paths

        Returns:
            CodeContext object with all relevant information

        Raises:
            FileAccessError: If file cannot be read
            BinaryFileError: If file is binary
        """
        file_path = Path(file_path)
        logger.info("Hawk building code context for %s:%d", file_path, error_line)

        # Get full file content
        file_content = self.get_file_content(file_path)

        # Get surrounding context
        surrounding = self.get_surrounding_context(file_path, error_line, context_lines)

        return CodeContext(
            file_path=str(file_path),
            file_content=file_content,
            error_line=error_line,
            error_column=error_column,
            surrounding_lines=surrounding,
            related_files=related_files or [],
        )

    def find_related_files(
        self,
        repo_path: Path,
        main_file: Path,
        max_files: int = 10,
    ) -> list[Path]:
        """Find files that might be related to the main file.

        This uses heuristics like:
        - Same directory
        - Import statements
        - Similar naming patterns

        Args:
            repo_path: Path to repository root
            main_file: The main file to find related files for
            max_files: Maximum number of related files to return

        Returns:
            List of paths to potentially related files
        """
        logger.debug("Hawk searching for files related to: %s", main_file)

        main_file = Path(main_file)
        repo_path = Path(repo_path)
        related: list[Path] = []

        # Get files in same directory
        main_dir = main_file.parent
        if main_dir.exists():
            for sibling in main_dir.iterdir():
                if sibling.is_file() and sibling != main_file:
                    if sibling.suffix in self.TEXT_EXTENSIONS or sibling.suffix == main_file.suffix:
                        related.append(sibling)

        # Parse imports if Python file
        if main_file.suffix == ".py" and main_file.exists():
            try:
                imports = self._extract_python_imports(main_file)
                for imp in imports:
                    # Convert import to potential file path
                    imp_path = imp.replace(".", "/") + ".py"
                    found = self.find_file_in_repo(repo_path, imp_path, use_fuzzy=False)
                    if found and found not in related:
                        related.append(found)
            except Exception as e:
                logger.debug("Could not parse imports: %s", e)

        # Limit results
        result = related[:max_files]
        logger.info("Hawk found %d related files", len(result))
        return result

    def _is_binary_file(self, file_path: Path) -> bool:
        """Check if a file is binary.

        Args:
            file_path: Path to the file

        Returns:
            True if file appears to be binary
        """
        # Check by extension first
        if file_path.suffix.lower() in self.TEXT_EXTENSIONS:
            return False

        # Check by name (for files without extensions)
        if file_path.name in {"Dockerfile", "Makefile", "Jenkinsfile"}:
            return False

        # Check MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type and mime_type.startswith("text/"):
            return False

        # Read first chunk and check for binary characters
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(8192)
                # Check for null bytes (common in binary files)
                if b"\x00" in chunk:
                    return True
                # Try to decode as UTF-8
                try:
                    chunk.decode("utf-8")
                    return False
                except UnicodeDecodeError:
                    return True
        except OSError:
            return True

        return False

    def _extract_python_imports(self, file_path: Path) -> list[str]:
        """Extract import statements from a Python file.

        Args:
            file_path: Path to the Python file

        Returns:
            List of imported module names
        """
        imports: list[str] = []

        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("import "):
                        # Handle: import foo, bar, baz
                        parts = line[7:].split(",")
                        for part in parts:
                            module = part.strip().split(" ")[0]  # Handle 'as' aliases
                            if module and not module.startswith("."):
                                imports.append(module)
                    elif line.startswith("from "):
                        # Handle: from foo.bar import baz
                        parts = line[5:].split(" import ")
                        if parts:
                            module = parts[0].strip()
                            if module and not module.startswith("."):
                                imports.append(module)
        except OSError:
            pass

        return imports

    def cleanup(self, path: Path | None = None) -> None:
        """Clean up temporary files.

        Args:
            path: Specific path to clean up. If None, cleans entire temp directory.
        """
        target = path or self.temp_dir
        target = Path(target)

        if target.exists():
            logger.debug("Hawk cleaning up: %s", target)
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                logger.info("Hawk cleaned up: %s", target)
            except PermissionError as e:
                logger.warning("Permission denied during cleanup: %s", e)
            except OSError as e:
                logger.warning("OS error during cleanup: %s", e)

    def validate_repository(self, repo_path: Path) -> bool:
        """Validate that a path is a valid Git repository.

        Args:
            repo_path: Path to check

        Returns:
            True if path is a valid Git repository
        """
        try:
            Repo(repo_path)
            return True
        except InvalidGitRepositoryError:
            return False
        except Exception:
            return False
