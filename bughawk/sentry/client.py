"""Sentry API client for fetching issues and events.

This module provides a robust client for interacting with the Sentry API,
including authentication, pagination, retry logic, and comprehensive error handling.
"""

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bughawk.core.config import Settings, get_settings
from bughawk.core.models import Event, Issue, SentryIssue
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


# Custom Exceptions


class SentryAPIError(Exception):
    """Base exception for Sentry API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Initialize SentryAPIError.

        Args:
            message: Error description
            status_code: HTTP status code if available
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class SentryAuthenticationError(SentryAPIError):
    """Raised when authentication with Sentry fails."""

    pass


class SentryRateLimitError(SentryAPIError):
    """Raised when Sentry rate limit is exceeded."""

    def __init__(
        self, message: str, retry_after: int | None = None, status_code: int = 429
    ) -> None:
        """Initialize SentryRateLimitError.

        Args:
            message: Error description
            retry_after: Seconds to wait before retrying
            status_code: HTTP status code
        """
        super().__init__(message, status_code)
        self.retry_after = retry_after


class SentryNotFoundError(SentryAPIError):
    """Raised when a requested resource is not found."""

    pass


class SentryClient:
    """Client for interacting with Sentry API.

    This client provides methods for fetching and managing issues, events,
    and projects from Sentry. It includes:
    - Connection pooling via requests Session
    - Automatic retry with exponential backoff
    - Pagination support for large result sets
    - Comprehensive error handling

    Example:
        >>> client = SentryClient()
        >>> issues = client.get_issues("my-project", {"query": "is:unresolved"})
        >>> for issue in issues:
        ...     print(issue.title)
    """

    BASE_URL = "https://sentry.io/api/0"

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    RETRY_STATUS_CODES = (500, 502, 503, 504)

    def __init__(
        self,
        settings: Settings | None = None,
        base_url: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        """Initialize Sentry client.

        Args:
            settings: Application settings. If None, loads from environment.
            base_url: Optional custom base URL for the Sentry API.
            max_retries: Maximum number of retry attempts for failed requests.
        """
        self.settings = settings or get_settings()
        self.base_url = base_url or self.BASE_URL
        self.max_retries = max_retries or self.MAX_RETRIES

        self.session = self._create_session()
        logger.debug("SentryClient initialized with base URL: %s", self.base_url)

    def _create_session(self) -> requests.Session:
        """Create and configure a requests session with retry logic.

        Returns:
            Configured requests Session with retry adapter
        """
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_CODES,
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )

        # Mount adapter with retry strategy for both HTTP and HTTPS
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set authentication headers
        session.headers.update(
            {
                "Authorization": f"Bearer {self.settings.sentry_auth_token}",
                "Content-Type": "application/json",
            }
        )

        return session

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Make an authenticated request to Sentry API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint path (without base URL)
            **kwargs: Additional arguments passed to requests

        Returns:
            Parsed JSON response

        Raises:
            SentryAuthenticationError: If authentication fails (401)
            SentryNotFoundError: If resource is not found (404)
            SentryRateLimitError: If rate limit is exceeded (429)
            SentryAPIError: For other API errors
        """
        url = f"{self.base_url}{endpoint}"
        logger.debug("Making %s request to %s", method, url)

        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            logger.error("Request failed: %s", str(e))
            raise SentryAPIError(f"Request failed: {e}") from e

        return self._handle_response(response)

    def _handle_response(
        self, response: requests.Response
    ) -> dict[str, Any] | list[Any]:
        """Handle API response and raise appropriate exceptions.

        Args:
            response: The requests Response object

        Returns:
            Parsed JSON response

        Raises:
            SentryAuthenticationError: If authentication fails (401)
            SentryNotFoundError: If resource is not found (404)
            SentryRateLimitError: If rate limit is exceeded (429)
            SentryAPIError: For other API errors
        """
        status_code = response.status_code
        logger.debug("Response status: %d", status_code)

        if status_code == 401:
            logger.error("Authentication failed")
            raise SentryAuthenticationError(
                "Authentication failed. Check your auth token.", status_code=401
            )

        if status_code == 404:
            logger.warning("Resource not found: %s", response.url)
            raise SentryNotFoundError(
                f"Resource not found: {response.url}", status_code=404
            )

        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            logger.warning("Rate limit exceeded. Retry after: %s seconds", retry_after)
            raise SentryRateLimitError(
                "Rate limit exceeded", retry_after=retry_seconds, status_code=429
            )

        if status_code >= 400:
            error_msg = f"API error: {response.text}"
            logger.error("API error (status %d): %s", status_code, response.text)
            raise SentryAPIError(error_msg, status_code=status_code)

        # Success - parse JSON
        try:
            return response.json()
        except ValueError as e:
            logger.error("Failed to parse JSON response: %s", str(e))
            raise SentryAPIError("Invalid JSON response from API") from e

    def _paginate(
        self,
        method: str,
        endpoint: str,
        max_pages: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Handle paginated API responses.

        Sentry uses cursor-based pagination via Link headers. This method
        automatically follows pagination links to fetch all results.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            max_pages: Maximum number of pages to fetch (None for all)
            **kwargs: Additional arguments passed to requests

        Returns:
            Combined list of all results across pages
        """
        all_results: list[Any] = []
        current_url = f"{self.base_url}{endpoint}"
        page_count = 0

        while current_url:
            logger.debug("Fetching page %d from %s", page_count + 1, current_url)

            try:
                response = self.session.request(method, current_url, **kwargs)
                data = self._handle_response(response)
            except SentryAPIError:
                raise

            if isinstance(data, list):
                all_results.extend(data)
            else:
                all_results.append(data)

            page_count += 1
            if max_pages and page_count >= max_pages:
                logger.debug("Reached max pages limit: %d", max_pages)
                break

            # Check for next page in Link header
            current_url = self._get_next_page_url(response)

        logger.info("Fetched %d items across %d pages", len(all_results), page_count)
        return all_results

    def _get_next_page_url(self, response: requests.Response) -> str | None:
        """Extract next page URL from Link header.

        Sentry uses cursor-based pagination with Link headers in the format:
        <url>; rel="previous"; results="true"; cursor="xxx",
        <url>; rel="next"; results="true"; cursor="xxx"

        Args:
            response: The requests Response object

        Returns:
            Next page URL if available, None otherwise
        """
        link_header = response.headers.get("Link", "")

        for link in link_header.split(","):
            parts = link.strip().split(";")
            if len(parts) < 2:
                continue

            url_part = parts[0].strip()
            if not (url_part.startswith("<") and url_part.endswith(">")):
                continue

            url = url_part[1:-1]
            link_params = {}

            for part in parts[1:]:
                if "=" in part:
                    key, value = part.strip().split("=", 1)
                    link_params[key.strip()] = value.strip().strip('"')

            if link_params.get("rel") == "next" and link_params.get("results") == "true":
                return url

        return None

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Make a request with exponential backoff retry for rate limits.

        This method handles rate limit errors (429) with exponential backoff,
        respecting the Retry-After header when provided.

        Args:
            method: HTTP method
            endpoint: API endpoint path
            max_retries: Maximum retry attempts (defaults to self.max_retries)
            **kwargs: Additional arguments passed to requests

        Returns:
            Parsed JSON response

        Raises:
            SentryRateLimitError: If rate limit persists after all retries
            SentryAPIError: For other API errors
        """
        retries = max_retries if max_retries is not None else self.max_retries
        last_exception: SentryAPIError | None = None

        for attempt in range(retries + 1):
            try:
                return self._request(method, endpoint, **kwargs)
            except SentryRateLimitError as e:
                last_exception = e
                if attempt < retries:
                    wait_time = e.retry_after or (2**attempt * self.RETRY_BACKOFF_FACTOR)
                    logger.warning(
                        "Rate limited. Waiting %s seconds before retry %d/%d",
                        wait_time,
                        attempt + 1,
                        retries,
                    )
                    time.sleep(wait_time)
                else:
                    raise
            except SentryAPIError:
                raise

        if last_exception:
            raise last_exception
        raise SentryAPIError("Request failed after retries")

    # Public API Methods

    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all projects for an organization.

        Args:
            organization: Organization slug

        Returns:
            List of project dictionaries with keys like 'id', 'slug', 'name'

        Raises:
            SentryAPIError: If the API request fails
        """
        logger.info("Fetching projects for organization: %s", organization)
        endpoint = f"/organizations/{organization}/projects/"

        data = self._paginate("GET", endpoint)
        logger.info("Found %d projects", len(data))
        return data

    def get_issues(
        self,
        project: str,
        filters: dict[str, Any] | None = None,
        organization: str | None = None,
        max_pages: int | None = None,
    ) -> list[SentryIssue]:
        """Fetch issues from a Sentry project with optional filters.

        Args:
            project: Project slug
            filters: Optional filters (e.g., {"query": "is:unresolved", "statsPeriod": "24h"})
            organization: Organization slug (uses settings default if not provided)
            max_pages: Maximum number of pages to fetch (None for all)

        Returns:
            List of SentryIssue objects

        Raises:
            SentryAPIError: If the API request fails

        Example:
            >>> issues = client.get_issues(
            ...     "my-project",
            ...     filters={"query": "is:unresolved level:error"}
            ... )
        """
        org = organization or self.settings.sentry_org
        logger.info("Fetching issues for project: %s/%s", org, project)

        endpoint = f"/projects/{org}/{project}/issues/"
        params = filters or {}

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        issues: list[SentryIssue] = []
        for item in data:
            issues.append(self._parse_sentry_issue(item))

        logger.info("Parsed %d issues", len(issues))
        return issues

    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific issue.

        Args:
            issue_id: The Sentry issue ID

        Returns:
            SentryIssue object with full details

        Raises:
            SentryNotFoundError: If issue is not found
            SentryAPIError: If the API request fails
        """
        logger.info("Fetching issue details for: %s", issue_id)
        endpoint = f"/issues/{issue_id}/"

        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise SentryAPIError("Unexpected response format")

        return self._parse_sentry_issue(data)

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
            SentryNotFoundError: If issue is not found
            SentryAPIError: If the API request fails
        """
        logger.info("Fetching events for issue: %s (limit=%d)", issue_id, limit)
        endpoint = f"/issues/{issue_id}/events/"

        params: dict[str, Any] = {}
        if full:
            params["full"] = "true"

        # Calculate max pages needed based on limit (Sentry typically returns 100 per page)
        page_size = 100
        max_pages = (limit + page_size - 1) // page_size if limit else None

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        # Trim to requested limit
        result = data[:limit] if limit else data
        logger.info("Fetched %d events for issue %s", len(result), issue_id)
        return result

    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific event including stack trace.

        Args:
            issue_id: The parent issue ID
            event_id: The event ID to fetch

        Returns:
            Dictionary containing full event data including:
            - entries: List of data entries (exception, stacktrace, etc.)
            - context: Event context data
            - tags: Event tags
            - sdk: SDK information

        Raises:
            SentryNotFoundError: If event is not found
            SentryAPIError: If the API request fails
        """
        logger.info("Fetching event details: issue=%s, event=%s", issue_id, event_id)
        endpoint = f"/issues/{issue_id}/events/{event_id}/"

        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise SentryAPIError("Unexpected response format")

        logger.debug("Event contains %d entries", len(data.get("entries", [])))
        return data

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
            SentryNotFoundError: If issue is not found
            SentryAPIError: If the API request fails
        """
        valid_statuses = {"resolved", "unresolved", "ignored"}
        if status not in valid_statuses:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {valid_statuses}")

        logger.info("Updating issue %s status to: %s", issue_id, status)
        endpoint = f"/issues/{issue_id}/"

        payload = {"status": status}
        data = self._request_with_retry("PUT", endpoint, json=payload)

        if isinstance(data, dict) and data.get("status") == status:
            logger.info("Successfully updated issue %s status to %s", issue_id, status)
            return True

        logger.warning("Status update response did not confirm new status")
        return False

    def add_comment(self, issue_id: str, comment: str) -> bool:
        """Add a comment (note) to an issue.

        Args:
            issue_id: The issue ID to add comment to
            comment: The comment text

        Returns:
            True if comment was added successfully

        Raises:
            SentryNotFoundError: If issue is not found
            SentryAPIError: If the API request fails
        """
        if not comment.strip():
            raise ValueError("Comment cannot be empty")

        logger.info("Adding comment to issue: %s", issue_id)
        endpoint = f"/issues/{issue_id}/comments/"

        payload = {"text": comment}
        data = self._request_with_retry("POST", endpoint, json=payload)

        if isinstance(data, dict) and "id" in data:
            logger.info("Successfully added comment to issue %s", issue_id)
            return True

        logger.warning("Comment creation response did not contain expected data")
        return False

    # Legacy methods for backward compatibility

    def get_issues_legacy(self, project_slug: str | None = None) -> list[Issue]:
        """Fetch unresolved issues from Sentry (legacy method).

        This method is maintained for backward compatibility.
        Consider using get_issues() instead.

        Args:
            project_slug: Project slug. Uses settings default if not provided.

        Returns:
            List of Issue objects
        """
        project = project_slug or self.settings.sentry_project
        org = self.settings.sentry_org
        endpoint = f"/projects/{org}/{project}/issues/"

        data = self._request("GET", endpoint, params={"query": "is:unresolved"})

        issues: list[Issue] = []
        if isinstance(data, list):
            for item in data:
                issues.append(
                    Issue(
                        id=item.get("id", ""),
                        title=item.get("title", ""),
                        culprit=item.get("culprit", ""),
                        severity=item.get("level", "error"),
                        status=item.get("status", "unresolved"),
                        first_seen=item.get("firstSeen"),
                        last_seen=item.get("lastSeen"),
                        count=item.get("count", 0),
                        project=project,
                    )
                )
        return issues

    def get_issue_events_legacy(self, issue_id: str) -> list[Event]:
        """Fetch events for a specific issue (legacy method).

        This method is maintained for backward compatibility.
        Consider using get_issue_events() instead.

        Args:
            issue_id: The issue ID to fetch events for

        Returns:
            List of Event objects
        """
        endpoint = f"/issues/{issue_id}/events/"
        data = self._request("GET", endpoint)

        events: list[Event] = []
        if isinstance(data, list):
            for item in data:
                stacktrace = self._extract_stacktrace(item)
                events.append(
                    Event(
                        id=item.get("eventID", ""),
                        issue_id=issue_id,
                        message=item.get("message", ""),
                        timestamp=item.get("dateCreated"),
                        stacktrace=stacktrace,
                        tags={tag["key"]: tag["value"] for tag in item.get("tags", [])},
                    )
                )
        return events

    # Helper methods

    def _parse_sentry_issue(self, data: dict[str, Any]) -> SentryIssue:
        """Parse API response into a SentryIssue model.

        Args:
            data: Raw issue data from Sentry API

        Returns:
            Parsed SentryIssue object
        """
        return SentryIssue(
            id=data.get("id", ""),
            title=data.get("title", ""),
            culprit=data.get("culprit", ""),
            level=data.get("level", "error"),
            count=int(data.get("count", 0)),
            first_seen=data.get("firstSeen"),
            last_seen=data.get("lastSeen"),
            status=data.get("status", "unresolved"),
            metadata=data.get("metadata", {}),
            tags={tag["key"]: tag["value"] for tag in data.get("tags", [])},
        )

    def _extract_stacktrace(self, event_data: dict[str, Any]) -> str:
        """Extract stacktrace from event data.

        Args:
            event_data: Raw event data from Sentry API

        Returns:
            Formatted stacktrace string
        """
        entries = event_data.get("entries", [])
        for entry in entries:
            if entry.get("type") == "exception":
                values = entry.get("data", {}).get("values", [])
                if values:
                    frames = values[0].get("stacktrace", {}).get("frames", [])
                    lines = []
                    for frame in frames:
                        filename = frame.get("filename", "unknown")
                        lineno = frame.get("lineNo", "?")
                        function = frame.get("function", "unknown")
                        lines.append(f'  File "{filename}", line {lineno}, in {function}')
                    return "\n".join(lines)
        return ""
