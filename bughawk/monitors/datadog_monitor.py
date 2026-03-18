"""Datadog monitor client implementation.

This module provides a MonitorClient implementation for Datadog Error Tracking,
enabling BugHawk to fetch and analyze errors from Datadog.
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


class DatadogMonitorClient(MonitorClient):
    """Monitor client for Datadog Error Tracking.

    This client provides methods for fetching and managing errors from
    Datadog's Error Tracking feature.

    Note: Datadog uses different terminology:
    - "Issues" in BugHawk = "Error Groups" in Datadog
    - "Events" in BugHawk = "Error Occurrences" in Datadog

    Example:
        >>> client = DatadogMonitorClient(
        ...     api_key="your-api-key",
        ...     app_key="your-app-key",
        ...     site="datadoghq.com"
        ... )
        >>> issues = client.get_issues("my-service")
    """

    monitor_type = "datadog"

    # Datadog sites and their API endpoints
    SITES = {
        "datadoghq.com": "https://api.datadoghq.com",
        "us3.datadoghq.com": "https://api.us3.datadoghq.com",
        "us5.datadoghq.com": "https://api.us5.datadoghq.com",
        "datadoghq.eu": "https://api.datadoghq.eu",
        "ddog-gov.com": "https://api.ddog-gov.com",
        "ap1.datadoghq.com": "https://api.ap1.datadoghq.com",
    }

    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 0.5
    RETRY_STATUS_CODES = (500, 502, 503, 504)

    def __init__(
        self,
        api_key: str,
        app_key: str,
        site: str = "datadoghq.com",
        service: str = "",
        env: str = "",
        max_retries: int | None = None,
    ) -> None:
        """Initialize Datadog monitor client.

        Args:
            api_key: Datadog API key
            app_key: Datadog Application key
            site: Datadog site (e.g., "datadoghq.com", "datadoghq.eu")
            service: Default service name to filter by
            env: Default environment to filter by
            max_retries: Maximum retry attempts
        """
        self.api_key = api_key
        self.app_key = app_key
        self.site = site
        self.service = service
        self.env = env
        self.max_retries = max_retries or self.MAX_RETRIES

        self.base_url = self.SITES.get(site, f"https://api.{site}")
        self.session = self._create_session()
        logger.debug("DatadogMonitorClient initialized for site: %s", site)

    def _create_session(self) -> requests.Session:
        """Create and configure a requests session."""
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
                "DD-API-KEY": self.api_key,
                "DD-APPLICATION-KEY": self.app_key,
                "Content-Type": "application/json",
            }
        )

        return session

    def _request(
        self,
        method: str,
        endpoint: str,
        api_version: str = "v2",
        **kwargs: Any,
    ) -> dict[str, Any] | list[Any]:
        """Make an authenticated request to Datadog API."""
        url = f"{self.base_url}/api/{api_version}{endpoint}"
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

        if status_code == 401 or status_code == 403:
            logger.error("Authentication failed")
            raise MonitorAuthenticationError(
                "Authentication failed. Check your API and App keys.",
                status_code=status_code
            )

        if status_code == 404:
            logger.warning("Resource not found: %s", response.url)
            raise MonitorNotFoundError(
                f"Resource not found: {response.url}", status_code=404
            )

        if status_code == 429:
            retry_after = response.headers.get("X-RateLimit-Reset")
            retry_seconds = int(retry_after) if retry_after else 60
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

    # MonitorClient interface implementation

    def get_projects(self, organization: str) -> list[dict[str, Any]]:
        """Fetch all services (projects) from Datadog.

        In Datadog, "services" are roughly equivalent to projects.
        """
        logger.info("Fetching services from Datadog")

        # Use APM services endpoint
        endpoint = "/services"
        data = self._request_with_retry("GET", endpoint, api_version="v1")

        if not isinstance(data, dict):
            return []

        services = data.get("services", [])
        return [
            {
                "id": svc.get("name", ""),
                "slug": svc.get("name", ""),
                "name": svc.get("name", ""),
            }
            for svc in services
        ]

    def get_issues(
        self,
        project: str,
        filters: dict[str, Any] | None = None,
        organization: str | None = None,
        max_pages: int | None = None,
    ) -> list[SentryIssue]:
        """Fetch error tracking issues from Datadog.

        Args:
            project: Service name to filter by
            filters: Optional filters (e.g., {"env": "production", "status": "open"})
            organization: Not used for Datadog (org is implicit in API keys)
            max_pages: Maximum pages to fetch
        """
        service = project or self.service
        logger.info("Fetching error tracking issues for service: %s", service)

        filters = filters or {}
        env = filters.get("env", self.env)

        # Build query for error tracking
        query_parts = []
        if service:
            query_parts.append(f"service:{service}")
        if env:
            query_parts.append(f"env:{env}")

        # Add status filter
        status = filters.get("status", "open")
        if status:
            query_parts.append(f"status:{status}")

        query = " ".join(query_parts) if query_parts else "*"

        # Time range
        now = datetime.utcnow()
        from_time = filters.get("from", now - timedelta(days=30))
        to_time = filters.get("to", now)

        if isinstance(from_time, datetime):
            from_time = int(from_time.timestamp())
        if isinstance(to_time, datetime):
            to_time = int(to_time.timestamp())

        params = {
            "filter[query]": query,
            "filter[from]": from_time,
            "filter[to]": to_time,
            "page[limit]": 100,
        }

        all_issues: list[SentryIssue] = []
        page_count = 0
        cursor = None

        while True:
            if cursor:
                params["page[cursor]"] = cursor

            data = self._request_with_retry("GET", "/rum/error_tracking/issues", params=params)

            if not isinstance(data, dict):
                break

            issues_data = data.get("data", [])
            for item in issues_data:
                all_issues.append(self._parse_issue(item))

            page_count += 1
            if max_pages and page_count >= max_pages:
                break

            # Check for next page
            links = data.get("links", {})
            next_link = links.get("next")
            if not next_link:
                break

            # Extract cursor from next link
            cursor = data.get("meta", {}).get("page", {}).get("after")
            if not cursor:
                break

        logger.info("Fetched %d issues from Datadog", len(all_issues))
        return all_issues

    def get_issue_details(self, issue_id: str) -> SentryIssue:
        """Fetch detailed information about a specific error group."""
        logger.info("Fetching issue details for: %s", issue_id)

        endpoint = f"/rum/error_tracking/issues/{issue_id}"
        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        issue_data = data.get("data", data)
        return self._parse_issue(issue_data)

    def get_issue_events(
        self,
        issue_id: str,
        limit: int = 100,
        full: bool = False,
    ) -> list[dict[str, Any]]:
        """Fetch error occurrences for a specific issue."""
        logger.info("Fetching events for issue: %s (limit=%d)", issue_id, limit)

        # Datadog stores events separately, query by issue ID
        now = datetime.utcnow()
        from_time = int((now - timedelta(days=30)).timestamp())
        to_time = int(now.timestamp())

        params = {
            "filter[query]": f"issue.id:{issue_id}",
            "filter[from]": from_time,
            "filter[to]": to_time,
            "page[limit]": min(limit, 100),
        }

        data = self._request_with_retry("GET", "/rum/error_tracking/events", params=params)

        if not isinstance(data, dict):
            return []

        events = data.get("data", [])

        # Convert to BugHawk event format
        result = []
        for event in events[:limit]:
            attrs = event.get("attributes", {})
            result.append({
                "eventID": event.get("id", ""),
                "dateCreated": attrs.get("timestamp"),
                "message": attrs.get("error", {}).get("message", ""),
                "tags": [
                    {"key": k, "value": v}
                    for k, v in attrs.get("tags", {}).items()
                ],
                "entries": self._build_event_entries(attrs),
            })

        logger.info("Fetched %d events for issue %s", len(result), issue_id)
        return result

    def get_event_details(self, issue_id: str, event_id: str) -> dict[str, Any]:
        """Fetch full details for a specific event."""
        logger.info("Fetching event details: issue=%s, event=%s", issue_id, event_id)

        endpoint = f"/rum/error_tracking/events/{event_id}"
        data = self._request_with_retry("GET", endpoint)

        if not isinstance(data, dict):
            raise MonitorAPIError("Unexpected response format")

        event_data = data.get("data", {})
        attrs = event_data.get("attributes", {})

        return {
            "eventID": event_data.get("id", ""),
            "dateCreated": attrs.get("timestamp"),
            "message": attrs.get("error", {}).get("message", ""),
            "tags": [
                {"key": k, "value": v}
                for k, v in attrs.get("tags", {}).items()
            ],
            "entries": self._build_event_entries(attrs),
            "context": attrs.get("context", {}),
        }

    def update_issue_status(self, issue_id: str, status: str) -> bool:
        """Update the status of an error group."""
        status_map = {
            "resolved": "resolved",
            "unresolved": "open",
            "ignored": "ignored",
        }

        dd_status = status_map.get(status)
        if not dd_status:
            raise ValueError(f"Invalid status '{status}'. Must be one of: {set(status_map.keys())}")

        logger.info("Updating issue %s status to: %s", issue_id, dd_status)

        endpoint = f"/rum/error_tracking/issues/{issue_id}"
        payload = {
            "data": {
                "type": "issue",
                "attributes": {
                    "status": dd_status
                }
            }
        }

        data = self._request_with_retry("PATCH", endpoint, json=payload)

        if isinstance(data, dict):
            new_status = data.get("data", {}).get("attributes", {}).get("status")
            if new_status == dd_status:
                logger.info("Successfully updated issue %s status", issue_id)
                return True

        return False

    def test_connection(self) -> bool:
        """Test the connection to Datadog."""
        try:
            # Use validate endpoint
            self._request("GET", "/validate", api_version="v1")
            return True
        except MonitorAPIError:
            return False

    def close(self) -> None:
        """Close the session."""
        if self.session:
            self.session.close()

    # Helper methods

    def _parse_issue(self, data: dict[str, Any]) -> SentryIssue:
        """Parse Datadog error group into SentryIssue format."""
        attrs = data.get("attributes", {})

        # Map Datadog status to BugHawk status
        dd_status = attrs.get("status", "open")
        status_map = {
            "open": IssueStatus.UNRESOLVED,
            "resolved": IssueStatus.RESOLVED,
            "ignored": IssueStatus.IGNORED,
        }
        status = status_map.get(dd_status, IssueStatus.UNRESOLVED)

        # Map severity
        level_str = attrs.get("level", "error").lower()
        try:
            level = IssueSeverity(level_str)
        except ValueError:
            level = IssueSeverity.ERROR

        # Parse timestamps
        first_seen = attrs.get("first_seen")
        last_seen = attrs.get("last_seen")

        return SentryIssue(
            id=data.get("id", ""),
            title=attrs.get("name", attrs.get("message", "")),
            culprit=attrs.get("source_file", ""),
            level=level,
            count=int(attrs.get("count", 0)),
            first_seen=first_seen,
            last_seen=last_seen,
            status=status,
            metadata={
                "service": attrs.get("service"),
                "env": attrs.get("env"),
                "version": attrs.get("version"),
                "platform": "datadog",
            },
            tags=attrs.get("tags", {}),
        )

    def _build_event_entries(self, attrs: dict[str, Any]) -> list[dict[str, Any]]:
        """Build event entries in Sentry-compatible format."""
        entries = []

        error = attrs.get("error", {})
        if error:
            stack = error.get("stack", "")
            frames = self._parse_stack_trace(stack)

            entries.append({
                "type": "exception",
                "data": {
                    "values": [{
                        "type": error.get("type", "Error"),
                        "value": error.get("message", ""),
                        "stacktrace": {
                            "frames": frames
                        }
                    }]
                }
            })

        return entries

    def _parse_stack_trace(self, stack: str) -> list[dict[str, Any]]:
        """Parse a stack trace string into frame objects."""
        frames = []

        if not stack:
            return frames

        lines = stack.split("\n")
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try to parse common stack trace formats
            frame = {
                "filename": "unknown",
                "lineNo": 0,
                "function": "unknown",
                "inApp": True,
            }

            # Python format: File "path", line X, in func
            if 'File "' in line:
                try:
                    parts = line.split('"')
                    if len(parts) >= 2:
                        frame["filename"] = parts[1]
                    if "line " in line:
                        line_part = line.split("line ")[1].split(",")[0]
                        frame["lineNo"] = int(line_part)
                    if " in " in line:
                        frame["function"] = line.split(" in ")[-1]
                except (IndexError, ValueError):
                    pass

            # JavaScript format: at func (file:line:col)
            elif line.startswith("at "):
                try:
                    line = line[3:]  # Remove "at "
                    if "(" in line:
                        func = line.split("(")[0].strip()
                        loc = line.split("(")[1].rstrip(")")
                        frame["function"] = func
                    else:
                        loc = line

                    if ":" in loc:
                        parts = loc.rsplit(":", 2)
                        frame["filename"] = parts[0]
                        if len(parts) > 1:
                            frame["lineNo"] = int(parts[1])
                except (IndexError, ValueError):
                    pass

            frames.append(frame)

        # Reverse to match Sentry's order (most recent last)
        return list(reversed(frames))
