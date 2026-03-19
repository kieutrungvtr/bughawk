"""Base classes and data models for context resolution."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class ContextSource(Enum):
    """Source of the resolved context."""

    STACKTRACE = "stacktrace"
    CODEBASE_SEARCH = "codebase_search"
    CULPRIT = "culprit"
    MANUAL = "manual"


@dataclass
class CodeSnippet:
    """A snippet of code with context."""

    file_path: str
    start_line: int
    end_line: int
    content: str
    highlight_line: Optional[int] = None  # The main line of interest

    @property
    def line_count(self) -> int:
        """Number of lines in the snippet."""
        return self.end_line - self.start_line + 1


@dataclass
class SourceFile:
    """Information about a source file related to the issue."""

    path: str  # Relative path in repo
    absolute_path: Optional[Path] = None  # Absolute path on disk
    language: Optional[str] = None
    snippets: list[CodeSnippet] = field(default_factory=list)
    relevance_score: float = 1.0  # 0.0 - 1.0, higher = more relevant
    match_reason: str = ""  # Why this file was matched

    def add_snippet(
        self,
        start_line: int,
        end_line: int,
        content: str,
        highlight_line: Optional[int] = None,
    ) -> CodeSnippet:
        """Add a code snippet to this file."""
        snippet = CodeSnippet(
            file_path=self.path,
            start_line=start_line,
            end_line=end_line,
            content=content,
            highlight_line=highlight_line,
        )
        self.snippets.append(snippet)
        return snippet


@dataclass
class IssueContext:
    """Unified context for an issue, regardless of source.

    This is the output of the context resolution process,
    providing all information needed for LLM to analyze and fix the issue.
    """

    # Source information
    source: ContextSource
    confidence: float  # 0.0 - 1.0, confidence in the resolved context

    # Error information
    error_message: str
    error_type: Optional[str] = None

    # Code context
    source_files: list[SourceFile] = field(default_factory=list)
    primary_file: Optional[SourceFile] = None  # The main file to fix
    error_line: Optional[int] = None  # Line number where error occurred

    # Additional context
    breadcrumbs: list[dict[str, Any]] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)

    # Resolution metadata
    resolution_method: str = ""  # Description of how context was resolved
    search_patterns: list[str] = field(default_factory=list)  # Patterns used for search

    @property
    def has_code_context(self) -> bool:
        """Check if we have any code context."""
        return bool(self.source_files)

    @property
    def has_primary_file(self) -> bool:
        """Check if we identified a primary file to fix."""
        return self.primary_file is not None

    def get_all_snippets(self) -> list[CodeSnippet]:
        """Get all code snippets from all source files."""
        snippets = []
        for sf in self.source_files:
            snippets.extend(sf.snippets)
        return snippets

    def to_llm_context(self) -> str:
        """Format context for LLM consumption."""
        parts = []

        # Error info
        parts.append(f"## Error Information")
        if self.error_type:
            parts.append(f"**Type:** {self.error_type}")
        parts.append(f"**Message:** {self.error_message}")
        parts.append("")

        # Primary file
        if self.primary_file:
            parts.append(f"## Primary File: {self.primary_file.path}")
            if self.error_line:
                parts.append(f"**Error Line:** {self.error_line}")
            parts.append(f"**Match Reason:** {self.primary_file.match_reason}")
            parts.append("")

            for snippet in self.primary_file.snippets:
                parts.append(f"```{self.primary_file.language or ''}")
                # Add line numbers
                lines = snippet.content.split('\n')
                for i, line in enumerate(lines):
                    line_num = snippet.start_line + i
                    marker = ">>> " if line_num == snippet.highlight_line else "    "
                    parts.append(f"{marker}{line_num}: {line}")
                parts.append("```")
                parts.append("")

        # Related files
        related = [sf for sf in self.source_files if sf != self.primary_file]
        if related:
            parts.append("## Related Files")
            for sf in related[:5]:  # Limit to 5 related files
                parts.append(f"### {sf.path}")
                parts.append(f"**Relevance:** {sf.relevance_score:.0%}")
                parts.append(f"**Reason:** {sf.match_reason}")
                for snippet in sf.snippets[:2]:  # Limit snippets per file
                    parts.append(f"```{sf.language or ''}")
                    parts.append(snippet.content)
                    parts.append("```")
                parts.append("")

        # Resolution info
        parts.append("## Context Resolution")
        parts.append(f"**Source:** {self.source.value}")
        parts.append(f"**Confidence:** {self.confidence:.0%}")
        parts.append(f"**Method:** {self.resolution_method}")

        return "\n".join(parts)


@dataclass
class ResolverResult:
    """Result from a resolver attempt."""

    success: bool
    context: Optional[IssueContext] = None
    error: Optional[str] = None

    @classmethod
    def ok(cls, context: IssueContext) -> "ResolverResult":
        """Create a successful result."""
        return cls(success=True, context=context)

    @classmethod
    def fail(cls, error: str) -> "ResolverResult":
        """Create a failed result."""
        return cls(success=False, error=error)


class BaseResolver(ABC):
    """Base class for context resolvers.

    Each resolver implements a specific strategy for extracting
    code context from issue information.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of this resolver."""
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        """Priority of this resolver (lower = tried first)."""
        pass

    @abstractmethod
    def can_resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
    ) -> bool:
        """Check if this resolver can handle the given issue.

        Args:
            issue: The Sentry issue object
            event: The latest event data (may be None)

        Returns:
            True if this resolver can attempt to resolve context
        """
        pass

    @abstractmethod
    def resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
        repo_path: Path,
    ) -> ResolverResult:
        """Attempt to resolve context for the issue.

        Args:
            issue: The Sentry issue object
            event: The latest event data
            repo_path: Path to the local repository

        Returns:
            ResolverResult with success/failure and context
        """
        pass
