"""Context builder module for creating rich LLM analysis context.

This module provides functionality to build comprehensive code context
for LLM analysis, including stack traces, code context, git history,
and related files.
"""

import ast
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from git import InvalidGitRepositoryError, Repo
from git.exc import GitCommandError

from bughawk.analyzer.code_locator import CodeLocator
from bughawk.core.models import CodeContext, SentryIssue, StackFrame, StackTrace
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


# Data classes for git information


@dataclass
class GitBlameInfo:
    """Git blame information for a specific line."""

    line_number: int
    commit_hash: str
    author: str
    author_email: str
    timestamp: datetime | None
    commit_message: str
    original_line_number: int


@dataclass
class GitCommitInfo:
    """Git commit information."""

    hash: str
    short_hash: str
    author: str
    author_email: str
    timestamp: datetime | None
    message: str
    files_changed: list[str] = field(default_factory=list)


@dataclass
class EnrichedContext:
    """Enriched code context with git information."""

    code_context: CodeContext
    stack_trace: StackTrace | None
    blame_info: list[GitBlameInfo]
    recent_commits: list[GitCommitInfo]
    related_contexts: list[CodeContext]
    language: str
    repo_path: Path | None


class ContextBuilder:
    """Builds rich context for LLM analysis.

    This class orchestrates the gathering of all relevant information
    about an error, including source code, stack traces, git history,
    and related files.

    Example:
        >>> builder = ContextBuilder()
        >>> context = builder.build_context(issue, repo_path)
        >>> prompt = builder.build_llm_prompt(context, issue)
    """

    # Language detection by file extension
    LANGUAGE_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".php": "php",
        ".rb": "ruby",
        ".java": "java",
        ".go": "go",
        ".rs": "rust",
        ".cs": "csharp",
        ".cpp": "cpp",
        ".c": "c",
        ".swift": "swift",
        ".kt": "kotlin",
    }

    def __init__(self, code_locator: CodeLocator | None = None) -> None:
        """Initialize ContextBuilder.

        Args:
            code_locator: CodeLocator instance. Creates new one if not provided.
        """
        self.locator = code_locator or CodeLocator()
        logger.debug("ContextBuilder initialized")

    def build_context(
        self,
        issue: SentryIssue,
        repo_path: Path,
        context_lines: int = 50,
        include_git_info: bool = True,
    ) -> EnrichedContext:
        """Build comprehensive context for an issue.

        This method extracts stack trace information, locates source files,
        gathers code context, and enriches with git information.

        Args:
            issue: The Sentry issue to build context for
            repo_path: Path to the repository
            context_lines: Number of lines of context around error
            include_git_info: Whether to include git blame and history

        Returns:
            EnrichedContext with all gathered information
        """
        logger.info("Hawk building context for issue: %s", issue.id)

        repo_path = Path(repo_path)

        # Extract stack trace from issue metadata
        stack_trace = self._extract_stack_trace(issue)

        # Find the primary error location
        primary_frame = self._get_primary_frame(stack_trace)

        code_context: CodeContext | None = None
        blame_info: list[GitBlameInfo] = []
        recent_commits: list[GitCommitInfo] = []
        related_contexts: list[CodeContext] = []
        language = "unknown"

        if primary_frame:
            # Locate the file in the repository
            file_path = self.locator.find_file_in_repo(
                repo_path, primary_frame.filename
            )

            if file_path:
                logger.info("Hawk located primary error file: %s", file_path)
                language = self._detect_language(file_path)

                # Build code context
                try:
                    code_context = self.locator.build_code_context(
                        file_path,
                        primary_frame.line_number,
                        context_lines=context_lines,
                    )
                except Exception as e:
                    logger.warning("Failed to build code context: %s", e)

                # Get git information
                if include_git_info:
                    blame_info = self._get_git_blame(
                        repo_path,
                        file_path,
                        primary_frame.line_number,
                        context_lines=10,
                    )
                    recent_commits = self._get_recent_commits(
                        repo_path, file_path, max_commits=5
                    )

                # Find related files
                related_files = self.extract_related_files(
                    file_path, repo_path, max_depth=2
                )
                for related_path in related_files[:5]:  # Limit to 5 related files
                    try:
                        related_ctx = CodeContext(
                            file_path=str(related_path),
                            file_content=self.locator.get_file_content(related_path),
                        )
                        related_contexts.append(related_ctx)
                    except Exception as e:
                        logger.debug("Could not get related file content: %s", e)
            else:
                logger.warning(
                    "Hawk could not locate file: %s", primary_frame.filename
                )

        # Build fallback context if none found
        if code_context is None:
            code_context = CodeContext(
                file_path=primary_frame.filename if primary_frame else "unknown",
                file_content="",
                error_line=primary_frame.line_number if primary_frame else None,
            )

        return EnrichedContext(
            code_context=code_context,
            stack_trace=stack_trace,
            blame_info=blame_info,
            recent_commits=recent_commits,
            related_contexts=related_contexts,
            language=language,
            repo_path=repo_path,
        )

    def _extract_stack_trace(self, issue: SentryIssue) -> StackTrace | None:
        """Extract stack trace from Sentry issue metadata.

        Args:
            issue: The Sentry issue

        Returns:
            StackTrace object or None if not found
        """
        logger.debug("Extracting stack trace from issue: %s", issue.id)

        metadata = issue.metadata
        frames: list[StackFrame] = []

        # Try to extract from various metadata formats
        exception_data = metadata.get("exception", {})
        values = exception_data.get("values", [])

        if not values and "stacktrace" in metadata:
            # Alternative format
            values = [{"stacktrace": metadata["stacktrace"]}]

        for exc_value in values:
            stacktrace_data = exc_value.get("stacktrace", {})
            frame_list = stacktrace_data.get("frames", [])

            for frame_data in frame_list:
                frame = StackFrame(
                    filename=frame_data.get("filename", "unknown"),
                    line_number=frame_data.get("lineNo", frame_data.get("lineno", 1)),
                    function=frame_data.get("function", "<unknown>"),
                    context_line=frame_data.get("contextLine", frame_data.get("context_line")),
                    pre_context=frame_data.get("preContext", frame_data.get("pre_context", [])),
                    post_context=frame_data.get("postContext", frame_data.get("post_context", [])),
                    in_app=frame_data.get("inApp", frame_data.get("in_app", True)),
                )
                frames.append(frame)

            exception_type = exc_value.get("type", "Exception")
            exception_value = exc_value.get("value", "")

            if frames:
                return StackTrace(
                    frames=frames,
                    exception_type=exception_type,
                    exception_value=exception_value,
                )

        # Try parsing from issue title/culprit if no structured data
        if not frames and issue.culprit:
            # Parse culprit like "module.function in file.py"
            parts = issue.culprit.split(" in ")
            if len(parts) >= 2:
                function = parts[0]
                filename = parts[1]
                frames.append(
                    StackFrame(
                        filename=filename,
                        line_number=1,
                        function=function,
                        in_app=True,
                    )
                )

        if frames:
            # Extract exception info from title
            exception_type = "Exception"
            exception_value = issue.title

            # Try to parse "ExceptionType: message" format
            if ": " in issue.title:
                parts = issue.title.split(": ", 1)
                exception_type = parts[0]
                exception_value = parts[1] if len(parts) > 1 else ""

            return StackTrace(
                frames=frames,
                exception_type=exception_type,
                exception_value=exception_value,
            )

        logger.warning("No stack trace found in issue metadata")
        return None

    def _get_primary_frame(self, stack_trace: StackTrace | None) -> StackFrame | None:
        """Get the primary frame (most relevant in-app frame).

        Args:
            stack_trace: The stack trace

        Returns:
            The most relevant StackFrame or None
        """
        if not stack_trace or not stack_trace.frames:
            return None

        # Prefer the last in-app frame (most specific to user code)
        in_app_frames = [f for f in stack_trace.frames if f.in_app]

        if in_app_frames:
            return in_app_frames[-1]

        # Fall back to last frame
        return stack_trace.frames[-1]

    def _detect_language(self, file_path: Path) -> str:
        """Detect programming language from file extension.

        Args:
            file_path: Path to the file

        Returns:
            Language name string
        """
        suffix = file_path.suffix.lower()
        return self.LANGUAGE_MAP.get(suffix, "unknown")

    def _get_git_blame(
        self,
        repo_path: Path,
        file_path: Path,
        target_line: int,
        context_lines: int = 10,
    ) -> list[GitBlameInfo]:
        """Get git blame information around the error line.

        Args:
            repo_path: Path to repository
            file_path: Path to file
            target_line: Line number of the error
            context_lines: Number of lines around target to include

        Returns:
            List of GitBlameInfo objects
        """
        logger.debug("Hawk gathering git blame for %s:%d", file_path, target_line)
        blame_info: list[GitBlameInfo] = []

        try:
            repo = Repo(repo_path)

            # Calculate line range
            start_line = max(1, target_line - context_lines)
            end_line = target_line + context_lines

            # Get relative path from repo root
            try:
                rel_path = file_path.relative_to(repo_path)
            except ValueError:
                rel_path = file_path

            # Run git blame
            try:
                blame_result = repo.blame(
                    "HEAD",
                    str(rel_path),
                    L=f"{start_line},{end_line}",
                )
            except GitCommandError as e:
                logger.debug("Git blame failed: %s", e)
                return blame_info

            line_num = start_line
            for commit, lines in blame_result:
                for _line in lines:
                    try:
                        timestamp = datetime.fromtimestamp(commit.committed_date)
                    except (OSError, ValueError):
                        timestamp = None

                    blame_info.append(
                        GitBlameInfo(
                            line_number=line_num,
                            commit_hash=commit.hexsha,
                            author=commit.author.name,
                            author_email=commit.author.email,
                            timestamp=timestamp,
                            commit_message=commit.message.strip().split("\n")[0],
                            original_line_number=line_num,
                        )
                    )
                    line_num += 1

            logger.info("Hawk collected %d blame entries", len(blame_info))

        except InvalidGitRepositoryError:
            logger.warning("Not a valid git repository: %s", repo_path)
        except Exception as e:
            logger.warning("Failed to get git blame: %s", e)

        return blame_info

    def _get_recent_commits(
        self,
        repo_path: Path,
        file_path: Path,
        max_commits: int = 5,
    ) -> list[GitCommitInfo]:
        """Get recent commits that modified the file.

        Args:
            repo_path: Path to repository
            file_path: Path to file
            max_commits: Maximum number of commits to return

        Returns:
            List of GitCommitInfo objects
        """
        logger.debug("Hawk tracking recent commits for: %s", file_path)
        commits: list[GitCommitInfo] = []

        try:
            repo = Repo(repo_path)

            # Get relative path
            try:
                rel_path = file_path.relative_to(repo_path)
            except ValueError:
                rel_path = file_path

            # Get commits for this file
            for commit in repo.iter_commits(paths=str(rel_path), max_count=max_commits):
                try:
                    timestamp = datetime.fromtimestamp(commit.committed_date)
                except (OSError, ValueError):
                    timestamp = None

                # Get files changed in this commit
                files_changed: list[str] = []
                try:
                    if commit.parents:
                        diff = commit.diff(commit.parents[0])
                        files_changed = [d.a_path or d.b_path for d in diff if d.a_path or d.b_path]
                except Exception:
                    pass

                commits.append(
                    GitCommitInfo(
                        hash=commit.hexsha,
                        short_hash=commit.hexsha[:7],
                        author=commit.author.name,
                        author_email=commit.author.email,
                        timestamp=timestamp,
                        message=commit.message.strip(),
                        files_changed=files_changed[:10],  # Limit files
                    )
                )

            logger.info("Hawk found %d recent commits", len(commits))

        except InvalidGitRepositoryError:
            logger.warning("Not a valid git repository: %s", repo_path)
        except Exception as e:
            logger.warning("Failed to get commit history: %s", e)

        return commits

    def extract_related_files(
        self,
        file_path: Path,
        repo_path: Path,
        max_depth: int = 2,
        max_files: int = 20,
    ) -> list[Path]:
        """Extract files related to the given file.

        This analyzes imports and finds both:
        - Files that this file imports
        - Files that import this file

        Args:
            file_path: Path to the main file
            repo_path: Path to repository root
            max_depth: Maximum depth of import chain to follow
            max_files: Maximum number of files to return

        Returns:
            List of related file paths
        """
        logger.debug(
            "Hawk hunting for related files (depth=%d): %s", max_depth, file_path
        )

        file_path = Path(file_path)
        repo_path = Path(repo_path)
        related: set[Path] = set()
        processed: set[Path] = set()

        language = self._detect_language(file_path)

        def process_file(path: Path, depth: int) -> None:
            if depth > max_depth or path in processed or len(related) >= max_files:
                return

            processed.add(path)

            # Extract imports based on language
            imports = self._extract_imports(path, language)

            for imp in imports:
                # Try to resolve import to file
                resolved = self._resolve_import(imp, path, repo_path, language)
                if resolved and resolved not in related:
                    related.add(resolved)
                    if depth < max_depth:
                        process_file(resolved, depth + 1)

        # Process the main file
        process_file(file_path, 0)

        # Also find files that import this file
        reverse_imports = self._find_reverse_imports(file_path, repo_path, language)
        for rev_path in reverse_imports:
            if len(related) >= max_files:
                break
            related.add(rev_path)

        result = list(related)[:max_files]
        logger.info("Hawk found %d related files", len(result))
        return result

    def _extract_imports(self, file_path: Path, language: str) -> list[str]:
        """Extract imports from a file.

        Args:
            file_path: Path to the file
            language: Programming language

        Returns:
            List of import strings
        """
        if not file_path.exists():
            return []

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        if language == "python":
            return self._extract_python_imports_ast(content)
        elif language in ("javascript", "typescript"):
            return self._extract_js_imports(content)
        elif language == "php":
            return self._extract_php_imports(content)

        return []

    def _extract_python_imports_ast(self, content: str) -> list[str]:
        """Extract imports from Python code using AST.

        Args:
            content: Python source code

        Returns:
            List of imported module names
        """
        imports: list[str] = []

        try:
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imports.append(node.module)
                        # Also track specific imports for completeness
                        for alias in node.names:
                            if alias.name != "*":
                                imports.append(f"{node.module}.{alias.name}")
        except SyntaxError:
            # Fall back to regex parsing
            return self._extract_python_imports_regex(content)

        return imports

    def _extract_python_imports_regex(self, content: str) -> list[str]:
        """Extract imports from Python code using regex (fallback).

        Args:
            content: Python source code

        Returns:
            List of imported module names
        """
        imports: list[str] = []

        # Match: import foo, bar
        import_pattern = re.compile(r"^import\s+([\w\.,\s]+)", re.MULTILINE)
        for match in import_pattern.finditer(content):
            modules = match.group(1).split(",")
            for mod in modules:
                mod = mod.strip().split(" as ")[0].strip()
                if mod:
                    imports.append(mod)

        # Match: from foo import bar
        from_pattern = re.compile(r"^from\s+([\w\.]+)\s+import", re.MULTILINE)
        for match in from_pattern.finditer(content):
            imports.append(match.group(1))

        return imports

    def _extract_js_imports(self, content: str) -> list[str]:
        """Extract imports from JavaScript/TypeScript code.

        Args:
            content: JS/TS source code

        Returns:
            List of imported module paths
        """
        imports: list[str] = []

        # Match: import ... from 'module'
        import_pattern = re.compile(
            r"""(?:import|export)\s+.*?from\s+['"]([^'"]+)['"]""",
            re.MULTILINE,
        )
        for match in import_pattern.finditer(content):
            imports.append(match.group(1))

        # Match: require('module')
        require_pattern = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
        for match in require_pattern.finditer(content):
            imports.append(match.group(1))

        # Match: dynamic import('module')
        dynamic_pattern = re.compile(r"""import\s*\(\s*['"]([^'"]+)['"]\s*\)""")
        for match in dynamic_pattern.finditer(content):
            imports.append(match.group(1))

        return imports

    def _extract_php_imports(self, content: str) -> list[str]:
        """Extract imports from PHP code.

        Args:
            content: PHP source code

        Returns:
            List of imported class/namespace names
        """
        imports: list[str] = []

        # Match: use Namespace\Class;
        use_pattern = re.compile(r"use\s+([\w\\]+)(?:\s+as\s+\w+)?;", re.MULTILINE)
        for match in use_pattern.finditer(content):
            imports.append(match.group(1))

        # Match: require/include statements
        require_pattern = re.compile(
            r"""(?:require|include)(?:_once)?\s*(?:\(?\s*['"]([^'"]+)['"]\s*\)?)""",
            re.MULTILINE,
        )
        for match in require_pattern.finditer(content):
            imports.append(match.group(1))

        return imports

    def _resolve_import(
        self,
        import_path: str,
        source_file: Path,
        repo_path: Path,
        language: str,
    ) -> Path | None:
        """Resolve an import string to an actual file path.

        Args:
            import_path: The import string
            source_file: File containing the import
            repo_path: Repository root
            language: Programming language

        Returns:
            Resolved file path or None
        """
        if language == "python":
            # Convert module path to file path
            file_path = import_path.replace(".", "/") + ".py"
            # Also try as package __init__.py
            package_path = import_path.replace(".", "/") + "/__init__.py"

            found = self.locator.find_file_in_repo(repo_path, file_path, use_fuzzy=False)
            if found:
                return found

            found = self.locator.find_file_in_repo(repo_path, package_path, use_fuzzy=False)
            if found:
                return found

        elif language in ("javascript", "typescript"):
            # Handle relative imports
            if import_path.startswith("."):
                base_dir = source_file.parent
                resolved = (base_dir / import_path).resolve()

                # Try various extensions
                for ext in [".ts", ".tsx", ".js", ".jsx", "/index.ts", "/index.js"]:
                    test_path = Path(str(resolved) + ext)
                    if test_path.exists():
                        return test_path

                if resolved.exists():
                    return resolved
            else:
                # Node module - skip for now
                pass

        elif language == "php":
            # Handle PSR-4 style namespaces
            file_path = import_path.replace("\\", "/") + ".php"
            found = self.locator.find_file_in_repo(repo_path, file_path, use_fuzzy=False)
            if found:
                return found

        return None

    def _find_reverse_imports(
        self,
        file_path: Path,
        repo_path: Path,
        language: str,
        max_files: int = 10,
    ) -> list[Path]:
        """Find files that import the given file.

        Args:
            file_path: File to search for
            repo_path: Repository root
            language: Programming language
            max_files: Maximum files to return

        Returns:
            List of files that import the target file
        """
        reverse_imports: list[Path] = []

        # Get the module name for this file
        try:
            rel_path = file_path.relative_to(repo_path)
        except ValueError:
            return reverse_imports

        # Build search patterns based on language
        search_patterns: list[str] = []

        if language == "python":
            module_name = str(rel_path).replace("/", ".").replace(".py", "")
            search_patterns = [
                f"from {module_name}",
                f"import {module_name}",
            ]
        elif language in ("javascript", "typescript"):
            # Handle relative import patterns
            file_name = file_path.stem
            search_patterns = [
                f"from './{file_name}'",
                f"from './{file_name}.js'",
                f"from './{file_name}.ts'",
                f'require("./{file_name}")',
            ]
        elif language == "php":
            class_name = file_path.stem
            search_patterns = [
                f"use.*{class_name}",
            ]

        if not search_patterns:
            return reverse_imports

        # Search through repository files
        extensions = {".py"} if language == "python" else {".js", ".ts", ".jsx", ".tsx"} if language in ("javascript", "typescript") else {".php"}

        import os
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in CodeLocator.SKIP_DIRECTORIES]

            for filename in files:
                if len(reverse_imports) >= max_files:
                    break

                file_p = Path(root) / filename
                if file_p.suffix not in extensions or file_p == file_path:
                    continue

                try:
                    content = file_p.read_text(encoding="utf-8", errors="replace")
                    for pattern in search_patterns:
                        if pattern in content:
                            reverse_imports.append(file_p)
                            break
                except OSError:
                    continue

        return reverse_imports

    def build_llm_prompt(
        self,
        context: EnrichedContext,
        issue: SentryIssue,
        include_fix_request: bool = True,
    ) -> str:
        """Build a well-structured prompt for LLM analysis.

        Args:
            context: The enriched code context
            issue: The Sentry issue
            include_fix_request: Whether to request a fix in the prompt

        Returns:
            Formatted prompt string
        """
        logger.info("Hawk crafting LLM prompt for issue: %s", issue.id)

        sections: list[str] = []

        # Header with hawk hunting metaphor
        sections.append(self._build_header(issue))

        # Error summary
        sections.append(self._build_error_summary(issue, context))

        # Stack trace
        if context.stack_trace:
            sections.append(self._build_stack_trace_section(context.stack_trace))

        # Primary code context
        sections.append(self._build_code_section(context))

        # Git context
        if context.blame_info or context.recent_commits:
            sections.append(self._build_git_section(context))

        # Related files
        if context.related_contexts:
            sections.append(self._build_related_files_section(context))

        # Analysis request
        sections.append(self._build_analysis_request(include_fix_request))

        prompt = "\n\n".join(sections)
        logger.debug("Hawk crafted prompt with %d characters", len(prompt))
        return prompt

    def _build_header(self, issue: SentryIssue) -> str:
        """Build prompt header."""
        return f"""# BugHawk Analysis Request

You are assisting BugHawk, an automated bug hunting and fixing system.
A hawk has spotted prey (a bug) and needs your help analyzing it.

**Issue ID**: {issue.id}
**Occurrences**: {issue.count:,}
**Severity**: {issue.level.value if hasattr(issue.level, 'value') else issue.level}
**Status**: {issue.status.value if hasattr(issue.status, 'value') else issue.status}"""

    def _build_error_summary(
        self, issue: SentryIssue, context: EnrichedContext
    ) -> str:
        """Build error summary section."""
        lines = ["## Error Summary"]

        lines.append(f"\n**Title**: {issue.title}")
        lines.append(f"**Culprit**: {issue.culprit or 'Unknown'}")

        if context.stack_trace:
            lines.append(f"**Exception Type**: {context.stack_trace.exception_type}")
            lines.append(f"**Exception Message**: {context.stack_trace.exception_value}")

        lines.append(f"**Language**: {context.language.title()}")

        if issue.first_seen:
            lines.append(f"**First Seen**: {issue.first_seen.isoformat()}")
        if issue.last_seen:
            lines.append(f"**Last Seen**: {issue.last_seen.isoformat()}")

        return "\n".join(lines)

    def _build_stack_trace_section(self, stack_trace: StackTrace) -> str:
        """Build stack trace section."""
        lines = ["## Stack Trace"]
        lines.append("")
        lines.append(f"**{stack_trace.exception_type}**: {stack_trace.exception_value}")
        lines.append("")
        lines.append("```")

        for i, frame in enumerate(reversed(stack_trace.frames)):
            marker = " <-- ERROR" if i == 0 and frame.in_app else ""
            app_marker = "[APP]" if frame.in_app else "[LIB]"

            lines.append(
                f"{app_marker} File \"{frame.filename}\", line {frame.line_number}, "
                f"in {frame.function}{marker}"
            )

            if frame.context_line:
                lines.append(f"    {frame.context_line.strip()}")

        lines.append("```")
        return "\n".join(lines)

    def _build_code_section(self, context: EnrichedContext) -> str:
        """Build primary code context section."""
        lines = ["## Source Code Context"]
        lines.append("")
        lines.append(f"**File**: `{context.code_context.file_path}`")

        if context.code_context.error_line:
            lines.append(f"**Error Line**: {context.code_context.error_line}")

        lines.append("")

        if context.code_context.surrounding_lines:
            lines.append(f"```{context.language}")

            for line_num, content in sorted(context.code_context.surrounding_lines.items()):
                error_marker = ""
                if line_num == context.code_context.error_line:
                    error_marker = "  # <-- ERROR HERE"

                lines.append(f"{line_num:4d} | {content}{error_marker}")

            lines.append("```")
        elif context.code_context.file_content:
            # Show truncated file content
            content_lines = context.code_context.file_content.split("\n")[:100]
            lines.append(f"```{context.language}")
            for i, line in enumerate(content_lines, 1):
                lines.append(f"{i:4d} | {line}")
            if len(content_lines) == 100:
                lines.append("     | ... (truncated)")
            lines.append("```")
        else:
            lines.append("*No source code available*")

        return "\n".join(lines)

    def _build_git_section(self, context: EnrichedContext) -> str:
        """Build git history section."""
        lines = ["## Git History"]

        # Blame info for error line
        if context.blame_info:
            error_blame = None
            if context.code_context.error_line:
                for blame in context.blame_info:
                    if blame.line_number == context.code_context.error_line:
                        error_blame = blame
                        break

            if error_blame:
                lines.append("")
                lines.append("**Last modification to error line:**")
                lines.append(f"- **Author**: {error_blame.author} <{error_blame.author_email}>")
                if error_blame.timestamp:
                    lines.append(f"- **Date**: {error_blame.timestamp.isoformat()}")
                lines.append(f"- **Commit**: `{error_blame.commit_hash[:7]}`")
                lines.append(f"- **Message**: {error_blame.commit_message}")

        # Recent commits
        if context.recent_commits:
            lines.append("")
            lines.append("**Recent commits to this file:**")
            lines.append("")

            for commit in context.recent_commits[:5]:
                date_str = commit.timestamp.strftime("%Y-%m-%d") if commit.timestamp else "Unknown"
                first_line = commit.message.split("\n")[0][:60]
                lines.append(f"- `{commit.short_hash}` ({date_str}) - {first_line}")

        return "\n".join(lines)

    def _build_related_files_section(self, context: EnrichedContext) -> str:
        """Build related files section."""
        lines = ["## Related Files"]
        lines.append("")

        for related in context.related_contexts[:3]:  # Limit to 3 files in prompt
            lines.append(f"### `{related.file_path}`")
            lines.append("")

            if related.file_content:
                # Show first 50 lines
                content_lines = related.file_content.split("\n")[:50]
                lines.append(f"```{context.language}")
                for i, line in enumerate(content_lines, 1):
                    lines.append(f"{i:4d} | {line}")
                if len(content_lines) == 50:
                    lines.append("     | ... (truncated)")
                lines.append("```")
            else:
                lines.append("*Content not available*")

            lines.append("")

        return "\n".join(lines)

    def _build_analysis_request(self, include_fix_request: bool) -> str:
        """Build the analysis request section."""
        lines = ["## Analysis Request"]
        lines.append("")
        lines.append("Please analyze this error and provide:")
        lines.append("")
        lines.append("1. **Root Cause Analysis**: What is causing this error?")
        lines.append("2. **Impact Assessment**: How severe is this bug? What functionality is affected?")
        lines.append("3. **Related Code**: Are there related code paths that might have similar issues?")

        if include_fix_request:
            lines.append("")
            lines.append("4. **Proposed Fix**: Provide a code fix with:")
            lines.append("   - The specific file(s) to modify")
            lines.append("   - The exact changes needed (as a diff if possible)")
            lines.append("   - Any test cases that should be added")
            lines.append("")
            lines.append("5. **Confidence Score**: Rate your confidence in the fix from 0.0 to 1.0")

        lines.append("")
        lines.append("---")
        lines.append("*Hawk is watching and waiting for your expert analysis.*")

        return "\n".join(lines)
