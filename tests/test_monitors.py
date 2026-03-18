"""Tests for Error Monitor Clients - Datadog, Rollbar, Bugsnag.

This test file is organized by feature groups:

Feature Groups:
1. Monitor Base Classes (Exception hierarchy, MonitorClient interface)
2. Datadog Monitor Client
   - Initialization and Session
   - Request handling and retry logic
   - Issue fetching and parsing
   - Event handling
   - Status updates
3. Rollbar Monitor Client
   - Initialization and Session
   - Request handling
   - Issue and occurrence management
   - Comments feature
4. Bugsnag Monitor Client
   - Initialization and Session
   - Pagination handling
   - Issue and event management
5. Integration Scenarios
"""

import json
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch, PropertyMock

import pytest
import requests


# =============================================================================
# Feature Group 1: Monitor Base Classes
# =============================================================================


class TestMonitorExceptions:
    """Tests for monitor exception hierarchy."""

    def test_monitor_api_error(self):
        """Test MonitorAPIError base exception."""
        from bughawk.monitors.base import MonitorAPIError

        error = MonitorAPIError("Test error", status_code=500)
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.status_code == 500

    def test_monitor_api_error_no_status(self):
        """Test MonitorAPIError without status code."""
        from bughawk.monitors.base import MonitorAPIError

        error = MonitorAPIError("Test error")
        assert error.status_code is None

    def test_monitor_authentication_error(self):
        """Test MonitorAuthenticationError."""
        from bughawk.monitors.base import MonitorAuthenticationError

        error = MonitorAuthenticationError("Auth failed", status_code=401)
        assert str(error) == "Auth failed"
        assert error.status_code == 401

    def test_monitor_rate_limit_error(self):
        """Test MonitorRateLimitError with retry_after."""
        from bughawk.monitors.base import MonitorRateLimitError

        error = MonitorRateLimitError("Rate limited", retry_after=60, status_code=429)
        assert error.retry_after == 60
        assert error.status_code == 429

    def test_monitor_not_found_error(self):
        """Test MonitorNotFoundError."""
        from bughawk.monitors.base import MonitorNotFoundError

        error = MonitorNotFoundError("Not found", status_code=404)
        assert str(error) == "Not found"
        assert error.status_code == 404

    def test_exception_inheritance(self):
        """Test exception inheritance chain."""
        from bughawk.monitors.base import (
            MonitorAPIError,
            MonitorAuthenticationError,
            MonitorRateLimitError,
            MonitorNotFoundError,
        )

        assert issubclass(MonitorAuthenticationError, MonitorAPIError)
        assert issubclass(MonitorRateLimitError, MonitorAPIError)
        assert issubclass(MonitorNotFoundError, MonitorAPIError)


class TestMonitorClientBase:
    """Tests for MonitorClient abstract base class."""

    def test_monitor_client_is_abstract(self):
        """Test that MonitorClient cannot be instantiated directly."""
        from bughawk.monitors.base import MonitorClient

        with pytest.raises(TypeError):
            MonitorClient()

    def test_monitor_client_context_manager(self):
        """Test context manager protocol."""
        from bughawk.monitors.base import MonitorClient

        class TestClient(MonitorClient):
            monitor_type = "test"
            closed = False

            def get_projects(self, org):
                return []

            def get_issues(self, project, filters=None, organization=None, max_pages=None):
                return []

            def get_issue_details(self, issue_id):
                return MagicMock()

            def get_issue_events(self, issue_id, limit=100, full=False):
                return []

            def get_event_details(self, issue_id, event_id):
                return {}

            def close(self):
                self.closed = True

        with TestClient() as client:
            assert client.monitor_type == "test"
        assert client.closed


# =============================================================================
# Feature Group 2: Datadog Monitor Client
# =============================================================================


class TestDatadogClientInitialization:
    """Tests for DatadogMonitorClient initialization."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_init_default_site(self, mock_session):
        """Test initialization with default site."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        client = DatadogMonitorClient(
            api_key="test-api-key",
            app_key="test-app-key",
        )

        assert client.api_key == "test-api-key"
        assert client.app_key == "test-app-key"
        assert client.site == "datadoghq.com"
        assert client.base_url == "https://api.datadoghq.com"
        assert client.monitor_type == "datadog"

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_init_eu_site(self, mock_session):
        """Test initialization with EU site."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        client = DatadogMonitorClient(
            api_key="key",
            app_key="app",
            site="datadoghq.eu",
        )

        assert client.base_url == "https://api.datadoghq.eu"

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_init_custom_site(self, mock_session):
        """Test initialization with custom site."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        client = DatadogMonitorClient(
            api_key="key",
            app_key="app",
            site="custom.datadog.com",
        )

        assert client.base_url == "https://api.custom.datadog.com"

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_init_with_service_env(self, mock_session):
        """Test initialization with service and env."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        client = DatadogMonitorClient(
            api_key="key",
            app_key="app",
            service="my-service",
            env="production",
        )

        assert client.service == "my-service"
        assert client.env == "production"


class TestDatadogClientSession:
    """Tests for Datadog session configuration."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_session_headers(self, mock_session_class):
        """Test that session has correct headers."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="api", app_key="app")

        # Check headers were updated
        mock_session.headers.update.assert_called_once()
        headers = mock_session.headers.update.call_args[0][0]
        assert headers["DD-API-KEY"] == "api"
        assert headers["DD-APPLICATION-KEY"] == "app"
        assert headers["Content-Type"] == "application/json"


class TestDatadogResponseHandling:
    """Tests for Datadog response handling."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_handle_401_response(self, mock_session_class):
        """Test 401 raises authentication error."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.monitors.base import MonitorAuthenticationError

        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        with pytest.raises(MonitorAuthenticationError) as exc_info:
            client._handle_response(mock_response)
        assert exc_info.value.status_code == 401

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_handle_404_response(self, mock_session_class):
        """Test 404 raises not found error."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.monitors.base import MonitorNotFoundError

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.url = "https://api.datadog.com/test"

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        with pytest.raises(MonitorNotFoundError) as exc_info:
            client._handle_response(mock_response)
        assert exc_info.value.status_code == 404

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_handle_429_response(self, mock_session_class):
        """Test 429 raises rate limit error."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.monitors.base import MonitorRateLimitError

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"X-RateLimit-Reset": "120"}

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        with pytest.raises(MonitorRateLimitError) as exc_info:
            client._handle_response(mock_response)
        assert exc_info.value.retry_after == 120

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_handle_success_response(self, mock_session_class):
        """Test successful response parsing."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"id": "1"}]}

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")
        result = client._handle_response(mock_response)

        assert result == {"data": [{"id": "1"}]}


class TestDatadogIssueHandling:
    """Tests for Datadog issue fetching and parsing."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_parse_issue(self, mock_session_class):
        """Test parsing Datadog issue to SentryIssue format."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.core.models import IssueSeverity, IssueStatus

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        issue_data = {
            "id": "dd-123",
            "attributes": {
                "name": "TypeError: null reference",
                "status": "open",
                "level": "error",
                "count": 42,
                "first_seen": "2024-01-01T10:00:00Z",
                "last_seen": "2024-01-15T14:30:00Z",
                "service": "web-app",
                "env": "production",
                "source_file": "src/app.py",
            },
        }

        result = client._parse_issue(issue_data)

        assert result.id == "dd-123"
        assert result.title == "TypeError: null reference"
        assert result.status == IssueStatus.UNRESOLVED
        assert result.level == IssueSeverity.ERROR
        assert result.count == 42
        assert result.metadata["platform"] == "datadog"

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_parse_issue_resolved_status(self, mock_session_class):
        """Test parsing resolved issue."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.core.models import IssueStatus

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        issue_data = {
            "id": "dd-456",
            "attributes": {
                "name": "Fixed bug",
                "status": "resolved",
                "level": "warning",
            },
        }

        result = client._parse_issue(issue_data)
        assert result.status == IssueStatus.RESOLVED


class TestDatadogStackTraceParser:
    """Tests for Datadog stack trace parsing."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_parse_python_stack_trace(self, mock_session_class):
        """Test parsing Python stack trace format."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        stack = '''File "/app/src/handler.py", line 42, in process_request
    result = data.process()
File "/app/src/data.py", line 15, in process
    return self.items.map(fn)'''

        frames = client._parse_stack_trace(stack)

        assert len(frames) == 2
        # Frames are reversed (most recent last)
        assert frames[0]["filename"] == "/app/src/data.py"
        assert frames[0]["lineNo"] == 15
        assert frames[1]["filename"] == "/app/src/handler.py"

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_parse_javascript_stack_trace(self, mock_session_class):
        """Test parsing JavaScript stack trace format."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        stack = '''at processData (/app/src/utils.js:42:15)
at handleRequest (/app/src/handler.js:10:5)'''

        frames = client._parse_stack_trace(stack)

        assert len(frames) == 2
        assert frames[0]["function"] == "handleRequest"
        assert frames[1]["function"] == "processData"


class TestDatadogStatusUpdate:
    """Tests for Datadog issue status updates."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_update_status_valid(self, mock_session_class):
        """Test updating status with valid value."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"attributes": {"status": "resolved"}}},
        )

        client = DatadogMonitorClient(api_key="key", app_key="app")
        result = client.update_issue_status("issue-1", "resolved")

        assert result is True

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_update_status_invalid(self, mock_session_class):
        """Test updating status with invalid value."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = DatadogMonitorClient(api_key="key", app_key="app")

        with pytest.raises(ValueError) as exc_info:
            client.update_issue_status("issue-1", "invalid_status")
        assert "Invalid status" in str(exc_info.value)


# =============================================================================
# Feature Group 3: Rollbar Monitor Client
# =============================================================================


class TestRollbarClientInitialization:
    """Tests for RollbarMonitorClient initialization."""

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_init_basic(self, mock_session):
        """Test basic initialization."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        client = RollbarMonitorClient(access_token="test-token")

        assert client.access_token == "test-token"
        assert client.monitor_type == "rollbar"
        assert client.BASE_URL == "https://api.rollbar.com/api/1"

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_init_with_slugs(self, mock_session):
        """Test initialization with account and project slugs."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        client = RollbarMonitorClient(
            access_token="token",
            account_slug="my-account",
            project_slug="my-project",
        )

        assert client.account_slug == "my-account"
        assert client.project_slug == "my-project"


class TestRollbarResponseHandling:
    """Tests for Rollbar response handling."""

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_handle_rollbar_error_response(self, mock_session_class):
        """Test handling Rollbar error format."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient
        from bughawk.monitors.base import MonitorAPIError

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "err": 1,
            "message": "Project not found",
        }

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = RollbarMonitorClient(access_token="token")

        with pytest.raises(MonitorAPIError) as exc_info:
            client._handle_response(mock_response)
        assert "Rollbar error" in str(exc_info.value)

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_handle_rollbar_success_response(self, mock_session_class):
        """Test handling Rollbar success format."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "err": 0,
            "result": {"items": [{"id": 1}]},
        }

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = RollbarMonitorClient(access_token="token")
        result = client._handle_response(mock_response)

        assert result == {"items": [{"id": 1}]}


class TestRollbarIssueHandling:
    """Tests for Rollbar issue handling."""

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_parse_issue(self, mock_session_class):
        """Test parsing Rollbar item to SentryIssue format."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient
        from bughawk.core.models import IssueSeverity, IssueStatus

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = RollbarMonitorClient(access_token="token")

        item_data = {
            "id": "rb-123",
            "counter": 456,
            "title": "TypeError in process",
            "status": "active",
            "level": "error",
            "total_occurrences": 100,
            "first_occurrence_timestamp": 1704067200,  # 2024-01-01
            "last_occurrence_timestamp": 1705276200,  # 2024-01-15
            "framework": "django",
            "environment": "production",
        }

        result = client._parse_issue(item_data)

        assert result.id == "rb-123"
        assert result.title == "TypeError in process"
        assert result.status == IssueStatus.UNRESOLVED
        assert result.level == IssueSeverity.ERROR
        assert result.count == 100
        assert result.metadata["platform"] == "rollbar"

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_level_mapping(self, mock_session_class):
        """Test Rollbar level mapping."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient
        from bughawk.core.models import IssueSeverity

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = RollbarMonitorClient(access_token="token")

        # Test all level mappings
        for rollbar_level, expected_severity in [
            ("critical", IssueSeverity.FATAL),
            ("error", IssueSeverity.ERROR),
            ("warning", IssueSeverity.WARNING),
            ("info", IssueSeverity.INFO),
            ("debug", IssueSeverity.DEBUG),
        ]:
            result = client._parse_issue({"level": rollbar_level})
            assert result.level == expected_severity


class TestRollbarComments:
    """Tests for Rollbar comment feature."""

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_add_comment_success(self, mock_session_class):
        """Test adding comment successfully."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"err": 0, "result": {"id": "comment-1"}},
        )

        client = RollbarMonitorClient(access_token="token")
        result = client.add_comment("issue-1", "This is a comment")

        assert result is True

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_add_comment_empty(self, mock_session_class):
        """Test adding empty comment raises error."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = RollbarMonitorClient(access_token="token")

        with pytest.raises(ValueError) as exc_info:
            client.add_comment("issue-1", "   ")
        assert "empty" in str(exc_info.value).lower()


# =============================================================================
# Feature Group 4: Bugsnag Monitor Client
# =============================================================================


class TestBugsnagClientInitialization:
    """Tests for BugsnagMonitorClient initialization."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_init_basic(self, mock_session):
        """Test basic initialization."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        client = BugsnagMonitorClient(auth_token="test-token")

        assert client.auth_token == "test-token"
        assert client.monitor_type == "bugsnag"
        assert client.BASE_URL == "https://api.bugsnag.com"

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_init_with_ids(self, mock_session):
        """Test initialization with org and project IDs."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        client = BugsnagMonitorClient(
            auth_token="token",
            org_id="org-123",
            project_id="proj-456",
        )

        assert client.org_id == "org-123"
        assert client.project_id == "proj-456"


class TestBugsnagSessionConfiguration:
    """Tests for Bugsnag session configuration."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_session_headers(self, mock_session_class):
        """Test session has correct headers."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="my-token")

        headers = mock_session.headers.update.call_args[0][0]
        assert headers["Authorization"] == "token my-token"
        assert headers["X-Version"] == "2"


class TestBugsnagPagination:
    """Tests for Bugsnag pagination handling."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_get_next_page_url(self, mock_session_class):
        """Test extracting next page URL from Link header."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        # Create mock response with Link header
        mock_response = MagicMock()
        mock_response.headers = {
            "Link": '<https://api.bugsnag.com/page1>; rel="prev", <https://api.bugsnag.com/page3>; rel="next"'
        }

        result = client._get_next_page_url(mock_response)
        assert result == "https://api.bugsnag.com/page3"

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_get_next_page_url_no_next(self, mock_session_class):
        """Test when no next page exists."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        mock_response = MagicMock()
        mock_response.headers = {
            "Link": '<https://api.bugsnag.com/page1>; rel="prev"'
        }

        result = client._get_next_page_url(mock_response)
        assert result is None


class TestBugsnagIssueHandling:
    """Tests for Bugsnag issue handling."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_parse_issue(self, mock_session_class):
        """Test parsing Bugsnag error to SentryIssue format."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient
        from bughawk.core.models import IssueSeverity, IssueStatus

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        error_data = {
            "id": "bs-123",
            "error_class": "TypeError",
            "message": "Cannot read property 'x' of null",
            "status": "open",
            "severity": "error",
            "events": 50,
            "first_seen": "2024-01-01T10:00:00Z",
            "last_seen": "2024-01-15T14:30:00Z",
            "context": "UserController#show",
            "release_stages": ["production", "staging"],
        }

        result = client._parse_issue(error_data)

        assert result.id == "bs-123"
        assert "TypeError" in result.title
        assert result.status == IssueStatus.UNRESOLVED
        assert result.level == IssueSeverity.ERROR
        assert result.count == 50
        assert result.metadata["platform"] == "bugsnag"

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_severity_mapping(self, mock_session_class):
        """Test Bugsnag severity mapping."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient
        from bughawk.core.models import IssueSeverity

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        for bugsnag_severity, expected in [
            ("error", IssueSeverity.ERROR),
            ("warning", IssueSeverity.WARNING),
            ("info", IssueSeverity.INFO),
        ]:
            result = client._parse_issue({"severity": bugsnag_severity})
            assert result.level == expected


class TestBugsnagEventConversion:
    """Tests for Bugsnag event conversion."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_convert_event(self, mock_session_class):
        """Test converting Bugsnag event to BugHawk format."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        event_data = {
            "id": "event-123",
            "received_at": "2024-01-15T14:30:00Z",
            "exceptions": [
                {
                    "error_class": "TypeError",
                    "message": "null reference",
                    "stacktrace": [
                        {
                            "file": "src/app.js",
                            "line_number": 42,
                            "method": "processData",
                            "in_project": True,
                        },
                        {
                            "file": "src/utils.js",
                            "line_number": 10,
                            "method": "helper",
                            "in_project": True,
                        },
                    ],
                }
            ],
            "app": {"version": "1.0.0"},
            "device": {"os_name": "Linux"},
        }

        result = client._convert_event(event_data)

        assert result["eventID"] == "event-123"
        assert result["dateCreated"] == "2024-01-15T14:30:00Z"
        assert result["message"] == "null reference"

        # Check frames (should be reversed)
        frames = result["entries"][0]["data"]["values"][0]["stacktrace"]["frames"]
        assert len(frames) == 2
        assert frames[0]["function"] == "helper"  # First in reversed order
        assert frames[1]["function"] == "processData"


class TestBugsnagComments:
    """Tests for Bugsnag comment feature."""

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_add_comment_success(self, mock_session_class):
        """Test adding comment successfully."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "comment-1"},
        )

        client = BugsnagMonitorClient(auth_token="token", project_id="proj-1")
        result = client.add_comment("error-1", "BugHawk fix applied")

        assert result is True

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_add_comment_empty(self, mock_session_class):
        """Test adding empty comment raises error."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        client = BugsnagMonitorClient(auth_token="token")

        with pytest.raises(ValueError):
            client.add_comment("error-1", "")


# =============================================================================
# Feature Group 5: Integration Scenarios
# =============================================================================


class TestMonitorConnectionTests:
    """Tests for connection testing across monitors."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_datadog_test_connection(self, mock_session_class):
        """Test Datadog connection test."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"valid": True},
        )

        client = DatadogMonitorClient(api_key="key", app_key="app")
        result = client.test_connection()

        assert result is True

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_rollbar_test_connection(self, mock_session_class):
        """Test Rollbar connection test."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"err": 0, "result": []},
        )

        client = RollbarMonitorClient(access_token="token")
        result = client.test_connection()

        assert result is True

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_bugsnag_test_connection(self, mock_session_class):
        """Test Bugsnag connection test."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session
        mock_session.request.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": "user-123"},
        )

        client = BugsnagMonitorClient(auth_token="token")
        result = client.test_connection()

        assert result is True


class TestMonitorContextManager:
    """Tests for context manager usage across monitors."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_datadog_context_manager(self, mock_session_class):
        """Test Datadog as context manager."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        with DatadogMonitorClient(api_key="key", app_key="app") as client:
            assert client.api_key == "key"

        mock_session.close.assert_called_once()

    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    def test_rollbar_context_manager(self, mock_session_class):
        """Test Rollbar as context manager."""
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        with RollbarMonitorClient(access_token="token") as client:
            assert client.access_token == "token"

        mock_session.close.assert_called_once()

    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_bugsnag_context_manager(self, mock_session_class):
        """Test Bugsnag as context manager."""
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        with BugsnagMonitorClient(auth_token="token") as client:
            assert client.auth_token == "token"

        mock_session.close.assert_called_once()


class TestRetryLogicAcrossMonitors:
    """Tests for retry logic implementation."""

    @patch("bughawk.monitors.datadog_monitor.time.sleep")
    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    def test_datadog_retry_on_rate_limit(self, mock_session_class, mock_sleep):
        """Test Datadog retries on rate limit."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.monitors.base import MonitorRateLimitError

        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # First call rate limited, second succeeds
        mock_session.request.side_effect = [
            MagicMock(status_code=429, headers={"X-RateLimit-Reset": "1"}),
            MagicMock(status_code=200, json=lambda: {"data": []}),
        ]

        client = DatadogMonitorClient(api_key="key", app_key="app", max_retries=2)

        # Should succeed after retry
        result = client._request_with_retry("GET", "/test")
        assert result == {"data": []}
        assert mock_session.request.call_count == 2


class TestStatusMappingConsistency:
    """Tests for consistent status mapping across monitors."""

    @patch("bughawk.monitors.datadog_monitor.requests.Session")
    @patch("bughawk.monitors.rollbar_monitor.requests.Session")
    @patch("bughawk.monitors.bugsnag_monitor.requests.Session")
    def test_resolved_status_mapping(
        self, mock_bs_session, mock_rb_session, mock_dd_session
    ):
        """Test 'resolved' maps correctly across monitors."""
        from bughawk.monitors.datadog_monitor import DatadogMonitorClient
        from bughawk.monitors.rollbar_monitor import RollbarMonitorClient
        from bughawk.monitors.bugsnag_monitor import BugsnagMonitorClient
        from bughawk.core.models import IssueStatus

        # Create clients
        dd_client = DatadogMonitorClient(api_key="k", app_key="a")
        rb_client = RollbarMonitorClient(access_token="t")
        bs_client = BugsnagMonitorClient(auth_token="t")

        # Test Datadog
        dd_issue = dd_client._parse_issue({"id": "1", "attributes": {"status": "resolved"}})
        assert dd_issue.status == IssueStatus.RESOLVED

        # Test Rollbar
        rb_issue = rb_client._parse_issue({"id": "1", "status": "resolved"})
        assert rb_issue.status == IssueStatus.RESOLVED

        # Test Bugsnag (uses "fixed" for resolved)
        bs_issue = bs_client._parse_issue({"id": "1", "status": "fixed"})
        assert bs_issue.status == IssueStatus.RESOLVED
