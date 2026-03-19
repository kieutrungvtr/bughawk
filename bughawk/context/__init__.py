"""Context resolution module for BugHawk.

This module provides components for resolving issue context from various sources:
- Phase 1: StacktraceResolver - Extract context from Sentry stacktraces
- Phase 2: CodebaseSearchResolver - Search codebase when stacktrace is missing
"""

from bughawk.context.base import (
    IssueContext,
    SourceFile,
    CodeSnippet,
    BaseResolver,
    ResolverResult,
)
from bughawk.context.resolver import ContextResolver
from bughawk.context.stacktrace_resolver import StacktraceResolver
from bughawk.context.codebase_resolver import CodebaseSearchResolver

__all__ = [
    # Data models
    "IssueContext",
    "SourceFile",
    "CodeSnippet",
    "ResolverResult",
    # Resolvers
    "BaseResolver",
    "StacktraceResolver",
    "CodebaseSearchResolver",
    "ContextResolver",
]
