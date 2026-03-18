"""LLM provider registry for managing available LLM providers.

This module provides a registry pattern for discovering and instantiating
LLM providers based on configuration, similar to the monitor registry.
"""

from typing import Any, Type

from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


class LLMProviderRegistry:
    """Registry for LLM provider implementations.

    This class maintains a registry of available LLM providers and
    provides factory methods for creating provider instances.

    Example:
        >>> registry = LLMProviderRegistry()
        >>> registry.register("openai", OpenAIProvider)
        >>> provider = registry.create("openai", api_key="xxx")
    """

    _instance: "LLMProviderRegistry | None" = None
    _providers: dict[str, Type] = {}
    _default_models: dict[str, str] = {}

    def __new__(cls) -> "LLMProviderRegistry":
        """Singleton pattern to ensure one registry instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers = {}
            cls._instance._default_models = {}
        return cls._instance

    @classmethod
    def register(
        cls,
        provider_type: str,
        provider_class: Type,
        default_model: str = "",
    ) -> None:
        """Register an LLM provider class.

        Args:
            provider_type: Unique identifier for the provider (e.g., "openai")
            provider_class: The BaseLLMProvider subclass to register
            default_model: Default model for this provider
        """
        instance = cls()
        instance._providers[provider_type.lower()] = provider_class
        if default_model:
            instance._default_models[provider_type.lower()] = default_model
        logger.debug("Registered LLM provider: %s (default model: %s)", provider_type, default_model)

    @classmethod
    def get_provider_class(cls, provider_type: str) -> Type | None:
        """Get the provider class for a provider type.

        Args:
            provider_type: The provider type identifier

        Returns:
            The BaseLLMProvider subclass or None if not found
        """
        instance = cls()
        return instance._providers.get(provider_type.lower())

    @classmethod
    def get_default_model(cls, provider_type: str) -> str:
        """Get the default model for a provider type.

        Args:
            provider_type: The provider type identifier

        Returns:
            The default model name or empty string if not set
        """
        instance = cls()
        return instance._default_models.get(provider_type.lower(), "")

    @classmethod
    def create(cls, provider_type: str, **kwargs: Any):
        """Create an LLM provider instance.

        Args:
            provider_type: The provider type identifier
            **kwargs: Arguments to pass to the provider constructor

        Returns:
            An instance of the appropriate BaseLLMProvider subclass

        Raises:
            ValueError: If provider_type is not registered
        """
        provider_class = cls.get_provider_class(provider_type)
        if provider_class is None:
            available = cls.list_available()
            raise ValueError(
                f"Unknown LLM provider: {provider_type}. "
                f"Available providers: {', '.join(available)}"
            )

        logger.info("Creating %s LLM provider", provider_type)
        return provider_class(**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered provider types.

        Returns:
            List of registered provider type identifiers
        """
        instance = cls()
        return list(instance._providers.keys())

    @classmethod
    def is_registered(cls, provider_type: str) -> bool:
        """Check if a provider type is registered.

        Args:
            provider_type: The provider type identifier

        Returns:
            True if the provider type is registered
        """
        return cls.get_provider_class(provider_type) is not None

    @classmethod
    def get_provider_info(cls) -> dict[str, dict[str, str]]:
        """Get information about all registered providers.

        Returns:
            Dictionary with provider details including default models
        """
        instance = cls()
        info = {}
        for provider_type in instance._providers:
            info[provider_type] = {
                "default_model": instance._default_models.get(provider_type, ""),
            }
        return info


def get_llm_provider(provider_type: str, **kwargs):
    """Convenience function to get an LLM provider.

    Args:
        provider_type: The provider type (e.g., "openai", "anthropic")
        **kwargs: Configuration arguments for the provider

    Returns:
        An instance of the appropriate BaseLLMProvider

    Raises:
        ValueError: If provider_type is not registered
    """
    return LLMProviderRegistry.create(provider_type, **kwargs)
