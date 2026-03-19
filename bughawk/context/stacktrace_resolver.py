"""Phase 1: Stacktrace-based context resolver.

This resolver extracts context from Sentry stacktraces when available.
It's the primary and most reliable method for resolving issue context.
"""

import logging
from pathlib import Path
from typing import Any, Optional

from bughawk.context.base import (
    BaseResolver,
    ContextSource,
    IssueContext,
    ResolverResult,
    SourceFile,
)

logger = logging.getLogger(__name__)


class StacktraceResolver(BaseResolver):
    """Resolve context from Sentry exception stacktraces.

    This is Phase 1 - the standard flow when stacktrace is available.
    """

    @property
    def name(self) -> str:
        return "stacktrace"

    @property
    def priority(self) -> int:
        return 1  # Highest priority - try first

    def can_resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
    ) -> bool:
        """Check if event has exception stacktrace."""
        if not event:
            return False

        entries = event.get("entries", [])
        for entry in entries:
            if entry.get("type") == "exception":
                values = entry.get("data", {}).get("values", [])
                if values:
                    stacktrace = values[0].get("stacktrace", {})
                    frames = stacktrace.get("frames", [])
                    # Need at least one in-app frame
                    return any(f.get("inApp", False) for f in frames)

        return False

    def resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
        repo_path: Path,
    ) -> ResolverResult:
        """Extract context from stacktrace."""
        if not event:
            return ResolverResult.fail("No event data available")

        try:
            # Extract exception info
            entries = event.get("entries", [])
            exception_entry = None
            for entry in entries:
                if entry.get("type") == "exception":
                    exception_entry = entry
                    break

            if not exception_entry:
                return ResolverResult.fail("No exception entry in event")

            values = exception_entry.get("data", {}).get("values", [])
            if not values:
                return ResolverResult.fail("No exception values")

            exc = values[0]
            exception_type = exc.get("type", "Exception")
            exception_value = exc.get("value", "")
            stacktrace = exc.get("stacktrace", {})
            frames = stacktrace.get("frames", [])

            if not frames:
                return ResolverResult.fail("No stack frames")

            # Process frames - find in-app frames
            source_files: list[SourceFile] = []
            primary_file: Optional[SourceFile] = None
            error_line: Optional[int] = None

            # Process frames in reverse (most recent first)
            for i, frame in enumerate(reversed(frames)):
                if not frame.get("inApp", False):
                    continue

                filename = frame.get("filename", "")
                if not filename:
                    continue

                line_number = frame.get("lineNo", 1)
                function = frame.get("function", "<unknown>")
                context_line = frame.get("contextLine", "")
                pre_context = frame.get("preContext", [])
                post_context = frame.get("postContext", [])

                # Try to find actual file in repo
                abs_path = self._find_file(repo_path, filename)

                # Determine language from extension
                language = self._detect_language(filename)

                # Build code snippet
                snippet_content = self._build_snippet(
                    pre_context, context_line, post_context
                )
                start_line = line_number - len(pre_context)
                end_line = line_number + len(post_context)

                source_file = SourceFile(
                    path=filename,
                    absolute_path=abs_path,
                    language=language,
                    relevance_score=1.0 - (i * 0.1),  # Decrease relevance for older frames
                    match_reason=f"Stack frame in function `{function}()`",
                )

                source_file.add_snippet(
                    start_line=start_line,
                    end_line=end_line,
                    content=snippet_content,
                    highlight_line=line_number,
                )

                source_files.append(source_file)

                # First in-app frame is the primary file
                if primary_file is None:
                    primary_file = source_file
                    error_line = line_number

            if not source_files:
                return ResolverResult.fail("No in-app frames found")

            # Build context
            context = IssueContext(
                source=ContextSource.STACKTRACE,
                confidence=0.95,  # High confidence for stacktrace
                error_message=exception_value,
                error_type=exception_type,
                source_files=source_files,
                primary_file=primary_file,
                error_line=error_line,
                tags=self._extract_tags(event),
                environment=self._extract_environment(event),
                resolution_method="Extracted from Sentry exception stacktrace",
            )

            logger.info(
                "Resolved context from stacktrace: %d files, primary=%s",
                len(source_files),
                primary_file.path if primary_file else None,
            )

            return ResolverResult.ok(context)

        except Exception as e:
            logger.exception("Failed to resolve context from stacktrace")
            return ResolverResult.fail(f"Error extracting stacktrace: {e}")

    def _find_file(self, repo_path: Path, filename: str) -> Optional[Path]:
        """Try to find the actual file in the repository."""
        # Direct match
        direct = repo_path / filename
        if direct.exists():
            return direct

        # Search for file by name
        name = Path(filename).name
        for found in repo_path.rglob(name):
            if found.is_file():
                return found

        return None

    def _detect_language(self, filename: str) -> str:
        """Detect programming language from filename."""
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "jsx",
            ".tsx": "tsx",
            ".php": "php",
            ".rb": "ruby",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".kt": "kotlin",
            ".swift": "swift",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".c": "c",
            ".h": "c",
        }
        ext = Path(filename).suffix.lower()
        return ext_map.get(ext, "")

    def _build_snippet(
        self,
        pre_context: list[str],
        context_line: str,
        post_context: list[str],
    ) -> str:
        """Build a code snippet from context lines."""
        lines = []
        lines.extend(pre_context)
        lines.append(context_line)
        lines.extend(post_context)
        return "\n".join(lines)

    def _extract_tags(self, event: dict[str, Any]) -> dict[str, str]:
        """Extract tags from event."""
        tags = {}
        for tag in event.get("tags", []):
            if isinstance(tag, dict) and "key" in tag:
                tags[tag["key"]] = tag.get("value", "")
        return tags

    def _extract_environment(self, event: dict[str, Any]) -> dict[str, str]:
        """Extract environment info from event contexts."""
        env = {}
        contexts = event.get("contexts", {})

        # Runtime
        runtime = contexts.get("runtime", {})
        if runtime:
            env["runtime"] = runtime.get("runtime", runtime.get("name", ""))

        # OS
        os_ctx = contexts.get("os", {})
        if os_ctx:
            env["os"] = os_ctx.get("os", os_ctx.get("name", ""))

        # Server
        server = contexts.get("server_name") or event.get("server_name")
        if server:
            env["server"] = server

        return env
