"""Sentry monitor client implementation.

This module provides a MonitorClient implementation for Sentry,
wrapping the existing SentryClient with the unified interface.
"""

import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from bughawk.core.models import SentryIssue, IssueSeverity, IssueStatus
from bughawk.monitors.base import (
    MonitorClient,
    MonitorAPIError,
    MonitorAuthenticationError,
    MonitorNotFoundError,
    MonitorRateLimitError,
)
from bughawk.utils.logger import get_logger


logger = get_logger(__name__)


class SentryMonitorClient(MonitorClient):
    """Monitor client for Sentry.

    This client provides methods for fetching and managing issues, events,
    and projects from Sentry. It includes:
    - Connection pooling via requests Session
    - Automatic retry with exponential backoff
    - Pagination support for large result sets
    - Comprehensive error handling

    Example:
        >>> client = SentryMonitorClient(
        ...     auth_token="your-token",
        ...     org="your-org"
        ... )
        >>> issues = client.get_issues("my-project", {"query": "is:unresolved"})
        >>> for issue in issues:
        ...     print(issue.title)
    """

    monitor_type = "sentry"
    BASE_URL = "https://sentry.io/api/0"

    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    RETRY_STATUS_CODES = (500, 502, 503, 504)

    def __init__(
        self,
        auth_token: str,
        org: str,
        project: str = "",
        base_url: str | None = None,
        max_retries: int | None = None,
    ) -> None:
        """Initialize Sentry monitor client.

        Args:
            auth_token: Sentry API authentication token
            org: Organization slug
            project: Default project slug (optional)
            base_url: Optional custom base URL for the Sentry API
            max_retries: Maximum number of retry attempts for failed requests
        """
        self.auth_token = auth_token
        self.org = org
        self.project = project
        self.base_url = base_url or self.BASE_URL
        self.max_retries = max_retries or self.MAX_RETRIES

        self.session = self._create_session()
        logger.debug("SentryMonitorClient initialized with base URL: %s", self.base_url)

    def _create_session(self) -> requests.Session:
        """Create and configure a requests session with retry logic."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_CODES,
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update(
            {
                "Authorization": f"Bearer {self.auth_token}",
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
        """Make an authenticated request to Sentry API."""
        url = f"{self.base_url}{endpoint}"
        logger.debug("Making %s request to %s", method, url)

        try:
            response = self.session.request(method, url, **kwargs)
        except requests.RequestException as e:
            logger.error("Request failed: %s", str(e))
            raise MonitorAPIError(f"Request failed: {e}") from e

        return self._handle_response(response)

    def _handle_response(
        self, response: requests.Response
    ) -> dict[str, Any] | list[Any]:
        """Handle API response and raise appropriate exceptions."""
        status_code = response.status_code
        logger.debug("Response status: %d", status_code)

        if status_code == 401:
            logger.error("Authentication failed")
            raise MonitorAuthenticationError(
                "Authentication failed. Check your auth token.", status_code=401
            )

        if status_code == 404:
            logger.warning("Resource not found: %s", response.url)
            raise MonitorNotFoundError(
                f"Resource not found: {response.url}", status_code=404
            )

        if status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_seconds = int(retry_after) if retry_after else None
            logger.warning("Rate limit exceeded. Retry after: %s seconds", retry_after)
            raise MonitorRateLimitError(
                "Rate limit exceeded", retry_after=retry_seconds, status_code=429
            )

        if status_code >= 400:
            error_msg = f"API error: {response.text}"
            logger.error("API error (status %d): %s", status_code, response.text)
            raise MonitorAPIError(error_msg, status_code=status_code)

        try:
            return response.json()
        except ValueError as e:
            logger.error("Failed to parse JSON response: %s", str(e))
            raise MonitorAPIError("Invalid JSON response from API") from e

    def _paginate(
        self,
        method: str,
        endpoint: str,
        max_pages: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Handle paginated API responses."""
        all_results: list[Any] = []
        current_url = f"{self.base_url}{endpoint}"
        page_count = 0

        while current_url:
            logger.debug("Fetching page %d from %s", page_count + 1, current_url)

            try:
                response = self.session.request(method, current_url, **kwargs)
                data = self._handle_response(response)
            except MonitorAPIError:
                raise

            if isinstance(data, list):
                all_results.extend(data)
            else:
                all_results.append(data)

            page_count += 1
            if max_pages and page_count >= max_pages:
                logger.debug("Reached max pages limit: %d", max_pages)
                break

            current_url = self._get_next_page_url(response)

        logger.info("Fetched %d items across %d pages", len(all_results), page_count)
        return all_results

    def _get_next_page_url(self, response: requests.Response) -> str | None:
        """Extract next page URL from Link header."""
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
        """Make a request with exponential backoff retry for rate limits."""
        retries = max_retries if max_retries is not None else self.max_retries
        last_exception: MonitorAPIError | None = None

        for attempt in range(retries + 1):
            try:
                return self._request(method, endpoint, **kwargs)
            except MonitorRateLimitError as e:
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
            except MonitorAPIError:
                raise

        if last_exception:
            raise last_exception
        raise MonitorAPIError("Request failed after retries")

    # MonitorClient interface implementation

    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all projects for an organization."""
        org = organization or self.org
        logger.info("Fetching projects for organization: %s", org)
        endpoint = f"/organizations/{org}/projects/"

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
        """Fetch issues from a Sentry project with optional filters."""
        org = organization or self.org
        logger.info("Fetching issues for project: %s/%s", org, project)

        endpoint = f"/projects/{org}/{project}/issues/"
        params = filters or {}

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        issues: list[SentryIssue] = []
        for item in data:
            issues.append(self._parse_issue(item))

        logger.info("Parsed %d issues", len(issues))
        return issues

    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific issue."""
        logger.info("Fetching issue details for: %s", issue_id)
        endpoint = f"/issues/{issue_id}/"

        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        return self._parse_issue(data)

    def get_issue_events(
        self,
        issue_id: str,
        limit: int = 100,
        full: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch events for a specific issue."""
        logger.info("Fetching events for issue: %s (limit=%d)", issue_id, limit)
        endpoint = f"/issues/{issue_id}/events/"

        params: dict[str, Any] = {}
        if full:
            params["full"] = "true"

        page_size = 100
        max_pages = (limit + page_size - 1) // page_size if limit else None

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        result = data[:limit] if limit else data
        logger.info("Fetched %d events for issue %s", len(result), issue_id)
        return result

    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific event including stack trace."""
        logger.info("Fetching event details: issue=%s, event=%s", issue_id, event_id)
        endpoint = f"/issues/{issue_id}/events/{event_id}/"

        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        logger.debug("Event contains %d entries", len(data.get("entries", [])))
        return data

    def update_issue_status(
        self,
        issue_id: str,
        status: str,
    ) -> bool:
        """Update the status of an issue."""
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
        """Add a comment (note) to an issue."""
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

    def test_connection(self) -> bool:
        """Test the connection to Sentry."""
        try:
            self.get_projects(self.org)
            return True
        except MonitorNotFoundError:
            return True
        except MonitorAPIError:
            return False

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()

    # Helper methods

    def _parse_issue(self, data: dict[str, Any]) -> SentryIssue:
        """Parse API response into a SentryIssue model."""
        # Parse severity level
        level_str = data.get("level", "error")
        try:
            level = IssueSeverity(level_str)
        except ValueError:
            level = IssueSeverity.ERROR

        # Parse status
        status_str = data.get("status", "unresolved")
        try:
            status = IssueStatus(status_str)
        except ValueError:
            status = IssueStatus.UNRESOLVED

        return SentryIssue(
            id=data.get("id", ""),
            title=data.get("title", ""),
            culprit=data.get("culprit", ""),
            level=level,
            count=int(data.get("count", 0)),
            first_seen=data.get("firstSeen"),
            last_seen=data.get("lastSeen"),
            status=status,
            metadata=data.get("metadata", {}),
            tags={tag["key"]: tag.get("value", "") for tag in data.get("tags", []) if isinstance(tag, dict) and "key" in tag},
        )
