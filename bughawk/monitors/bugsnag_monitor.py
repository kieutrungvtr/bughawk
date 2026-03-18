"""Bugsnag monitor client implementation.

This module provides a MonitorClient implementation for Bugsnag,
enabling BugHawk to fetch and analyze errors from Bugsnag.
"""

import time
from datetime import datetime
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


class BugsnagMonitorClient(MonitorClient):
    """Monitor client for Bugsnag.

    This client provides methods for fetching and managing errors from
    Bugsnag's error tracking platform.

    Note: Bugsnag terminology mapping:
    - "Issues" in BugHawk = "Errors" in Bugsnag
    - "Events" in BugHawk = "Events" in Bugsnag (same)

    Example:
        >>> client = BugsnagMonitorClient(
        ...     auth_token="your-personal-auth-token",
        ...     org_id="your-org-id"
        ... )
        >>> issues = client.get_issues("project-id")
    """

    monitor_type = "bugsnag"
    BASE_URL = "https://api.bugsnag.com"

    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    RETRY_STATUS_CODES = (500, 502, 503, 504)

    # Bugsnag severity mapping
    SEVERITY_MAP = {
        "error": IssueSeverity.ERROR,
        "warning": IssueSeverity.WARNING,
        "info": IssueSeverity.INFO,
    }

    def __init__(
        self,
        auth_token: str,
        org_id: str = "",
        project_id: str = "",
        max_retries: int | None = None,
    ) -> None:
        """Initialize Bugsnag monitor client.

        Args:
            auth_token: Bugsnag Personal Auth Token
            org_id: Organization ID
            project_id: Default project ID
            max_retries: Maximum retry attempts
        """
        self.auth_token = auth_token
        self.org_id = org_id
        self.project_id = project_id
        self.max_retries = max_retries or self.MAX_RETRIES

        self.session = self._create_session()
        logger.debug("BugsnagMonitorClient initialized")

    def _create_session(self) -> requests.Session:
        """Create and configure a requests session."""
        session = requests.Session()

        retry_strategy = Retry(
            total=self.max_retries,
            backoff_factor=self.RETRY_BACKOFF_FACTOR,
            status_forcelist=self.RETRY_STATUS_CODES,
            allowed_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            raise_on_status=False,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update(
            {
                "Authorization": f"token {self.auth_token}",
                "Content-Type": "application/json",
                "X-Version": "2",
            }
        )

        return session

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Make an authenticated request to Bugsnag API."""
        url = f"{self.BASE_URL}{endpoint}"
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

        if status_code in (401, 403):
            logger.error("Authentication failed")
            raise MonitorAuthenticationError(
                "Authentication failed. Check your auth token.",
                status_code=status_code
            )

        if status_code == 404:
            logger.warning("Resource not found: %s", response.url)
            raise MonitorNotFoundError(
                f"Resource not found: {response.url}", status_code=404
            )

        if status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            retry_seconds = int(retry_after)
            logger.warning("Rate limit exceeded. Retry after: %s seconds", retry_seconds)
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

    def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        max_retries: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Make a request with exponential backoff retry."""
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

    def _paginate(
        self,
        method: str,
        endpoint: str,
        max_pages: int | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        """Handle paginated API responses using Link headers."""
        all_results: list[Any] = []
        current_url = f"{self.BASE_URL}{endpoint}"
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
            elif isinstance(data, dict):
                # Some endpoints return {"errors": [...], ...}
                if "errors" in data:
                    all_results.extend(data["errors"])
                else:
                    all_results.append(data)

            page_count += 1
            if max_pages and page_count >= max_pages:
                break

            # Check for next page in Link header
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

            for part in parts[1:]:
                if 'rel="next"' in part:
                    return url

        return None

    # MonitorClient interface implementation

    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all projects from Bugsnag."""
        org_id = organization or self.org_id
        logger.info("Fetching projects for organization: %s", org_id)

        endpoint = f"/organizations/{org_id}/projects"
        data = self._paginate("GET", endpoint)

        return [
            {
                "id": proj.get("id", ""),
                "slug": proj.get("slug", proj.get("name", "").lower().replace(" ", "-")),
                "name": proj.get("name", ""),
            }
            for proj in data
        ]

    def get_issues(
        self,
        project: str,
        filters: dict[str, Any] | None = None,
        organization: str | None = None,
        max_pages: int | None = None,
    ) -> list[SentryIssue]:
        """Fetch errors from Bugsnag.

        Args:
            project: Project ID
            filters: Optional filters:
                - status: "open", "fixed", "snoozed", "ignored"
                - severity: "error", "warning", "info"
                - release_stage: Environment name (e.g., "production")
            organization: Not directly used (project ID is sufficient)
            max_pages: Maximum pages to fetch
        """
        project_id = project or self.project_id
        logger.info("Fetching errors for project: %s", project_id)

        filters = filters or {}

        params: dict[str, Any] = {
            "per_page": 100,
        }

        # Build filters
        filter_parts = []

        status = filters.get("status", "open")
        if status:
            filter_parts.append(f"status:{status}")

        severity = filters.get("severity")
        if severity:
            filter_parts.append(f"severity:{severity}")

        release_stage = filters.get("release_stage", filters.get("environment"))
        if release_stage:
            filter_parts.append(f"release_stage:{release_stage}")

        if filter_parts:
            params["filters"] = " ".join(filter_parts)

        endpoint = f"/projects/{project_id}/errors"
        all_issues: list[SentryIssue] = []

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        for item in data:
            all_issues.append(self._parse_issue(item))

        logger.info("Fetched %d errors from Bugsnag", len(all_issues))
        return all_issues

    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific error."""
        logger.info("Fetching error details for: %s", issue_id)

        # Bugsnag requires project_id to get error details
        # We'll try to get it from the issue_id or use the default
        endpoint = f"/projects/{self.project_id}/errors/{issue_id}"
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
        """Fetch events for a specific error."""
        logger.info("Fetching events for error: %s (limit=%d)", issue_id, limit)

        endpoint = f"/projects/{self.project_id}/errors/{issue_id}/events"
        params = {"per_page": min(limit, 100)}

        all_events: list[dict[str, Any]] = []
        max_pages = (limit + 99) // 100 if limit else None

        data = self._paginate("GET", endpoint, max_pages=max_pages, params=params)

        for event in data[:limit]:
            all_events.append(self._convert_event(event))

        logger.info("Fetched %d events for error %s", len(all_events), issue_id)
        return all_events

    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific event."""
        logger.info("Fetching event details: error=%s, event=%s", issue_id, event_id)

        endpoint = f"/projects/{self.project_id}/errors/{issue_id}/events/{event_id}"
        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        return self._convert_event(data)

    def update_issue_status(self, issue_id: str, status: str) -> bool:
        """Update the status of an error."""
        status_map = {
            "resolved": "fixed",
            "unresolved": "open",
            "ignored": "ignored",
        }

        bugsnag_status = status_map.get(status)
        if not bugsnag_status:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {set(status_map.keys())}")

        logger.info("Updating error %s status to: %s", issue_id, bugsnag_status)

        endpoint = f"/projects/{self.project_id}/errors/{issue_id}"
        payload = {"status": bugsnag_status}

        data = self._request_with_retry("PATCH", endpoint, json=payload)

        if isinstance(data, dict):
            new_status = data.get("status")
            if new_status == bugsnag_status:
                logger.info("Successfully updated error %s status", issue_id)
                return True

        return False

    def add_comment(self, issue_id: str, comment: str) -> bool:
        """Add a comment to an error."""
        if not comment.strip():
            raise ValueError("Comment cannot be empty")

        logger.info("Adding comment to error: %s", issue_id)

        endpoint = f"/projects/{self.project_id}/errors/{issue_id}/comments"
        payload = {"message": comment}

        data = self._request_with_retry("POST", endpoint, json=payload)

        if isinstance(data, dict) and data.get("id"):
            logger.info("Successfully added comment to error %s", issue_id)
            return True

        return False

    def test_connection(self) -> bool:
        """Test the connection to Bugsnag."""
        try:
            # Try to get current user to test auth
            self._request("GET", "/user")
            return True
        except MonitorAPIError:
            return False

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()

    # Helper methods

    def _parse_issue(self, data: dict[str, Any]) -> SentryIssue:
        """Parse Bugsnag error into SentryIssue format."""
        # Map Bugsnag status
        bugsnag_status = data.get("status", "open")
        status_map = {
            "open": IssueStatus.UNRESOLVED,
            "fixed": IssueStatus.RESOLVED,
            "snoozed": IssueStatus.IGNORED,
            "ignored": IssueStatus.IGNORED,
        }
        status = status_map.get(bugsnag_status, IssueStatus.UNRESOLVED)

        # Map severity
        severity_str = data.get("severity", "error")
        level = self.SEVERITY_MAP.get(severity_str, IssueSeverity.ERROR)

        # Parse timestamps
        first_seen = data.get("first_seen")
        last_seen = data.get("last_seen")

        # Get error class and message
        error_class = data.get("error_class", "Error")
        message = data.get("message", data.get("context", ""))
        title = f"{error_class}: {message}" if message else error_class

        return SentryIssue(
            id=data.get("id", ""),
            title=title,
            culprit=data.get("context", ""),
            level=level,
            count=int(data.get("events", data.get("events_count", 0))),
            first_seen=first_seen,
            last_seen=last_seen,
            status=status,
            metadata={
                "error_class": error_class,
                "release_stages": data.get("release_stages", []),
                "url": data.get("url"),
                "platform": "bugsnag",
            },
            tags={},
        )

    def _convert_event(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Bugsnag event to BugHawk event format."""
        exceptions = data.get("exceptions", [])

        # Build frames from first exception
        sentry_frames = []
        exception_type = "Error"
        exception_value = ""

        if exceptions:
            exc = exceptions[0]
            exception_type = exc.get("error_class", "Error")
            exception_value = exc.get("message", "")

            for frame in exc.get("stacktrace", []):
                sentry_frames.append({
                    "filename": frame.get("file", "unknown"),
                    "lineNo": frame.get("line_number", 0),
                    "function": frame.get("method", "unknown"),
                    "contextLine": frame.get("code", {}).get(str(frame.get("line_number", 0))),
                    "preContext": [],
                    "postContext": [],
                    "inApp": frame.get("in_project", True),
                })

        # Bugsnag frames are already in the right order (most recent first)
        # but Sentry format expects most recent last
        sentry_frames = list(reversed(sentry_frames))

        return {
            "eventID": data.get("id", ""),
            "dateCreated": data.get("received_at"),
            "message": exception_value,
            "tags": [
                {"key": k, "value": str(v)}
                for k, v in data.get("meta_data", {}).items()
                if isinstance(v, (str, int, float, bool))
            ],
            "entries": [{
                "type": "exception",
                "data": {
                    "values": [{
                        "type": exception_type,
                        "value": exception_value,
                        "stacktrace": {
                            "frames": sentry_frames
                        }
                    }]
                }
            }],
            "context": {
                "app": data.get("app", {}),
                "device": data.get("device", {}),
                "user": data.get("user", {}),
                "request": data.get("request", {}),
            },
        }
