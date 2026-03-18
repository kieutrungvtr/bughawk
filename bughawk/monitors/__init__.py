"""Monitor integrations for BugHawk.

This module provides a unified interface for integrating with various
error monitoring platforms like Sentry, Datadog, Rollbar, and Bugsnag.
"""

from bughawk.monitors.base import (
    MonitorClient,
    MonitorAPIError,
    MonitorAuthenticationError,
    MonitorRateLimitError,
    MonitorNotFoundError,
)
from bughawk.monitors.registry import MonitorRegistry, get_monitor_client

__all__ = [
    "MonitorClient",
    "MonitorAPIError",
    "MonitorAuthenticationError",
    "MonitorRateLimitError",
    "MonitorNotFoundError",
    "MonitorRegistry",
    "get_monitor_client",
]
