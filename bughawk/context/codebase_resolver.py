"""Phase 2: Codebase search-based context resolver.

This resolver searches the codebase when stacktrace is not available.
It extracts keywords from the error message and searches for matching code.
"""

import logging
import re
import subprocess
from dataclasses import dataclass
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


@dataclass
class SearchMatch:
    """A search match in the codebase."""

    file_path: Path
    line_number: int
    line_content: str
    pattern: str
    relevance_score: float = 1.0


class CodebaseSearchResolver(BaseResolver):
    """Resolve context by searching the codebase.

    This is Phase 2 - fallback when stacktrace is not available.
    Searches for error messages, API endpoints, and other identifiable patterns.
    """

    # Common patterns to extract from error messages
    PATTERNS = [
        # API endpoints
        (r"/[a-zA-Z0-9/_-]+", "api_endpoint"),
        # Function/method names
        (r"\b[a-z_][a-zA-Z0-9_]*\s*\(", "function_call"),
        # Class names
        (r"\b[A-Z][a-zA-Z0-9]+(?:Error|Exception|Handler|Service|Controller|Manager)\b", "class_name"),
        # String literals
        (r'"([^"]{5,})"', "string_literal"),
        (r"'([^']{5,})'", "string_literal"),
        # Error messages (quoted text)
        (r'(?:error|Error|ERROR):\s*["\']?([^"\']+)["\']?', "error_msg"),
    ]

    # File extensions to search (by language)
    LANG_EXTENSIONS = {
        "php": ["*.php"],
        "python": ["*.py"],
        "javascript": ["*.js", "*.jsx", "*.ts", "*.tsx"],
        "ruby": ["*.rb"],
        "go": ["*.go"],
        "java": ["*.java"],
        "csharp": ["*.cs"],
    }

    # Directories to exclude from search
    EXCLUDE_DIRS = [
        "node_modules",
        "vendor",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".bughawk",
    ]

    def __init__(self, context_lines: int = 5, max_matches: int = 10):
        """Initialize the resolver.

        Args:
            context_lines: Number of lines to include around matches
            max_matches: Maximum matches to return per search
        """
        self.context_lines = context_lines
        self.max_matches = max_matches

    @property
    def name(self) -> str:
        return "codebase_search"

    @property
    def priority(self) -> int:
        return 10  # Lower priority - try after stacktrace

    def can_resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
    ) -> bool:
        """Check if we have an error message to search for."""
        # We can always try to search if there's an error message
        if hasattr(issue, "title") and issue.title:
            return True

        if event:
            message = event.get("message", "")
            if message:
                return True

        return False

    def resolve(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
        repo_path: Path,
    ) -> ResolverResult:
        """Search codebase for error-related code."""
        try:
            # Get error message
            error_message = self._get_error_message(issue, event)
            if not error_message:
                return ResolverResult.fail("No error message to search for")

            logger.info("Searching codebase for: %s", error_message[:100])

            # Extract search patterns from error message
            patterns = self._extract_patterns(error_message)
            if not patterns:
                return ResolverResult.fail("Could not extract search patterns")

            logger.info("Extracted patterns: %s", patterns)

            # Detect language from SDK/tags
            language = self._detect_language(issue, event)

            # Search for each pattern
            all_matches: list[SearchMatch] = []
            for pattern, pattern_type in patterns:
                matches = self._search_pattern(repo_path, pattern, language)
                for match in matches:
                    match.pattern = pattern
                    # Adjust relevance based on pattern type
                    if pattern_type == "api_endpoint":
                        match.relevance_score *= 1.2
                    elif pattern_type == "error_msg":
                        match.relevance_score *= 1.5
                all_matches.extend(matches)

            if not all_matches:
                return ResolverResult.fail(
                    f"No matches found in codebase for patterns: {[p[0] for p in patterns]}"
                )

            # Group by file and rank
            source_files = self._build_source_files(
                all_matches, repo_path, language
            )

            if not source_files:
                return ResolverResult.fail("Could not build source file context")

            # Primary file is the one with highest relevance
            source_files.sort(key=lambda sf: sf.relevance_score, reverse=True)
            primary_file = source_files[0]

            # Build context
            context = IssueContext(
                source=ContextSource.CODEBASE_SEARCH,
                confidence=min(0.7, primary_file.relevance_score),  # Lower confidence than stacktrace
                error_message=error_message,
                error_type=None,
                source_files=source_files,
                primary_file=primary_file,
                error_line=primary_file.snippets[0].highlight_line if primary_file.snippets else None,
                tags=self._extract_tags(event) if event else {},
                environment=self._extract_environment(event) if event else {},
                resolution_method=f"Searched codebase for patterns: {[p[0] for p in patterns[:3]]}",
                search_patterns=[p[0] for p in patterns],
            )

            logger.info(
                "Resolved context from codebase search: %d files, primary=%s (confidence=%.0f%%)",
                len(source_files),
                primary_file.path,
                context.confidence * 100,
            )

            return ResolverResult.ok(context)

        except Exception as e:
            logger.exception("Failed to resolve context from codebase search")
            return ResolverResult.fail(f"Codebase search error: {e}")

    def _get_error_message(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
    ) -> str:
        """Extract error message from issue/event."""
        # Try event message first
        if event:
            # Check for message entry
            for entry in event.get("entries", []):
                if entry.get("type") == "message":
                    data = entry.get("data", {})
                    msg = data.get("formatted") or data.get("message")
                    if msg:
                        return msg

            # Direct message
            if event.get("message"):
                return event["message"]

        # Fall back to issue title
        if hasattr(issue, "title"):
            return issue.title

        return ""

    def _extract_patterns(self, error_message: str) -> list[tuple[str, str]]:
        """Extract searchable patterns from error message.

        Extracts multiple types of patterns:
        1. Error message prefixes (e.g., "Call api error")
        2. Generalized URL patterns (IDs replaced with path structure)
        3. Function/class names
        4. String literals
        """
        patterns = []

        # 1. Extract error message prefix (text before dynamic content)
        # e.g., "Call api error: /shops/123..." -> "Call api error"
        error_prefix_match = re.match(r"^['\"]?([A-Za-z][A-Za-z\s]+(?:error|Error|failed|Failed|exception|Exception)?)[:\s]", error_message)
        if error_prefix_match:
            prefix = error_prefix_match.group(1).strip()
            if len(prefix) >= 5:
                patterns.append((prefix, "error_prefix"))

        # 2. Extract generalized URL patterns
        # Replace numeric IDs with path structure for searching
        url_match = re.search(r"(/[a-zA-Z0-9/_-]+)", error_message)
        if url_match:
            url = url_match.group(1)
            # Extract path segments without numeric IDs
            # /shops/123/listings/456/images/789 -> ["shops", "listings", "images"]
            segments = [s for s in url.split("/") if s and not s.isdigit()]
            if segments:
                # Search for each significant segment
                for segment in segments:
                    if len(segment) >= 4:  # Skip short segments like "api"
                        patterns.append((segment, "url_segment"))

                # Also try path pattern combinations
                if len(segments) >= 2:
                    # e.g., "listings/images" or "shops.*listings"
                    patterns.append((f"{segments[-2]}.*{segments[-1]}", "url_pattern"))

        # 3. Standard pattern extraction
        for regex, pattern_type in self.PATTERNS:
            matches = re.findall(regex, error_message)
            for match in matches:
                # Clean up the match
                if isinstance(match, tuple):
                    match = match[0]
                match = match.strip()

                # Filter out too short or too common patterns
                if len(match) < 3:
                    continue
                if match.lower() in ("error", "exception", "null", "undefined", "api"):
                    continue
                # Skip full URLs with IDs (we already generalized above)
                if re.match(r"/[a-z]+/\d+", match):
                    continue

                patterns.append((match, pattern_type))

        # 4. Extract the full error message if it looks like a string literal
        if error_message.startswith(("'", '"')) and error_message.endswith(("'", '"')):
            clean_msg = error_message[1:-1]
            # Extract just the static part before dynamic values
            static_part = re.split(r"[:/]\s*\d+", clean_msg)[0]
            if len(static_part) >= 10:
                patterns.append((static_part, "error_msg"))

        # Deduplicate while preserving order
        seen = set()
        unique = []
        for p in patterns:
            if p[0] not in seen:
                seen.add(p[0])
                unique.append(p)

        return unique[:10]  # Limit patterns to search

    def _detect_language(
        self,
        issue: Any,
        event: Optional[dict[str, Any]],
    ) -> Optional[str]:
        """Detect programming language from issue/event metadata."""
        # Check SDK info
        if hasattr(issue, "metadata"):
            sdk = issue.metadata.get("sdk", {})
            sdk_name = sdk.get("name", "").lower()
            if "php" in sdk_name:
                return "php"
            elif "python" in sdk_name:
                return "python"
            elif "javascript" in sdk_name or "node" in sdk_name:
                return "javascript"
            elif "ruby" in sdk_name:
                return "ruby"
            elif "go" in sdk_name:
                return "go"
            elif "java" in sdk_name:
                return "java"

        # Check event tags
        if event:
            for tag in event.get("tags", []):
                if isinstance(tag, dict):
                    if tag.get("key") == "runtime.name":
                        runtime = tag.get("value", "").lower()
                        if "php" in runtime:
                            return "php"
                        elif "python" in runtime:
                            return "python"

        return None

    def _search_pattern(
        self,
        repo_path: Path,
        pattern: str,
        language: Optional[str] = None,
    ) -> list[SearchMatch]:
        """Search for a pattern in the codebase using grep."""
        matches = []

        # Build file extension filter
        extensions = self.LANG_EXTENSIONS.get(language, ["*.php", "*.py", "*.js", "*.ts", "*.rb", "*.go", "*.java"])
        if isinstance(extensions, list) and extensions:
            # Use first extension for simplicity, or search all
            ext_filter = " -o ".join(f'-name "{ext}"' for ext in extensions)
            ext_filter = f"\\( {ext_filter} \\)"
        else:
            ext_filter = '-name "*.php"'  # Default to PHP

        # Build exclude directories
        exclude_dirs = " ".join(f'-not -path "*/{d}/*"' for d in self.EXCLUDE_DIRS)

        # Escape pattern for grep (basic regex)
        # For grep, we need to escape special chars differently
        grep_pattern = pattern.replace("\\", "\\\\").replace('"', '\\"')

        try:
            # Use grep with find for better compatibility
            cmd = f'''find "{repo_path}" {ext_filter} {exclude_dirs} -type f -exec grep -l -n "{grep_pattern}" {{}} \\; 2>/dev/null | head -n {self.max_matches}'''

            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode == 0 and result.stdout.strip():
                # Get file paths from find+grep -l output
                file_paths = [Path(p) for p in result.stdout.strip().split("\n") if p]

                # Now get line numbers for each file
                for file_path in file_paths[:self.max_matches]:
                    try:
                        # Get specific matches with line numbers
                        grep_cmd = f'grep -n "{grep_pattern}" "{file_path}" 2>/dev/null | head -n 3'
                        grep_result = subprocess.run(
                            grep_cmd,
                            shell=True,
                            capture_output=True,
                            text=True,
                            timeout=10,
                        )

                        if grep_result.returncode == 0:
                            for line in grep_result.stdout.strip().split("\n"):
                                if ":" in line:
                                    parts = line.split(":", 1)
                                    try:
                                        line_num = int(parts[0])
                                        line_content = parts[1] if len(parts) > 1 else ""
                                        matches.append(SearchMatch(
                                            file_path=file_path,
                                            line_number=line_num,
                                            line_content=line_content.strip(),
                                            pattern=pattern,
                                        ))
                                    except ValueError:
                                        continue
                    except Exception:
                        continue

        except subprocess.TimeoutExpired:
            logger.warning("Search timed out for pattern: %s", pattern)
        except Exception as e:
            logger.warning("Search failed for pattern %s: %s", pattern, e)

        return matches

    def _parse_rg_output(
        self,
        output: str,
        repo_path: Path,
        pattern: str,
    ) -> list[SearchMatch]:
        """Parse ripgrep output into SearchMatch objects."""
        matches = []
        for line in output.strip().split("\n"):
            if not line:
                continue

            # Format: file:line:content
            parts = line.split(":", 2)
            if len(parts) >= 3:
                file_path = Path(parts[0])
                try:
                    line_number = int(parts[1])
                except ValueError:
                    continue
                line_content = parts[2]

                matches.append(SearchMatch(
                    file_path=file_path,
                    line_number=line_number,
                    line_content=line_content.strip(),
                    pattern=pattern,
                ))

        return matches

    def _search_with_grep(
        self,
        repo_path: Path,
        pattern: str,
        language: Optional[str] = None,
    ) -> list[SearchMatch]:
        """Fallback search using grep."""
        matches = []

        # Build find + grep command
        extensions = self.LANG_EXTENSIONS.get(language, ["*"])
        exclude_dirs = " ".join(f"-not -path '*/{d}/*'" for d in self.EXCLUDE_DIRS)

        for ext in extensions:
            try:
                cmd = f"find {repo_path} -name '{ext}' {exclude_dirs} -exec grep -l -n '{pattern}' {{}} \\; 2>/dev/null | head -n {self.max_matches}"
                result = subprocess.run(
                    cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        if ":" in line:
                            parts = line.split(":", 1)
                            if len(parts) == 2:
                                matches.append(SearchMatch(
                                    file_path=Path(parts[0]),
                                    line_number=1,  # grep -l doesn't give line numbers
                                    line_content="",
                                    pattern=pattern,
                                ))
            except Exception:
                continue

        return matches

    def _build_source_files(
        self,
        matches: list[SearchMatch],
        repo_path: Path,
        language: Optional[str],
    ) -> list[SourceFile]:
        """Build SourceFile objects from search matches."""
        # Group by file
        file_matches: dict[Path, list[SearchMatch]] = {}
        for match in matches:
            if match.file_path not in file_matches:
                file_matches[match.file_path] = []
            file_matches[match.file_path].append(match)

        source_files = []
        for file_path, file_match_list in file_matches.items():
            # Calculate relevance score based on number of matches
            relevance = min(1.0, len(file_match_list) * 0.2 + 0.5)

            # Determine relative path
            try:
                rel_path = file_path.relative_to(repo_path)
            except ValueError:
                rel_path = file_path

            # Detect language from file
            detected_lang = self._detect_file_language(file_path)

            sf = SourceFile(
                path=str(rel_path),
                absolute_path=file_path if file_path.exists() else None,
                language=detected_lang or language,
                relevance_score=relevance,
                match_reason=f"Contains pattern(s): {', '.join(set(m.pattern for m in file_match_list[:3]))}",
            )

            # Add snippets for each match
            for match in file_match_list[:3]:  # Limit snippets per file
                snippet = self._get_snippet(
                    file_path,
                    match.line_number,
                    self.context_lines,
                )
                if snippet:
                    sf.add_snippet(
                        start_line=snippet["start"],
                        end_line=snippet["end"],
                        content=snippet["content"],
                        highlight_line=match.line_number,
                    )

            source_files.append(sf)

        return source_files

    def _detect_file_language(self, file_path: Path) -> Optional[str]:
        """Detect language from file extension."""
        ext_map = {
            ".py": "python",
            ".php": "php",
            ".js": "javascript",
            ".ts": "typescript",
            ".jsx": "javascript",
            ".tsx": "typescript",
            ".rb": "ruby",
            ".go": "go",
            ".java": "java",
            ".cs": "csharp",
        }
        return ext_map.get(file_path.suffix.lower())

    def _get_snippet(
        self,
        file_path: Path,
        line_number: int,
        context: int,
    ) -> Optional[dict]:
        """Read a code snippet from a file."""
        try:
            if not file_path.exists():
                return None

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start = max(0, line_number - context - 1)
            end = min(len(lines), line_number + context)

            content = "".join(lines[start:end])

            return {
                "start": start + 1,
                "end": end,
                "content": content.rstrip(),
            }
        except Exception as e:
            logger.warning("Failed to read snippet from %s: %s", file_path, e)
            return None

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

        runtime = contexts.get("runtime", {})
        if runtime:
            env["runtime"] = runtime.get("runtime", runtime.get("name", ""))

        os_ctx = contexts.get("os", {})
        if os_ctx:
            env["os"] = os_ctx.get("os", os_ctx.get("name", ""))

        return env
