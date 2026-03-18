"""Rollbar monitor client implementation.

This module provides a MonitorClient implementation for Rollbar,
enabling BugHawk to fetch and analyze errors from Rollbar.
"""

import time
from datetime import datetime, timedelta
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


class RollbarMonitorClient(MonitorClient):
    """Monitor client for Rollbar.

    This client provides methods for fetching and managing errors from
    Rollbar's error tracking platform.

    Note: Rollbar terminology mapping:
    - "Issues" in BugHawk = "Items" in Rollbar
    - "Events" in BugHawk = "Occurrences" in Rollbar

    Example:
        >>> client = RollbarMonitorClient(
        ...     access_token="your-token",
        ...     account_slug="your-account"
        ... )
        >>> issues = client.get_issues("my-project")
    """

    monitor_type = "rollbar"
    BASE_URL = "https://api.rollbar.com/api/1"

    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    RETRY_STATUS_CODES = (500, 502, 503, 504)

    # Rollbar level mapping
    LEVEL_MAP = {
        "critical": IssueSeverity.FATAL,
        "error": IssueSeverity.ERROR,
        "warning": IssueSeverity.WARNING,
        "info": IssueSeverity.INFO,
        "debug": IssueSeverity.DEBUG,
    }

    def __init__(
        self,
        access_token: str,
        account_slug: str = "",
        project_slug: str = "",
        max_retries: int | None = None,
    ) -> None:
        """Initialize Rollbar monitor client.

        Args:
            access_token: Rollbar project or account access token
            account_slug: Account slug for account-level operations
            project_slug: Default project slug
            max_retries: Maximum retry attempts
        """
        self.access_token = access_token
        self.account_slug = account_slug
        self.project_slug = project_slug
        self.max_retries = max_retries or self.MAX_RETRIES

        self.session = self._create_session()
        logger.debug("RollbarMonitorClient initialized")

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
                "X-Rollbar-Access-Token": self.access_token,
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
        """Make an authenticated request to Rollbar API."""
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
                "Authentication failed. Check your access token.",
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
            data = response.json()
            # Rollbar wraps responses in {"err": 0, "result": ...}
            if isinstance(data, dict):
                if data.get("err") != 0:
                    raise MonitorAPIError(f"Rollbar error: {data.get('message', 'Unknown error')}")
                return data.get("result", data)
            return data
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

    # MonitorClient interface implementation

    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all projects from Rollbar."""
        logger.info("Fetching projects from Rollbar")

        endpoint = "/projects"
        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, list):
            data = [data] if data else []

        return [
            {
                "id": str(proj.get("id", "")),
                "slug": proj.get("slug", proj.get("name", "")),
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
        """Fetch items (issues) from Rollbar.

        Args:
            project: Project slug or ID
            filters: Optional filters:
                - status: "active", "resolved", "muted"
                - level: "critical", "error", "warning", "info", "debug"
                - environment: Environment name
            organization: Not used for Rollbar
            max_pages: Maximum pages to fetch
        """
        logger.info("Fetching items for project: %s", project)

        filters = filters or {}

        params: dict[str, Any] = {}

        # Status filter
        status = filters.get("status", "active")
        if status:
            params["status"] = status

        # Level filter
        level = filters.get("level")
        if level:
            params["level"] = level

        # Environment filter
        env = filters.get("environment")
        if env:
            params["environment"] = env

        all_issues: list[SentryIssue] = []
        page = 1
        page_count = 0

        while True:
            params["page"] = page

            endpoint = f"/items"
            data = self._request_with_retry("GET", endpoint, params=params)

            if not isinstance(data, list):
                items = data.get("items", []) if isinstance(data, dict) else []
            else:
                items = data

            if not items:
                break

            for item in items:
                all_issues.append(self._parse_issue(item))

            page_count += 1
            if max_pages and page_count >= max_pages:
                break

            page += 1

        logger.info("Fetched %d items from Rollbar", len(all_issues))
        return all_issues

    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific item."""
        logger.info("Fetching item details for: %s", issue_id)

        endpoint = f"/item/{issue_id}"
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
        """Fetch occurrences for a specific item."""
        logger.info("Fetching occurrences for item: %s (limit=%d)", issue_id, limit)

        endpoint = f"/item/{issue_id}/instances"
        params = {"page": 1}

        all_events: list[dict[str, Any]] = []

        while len(all_events) < limit:
            data = self._request_with_retry("GET", endpoint, params=params)

            if isinstance(data, dict):
                instances = data.get("instances", [])
            else:
                instances = data if isinstance(data, list) else []

            if not instances:
                break

            for instance in instances:
                if len(all_events) >= limit:
                    break
                all_events.append(self._convert_occurrence(instance))

            params["page"] += 1

        logger.info("Fetched %d occurrences for item %s", len(all_events), issue_id)
        return all_events

    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific occurrence."""
        logger.info("Fetching occurrence details: item=%s, occurrence=%s", issue_id, event_id)

        endpoint = f"/instance/{event_id}"
        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        return self._convert_occurrence(data)

    def update_issue_status(self, issue_id: str, status: str) -> bool:
        """Update the status of an item."""
        status_map = {
            "resolved": "resolved",
            "unresolved": "active",
            "ignored": "muted",
        }

        rollbar_status = status_map.get(status)
        if not rollbar_status:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {set(status_map.keys())}")

        logger.info("Updating item %s status to: %s", issue_id, rollbar_status)

        endpoint = f"/item/{issue_id}"
        payload = {"status": rollbar_status}

        data = self._request_with_retry("PATCH", endpoint, json=payload)

        if isinstance(data, dict):
            new_status = data.get("status")
            if new_status == rollbar_status:
                logger.info("Successfully updated item %s status", issue_id)
                return True

        return False

    def add_comment(self, issue_id: str, comment: str) -> bool:
        """Add a comment to an item."""
        if not comment.strip():
            raise ValueError("Comment cannot be empty")

        logger.info("Adding comment to item: %s", issue_id)

        endpoint = f"/item/{issue_id}/comments"
        payload = {"body": comment}

        data = self._request_with_retry("POST", endpoint, json=payload)

        if isinstance(data, dict) and data.get("id"):
            logger.info("Successfully added comment to item %s", issue_id)
            return True

        return False

    def test_connection(self) -> bool:
        """Test the connection to Rollbar."""
        try:
            self.get_projects("")
            return True
        except MonitorAPIError:
            return False

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()

    # Helper methods

    def _parse_issue(self, data: dict[str, Any]) -> SentryIssue:
        """Parse Rollbar item into SentryIssue format."""
        # Map Rollbar status
        rollbar_status = data.get("status", "active")
        status_map = {
            "active": IssueStatus.UNRESOLVED,
            "resolved": IssueStatus.RESOLVED,
            "muted": IssueStatus.IGNORED,
        }
        status = status_map.get(rollbar_status, IssueStatus.UNRESOLVED)

        # Map severity level
        level_str = data.get("level", "error")
        level = self.LEVEL_MAP.get(level_str, IssueSeverity.ERROR)

        # Parse timestamps
        first_occurrence = data.get("first_occurrence_timestamp")
        last_occurrence = data.get("last_occurrence_timestamp")

        if first_occurrence:
            first_occurrence = datetime.fromtimestamp(first_occurrence).isoformat()
        if last_occurrence:
            last_occurrence = datetime.fromtimestamp(last_occurrence).isoformat()

        # Get title from title or framework message
        title = data.get("title", "")
        if not title:
            last_occ = data.get("last_occurrence", {})
            body = last_occ.get("body", {})
            trace = body.get("trace", body.get("trace_chain", [{}])[0] if body.get("trace_chain") else {})
            exception = trace.get("exception", {})
            title = f"{exception.get('class', 'Error')}: {exception.get('message', '')}"

        return SentryIssue(
            id=str(data.get("id", data.get("counter", ""))),
            title=title,
            culprit=data.get("framework", ""),
            level=level,
            count=int(data.get("total_occurrences", data.get("occurrences", 0))),
            first_seen=first_occurrence,
            last_seen=last_occurrence,
            status=status,
            metadata={
                "environment": data.get("environment"),
                "framework": data.get("framework"),
                "platform": "rollbar",
                "counter": data.get("counter"),
            },
            tags={},
        )

    def _convert_occurrence(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Rollbar occurrence to BugHawk event format."""
        body = data.get("data", {}).get("body", data.get("body", {}))

        # Get trace info
        trace = body.get("trace", {})
        if not trace and body.get("trace_chain"):
            trace = body["trace_chain"][0]

        exception = trace.get("exception", {})
        frames = trace.get("frames", [])

        # Convert frames to Sentry format
        sentry_frames = []
        for frame in frames:
            sentry_frames.append({
                "filename": frame.get("filename", "unknown"),
                "lineNo": frame.get("lineno", 0),
                "function": frame.get("method", frame.get("function", "unknown")),
                "contextLine": frame.get("code"),
                "preContext": [],
                "postContext": [],
                "inApp": not frame.get("filename", "").startswith("/"),
            })

        timestamp = data.get("timestamp")
        if timestamp:
            timestamp = datetime.fromtimestamp(timestamp).isoformat()

        return {
            "eventID": str(data.get("id", "")),
            "dateCreated": timestamp,
            "message": exception.get("message", ""),
            "tags": [
                {"key": k, "value": str(v)}
                for k, v in data.get("data", {}).get("custom", {}).items()
            ],
            "entries": [{
                "type": "exception",
                "data": {
                    "values": [{
                        "type": exception.get("class", "Error"),
                        "value": exception.get("message", ""),
                        "stacktrace": {
                            "frames": sentry_frames
                        }
                    }]
                }
            }],
        }
