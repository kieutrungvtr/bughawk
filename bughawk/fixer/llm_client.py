"""LLM client for generating code fixes.

This module provides a unified interface for interacting with LLM providers
(Anthropic Claude, OpenAI GPT, Google Gemini, Azure OpenAI, Ollama, and more)
to analyze errors and generate fixes.

The hawk's keen intellect - using AI to precisely identify and eliminate bugs.
"""

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from bughawk.core.config import LLMConfig, LLMProvider, get_config
from bughawk.core.models import CodeContext, FixProposal, SentryIssue
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


class LLMError(Exception):
    """Base exception for LLM errors."""

    pass


class LLMRateLimitError(LLMError):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class LLMAPIError(LLMError):
    """Raised when API call fails."""

    pass


class LLMResponseError(LLMError):
    """Raised when response parsing fails."""

    pass


@dataclass
class LLMResponse:
    """Response from an LLM call.

    The hawk's catch - processed intelligence from the AI.
    """

    content: str
    model: str
    provider: LLMProvider
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    latency_ms: float = 0.0


@dataclass
class ResponseCache:
    """Simple in-memory response cache.

    The hawk's memory - avoiding redundant hunts.
    """

    _cache: dict[str, LLMResponse] = field(default_factory=dict)
    max_size: int = 100

    def get(self, key: str) -> LLMResponse | None:
        """Get cached response by key."""
        return self._cache.get(key)

    def set(self, key: str, response: LLMResponse) -> None:
        """Cache a response."""
        # Simple LRU: remove oldest if at capacity
        if len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]
        self._cache[key] = response

    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


class BaseLLMProvider(ABC):
    """Base class for LLM providers.

    The hawk's hunting technique - each provider has its own approach.
    """

    @abstractmethod
    def generate(
        self,
        prompt: str,
        model: str,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> LLMResponse:
        """Generate a response from the LLM.

        Args:
            prompt: The prompt to send
            model: Model identifier
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature
            timeout: Request timeout in seconds

        Returns:
            LLMResponse with generated content

        Raises:
            LLMRateLimitError: If rate limited
            LLMAPIError: If API call fails
        """
        pass

    @abstractmethod
    def get_default_model(self) -> str:
        """Get the default model for this provider."""
        pass


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude provider.

    The hawk's partnership with Claude - a keen analytical mind.
    """

    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str) -> None:
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
        """
        try:
            import anthropic

            self.client = anthropic.Anthropic(api_key=api_key)
            self.provider = LLMProvider.ANTHROPIC
            logger.debug("Anthropic provider initialized")
        except ImportError:
            raise LLMError("anthropic package not installed. Run: pip install anthropic")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Claude.

        The hawk consults with Claude for deep analysis.
        """
        import anthropic

        model = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            content = ""
            for block in response.content:
                if hasattr(block, "text"):
                    content += block.text

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider,
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
            )

        except anthropic.RateLimitError as e:
            logger.warning("Anthropic rate limit hit: %s", e)
            raise LLMRateLimitError(str(e))
        except anthropic.APITimeoutError as e:
            logger.error("Anthropic timeout: %s", e)
            raise LLMAPIError(f"Request timed out: {e}")
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class OpenAIProvider(BaseLLMProvider):
    """OpenAI GPT provider.

    The hawk's partnership with GPT - versatile and capable.
    """

    DEFAULT_MODEL = "gpt-4"

    def __init__(self, api_key: str) -> None:
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
        """
        try:
            import openai

            self.client = openai.OpenAI(api_key=api_key)
            self.provider = LLMProvider.OPENAI
            logger.debug("OpenAI provider initialized")
        except ImportError:
            raise LLMError("openai package not installed. Run: pip install openai")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using GPT.

        The hawk consults with GPT for versatile analysis.
        """
        import openai

        model = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000

            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
            )

        except openai.RateLimitError as e:
            logger.warning("OpenAI rate limit hit: %s", e)
            raise LLMRateLimitError(str(e))
        except openai.APITimeoutError as e:
            logger.error("OpenAI timeout: %s", e)
            raise LLMAPIError(f"Request timed out: {e}")
        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class AzureOpenAIProvider(BaseLLMProvider):
    """Azure OpenAI provider.

    The hawk's partnership with Azure - enterprise-grade reliability.
    """

    DEFAULT_MODEL = "gpt-4"

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        deployment: str,
        api_version: str = "2024-02-15-preview",
    ) -> None:
        """Initialize Azure OpenAI provider.

        Args:
            api_key: Azure OpenAI API key
            endpoint: Azure OpenAI endpoint URL
            deployment: Deployment name
            api_version: API version
        """
        try:
            import openai

            self.client = openai.AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint,
            )
            self.deployment = deployment
            self.provider = LLMProvider.AZURE
            logger.debug("Azure OpenAI provider initialized")
        except ImportError:
            raise LLMError("openai package not installed. Run: pip install openai")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Azure OpenAI."""
        import openai

        # Use deployment name for Azure
        model = self.deployment
        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model,
                provider=self.provider,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
            )

        except openai.RateLimitError as e:
            logger.warning("Azure OpenAI rate limit hit: %s", e)
            raise LLMRateLimitError(str(e))
        except openai.APITimeoutError as e:
            logger.error("Azure OpenAI timeout: %s", e)
            raise LLMAPIError(f"Request timed out: {e}")
        except openai.APIError as e:
            logger.error("Azure OpenAI API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.deployment or self.DEFAULT_MODEL


class GeminiProvider(BaseLLMProvider):
    """Google Gemini provider.

    The hawk's partnership with Gemini - multimodal intelligence.
    """

    DEFAULT_MODEL = "gemini-1.5-pro"

    def __init__(self, api_key: str) -> None:
        """Initialize Gemini provider.

        Args:
            api_key: Google AI API key
        """
        try:
            import google.generativeai as genai

            genai.configure(api_key=api_key)
            self.genai = genai
            self.provider = LLMProvider.GEMINI
            logger.debug("Gemini provider initialized")
        except ImportError:
            raise LLMError("google-generativeai package not installed. Run: pip install google-generativeai")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Gemini."""
        model_name = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            model_instance = self.genai.GenerativeModel(model_name)
            generation_config = self.genai.GenerationConfig(
                max_output_tokens=max_tokens,
                temperature=temperature,
            )

            response = model_instance.generate_content(
                prompt,
                generation_config=generation_config,
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.text if response.text else ""

            # Gemini doesn't provide token counts in the same way
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, "usage_metadata"):
                prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", 0)
                completion_tokens = getattr(response.usage_metadata, "candidates_token_count", 0)

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )

        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "rate" in error_msg:
                logger.warning("Gemini rate limit hit: %s", e)
                raise LLMRateLimitError(str(e))
            logger.error("Gemini API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class OllamaProvider(BaseLLMProvider):
    """Ollama provider for local models.

    The hawk's local companion - privacy-focused local inference.
    """

    DEFAULT_MODEL = "llama3.1"

    def __init__(self, base_url: str = "http://localhost:11434") -> None:
        """Initialize Ollama provider.

        Args:
            base_url: Ollama server URL
        """
        self.base_url = base_url.rstrip("/")
        self.provider = LLMProvider.OLLAMA
        logger.debug("Ollama provider initialized with base URL: %s", base_url)

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 60.0,
    ) -> LLMResponse:
        """Generate response using Ollama."""
        import requests

        model_name = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model_name,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
                timeout=timeout,
            )

            response.raise_for_status()
            data = response.json()
            latency_ms = (time.time() - start_time) * 1000
            content = data.get("response", "")

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider,
                prompt_tokens=data.get("prompt_eval_count", 0),
                completion_tokens=data.get("eval_count", 0),
                latency_ms=latency_ms,
            )

        except requests.exceptions.Timeout as e:
            logger.error("Ollama timeout: %s", e)
            raise LLMAPIError(f"Request timed out: {e}")
        except requests.exceptions.RequestException as e:
            logger.error("Ollama API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class GroqProvider(BaseLLMProvider):
    """Groq provider for ultra-fast inference.

    The hawk's lightning-fast partner - speed without compromise.
    """

    DEFAULT_MODEL = "llama-3.1-70b-versatile"

    def __init__(self, api_key: str) -> None:
        """Initialize Groq provider.

        Args:
            api_key: Groq API key
        """
        try:
            from groq import Groq

            self.client = Groq(api_key=api_key)
            self.provider = LLMProvider.GROQ
            logger.debug("Groq provider initialized")
        except ImportError:
            raise LLMError("groq package not installed. Run: pip install groq")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Groq."""
        from groq import RateLimitError, APITimeoutError, APIError

        model_name = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = self.client.chat.completions.create(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
                timeout=timeout,
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
            )

        except RateLimitError as e:
            logger.warning("Groq rate limit hit: %s", e)
            raise LLMRateLimitError(str(e))
        except APITimeoutError as e:
            logger.error("Groq timeout: %s", e)
            raise LLMAPIError(f"Request timed out: {e}")
        except APIError as e:
            logger.error("Groq API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class MistralProvider(BaseLLMProvider):
    """Mistral AI provider.

    The hawk's European ally - efficient and powerful.
    """

    DEFAULT_MODEL = "mistral-large-latest"

    def __init__(self, api_key: str) -> None:
        """Initialize Mistral provider.

        Args:
            api_key: Mistral API key
        """
        try:
            from mistralai import Mistral

            self.client = Mistral(api_key=api_key)
            self.provider = LLMProvider.MISTRAL
            logger.debug("Mistral provider initialized")
        except ImportError:
            raise LLMError("mistralai package not installed. Run: pip install mistralai")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Mistral."""
        model_name = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = self.client.chat.complete(
                model=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider,
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                latency_ms=latency_ms,
            )

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg or "limit" in error_msg:
                logger.warning("Mistral rate limit hit: %s", e)
                raise LLMRateLimitError(str(e))
            logger.error("Mistral API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


class CohereProvider(BaseLLMProvider):
    """Cohere provider.

    The hawk's semantic specialist - understanding through embeddings.
    """

    DEFAULT_MODEL = "command-r-plus"

    def __init__(self, api_key: str) -> None:
        """Initialize Cohere provider.

        Args:
            api_key: Cohere API key
        """
        try:
            import cohere

            self.client = cohere.Client(api_key=api_key)
            self.provider = LLMProvider.COHERE
            logger.debug("Cohere provider initialized")
        except ImportError:
            raise LLMError("cohere package not installed. Run: pip install cohere")

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
        timeout: float = 30.0,
    ) -> LLMResponse:
        """Generate response using Cohere."""
        model_name = model or self.DEFAULT_MODEL
        start_time = time.time()

        try:
            response = self.client.chat(
                model=model_name,
                message=prompt,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.text or ""

            # Cohere provides token counts differently
            prompt_tokens = 0
            completion_tokens = 0
            if hasattr(response, "meta") and response.meta:
                if hasattr(response.meta, "tokens"):
                    tokens = response.meta.tokens
                    prompt_tokens = getattr(tokens, "input_tokens", 0)
                    completion_tokens = getattr(tokens, "output_tokens", 0)

            return LLMResponse(
                content=content,
                model=model_name,
                provider=self.provider,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )

        except Exception as e:
            error_msg = str(e).lower()
            if "rate" in error_msg or "limit" in error_msg:
                logger.warning("Cohere rate limit hit: %s", e)
                raise LLMRateLimitError(str(e))
            logger.error("Cohere API error: %s", e)
            raise LLMAPIError(f"API error: {e}")

    def get_default_model(self) -> str:
        return self.DEFAULT_MODEL


# Provider registry mapping
PROVIDER_CLASSES = {
    LLMProvider.OPENAI: OpenAIProvider,
    LLMProvider.ANTHROPIC: AnthropicProvider,
    LLMProvider.CLAUDE: AnthropicProvider,  # Alias for anthropic
    LLMProvider.AZURE: AzureOpenAIProvider,
    LLMProvider.GEMINI: GeminiProvider,
    LLMProvider.OLLAMA: OllamaProvider,
    LLMProvider.GROQ: GroqProvider,
    LLMProvider.MISTRAL: MistralProvider,
    LLMProvider.COHERE: CohereProvider,
}

DEFAULT_MODELS = {
    LLMProvider.OPENAI: "gpt-4",
    LLMProvider.ANTHROPIC: "claude-sonnet-4-20250514",
    LLMProvider.CLAUDE: "claude-sonnet-4-20250514",  # Alias for anthropic
    LLMProvider.AZURE: "gpt-4",
    LLMProvider.GEMINI: "gemini-1.5-pro",
    LLMProvider.OLLAMA: "llama3.1",
    LLMProvider.GROQ: "llama-3.1-70b-versatile",
    LLMProvider.MISTRAL: "mistral-large-latest",
    LLMProvider.COHERE: "command-r-plus",
}


def get_available_providers() -> list[str]:
    """Get list of all available LLM providers.

    Returns:
        List of provider names
    """
    return [p.value for p in LLMProvider]


def get_default_model_for_provider(provider: LLMProvider | str) -> str:
    """Get the default model for a given provider.

    Args:
        provider: Provider enum or string name

    Returns:
        Default model name for the provider
    """
    if isinstance(provider, str):
        provider = LLMProvider(provider)
    return DEFAULT_MODELS.get(provider, "")


class LLMClient:
    """Unified LLM client for code analysis and fix generation.

    The hawk's brain - orchestrating AI-powered bug hunting with precision.

    This client provides:
    - Multiple LLM provider support via factory pattern
    - Response caching to reduce costs
    - Automatic retry with exponential backoff
    - Structured output parsing

    Example:
        >>> client = LLMClient()
        >>> analysis = client.analyze_error(context, issue)
        >>> fix = client.suggest_fix(analysis, context)
    """

    # Retry configuration
    MAX_RETRIES = 3
    INITIAL_BACKOFF = 1.0
    MAX_BACKOFF = 30.0

    def __init__(
        self,
        provider: LLMProvider | None = None,
        api_key: str | None = None,
        config: LLMConfig | None = None,
        enable_cache: bool = True,
    ) -> None:
        """Initialize LLM client.

        The hawk sharpens its analytical tools.

        Args:
            provider: LLM provider to use. Defaults to config value.
            api_key: API key. Defaults to config value.
            config: LLM configuration. Loads from global config if not provided.
            enable_cache: Whether to cache responses.
        """
        if config is None:
            config = get_config().llm

        self.config = config
        self.provider_type = provider or LLMProvider(config.provider.value)
        self.api_key = api_key or config.api_key
        # Use configured model or fall back to provider default
        self.default_model = config.model or get_default_model_for_provider(self.provider_type)
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature

        self.cache = ResponseCache() if enable_cache else None
        self._provider: BaseLLMProvider | None = None

        logger.info("LLM client initialized with provider: %s", self.provider_type.value)

    @property
    def provider(self) -> BaseLLMProvider:
        """Get or create the LLM provider (lazy initialization)."""
        if self._provider is None:
            self._provider = self._create_provider()
        return self._provider

    def _create_provider(self) -> BaseLLMProvider:
        """Factory method to create the appropriate provider.

        The hawk selects its hunting companion based on the terrain.
        """
        # Ollama doesn't require an API key
        if self.provider_type != LLMProvider.OLLAMA and not self.api_key:
            raise LLMError(
                f"API key required for {self.provider_type.value}. "
                f"Set BUGHAWK_LLM_API_KEY or llm.api_key in config."
            )

        if self.provider_type in (LLMProvider.ANTHROPIC, LLMProvider.CLAUDE):
            return AnthropicProvider(self.api_key)
        elif self.provider_type == LLMProvider.OPENAI:
            return OpenAIProvider(self.api_key)
        elif self.provider_type == LLMProvider.AZURE:
            # Azure requires additional config
            if not self.config.azure_endpoint:
                raise LLMError(
                    "Azure endpoint required. Set BUGHAWK_LLM_AZURE_ENDPOINT or llm.azure_endpoint in config."
                )
            if not self.config.azure_deployment:
                raise LLMError(
                    "Azure deployment required. Set BUGHAWK_LLM_AZURE_DEPLOYMENT or llm.azure_deployment in config."
                )
            return AzureOpenAIProvider(
                api_key=self.api_key,
                endpoint=self.config.azure_endpoint,
                deployment=self.config.azure_deployment,
                api_version=self.config.azure_api_version,
            )
        elif self.provider_type == LLMProvider.GEMINI:
            return GeminiProvider(self.api_key)
        elif self.provider_type == LLMProvider.OLLAMA:
            return OllamaProvider(base_url=self.config.ollama_base_url)
        elif self.provider_type == LLMProvider.GROQ:
            return GroqProvider(self.api_key)
        elif self.provider_type == LLMProvider.MISTRAL:
            return MistralProvider(self.api_key)
        elif self.provider_type == LLMProvider.COHERE:
            return CohereProvider(self.api_key)
        else:
            raise LLMError(f"Unsupported provider: {self.provider_type}")

    def _get_cache_key(self, prompt: str, model: str) -> str:
        """Generate cache key from prompt and model.

        The hawk's memory indexing system.
        """
        content = f"{model}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def generate_fix(
        self,
        prompt: str,
        model: str | None = None,
        timeout: float = 30.0,
        use_cache: bool = True,
    ) -> str:
        """Generate a fix response from the LLM.

        The hawk strikes with precision, using AI to craft the perfect fix.

        Args:
            prompt: The prompt to send to the LLM
            model: Model to use. Defaults to configured model.
            timeout: Request timeout in seconds
            use_cache: Whether to use cached responses

        Returns:
            Generated response content

        Raises:
            LLMError: If generation fails after retries
        """
        model = model or self.default_model
        logger.debug("Generating fix with model: %s", model)

        # Check cache
        if use_cache and self.cache:
            cache_key = self._get_cache_key(prompt, model)
            cached = self.cache.get(cache_key)
            if cached:
                logger.info("Hawk retrieved cached response (saved API call)")
                return cached.content

        # Generate with retries
        response = self._generate_with_retry(prompt, model, timeout)

        # Cache response
        if use_cache and self.cache:
            response.cached = False
            self.cache.set(cache_key, response)

        logger.info(
            "Hawk received response: %d tokens in %.0fms",
            response.completion_tokens,
            response.latency_ms,
        )
        return response.content

    def _generate_with_retry(
        self,
        prompt: str,
        model: str,
        timeout: float,
    ) -> LLMResponse:
        """Generate response with exponential backoff retry.

        The hawk circles patiently, waiting for the right moment to strike.
        """
        last_error: Exception | None = None
        backoff = self.INITIAL_BACKOFF

        for attempt in range(self.MAX_RETRIES):
            try:
                return self.provider.generate(
                    prompt=prompt,
                    model=model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    timeout=timeout,
                )
            except LLMRateLimitError as e:
                last_error = e
                wait_time = e.retry_after or backoff
                logger.warning(
                    "Rate limited, waiting %.1fs before retry %d/%d",
                    wait_time,
                    attempt + 1,
                    self.MAX_RETRIES,
                )
                time.sleep(wait_time)
                backoff = min(backoff * 2, self.MAX_BACKOFF)
            except LLMAPIError as e:
                last_error = e
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(
                        "API error, retrying in %.1fs: %s",
                        backoff,
                        str(e),
                    )
                    time.sleep(backoff)
                    backoff = min(backoff * 2, self.MAX_BACKOFF)

        raise LLMError(f"Failed after {self.MAX_RETRIES} attempts: {last_error}")

    def analyze_error(
        self,
        context: CodeContext,
        issue: SentryIssue,
        stack_trace: str | None = None,
    ) -> str:
        """Analyze an error and identify root cause.

        The hawk circles overhead, studying its prey from every angle.

        Args:
            context: Code context around the error
            issue: The Sentry issue
            stack_trace: Optional formatted stack trace

        Returns:
            Analysis of the error and its root cause
        """
        logger.info("Hawk analyzing error: %s", issue.id)

        prompt = self._build_analysis_prompt(context, issue, stack_trace)
        response = self.generate_fix(prompt)

        return response

    def suggest_fix(
        self,
        analysis: str,
        context: CodeContext,
        issue: SentryIssue,
    ) -> FixProposal:
        """Generate a concrete fix proposal based on analysis.

        The hawk dives with precision, talons ready for the catch.

        Args:
            analysis: Previous error analysis
            context: Code context
            issue: The Sentry issue

        Returns:
            FixProposal with concrete code changes

        Raises:
            LLMResponseError: If response cannot be parsed
        """
        logger.info("Hawk crafting fix for issue: %s", issue.id)

        prompt = self._build_fix_prompt(analysis, context, issue)
        response = self.generate_fix(prompt)

        # Parse structured response
        return self._parse_fix_response(response, issue.id)

    def _build_analysis_prompt(
        self,
        context: CodeContext,
        issue: SentryIssue,
        stack_trace: str | None,
    ) -> str:
        """Build prompt for error analysis.

        The hawk formulates its hunting strategy.
        """
        # Build code context section
        code_section = ""
        if context.surrounding_lines:
            code_lines = []
            for line_num, content in sorted(context.surrounding_lines.items()):
                marker = " <-- ERROR" if line_num == context.error_line else ""
                code_lines.append(f"{line_num:4d} | {content}{marker}")
            code_section = "\n".join(code_lines)
        elif context.file_content:
            code_section = context.file_content[:3000]  # Limit size

        prompt = f"""You are BugHawk, an expert code analyzer with the precision of a hunting hawk.
Your task is to analyze this error and identify the root cause with surgical accuracy.

## Error Information

**Issue ID**: {issue.id}
**Title**: {issue.title}
**Occurrences**: {issue.count:,}
**Culprit**: {issue.culprit or 'Unknown'}

## Stack Trace

{stack_trace or 'No stack trace available'}

## Source Code

**File**: {context.file_path}
**Error Line**: {context.error_line or 'Unknown'}

```
{code_section}
```

## Analysis Request

Provide a thorough analysis covering:

1. **Root Cause**: What is the fundamental cause of this error?
2. **Error Flow**: How does the error propagate through the code?
3. **Impact**: What functionality is affected?
4. **Frequency Factors**: Why might this error occur {issue.count:,} times?
5. **Similar Patterns**: Are there related code paths that might have the same issue?

Be precise and technical. The hawk does not miss its mark."""

        return prompt

    def _build_fix_prompt(
        self,
        analysis: str,
        context: CodeContext,
        issue: SentryIssue,
    ) -> str:
        """Build prompt for fix generation.

        The hawk prepares for the decisive strike.
        """
        # Build code context
        code_section = ""
        if context.surrounding_lines:
            code_lines = []
            for line_num, content in sorted(context.surrounding_lines.items()):
                code_lines.append(f"{line_num:4d} | {content}")
            code_section = "\n".join(code_lines)
        elif context.file_content:
            code_section = context.file_content[:3000]

        prompt = f"""You are BugHawk, an expert code fixer with the precision of a hunting hawk.
Based on the analysis below, generate a concrete fix for this error.

## Previous Analysis

{analysis}

## Source Code

**File**: {context.file_path}
**Error Line**: {context.error_line or 'Unknown'}

```
{code_section}
```

## Fix Requirements

Generate a precise fix with the following structure. Respond with ONLY valid JSON:

```json
{{
  "fix_description": "Brief description of the fix",
  "confidence_score": 0.85,
  "explanation": "Detailed explanation of why this fix works and what it addresses",
  "code_changes": {{
    "{context.file_path}": "--- a/{context.file_path}\\n+++ b/{context.file_path}\\n@@ ... @@\\n-old line\\n+new line"
  }},
  "test_suggestions": [
    "Description of test case 1",
    "Description of test case 2"
  ],
  "caveats": [
    "Any important caveats or edge cases"
  ]
}}
```

## Guidelines

1. **Precision**: Only change what's necessary to fix the bug
2. **Safety**: Ensure the fix doesn't introduce new issues
3. **Completeness**: Handle edge cases mentioned in the analysis
4. **Confidence**: Set confidence_score between 0.0 and 1.0 based on certainty
5. **Format**: Use unified diff format for code_changes

The hawk strikes once, with lethal precision. Make every change count."""

        return prompt

    def _parse_fix_response(self, response: str, issue_id: str) -> FixProposal:
        """Parse LLM response into FixProposal.

        The hawk processes its catch.

        Args:
            response: Raw LLM response
            issue_id: Issue ID for the fix

        Returns:
            Parsed FixProposal

        Raises:
            LLMResponseError: If parsing fails
        """
        # Extract JSON from response (may be wrapped in markdown code blocks)
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try parsing entire response as JSON
            json_str = response.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response as JSON: %s", e)
            # Create fallback proposal from raw response
            return FixProposal(
                issue_id=issue_id,
                fix_description="Unable to parse structured response",
                code_changes={},
                confidence_score=0.3,
                explanation=response[:1000],
            )

        # Validate and extract fields
        try:
            return FixProposal(
                issue_id=issue_id,
                fix_description=data.get("fix_description", "Generated fix"),
                code_changes=data.get("code_changes", {}),
                confidence_score=float(data.get("confidence_score", 0.5)),
                explanation=data.get("explanation", ""),
            )
        except (ValueError, TypeError) as e:
            logger.warning("Error creating FixProposal: %s", e)
            return FixProposal(
                issue_id=issue_id,
                fix_description=str(data.get("fix_description", "Generated fix")),
                code_changes={},
                confidence_score=0.3,
                explanation=response[:1000],
            )

    def analyze_and_fix(
        self,
        context: CodeContext,
        issue: SentryIssue,
        stack_trace: str | None = None,
    ) -> tuple[str, FixProposal]:
        """Analyze error and generate fix in one call.

        The hawk's complete hunting sequence - spot, analyze, strike.

        Args:
            context: Code context
            issue: Sentry issue
            stack_trace: Optional stack trace

        Returns:
            Tuple of (analysis, fix_proposal)
        """
        logger.info("Hawk executing full hunting sequence for issue: %s", issue.id)

        # Analyze
        analysis = self.analyze_error(context, issue, stack_trace)

        # Generate fix
        fix = self.suggest_fix(analysis, context, issue)

        return analysis, fix

    def validate_fix(
        self,
        fix: FixProposal,
        context: CodeContext,
    ) -> dict[str, Any]:
        """Validate a proposed fix for potential issues.

        The hawk reviews its catch before delivering.

        Args:
            fix: The proposed fix
            context: Code context

        Returns:
            Validation results dict
        """
        prompt = f"""You are BugHawk, reviewing a proposed code fix for safety and correctness.

## Proposed Fix

**Description**: {fix.fix_description}
**Confidence**: {fix.confidence_score:.0%}

**Code Changes**:
{json.dumps(fix.code_changes, indent=2)}

**Explanation**:
{fix.explanation}

## Review Request

Validate this fix and respond with ONLY valid JSON:

```json
{{
  "is_safe": true,
  "issues_found": [],
  "suggestions": [],
  "adjusted_confidence": 0.85
}}
```

Check for:
1. Potential new bugs introduced
2. Edge cases not handled
3. Performance implications
4. Security concerns
5. Code style consistency

The hawk must be certain before delivering its catch."""

        response = self.generate_fix(prompt, use_cache=False)

        # Parse response
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_str = response.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "is_safe": True,
                "issues_found": [],
                "suggestions": [],
                "adjusted_confidence": fix.confidence_score,
            }

    def clear_cache(self) -> None:
        """Clear the response cache.

        The hawk clears its memory for a fresh hunt.
        """
        if self.cache:
            self.cache.clear()
            logger.info("LLM response cache cleared")
