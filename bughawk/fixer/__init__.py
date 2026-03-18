"""Fixer module for BugHawk - LLM-powered code fixing."""

from bughawk.fixer.fix_generator import (
    FixAttempt,
    FixGenerationError,
    FixGenerator,
    FixValidationError,
    ValidationResult,
)
from bughawk.fixer.llm_client import LLMClient, LLMError, LLMProvider
from bughawk.fixer.validator import (
    ConfidenceBreakdown,
    DiffAnalysis,
    FixValidator,
    SyntaxValidationResult,
    TestResult,
)

__all__ = [
    "ConfidenceBreakdown",
    "DiffAnalysis",
    "FixAttempt",
    "FixGenerationError",
    "FixGenerator",
    "FixValidationError",
    "FixValidator",
    "LLMClient",
    "LLMError",
    "LLMProvider",
    "SyntaxValidationResult",
    "TestResult",
    "ValidationResult",
]
