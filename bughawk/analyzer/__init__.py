"""Code analysis module for BugHawk."""

from bughawk.analyzer.code_locator import CodeLocator
from bughawk.analyzer.context_builder import ContextBuilder, EnrichedContext
from bughawk.analyzer.pattern_matcher import (
    ErrorCategory,
    ErrorPattern,
    FixTemplate,
    PatternMatch,
    PatternMatcher,
)

__all__ = [
    "CodeLocator",
    "ContextBuilder",
    "EnrichedContext",
    "ErrorCategory",
    "ErrorPattern",
    "FixTemplate",
    "PatternMatch",
    "PatternMatcher",
]
