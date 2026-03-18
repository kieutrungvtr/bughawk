"""Data models for BugHawk.

This module contains Pydantic models for representing Sentry issues,
stack traces, code context, and fix proposals.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class IssueSeverity(str, Enum):
    """Issue severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class IssueStatus(str, Enum):
    """Issue status values."""

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    IGNORED = "ignored"


class Issue(BaseModel):
    """Represents a bug/issue from Sentry."""

    id: str = Field(..., description="Unique issue identifier")
    title: str = Field(..., description="Issue title")
    culprit: str = Field(default="", description="Code location causing the issue")
    severity: IssueSeverity = Field(default=IssueSeverity.ERROR, description="Issue severity")
    status: IssueStatus = Field(default=IssueStatus.UNRESOLVED, description="Issue status")
    first_seen: datetime | None = Field(default=None, description="First occurrence timestamp")
    last_seen: datetime | None = Field(default=None, description="Last occurrence timestamp")
    count: int = Field(default=0, description="Number of occurrences")
    project: str = Field(default="", description="Project name")


class Event(BaseModel):
    """Represents a specific error event."""

    id: str = Field(..., description="Unique event identifier")
    issue_id: str = Field(..., description="Parent issue identifier")
    message: str = Field(default="", description="Error message")
    timestamp: datetime | None = Field(default=None, description="Event timestamp")
    stacktrace: str = Field(default="", description="Full stacktrace")
    tags: dict[str, str] = Field(default_factory=dict, description="Event tags")


class SentryIssue(BaseModel):
    """Represents an issue from Sentry.

    This model captures the essential information about an issue reported
    by Sentry, including occurrence counts, timestamps, and metadata.
    """

    id: str = Field(..., description="Unique Sentry issue identifier")
    title: str = Field(..., description="Issue title/summary")
    culprit: str = Field(default="", description="Code location causing the issue")
    level: IssueSeverity = Field(
        default=IssueSeverity.ERROR,
        description="Issue severity level (error, warning, fatal)",
    )
    count: int = Field(default=0, ge=0, description="Number of occurrences")
    first_seen: datetime | None = Field(
        default=None, description="Timestamp of first occurrence"
    )
    last_seen: datetime | None = Field(
        default=None, description="Timestamp of most recent occurrence"
    )
    status: IssueStatus = Field(
        default=IssueStatus.UNRESOLVED,
        description="Current issue status (unresolved, resolved, ignored)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional issue metadata from Sentry"
    )
    tags: dict[str, str] = Field(
        default_factory=dict, description="Issue tags for filtering and categorization"
    )


class StackFrame(BaseModel):
    """Individual frame in a stack trace.

    Represents a single frame in the call stack, including file location,
    function name, and surrounding code context.
    """

    filename: str = Field(..., description="Source file path")
    line_number: int = Field(..., ge=1, description="Line number in the source file")
    function: str = Field(default="<unknown>", description="Function or method name")
    context_line: str | None = Field(
        default=None, description="The actual line of code that was executing"
    )
    pre_context: list[str] = Field(
        default_factory=list,
        description="Lines of code before the context line",
    )
    post_context: list[str] = Field(
        default_factory=list,
        description="Lines of code after the context line",
    )
    in_app: bool = Field(
        default=True,
        description="Whether this frame is from application code (vs library code)",
    )


class StackTrace(BaseModel):
    """Represents a stack trace from an exception.

    Contains the list of stack frames and exception information
    that led to the error.
    """

    frames: list[StackFrame] = Field(
        default_factory=list,
        description="List of stack frames, ordered from caller to callee",
    )
    exception_type: str = Field(
        default="Exception", description="The type/class of the exception"
    )
    exception_value: str = Field(
        default="", description="The exception message or value"
    )


class CodeContext(BaseModel):
    """Code context for analysis.

    Provides the relevant source code and surrounding context
    needed to analyze and fix an error.
    """

    file_path: str = Field(..., description="Absolute or relative path to the source file")
    file_content: str = Field(default="", description="Full content of the source file")
    error_line: int | None = Field(
        default=None, ge=1, description="Line number where the error occurred"
    )
    error_column: int | None = Field(
        default=None, ge=0, description="Column number where the error occurred"
    )
    surrounding_lines: dict[int, str] = Field(
        default_factory=dict,
        description="Mapping of line numbers to their content around the error",
    )
    related_files: list[str] = Field(
        default_factory=list,
        description="List of related file paths that may be relevant to the error",
    )


class FixProposal(BaseModel):
    """Proposed fix for an issue.

    Contains the suggested code changes and metadata about
    the proposed fix for a specific issue.
    """

    issue_id: str = Field(..., description="ID of the issue this fix addresses")
    fix_description: str = Field(
        ..., description="Human-readable description of the proposed fix"
    )
    code_changes: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of file paths to their unified diff patches",
    )
    confidence_score: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score from 0 (low) to 1 (high)",
    )
    explanation: str = Field(
        default="",
        description="Detailed explanation of why this fix should work",
    )

    @field_validator("confidence_score")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        """Ensure confidence score is within valid range."""
        return max(0.0, min(1.0, v))
