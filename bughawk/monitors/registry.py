"""Monitor registry for managing available monitor clients.

This module provides a registry pattern for discovering and instantiating
monitor clients based on configuration.
"""

from typing import Any, Type

from bughawk.monitors.base import MonitorClient, MonitorAPIError
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


class MonitorRegistry:
    """Registry for monitor client implementations.

    This class maintains a registry of available monitor clients and
    provides factory methods for creating client instances.

    Example:
        >>> registry = MonitorRegistry()
        >>> registry.register("sentry", SentryMonitorClient)
        >>> client = registry.create("sentry", auth_token="xxx", org="my-org")
    """

    _instance: "MonitorRegistry | None" = None
    _clients: dict[str, Type[MonitorClient]] = {}

    def __new__(cls) -> "MonitorRegistry":
        """Singleton pattern to ensure one registry instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}
        return cls._instance

    @classmethod
    def register(cls, monitor_type: str, client_class: Type[MonitorClient]) -> None:
        """Register a monitor client class.

        Args:
            monitor_type: Unique identifier for the monitor type (e.g., "sentry")
            client_class: The MonitorClient subclass to register
        """
        instance = cls()
        instance._clients[monitor_type.lower()] = client_class
        logger.debug("Registered monitor client: %s", monitor_type)

    @classmethod
    def get_client_class(cls, monitor_type: str) -> Type[MonitorClient] | None:
        """Get the client class for a monitor type.

        Args:
            monitor_type: The monitor type identifier

        Returns:
            The MonitorClient subclass or None if not found
        """
        instance = cls()
        return instance._clients.get(monitor_type.lower())

    @classmethod
    def create(cls, monitor_type: str, **kwargs: Any) -> MonitorClient:
        """Create a monitor client instance.

        Args:
            monitor_type: The monitor type identifier
            **kwargs: Arguments to pass to the client constructor

        Returns:
            An instance of the appropriate MonitorClient subclass

        Raises:
            ValueError: If monitor_type is not registered
        """
        client_class = cls.get_client_class(monitor_type)
        if client_class is None:
            available = cls.list_available()
            raise ValueError(
                f"Unknown monitor type: {monitor_type}. "
                f"Available types: {', '.join(available)}"
            )

        logger.info("Creating %s monitor client", monitor_type)
        return client_class(**kwargs)

    @classmethod
    def list_available(cls) -> list[str]:
        """List all registered monitor types.

        Returns:
            List of registered monitor type identifiers
        """
        instance = cls()
        return list(instance._clients.keys())

    @classmethod
    def is_registered(cls, monitor_type: str) -> bool:
        """Check if a monitor type is registered.

        Args:
            monitor_type: The monitor type identifier

        Returns:
            True if the monitor type is registered
        """
        return cls.get_client_class(monitor_type) is not None


def get_monitor_client(
    monitor_type: str,
    **kwargs: Any,
) -> MonitorClient:
    """Convenience function to get a monitor client.

    Args:
        monitor_type: The monitor type (e.g., "sentry", "datadog")
        **kwargs: Configuration arguments for the client

    Returns:
        An instance of the appropriate MonitorClient

    Raises:
        ValueError: If monitor_type is not registered
    """
    return MonitorRegistry.create(monitor_type, **kwargs)


# Auto-register built-in monitors when module is imported
def _register_builtin_monitors() -> None:
    """Register all built-in monitor implementations."""
    # Import here to avoid circular imports
    try:
        from bughawk.monitors.sentry_monitor import SentryMonitorClient
        MonitorRegistry.register("sentry", SentryMonitorClient)
    except ImportError as e:
        logger.debug("Sentry monitor not available: %s", e)

    try:
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        MonitorRegistry.register("datadog", DatadogMonitorClient)
    except ImportError as e:
        logger.debug("Datadog monitor not available: %s", e)

    try:
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient
        MonitorRegistry.register("rollbar", RollbarMonitorClient)
    except ImportError as e:
        logger.debug("Rollbar monitor not available: %s", e)

    try:
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient
        MonitorRegistry.register("bugsnag", BugsnagMonitorClient)
    except ImportError as e:
        logger.debug("Bugsnag monitor not available: %s", e)


# Register monitors on import
_register_builtin_monitors()
