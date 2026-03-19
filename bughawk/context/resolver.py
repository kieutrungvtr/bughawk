"""Context Resolver - Facade for context resolution strategies.

This is the main entry point for resolving issue context.
It orchestrates multiple resolvers in priority order.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from bughawk.context.base import (
    BaseResolver,
    IssueContext,
    ResolverResult,
)
from bughawk.context.stacktrace_resolver import StacktraceResolver
from bughawk.context.codebase_resolver import CodebaseSearchResolver

logger = logging.getLogger(__name__)


class ContextResolver:
    """Main facade for resolving issue context.

    This class manages multiple resolution strategies and tries them
    in priority order until one succeeds.

    Resolution phases:
    1. StacktraceResolver - Extract from Sentry stacktrace (highest priority)
    2. CodebaseSearchResolver - Search codebase for error patterns (fallback)

    Usage:
        resolver = ContextResolver()
        result = resolver.resolve(issue, event, repo_path)
        if result.success:
            context = result.context
            # Use context for LLM analysis
    """

    def __init__(
        self,
        resolvers: Optional[list[BaseResolver]] = None,
        interactive: bool = False,
    ):
        """Initialize the context resolver.

        Args:
            resolvers: Optional list of resolvers to use. If None, uses defaults.
            interactive: If True, may prompt user for confirmation (future feature).
        """
        if resolvers is None:
            resolvers = [
                StacktraceResolver(),
                CodebaseSearchResolver(),
            ]

        # Sort by priority
        self.resolvers = sorted(resolvers, key=lambda r: r.priority)
        self.interactive = interactive
        self._last_result: Optional[ResolverResult] = None

    def resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
        repo_path: Path,
    ) -> ResolverResult:
        """Resolve context for an issue.

        Tries each resolver in priority order until one succeeds.

        Args:
            issue: The Sentry issue object
            event: The latest event data (may be None)
            repo_path: Path to the local repository

        Returns:
            ResolverResult with success/failure and context
        """
        errors = []

        for resolver in self.resolvers:
            logger.debug(
                "Trying resolver: %s (priority=%d)",
                resolver.name,
                resolver.priority,
            )

            # Check if resolver can handle this issue
            if not resolver.can_resolve(issue, event):
                logger.debug(
                    "Resolver %s cannot resolve this issue",
                    resolver.name,
                )
                continue

            # Try to resolve
            result = resolver.resolve(issue, event, repo_path)

            if result.success:
                logger.info(
                    "Context resolved by %s (confidence=%.0f%%)",
                    resolver.name,
                    result.context.confidence * 100 if result.context else 0,
                )
                self._last_result = result
                return result

            # Log failure and continue to next resolver
            logger.debug(
                "Resolver %s failed: %s",
                resolver.name,
                result.error,
            )
            errors.append(f"{resolver.name}: {result.error}")

        # All resolvers failed
        error_msg = "All resolvers failed:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.warning(error_msg)
        return ResolverResult.fail(error_msg)

    def resolve_with_fallback(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
        repo_path: Path,
        min_confidence: float = 0.3,
    ) -> ResolverResult:
        """Resolve context with confidence threshold.

        If the first successful result has low confidence,
        continues trying other resolvers for potentially better results.

        Args:
            issue: The Sentry issue object
            event: The latest event data
            repo_path: Path to the local repository
            min_confidence: Minimum confidence to accept without trying more resolvers

        Returns:
            Best ResolverResult based on confidence
        """
        best_result: Optional[ResolverResult] = None
        errors = []

        for resolver in self.resolvers:
            if not resolver.can_resolve(issue, event):
                continue

            result = resolver.resolve(issue, event, repo_path)

            if result.success:
                confidence = result.context.confidence if result.context else 0

                # If high confidence, return immediately
                if confidence >= min_confidence:
                    self._last_result = result
                    return result

                # Keep track of best result
                if best_result is None or (
                    result.context and best_result.context and
                    result.context.confidence > best_result.context.confidence
                ):
                    best_result = result
            else:
                errors.append(f"{resolver.name}: {result.error}")

        # Return best result if any
        if best_result:
            self._last_result = best_result
            return best_result

        # All failed
        error_msg = "All resolvers failed:\n" + "\n".join(f"  - {e}" for e in errors)
        return ResolverResult.fail(error_msg)

    @property
    def last_result(self) -> Optional[ResolverResult]:
        """Get the last resolution result."""
        return self._last_result

    def get_resolver(self, name: str) -> Optional[BaseResolver]:
        """Get a resolver by name."""
        for resolver in self.resolvers:
            if resolver.name == name:
                return resolver
        return None

    def add_resolver(self, resolver: BaseResolver) -> None:
        """Add a resolver and re-sort by priority."""
        self.resolvers.append(resolver)
        self.resolvers.sort(key=lambda r: r.priority)

    def get_resolution_summary(self) -> dict[str, Any]:
        """Get a summary of the last resolution attempt."""
        if not self._last_result:
            return {"status": "no_resolution"}

        result = self._last_result
        summary = {
            "success": result.success,
            "error": result.error,
        }

        if result.context:
            ctx = result.context
            summary.update({
                "source": ctx.source.value,
                "confidence": ctx.confidence,
                "method": ctx.resolution_method,
                "files_found": len(ctx.source_files),
                "primary_file": ctx.primary_file.path if ctx.primary_file else None,
                "error_line": ctx.error_line,
                "patterns_searched": ctx.search_patterns,
            })

        return summary


def create_context_resolver(
    include_codebase_search: bool = True,
    interactive: bool = False,
) -> ContextResolver:
    """Factory function to create a context resolver.

    Args:
        include_codebase_search: Whether to include codebase search resolver
        interactive: Whether to enable interactive mode

    Returns:
        Configured ContextResolver instance
    """
    resolvers = [StacktraceResolver()]

    if include_codebase_search:
        resolvers.append(CodebaseSearchResolver())

    return ContextResolver(resolvers=resolvers, interactive=interactive)
