"""Tests for LLM Client - Multi-provider LLM integration.

This test file is organized by feature groups:
1. Exception Classes
2. Data Classes (LLMResponse, ResponseCache)
3. Provider Base Class
4. Individual Provider Implementations
5. LLMClient Core Functionality
6. Response Parsing
7. Caching Mechanism
8. Retry Logic
9. Prompt Building
10. Integration Scenarios
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest


# =============================================================================
# Feature Group 1: Exception Classes
# =============================================================================


class TestExceptionClasses:
    """Tests for LLM exception hierarchy."""

    def test_llm_error_base(self):
        """Test base LLMError exception."""
        from bughawk.fixer.llm_client import LLMError

        error = LLMError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)

    def test_llm_rate_limit_error(self):
        """Test rate limit error with retry_after."""
        from bughawk.fixer.llm_client import LLMRateLimitError

        error = LLMRateLimitError("Rate limited", retry_after=30.0)
        assert str(error) == "Rate limited"
        assert error.retry_after == 30.0

    def test_llm_rate_limit_error_no_retry_after(self):
        """Test rate limit error without retry_after."""
        from bughawk.fixer.llm_client import LLMRateLimitError

        error = LLMRateLimitError("Rate limited")
        assert error.retry_after is None

    def test_llm_api_error(self):
        """Test API error exception."""
        from bughawk.fixer.llm_client import LLMAPIError

        error = LLMAPIError("API failed")
        assert str(error) == "API failed"

    def test_llm_response_error(self):
        """Test response parsing error."""
        from bughawk.fixer.llm_client import LLMResponseError

        error = LLMResponseError("Invalid JSON")
        assert str(error) == "Invalid JSON"

    def test_exception_inheritance(self):
        """Test exception inheritance chain."""
        from bughawk.fixer.llm_client import (
            LLMError,
            LLMRateLimitError,
            LLMAPIError,
            LLMResponseError,
        )

        assert issubclass(LLMRateLimitError, LLMError)
        assert issubclass(LLMAPIError, LLMError)
        assert issubclass(LLMResponseError, LLMError)


# =============================================================================
# Feature Group 2: Data Classes
# =============================================================================


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_llm_response_creation(self):
        """Test creating LLMResponse with all fields."""
        from bughawk.fixer.llm_client import LLMResponse
        from bughawk.core.config import LLMProvider

        response = LLMResponse(
            content="Generated code fix",
            model="gpt-4",
            provider=LLMProvider.OPENAI,
            prompt_tokens=100,
            completion_tokens=50,
            cached=False,
            latency_ms=250.5,
        )

        assert response.content == "Generated code fix"
        assert response.model == "gpt-4"
        assert response.provider == LLMProvider.OPENAI
        assert response.prompt_tokens == 100
        assert response.completion_tokens == 50
        assert response.cached is False
        assert response.latency_ms == 250.5

    def test_llm_response_defaults(self):
        """Test LLMResponse default values."""
        from bughawk.fixer.llm_client import LLMResponse
        from bughawk.core.config import LLMProvider

        response = LLMResponse(
            content="Test",
            model="test-model",
            provider=LLMProvider.OPENAI,
        )

        assert response.prompt_tokens == 0
        assert response.completion_tokens == 0
        assert response.cached is False
        assert response.latency_ms == 0.0


class TestResponseCache:
    """Tests for ResponseCache."""

    def test_cache_set_and_get(self):
        """Test setting and getting cached response."""
        from bughawk.fixer.llm_client import ResponseCache, LLMResponse
        from bughawk.core.config import LLMProvider

        cache = ResponseCache()
        response = LLMResponse(
            content="Cached content",
            model="test",
            provider=LLMProvider.OPENAI,
        )

        cache.set("test-key", response)
        cached = cache.get("test-key")

        assert cached is not None
        assert cached.content == "Cached content"

    def test_cache_miss(self):
        """Test cache miss returns None."""
        from bughawk.fixer.llm_client import ResponseCache

        cache = ResponseCache()
        result = cache.get("nonexistent-key")

        assert result is None

    def test_cache_clear(self):
        """Test clearing cache."""
        from bughawk.fixer.llm_client import ResponseCache, LLMResponse
        from bughawk.core.config import LLMProvider

        cache = ResponseCache()
        response = LLMResponse(
            content="Test",
            model="test",
            provider=LLMProvider.OPENAI,
        )
        cache.set("key1", response)
        cache.set("key2", response)

        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        from bughawk.fixer.llm_client import ResponseCache, LLMResponse
        from bughawk.core.config import LLMProvider

        cache = ResponseCache(max_size=2)
        response1 = LLMResponse(content="1", model="m", provider=LLMProvider.OPENAI)
        response2 = LLMResponse(content="2", model="m", provider=LLMProvider.OPENAI)
        response3 = LLMResponse(content="3", model="m", provider=LLMProvider.OPENAI)

        cache.set("key1", response1)
        cache.set("key2", response2)
        cache.set("key3", response3)  # Should evict key1

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None


# =============================================================================
# Feature Group 3: Provider Base Class
# =============================================================================


class TestBaseLLMProvider:
    """Tests for BaseLLMProvider abstract class."""

    def test_base_provider_is_abstract(self):
        """Test that BaseLLMProvider cannot be instantiated directly."""
        from bughawk.fixer.llm_client import BaseLLMProvider

        with pytest.raises(TypeError):
            BaseLLMProvider()

    def test_base_provider_requires_generate(self):
        """Test that subclass must implement generate method."""
        from bughawk.fixer.llm_client import BaseLLMProvider

        class IncompleteProvider(BaseLLMProvider):
            def get_default_model(self):
                return "test"

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_base_provider_requires_get_default_model(self):
        """Test that subclass must implement get_default_model."""
        from bughawk.fixer.llm_client import BaseLLMProvider, LLMResponse
        from bughawk.core.config import LLMProvider

        class IncompleteProvider(BaseLLMProvider):
            def generate(self, prompt, model, max_tokens, temperature, timeout):
                return LLMResponse(content="", model="", provider=LLMProvider.OPENAI)

        with pytest.raises(TypeError):
            IncompleteProvider()


# =============================================================================
# Feature Group 4: Individual Provider Implementations
# =============================================================================


class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_init_without_package(self):
        """Test initialization when anthropic not installed."""
        from bughawk.fixer.llm_client import AnthropicProvider, LLMError

        with patch.dict("sys.modules", {"anthropic": None}):
            with pytest.raises(LLMError) as exc_info:
                AnthropicProvider(api_key="test-key")
            assert "anthropic package not installed" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.AnthropicProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import AnthropicProvider

        provider = AnthropicProvider.__new__(AnthropicProvider)
        assert provider.DEFAULT_MODEL == "claude-sonnet-4-20250514"


class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    def test_init_without_package(self):
        """Test initialization when openai not installed."""
        from bughawk.fixer.llm_client import OpenAIProvider, LLMError

        with patch.dict("sys.modules", {"openai": None}):
            with pytest.raises(LLMError) as exc_info:
                OpenAIProvider(api_key="test-key")
            assert "openai package not installed" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.OpenAIProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import OpenAIProvider

        provider = OpenAIProvider.__new__(OpenAIProvider)
        assert provider.DEFAULT_MODEL == "gpt-4"


class TestOllamaProvider:
    """Tests for OllamaProvider (local models)."""

    def test_init_with_default_url(self):
        """Test initialization with default URL."""
        from bughawk.fixer.llm_client import OllamaProvider
        from bughawk.core.config import LLMProvider

        provider = OllamaProvider()

        assert provider.base_url == "http://localhost:11434"
        assert provider.provider == LLMProvider.OLLAMA

    def test_init_with_custom_url(self):
        """Test initialization with custom URL."""
        from bughawk.fixer.llm_client import OllamaProvider

        provider = OllamaProvider(base_url="http://custom:8080/")

        assert provider.base_url == "http://custom:8080"  # Trailing slash removed

    def test_default_model(self):
        """Test default model value."""
        from bughawk.fixer.llm_client import OllamaProvider

        provider = OllamaProvider()
        assert provider.get_default_model() == "llama3.1"

    @patch("bughawk.fixer.llm_client.requests")
    def test_generate_success(self, mock_requests):
        """Test successful generation with Ollama."""
        from bughawk.fixer.llm_client import OllamaProvider
        from bughawk.core.config import LLMProvider

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": "Generated fix code",
            "prompt_eval_count": 100,
            "eval_count": 50,
        }
        mock_requests.post.return_value = mock_response

        provider = OllamaProvider()
        result = provider.generate(
            prompt="Fix this bug",
            model="llama3.1",
            max_tokens=1000,
            temperature=0.1,
            timeout=30.0,
        )

        assert result.content == "Generated fix code"
        assert result.provider == LLMProvider.OLLAMA
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50

    @patch("bughawk.fixer.llm_client.requests")
    def test_generate_timeout(self, mock_requests):
        """Test timeout handling."""
        import requests
        from bughawk.fixer.llm_client import OllamaProvider, LLMAPIError

        mock_requests.post.side_effect = requests.exceptions.Timeout("Timeout")
        mock_requests.exceptions = requests.exceptions

        provider = OllamaProvider()

        with pytest.raises(LLMAPIError) as exc_info:
            provider.generate("prompt", "model", 1000, 0.1, 30.0)
        assert "timed out" in str(exc_info.value).lower()


class TestGeminiProvider:
    """Tests for GeminiProvider."""

    def test_init_without_package(self):
        """Test initialization when google-generativeai not installed."""
        from bughawk.fixer.llm_client import GeminiProvider, LLMError

        with patch.dict("sys.modules", {"google.generativeai": None, "google": None}):
            with pytest.raises(LLMError) as exc_info:
                GeminiProvider(api_key="test-key")
            assert "google-generativeai" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.GeminiProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import GeminiProvider

        provider = GeminiProvider.__new__(GeminiProvider)
        assert provider.DEFAULT_MODEL == "gemini-1.5-pro"


class TestGroqProvider:
    """Tests for GroqProvider."""

    def test_init_without_package(self):
        """Test initialization when groq not installed."""
        from bughawk.fixer.llm_client import GroqProvider, LLMError

        with patch.dict("sys.modules", {"groq": None}):
            with pytest.raises(LLMError) as exc_info:
                GroqProvider(api_key="test-key")
            assert "groq package not installed" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.GroqProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import GroqProvider

        provider = GroqProvider.__new__(GroqProvider)
        assert provider.DEFAULT_MODEL == "llama-3.1-70b-versatile"


class TestMistralProvider:
    """Tests for MistralProvider."""

    def test_init_without_package(self):
        """Test initialization when mistralai not installed."""
        from bughawk.fixer.llm_client import MistralProvider, LLMError

        with patch.dict("sys.modules", {"mistralai": None}):
            with pytest.raises(LLMError) as exc_info:
                MistralProvider(api_key="test-key")
            assert "mistralai package not installed" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.MistralProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import MistralProvider

        provider = MistralProvider.__new__(MistralProvider)
        assert provider.DEFAULT_MODEL == "mistral-large-latest"


class TestCohereProvider:
    """Tests for CohereProvider."""

    def test_init_without_package(self):
        """Test initialization when cohere not installed."""
        from bughawk.fixer.llm_client import CohereProvider, LLMError

        with patch.dict("sys.modules", {"cohere": None}):
            with pytest.raises(LLMError) as exc_info:
                CohereProvider(api_key="test-key")
            assert "cohere package not installed" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.CohereProvider.__init__", return_value=None)
    def test_default_model(self, mock_init):
        """Test default model value."""
        from bughawk.fixer.llm_client import CohereProvider

        provider = CohereProvider.__new__(CohereProvider)
        assert provider.DEFAULT_MODEL == "command-r-plus"


# =============================================================================
# Feature Group 5: Provider Registry and Utility Functions
# =============================================================================


class TestProviderRegistry:
    """Tests for provider registry and utility functions."""

    def test_provider_classes_mapping(self):
        """Test PROVIDER_CLASSES contains all providers."""
        from bughawk.fixer.llm_client import PROVIDER_CLASSES
        from bughawk.core.config import LLMProvider

        assert LLMProvider.OPENAI in PROVIDER_CLASSES
        assert LLMProvider.ANTHROPIC in PROVIDER_CLASSES
        assert LLMProvider.AZURE in PROVIDER_CLASSES
        assert LLMProvider.GEMINI in PROVIDER_CLASSES
        assert LLMProvider.OLLAMA in PROVIDER_CLASSES
        assert LLMProvider.GROQ in PROVIDER_CLASSES
        assert LLMProvider.MISTRAL in PROVIDER_CLASSES
        assert LLMProvider.COHERE in PROVIDER_CLASSES

    def test_default_models_mapping(self):
        """Test DEFAULT_MODELS contains all providers."""
        from bughawk.fixer.llm_client import DEFAULT_MODELS
        from bughawk.core.config import LLMProvider

        assert DEFAULT_MODELS[LLMProvider.OPENAI] == "gpt-4"
        assert DEFAULT_MODELS[LLMProvider.ANTHROPIC] == "claude-sonnet-4-20250514"
        assert DEFAULT_MODELS[LLMProvider.GEMINI] == "gemini-1.5-pro"

    def test_get_available_providers(self):
        """Test getting list of available providers."""
        from bughawk.fixer.llm_client import get_available_providers

        providers = get_available_providers()

        assert "openai" in providers
        assert "anthropic" in providers
        assert "ollama" in providers

    def test_get_default_model_for_provider_enum(self):
        """Test getting default model with enum."""
        from bughawk.fixer.llm_client import get_default_model_for_provider
        from bughawk.core.config import LLMProvider

        model = get_default_model_for_provider(LLMProvider.OPENAI)
        assert model == "gpt-4"

    def test_get_default_model_for_provider_string(self):
        """Test getting default model with string."""
        from bughawk.fixer.llm_client import get_default_model_for_provider

        model = get_default_model_for_provider("openai")
        assert model == "gpt-4"


# =============================================================================
# Feature Group 6: LLMClient Core Functionality
# =============================================================================


class TestLLMClientInitialization:
    """Tests for LLMClient initialization."""

    @patch("bughawk.fixer.llm_client.get_config")
    def test_init_from_config(self, mock_get_config):
        """Test initialization from global config."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OPENAI
        mock_config.llm.api_key = "test-key"
        mock_config.llm.model = "gpt-4"
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_get_config.return_value = mock_config

        client = LLMClient()

        assert client.provider_type == LLMProvider.OPENAI
        assert client.api_key == "test-key"
        assert client.default_model == "gpt-4"

    @patch("bughawk.fixer.llm_client.get_config")
    def test_init_with_explicit_params(self, mock_get_config):
        """Test initialization with explicit parameters."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider, LLMConfig

        mock_config = MagicMock()
        mock_config.llm = MagicMock()
        mock_get_config.return_value = mock_config

        config = LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            api_key="explicit-key",
            model="claude-3",
            max_tokens=2000,
            temperature=0.2,
        )

        client = LLMClient(
            provider=LLMProvider.ANTHROPIC,
            api_key="explicit-key",
            config=config,
        )

        assert client.provider_type == LLMProvider.ANTHROPIC
        assert client.api_key == "explicit-key"

    @patch("bughawk.fixer.llm_client.get_config")
    def test_init_cache_enabled(self, mock_get_config):
        """Test cache is enabled by default."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = "llama3.1"
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_get_config.return_value = mock_config

        client = LLMClient()

        assert client.cache is not None

    @patch("bughawk.fixer.llm_client.get_config")
    def test_init_cache_disabled(self, mock_get_config):
        """Test cache can be disabled."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = "llama3.1"
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_get_config.return_value = mock_config

        client = LLMClient(enable_cache=False)

        assert client.cache is None


class TestLLMClientProviderCreation:
    """Tests for LLMClient provider creation."""

    @patch("bughawk.fixer.llm_client.get_config")
    def test_create_provider_requires_api_key(self, mock_get_config):
        """Test that non-Ollama providers require API key."""
        from bughawk.fixer.llm_client import LLMClient, LLMError
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OPENAI
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_get_config.return_value = mock_config

        client = LLMClient()

        with pytest.raises(LLMError) as exc_info:
            _ = client.provider
        assert "API key required" in str(exc_info.value)

    @patch("bughawk.fixer.llm_client.get_config")
    def test_create_ollama_provider_no_api_key(self, mock_get_config):
        """Test Ollama provider doesn't require API key."""
        from bughawk.fixer.llm_client import LLMClient, OllamaProvider
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()
        provider = client.provider

        assert isinstance(provider, OllamaProvider)

    @patch("bughawk.fixer.llm_client.get_config")
    def test_azure_requires_endpoint(self, mock_get_config):
        """Test Azure provider requires endpoint configuration."""
        from bughawk.fixer.llm_client import LLMClient, LLMError
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.AZURE
        mock_config.llm.api_key = "test-key"
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.azure_endpoint = None
        mock_get_config.return_value = mock_config

        client = LLMClient()

        with pytest.raises(LLMError) as exc_info:
            _ = client.provider
        assert "Azure endpoint required" in str(exc_info.value)


# =============================================================================
# Feature Group 7: Response Parsing
# =============================================================================


class TestResponseParsing:
    """Tests for LLM response parsing."""

    @patch("bughawk.fixer.llm_client.get_config")
    def test_parse_fix_response_valid_json(self, mock_get_config):
        """Test parsing valid JSON response."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        response = '''```json
{
    "fix_description": "Add null check",
    "confidence_score": 0.85,
    "explanation": "The variable may be null",
    "code_changes": {
        "test.py": "--- a/test.py\\n+++ b/test.py\\n-old\\n+new"
    }
}
```'''

        fix = client._parse_fix_response(response, "issue-123")

        assert fix.issue_id == "issue-123"
        assert fix.fix_description == "Add null check"
        assert fix.confidence_score == 0.85
        assert "test.py" in fix.code_changes

    @patch("bughawk.fixer.llm_client.get_config")
    def test_parse_fix_response_invalid_json(self, mock_get_config):
        """Test parsing invalid JSON returns fallback."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()
        response = "This is not valid JSON at all"

        fix = client._parse_fix_response(response, "issue-123")

        assert fix.issue_id == "issue-123"
        assert fix.confidence_score == 0.3  # Fallback confidence
        assert fix.code_changes == {}

    @patch("bughawk.fixer.llm_client.get_config")
    def test_parse_fix_response_raw_json(self, mock_get_config):
        """Test parsing raw JSON without code blocks."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()
        response = '{"fix_description": "Fix bug", "confidence_score": 0.9}'

        fix = client._parse_fix_response(response, "issue-123")

        assert fix.fix_description == "Fix bug"
        assert fix.confidence_score == 0.9


# =============================================================================
# Feature Group 8: Caching Mechanism
# =============================================================================


class TestCachingMechanism:
    """Tests for response caching."""

    @patch("bughawk.fixer.llm_client.get_config")
    def test_cache_key_generation(self, mock_get_config):
        """Test cache key is deterministic."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        key1 = client._get_cache_key("prompt", "model")
        key2 = client._get_cache_key("prompt", "model")
        key3 = client._get_cache_key("different", "model")

        assert key1 == key2  # Same inputs
        assert key1 != key3  # Different inputs

    @patch("bughawk.fixer.llm_client.get_config")
    def test_clear_cache(self, mock_get_config):
        """Test clearing cache."""
        from bughawk.fixer.llm_client import LLMClient, LLMResponse
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        # Add to cache
        response = LLMResponse(content="test", model="m", provider=LLMProvider.OLLAMA)
        client.cache.set("test-key", response)

        assert client.cache.get("test-key") is not None

        client.clear_cache()

        assert client.cache.get("test-key") is None


# =============================================================================
# Feature Group 9: Retry Logic
# =============================================================================


class TestRetryLogic:
    """Tests for retry with exponential backoff."""

    @patch("bughawk.fixer.llm_client.get_config")
    @patch("bughawk.fixer.llm_client.time.sleep")
    def test_retry_on_rate_limit(self, mock_sleep, mock_get_config):
        """Test retry on rate limit error."""
        from bughawk.fixer.llm_client import (
            LLMClient,
            LLMResponse,
            LLMRateLimitError,
            OllamaProvider,
        )
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        # Mock provider to fail twice then succeed
        mock_provider = MagicMock(spec=OllamaProvider)
        success_response = LLMResponse(
            content="Success",
            model="test",
            provider=LLMProvider.OLLAMA,
        )
        mock_provider.generate.side_effect = [
            LLMRateLimitError("Rate limited", retry_after=1.0),
            success_response,
        ]

        client._provider = mock_provider

        result = client._generate_with_retry("prompt", "model", 30.0)

        assert result.content == "Success"
        assert mock_provider.generate.call_count == 2
        mock_sleep.assert_called()

    @patch("bughawk.fixer.llm_client.get_config")
    @patch("bughawk.fixer.llm_client.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep, mock_get_config):
        """Test failure after max retries."""
        from bughawk.fixer.llm_client import (
            LLMClient,
            LLMRateLimitError,
            LLMError,
            OllamaProvider,
        )
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        mock_provider = MagicMock(spec=OllamaProvider)
        mock_provider.generate.side_effect = LLMRateLimitError("Rate limited")

        client._provider = mock_provider

        with pytest.raises(LLMError) as exc_info:
            client._generate_with_retry("prompt", "model", 30.0)

        assert "Failed after" in str(exc_info.value)
        assert mock_provider.generate.call_count == 3  # MAX_RETRIES


# =============================================================================
# Feature Group 10: Prompt Building
# =============================================================================


class TestPromptBuilding:
    """Tests for prompt construction."""

    @pytest.fixture
    def mock_context(self):
        """Create mock code context."""
        context = MagicMock()
        context.file_path = "src/app.py"
        context.error_line = 42
        context.surrounding_lines = {
            40: "def process():",
            41: "    data = get_data()",
            42: "    result = data.map(fn)",  # Error line
            43: "    return result",
        }
        context.file_content = ""
        return context

    @pytest.fixture
    def mock_issue(self):
        """Create mock Sentry issue."""
        issue = MagicMock()
        issue.id = "12345"
        issue.title = "TypeError: Cannot read property 'map' of undefined"
        issue.count = 100
        issue.culprit = "src/app.py in process"
        return issue

    @patch("bughawk.fixer.llm_client.get_config")
    def test_build_analysis_prompt(self, mock_get_config, mock_context, mock_issue):
        """Test analysis prompt construction."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()
        prompt = client._build_analysis_prompt(
            mock_context, mock_issue, "Error at line 42"
        )

        assert "BugHawk" in prompt
        assert "12345" in prompt  # Issue ID
        assert "TypeError" in prompt  # Issue title
        assert "src/app.py" in prompt  # File path
        assert "42" in prompt  # Error line
        assert "ERROR" in prompt  # Error marker

    @patch("bughawk.fixer.llm_client.get_config")
    def test_build_fix_prompt(self, mock_get_config, mock_context, mock_issue):
        """Test fix prompt construction."""
        from bughawk.fixer.llm_client import LLMClient
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()
        prompt = client._build_fix_prompt(
            "Root cause: null reference",
            mock_context,
            mock_issue,
        )

        assert "BugHawk" in prompt
        assert "Root cause: null reference" in prompt
        assert "JSON" in prompt  # Expects JSON response
        assert "fix_description" in prompt
        assert "confidence_score" in prompt


# =============================================================================
# Feature Group 11: Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Tests for end-to-end scenarios."""

    @pytest.fixture
    def mock_context(self):
        """Create mock code context."""
        context = MagicMock()
        context.file_path = "src/app.py"
        context.error_line = 42
        context.surrounding_lines = {
            40: "def process():",
            41: "    data = get_data()",
            42: "    result = data.map(fn)",
            43: "    return result",
        }
        context.file_content = ""
        return context

    @pytest.fixture
    def mock_issue(self):
        """Create mock Sentry issue."""
        issue = MagicMock()
        issue.id = "12345"
        issue.title = "TypeError: Cannot read property 'map' of undefined"
        issue.count = 100
        issue.culprit = "src/app.py in process"
        return issue

    @patch("bughawk.fixer.llm_client.get_config")
    def test_analyze_and_fix_workflow(self, mock_get_config, mock_context, mock_issue):
        """Test complete analyze and fix workflow."""
        from bughawk.fixer.llm_client import LLMClient, LLMResponse
        from bughawk.core.config import LLMProvider

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        # Mock provider responses
        analysis_response = LLMResponse(
            content="Root cause: data is undefined before map call",
            model="test",
            provider=LLMProvider.OLLAMA,
        )

        fix_response = LLMResponse(
            content='''```json
{
    "fix_description": "Add null check before map",
    "confidence_score": 0.9,
    "explanation": "Check if data exists before calling map",
    "code_changes": {
        "src/app.py": "--- a/src/app.py\\n+++ b/src/app.py\\n-    result = data.map(fn)\\n+    result = (data || []).map(fn)"
    }
}
```''',
            model="test",
            provider=LLMProvider.OLLAMA,
        )

        mock_provider = MagicMock()
        mock_provider.generate.side_effect = [analysis_response, fix_response]
        client._provider = mock_provider

        analysis, fix = client.analyze_and_fix(mock_context, mock_issue)

        assert "undefined" in analysis
        assert fix.issue_id == "12345"
        assert fix.confidence_score == 0.9
        assert "src/app.py" in fix.code_changes

    @patch("bughawk.fixer.llm_client.get_config")
    def test_validate_fix(self, mock_get_config):
        """Test fix validation."""
        from bughawk.fixer.llm_client import LLMClient, LLMResponse
        from bughawk.core.config import LLMProvider
        from bughawk.core.models import FixProposal

        mock_config = MagicMock()
        mock_config.llm.provider = LLMProvider.OLLAMA
        mock_config.llm.api_key = None
        mock_config.llm.model = None
        mock_config.llm.max_tokens = 4096
        mock_config.llm.temperature = 0.1
        mock_config.llm.ollama_base_url = "http://localhost:11434"
        mock_get_config.return_value = mock_config

        client = LLMClient()

        fix = FixProposal(
            issue_id="123",
            fix_description="Add null check",
            code_changes={"test.py": "--- a\\n+++ b\\n-old\\n+new"},
            confidence_score=0.85,
            explanation="Prevents null reference",
        )

        context = MagicMock()
        context.file_path = "test.py"

        validation_response = LLMResponse(
            content='''```json
{
    "is_safe": true,
    "issues_found": [],
    "suggestions": ["Consider adding unit test"],
    "adjusted_confidence": 0.9
}
```''',
            model="test",
            provider=LLMProvider.OLLAMA,
        )

        mock_provider = MagicMock()
        mock_provider.generate.return_value = validation_response
        client._provider = mock_provider

        result = client.validate_fix(fix, context)

        assert result["is_safe"] is True
        assert result["adjusted_confidence"] == 0.9
