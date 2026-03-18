"""Tests for Sentry client module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from bughawk.core.config import Settings
from bughawk.core.models import IssueSeverity, IssueStatus
from bughawk.sentry.client import (
    SentryAPIError,
    SentryAuthenticationError,
    SentryClient,
    SentryNotFoundError,
    SentryRateLimitError,
)


class TestSentryClientInitialization:
    """Tests for SentryClient initialization."""

    def test_client_initialization(self, mock_settings: Settings) -> None:
        """Test client initializes with correct settings."""
        client = SentryClient(settings=mock_settings)

        assert client.settings == mock_settings
        assert "Authorization" in client.session.headers
        assert client.session.headers["Authorization"] == "Bearer test-token-12345"

    def test_client_custom_base_url(self, mock_settings: Settings) -> None:
        """Test client with custom base URL."""
        custom_url = "https://custom-sentry.example.com/api/0"
        client = SentryClient(settings=mock_settings, base_url=custom_url)

        assert client.base_url == custom_url

    def test_client_default_headers(self, mock_settings: Settings) -> None:
        """Test client sets correct default headers."""
        client = SentryClient(settings=mock_settings)

        assert client.session.headers["Content-Type"] == "application/json"
        assert "User-Agent" in client.session.headers


class TestSentryClientGetIssues:
    """Tests for fetching issues from Sentry."""

    @patch.object(SentryClient, "_request")
    def test_get_issues_success(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
        mock_sentry_issues_response: list,
    ) -> None:
        """Test successful issue fetching."""
        mock_request.return_value = mock_sentry_issues_response

        client = SentryClient(settings=mock_settings)
        issues = client.get_issues(project="test-project")

        assert len(issues) == 2
        assert issues[0].id == "12345"
        assert issues[0].title == "TypeError: Cannot read property 'map' of undefined"
        assert issues[0].count == 42
        assert issues[0].level == IssueSeverity.ERROR

    @patch.object(SentryClient, "_request")
    def test_get_issues_with_filters(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test issue fetching with query filters."""
        mock_request.return_value = []

        client = SentryClient(settings=mock_settings)
        client.get_issues(
            project="test-project",
            filters={"query": "is:unresolved level:error"},
        )

        # Verify the request was made with correct parameters
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert "query" in str(call_args) or call_args[1].get("params")

    @patch.object(SentryClient, "_request")
    def test_get_issues_empty_response(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of empty issues response."""
        mock_request.return_value = []

        client = SentryClient(settings=mock_settings)
        issues = client.get_issues(project="test-project")

        assert issues == []


class TestSentryClientGetIssueDetails:
    """Tests for fetching issue details."""

    @patch.object(SentryClient, "_request")
    def test_get_issue_details_success(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test successful issue detail fetching."""
        mock_request.return_value = {
            "id": "12345",
            "title": "Test Error",
            "culprit": "test.py in main",
            "level": "error",
            "status": "unresolved",
            "count": 10,
            "firstSeen": "2024-01-01T00:00:00Z",
            "lastSeen": "2024-01-15T00:00:00Z",
            "metadata": {"url": "https://sentry.io/issues/12345/"},
        }

        client = SentryClient(settings=mock_settings)
        issue = client.get_issue_details("12345")

        assert issue.id == "12345"
        assert issue.title == "Test Error"
        assert issue.status == IssueStatus.UNRESOLVED

    @patch.object(SentryClient, "_request")
    def test_get_issue_details_not_found(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of non-existent issue."""
        mock_request.side_effect = SentryNotFoundError("Issue not found", 404)

        client = SentryClient(settings=mock_settings)

        with pytest.raises(SentryNotFoundError):
            client.get_issue_details("99999")


class TestSentryClientGetEvents:
    """Tests for fetching issue events."""

    @patch.object(SentryClient, "_request")
    def test_get_issue_events_success(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
        mock_sentry_event_response: dict,
    ) -> None:
        """Test successful event fetching."""
        mock_request.return_value = [mock_sentry_event_response]

        client = SentryClient(settings=mock_settings)
        events = client.get_issue_events("12345", limit=10)

        assert len(events) == 1
        assert events[0]["eventID"] == "event-abc123"

    @patch.object(SentryClient, "_request")
    def test_get_issue_events_with_full_details(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
        mock_sentry_event_response: dict,
    ) -> None:
        """Test event fetching with full details."""
        mock_request.return_value = [mock_sentry_event_response]

        client = SentryClient(settings=mock_settings)
        events = client.get_issue_events("12345", full=True)

        # Verify stack trace data is present
        assert "entries" in events[0]
        assert events[0]["entries"][0]["type"] == "exception"


class TestSentryClientErrorHandling:
    """Tests for error handling in Sentry client."""

    @patch.object(SentryClient, "_make_request")
    def test_authentication_error(
        self,
        mock_make_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of authentication errors."""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"detail": "Invalid token"}
        mock_make_request.return_value = mock_response

        client = SentryClient(settings=mock_settings)

        with pytest.raises(SentryAuthenticationError):
            client._request("GET", "/test/")

    @patch.object(SentryClient, "_make_request")
    def test_rate_limit_error(
        self,
        mock_make_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of rate limit errors."""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json.return_value = {"detail": "Rate limit exceeded"}
        mock_make_request.return_value = mock_response

        client = SentryClient(settings=mock_settings)

        with pytest.raises(SentryRateLimitError) as exc_info:
            client._request("GET", "/test/")

        assert exc_info.value.retry_after == 60

    @patch.object(SentryClient, "_make_request")
    def test_not_found_error(
        self,
        mock_make_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of not found errors."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.json.return_value = {"detail": "Not found"}
        mock_make_request.return_value = mock_response

        client = SentryClient(settings=mock_settings)

        with pytest.raises(SentryNotFoundError):
            client._request("GET", "/issues/99999/")

    @patch.object(SentryClient, "_make_request")
    def test_server_error(
        self,
        mock_make_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test handling of server errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"detail": "Internal server error"}
        mock_make_request.return_value = mock_response

        client = SentryClient(settings=mock_settings)

        with pytest.raises(SentryAPIError) as exc_info:
            client._request("GET", "/test/")

        assert exc_info.value.status_code == 500


class TestSentryClientHelpers:
    """Tests for helper methods in Sentry client."""

    def test_extract_stacktrace(self, mock_settings: Settings) -> None:
        """Test stacktrace extraction from event data."""
        event_data = {
            "entries": [
                {
                    "type": "exception",
                    "data": {
                        "values": [
                            {
                                "stacktrace": {
                                    "frames": [
                                        {
                                            "filename": "test.py",
                                            "lineNo": 42,
                                            "function": "test_func",
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                }
            ]
        }

        client = SentryClient(settings=mock_settings)
        stacktrace = client._extract_stacktrace(event_data)

        assert "test.py" in stacktrace
        assert "42" in stacktrace
        assert "test_func" in stacktrace

    def test_extract_stacktrace_empty(self, mock_settings: Settings) -> None:
        """Test stacktrace extraction with no exception data."""
        event_data = {"entries": []}
        client = SentryClient(settings=mock_settings)
        stacktrace = client._extract_stacktrace(event_data)

        assert stacktrace == ""

    def test_extract_stacktrace_multiple_frames(self, mock_settings: Settings) -> None:
        """Test stacktrace extraction with multiple frames."""
        event_data = {
            "entries": [
                {
                    "type": "exception",
                    "data": {
                        "values": [
                            {
                                "stacktrace": {
                                    "frames": [
                                        {
                                            "filename": "lib.py",
                                            "lineNo": 10,
                                            "function": "helper",
                                        },
                                        {
                                            "filename": "main.py",
                                            "lineNo": 20,
                                            "function": "main",
                                        },
                                    ]
                                }
                            }
                        ]
                    },
                }
            ]
        }

        client = SentryClient(settings=mock_settings)
        stacktrace = client._extract_stacktrace(event_data)

        assert "lib.py" in stacktrace
        assert "main.py" in stacktrace


class TestSentryClientProjects:
    """Tests for project-related methods."""

    @patch.object(SentryClient, "_request")
    def test_get_projects_success(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test successful project fetching."""
        mock_request.return_value = [
            {"slug": "project-1", "name": "Project 1"},
            {"slug": "project-2", "name": "Project 2"},
        ]

        client = SentryClient(settings=mock_settings)
        projects = client.get_projects("test-org")

        assert len(projects) == 2
        assert projects[0]["slug"] == "project-1"


class TestSentryClientComments:
    """Tests for comment/note methods."""

    @patch.object(SentryClient, "_request")
    def test_add_comment_success(
        self,
        mock_request: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """Test adding a comment to an issue."""
        mock_request.return_value = {"id": "note-123", "text": "Test comment"}

        client = SentryClient(settings=mock_settings)
        result = client.add_comment("12345", "Test comment")

        assert result is True
        mock_request.assert_called_once()
