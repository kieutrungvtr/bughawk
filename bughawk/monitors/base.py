"""Base classes for monitor integrations.

This module defines the abstract base class that all monitor clients
must implement, providing a unified interface for error monitoring platforms.
"""

from abc import ABC, abstractmethod
from typing import Any

from bughawk.core.models import SentryIssue


# Custom Exceptions


class MonitorAPIError(Exception):
    """Base exception for monitor API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize MonitorAPIError.

        Args:
            message: Error description
            status_code: HTTP status code if available
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class MonitorAuthenticationError(MonitorAPIError):
    """Raised when authentication with a monitor fails."""

    pass


class MonitorRateLimitError(MonitorAPIError):
    """Raised when monitor rate limit is exceeded."""

    def __init__(
        self, message: str, retry_after: int | None = None, status_code: int = 429
    ) -> None:
        """Initialize MonitorRateLimitError.

        Args:
            message: Error description
            retry_after: Seconds to wait before retrying
            status_code: HTTP status code
        """
        super().__init__(message, status_code)
        self.retry_after = retry_after


class MonitorNotFoundError(MonitorAPIError):
    """Raised when a requested resource is not found."""

    pass


class MonitorClient(ABC):
    """Abstract base class for monitor clients.

    All monitor integrations (Sentry, Datadog, Rollbar, Bugsnag, etc.)
    must implement this interface to provide a unified way of fetching
    and managing issues.

    Example:
        >>> class MyMonitorClient(MonitorClient):
        ...     def get_issues(self, project, filters=None, max_pages=None):
        ...         # Implementation
        ...         pass
    """

    # Class attribute identifying the monitor type
    monitor_type: str = "base"

    @abstractmethod
    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all projects for an organization.

        Args:
            organization: Organization slug or identifier

        Returns:
            List of project dictionaries with at least 'id', 'slug', 'name' keys

        Raises:
            MonitorAPIError: If the API request fails
        """
        pass

    @abstractmethod
    def get_issues(
        self,
        project: str,
        filters: dict[str, Any] | None = None,
        organization: str | None = None,
        max_pages: int | None = None,
    ) -> list[SentryIssue]:
        """Fetch issues from a project with optional filters.

        Note: Returns SentryIssue for backward compatibility. The model
        may be renamed to a more generic Issue type in the future.

        Args:
            project: Project slug or identifier
            filters: Optional filters specific to the monitor platform
            organization: Organization slug (uses settings default if not provided)
            max_pages: Maximum number of pages to fetch (None for all)

        Returns:
            List of SentryIssue objects (used as generic Issue type)

        Raises:
            MonitorAPIError: If the API request fails
        """
        pass

    @abstractmethod
    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific issue.

        Args:
            issue_id: The issue ID

        Returns:
            SentryIssue object with full details

        Raises:
            MonitorNotFoundError: If issue is not found
            MonitorAPIError: If the API request fails
        """
        pass

    @abstractmethod
    def get_issue_events(
        self,
        issue_id: str,
        limit: int = 100,
        full: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch events for a specific issue.

        Args:
            issue_id: The issue ID to fetch events for
            limit: Maximum number of events to return
            full: If True, fetch full event details including stack traces

        Returns:
            List of event dictionaries

        Raises:
            MonitorNotFoundError: If issue is not found
            MonitorAPIError: If the API request fails
        """
        pass

    @abstractmethod
    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific event including stack trace.

        Args:
            issue_id: The parent issue ID
            event_id: The event ID to fetch

        Returns:
            Dictionary containing full event data

        Raises:
            MonitorNotFoundError: If event is not found
            MonitorAPIError: If the API request fails
        """
        pass

    def update_issue_status(
        self,
        issue_id: str,
        status: str,
    ) -> bool:
        """Update the status of an issue.

        Args:
            issue_id: The issue ID to update
            status: New status ('resolved', 'unresolved', 'ignored')

        Returns:
            True if update was successful

        Raises:
            ValueError: If status is invalid
            MonitorNotFoundError: If issue is not found
            MonitorAPIError: If the API request fails
        """
        raise NotImplementedError("Status updates not supported by this monitor")

    def add_comment(self, issue_id: str, comment: str) -> bool:
        """Add a comment (note) to an issue.

        Args:
            issue_id: The issue ID to add comment to
            comment: The comment text

        Returns:
            True if comment was added successfully

        Raises:
            MonitorNotFoundError: If issue is not found
            MonitorAPIError: If the API request fails
        """
        raise NotImplementedError("Comments not supported by this monitor")

    def test_connection(self) -> bool:
        """Test the connection to the monitor.

        Returns:
            True if connection is successful

        Raises:
            MonitorAuthenticationError: If authentication fails
            MonitorAPIError: If connection fails
        """
        try:
            # Default implementation tries to get projects
            # Subclasses can override with more efficient checks
            self.get_projects("")
            return True
        except MonitorNotFoundError:
            # Organization not found but connection works
            return True
        except MonitorAPIError:
            return False

    def close(self) -> None:
        """Close any open connections.

        Subclasses should override this to clean up resources.
        """
        pass

    def __enter__(self) -> "MonitorClient":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()
