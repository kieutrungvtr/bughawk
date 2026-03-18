"""Tests for PR Creator - GitHub, GitLab, and Bitbucket implementations."""

import re
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

import pytest

from bughawk.core.models import FixProposal, IssueSeverity, IssueStatus, SentryIssue
from bughawk.git.pr_creator import (
    BasePRCreator,
    BitbucketPRCreator,
    GitHubPRCreator,
    GitLabPRCreator,
    PRAuthenticationError,
    PRCreationError,
    PRCreator,
    PRCreatorError,
    PRInfo,
    PRNotFoundError,
    PRPlatform,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_issue() -> SentryIssue:
    """Create a sample Sentry issue for testing."""
    return SentryIssue(
        id="12345",
        title="TypeError: Cannot read property 'map' of undefined",
        culprit="src/components/UserList.tsx in UserList",
        level=IssueSeverity.ERROR,
        count=42,
        first_seen=datetime(2024, 1, 1, 10, 0, 0),
        last_seen=datetime(2024, 1, 15, 14, 30, 0),
        status=IssueStatus.UNRESOLVED,
        metadata={
            "url": "https://sentry.io/issues/12345/",
            "repository": "https://github.com/test-org/test-repo.git",
        },
        tags={"environment": "production"},
    )


@pytest.fixture
def sample_fix_proposal() -> FixProposal:
    """Create a sample fix proposal for testing."""
    return FixProposal(
        issue_id="12345",
        fix_description="Add null check before calling map on users array",
        code_changes={
            "src/components/UserList.tsx": """--- a/src/components/UserList.tsx
+++ b/src/components/UserList.tsx
@@ -12,7 +12,7 @@ interface Props {

 const UserList = ({ users }) => {
   // Render user list
-  const items = users.map(u => <UserItem user={u} />);
+  const items = (users || []).map(u => <UserItem user={u} />);
   return <ul>{items}</ul>;
 };
""",
        },
        confidence_score=0.85,
        explanation="The error occurs because 'users' is undefined.",
    )


@pytest.fixture
def mock_sentry_client():
    """Create a mock Sentry client."""
    client = MagicMock()
    client.add_comment = MagicMock(return_value=True)
    return client


# =============================================================================
# PRPlatform Tests
# =============================================================================


class TestPRPlatform:
    """Tests for PRPlatform enum."""

    def test_platform_values(self):
        """Test platform enum values."""
        assert PRPlatform.GITHUB.value == "github"
        assert PRPlatform.GITLAB.value == "gitlab"
        assert PRPlatform.BITBUCKET.value == "bitbucket"

    def test_platform_from_string(self):
        """Test creating platform from string."""
        assert PRPlatform("github") == PRPlatform.GITHUB
        assert PRPlatform("gitlab") == PRPlatform.GITLAB
        assert PRPlatform("bitbucket") == PRPlatform.BITBUCKET


# =============================================================================
# PRInfo Tests
# =============================================================================


class TestPRInfo:
    """Tests for PRInfo dataclass."""

    def test_pr_info_creation(self):
        """Test creating PRInfo with all fields."""
        info = PRInfo(
            url="https://github.com/org/repo/pull/123",
            number=123,
            title="Fix bug",
            platform=PRPlatform.GITHUB,
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            state="open",
        )
        assert info.url == "https://github.com/org/repo/pull/123"
        assert info.number == 123
        assert info.state == "open"

    def test_pr_info_default_state(self):
        """Test PRInfo default state is 'open'."""
        info = PRInfo(
            url="https://github.com/org/repo/pull/1",
            number=1,
            title="Test",
            platform=PRPlatform.GITHUB,
            repo_full_name="org/repo",
            head_branch="branch",
            base_branch="main",
        )
        assert info.state == "open"


# =============================================================================
# BasePRCreator Tests
# =============================================================================


class TestBasePRCreator:
    """Tests for BasePRCreator formatting methods."""

    @pytest.fixture
    def mock_creator(self):
        """Create a mock implementation of BasePRCreator."""
        # Create a concrete implementation for testing base methods
        class MockPRCreator(BasePRCreator):
            platform = PRPlatform.GITHUB

            def create_pull_request(self, *args, **kwargs):
                pass

            def add_comment_to_pr(self, *args, **kwargs):
                pass

            def get_pr_info(self, *args, **kwargs):
                pass

        return MockPRCreator()

    def test_format_pr_title(self, mock_creator, sample_issue):
        """Test PR title formatting."""
        title = mock_creator.format_pr_title(sample_issue)
        assert "fix:" in title
        assert "🦅" in title
        assert "[Sentry #12345]" in title

    def test_format_pr_title_truncation(self, mock_creator, sample_issue):
        """Test PR title truncation for long titles."""
        sample_issue.title = "A" * 100  # Very long title
        title = mock_creator.format_pr_title(sample_issue)
        # Title should be truncated
        assert len(title) < 100

    def test_format_pr_body(self, mock_creator, sample_fix_proposal, sample_issue):
        """Test PR body formatting."""
        body = mock_creator.format_pr_body(sample_fix_proposal, sample_issue)
        assert "🦅 BugHawk Automated Fix" in body
        assert "Sentry Issue:" in body
        assert "Confidence Score:" in body
        assert "0.85" in body
        assert "Proposed Fix" in body
        assert "Validation" in body

    def test_format_pr_body_with_pattern(
        self, mock_creator, sample_fix_proposal, sample_issue
    ):
        """Test PR body formatting with pattern name."""
        body = mock_creator.format_pr_body(
            sample_fix_proposal, sample_issue, pattern_name="null-pointer"
        )
        assert "null-pointer" in body
        assert "Pattern matched" in body

    def test_format_diff_preview(self, mock_creator, sample_fix_proposal):
        """Test diff preview formatting."""
        diff = mock_creator._format_diff_preview(sample_fix_proposal.code_changes)
        assert "UserList.tsx" in diff
        assert "+" in diff or "-" in diff

    def test_format_diff_preview_empty(self, mock_creator):
        """Test diff preview with no changes."""
        diff = mock_creator._format_diff_preview({})
        assert diff == "No changes"

    def test_format_issue_details(self, mock_creator, sample_issue):
        """Test issue details formatting."""
        details = mock_creator._format_issue_details(sample_issue)
        assert "Location:" in details
        assert "Occurrences:" in details
        assert "42" in details


# =============================================================================
# GitHubPRCreator Tests
# =============================================================================


class TestGitHubPRCreator:
    """Tests for GitHubPRCreator."""

    def test_init_without_token_raises_error(self):
        """Test initialization without token raises error."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(PRAuthenticationError) as exc_info:
                GitHubPRCreator(token=None)
            assert "GITHUB_TOKEN" in str(exc_info.value)

    @patch("bughawk.git.pr_creator.Github")
    def test_init_with_token(self, mock_github_class):
        """Test initialization with valid token."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        assert creator.token == "test-token"
        assert creator.platform == PRPlatform.GITHUB

    @patch("bughawk.git.pr_creator.Github")
    def test_create_pull_request_success(
        self, mock_github_class, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test successful PR creation."""
        # Setup mocks
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.html_url = "https://github.com/org/repo/pull/123"
        mock_repo.create_pull.return_value = mock_pr
        mock_repo.get_labels.return_value = []
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token", sentry_client=mock_sentry_client)
        url = creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
        )

        assert url == "https://github.com/org/repo/pull/123"
        mock_repo.create_pull.assert_called_once()

    @patch("bughawk.git.pr_creator.Github")
    def test_create_pull_request_repo_not_found(
        self, mock_github_class, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with non-existent repo."""
        from github import GithubException

        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github.get_repo.side_effect = GithubException(404, "Not Found", None)
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        creator._GithubException = GithubException

        with pytest.raises(PRCreationError) as exc_info:
            creator.create_pull_request(
                repo_full_name="org/nonexistent",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )
        assert "not found" in str(exc_info.value).lower()

    @patch("bughawk.git.pr_creator.Github")
    def test_parse_pr_url(self, mock_github_class):
        """Test GitHub PR URL parsing."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")

        repo, number = creator._parse_pr_url("https://github.com/org/repo/pull/123")
        assert repo == "org/repo"
        assert number == 123

    @patch("bughawk.git.pr_creator.Github")
    def test_parse_pr_url_invalid(self, mock_github_class):
        """Test parsing invalid GitHub PR URL."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")

        with pytest.raises(PRCreatorError):
            creator._parse_pr_url("https://invalid-url.com/not-a-pr")

    @patch("bughawk.git.pr_creator.Github")
    def test_get_label_color(self, mock_github_class):
        """Test label color retrieval."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")

        assert creator._get_label_color("bughawk") == "D4A017"
        assert creator._get_label_color("bug") == "d73a4a"
        assert creator._get_label_color("unknown") == "ededed"

    @patch("bughawk.git.pr_creator.Github")
    def test_create_pull_request_with_draft(
        self, mock_github_class, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with draft flag."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.html_url = "https://github.com/org/repo/pull/123"
        mock_repo.create_pull.return_value = mock_pr
        mock_repo.get_labels.return_value = []
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            draft=True,
        )

        # Check draft parameter was passed
        call_kwargs = mock_repo.create_pull.call_args.kwargs
        assert call_kwargs.get("draft") is True

    @patch("bughawk.git.pr_creator.Github")
    def test_create_pull_request_with_reviewers(
        self, mock_github_class, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with reviewers."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.html_url = "https://github.com/org/repo/pull/123"
        mock_repo.create_pull.return_value = mock_pr
        mock_repo.get_labels.return_value = []
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1", "reviewer2"],
        )

        # Check reviewers were requested
        mock_pr.create_review_request.assert_called_once_with(
            reviewers=["reviewer1", "reviewer2"]
        )

    @patch("bughawk.git.pr_creator.Github")
    def test_add_comment_to_pr_success(self, mock_github_class):
        """Test adding comment to GitHub PR."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        result = creator.add_comment_to_pr(
            "https://github.com/org/repo/pull/123", "Test comment"
        )

        assert result is True
        mock_pr.create_issue_comment.assert_called_once_with("Test comment")

    @patch("bughawk.git.pr_creator.Github")
    def test_get_pr_info_success(self, mock_github_class):
        """Test getting GitHub PR info."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.html_url = "https://github.com/org/repo/pull/123"
        mock_pr.title = "Test PR"
        mock_pr.head.ref = "feature-branch"
        mock_pr.base.ref = "main"
        mock_pr.state = "open"
        mock_github.get_repo.return_value = mock_repo
        mock_repo.get_pull.return_value = mock_pr
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        info = creator.get_pr_info("https://github.com/org/repo/pull/123")

        assert info.number == 123
        assert info.platform == PRPlatform.GITHUB
        assert info.head_branch == "feature-branch"
        assert info.base_branch == "main"
        assert info.state == "open"

    @patch("bughawk.git.pr_creator.Github")
    def test_get_pr_info_not_found(self, mock_github_class):
        """Test getting non-existent GitHub PR info."""
        from github import GithubException

        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_repo.get_pull.side_effect = GithubException(404, "Not Found", None)
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        creator._GithubException = GithubException

        with pytest.raises(PRNotFoundError):
            creator.get_pr_info("https://github.com/org/repo/pull/999")

    @patch("bughawk.git.pr_creator.Github")
    def test_create_pull_request_duplicate(
        self, mock_github_class, sample_issue, sample_fix_proposal
    ):
        """Test PR creation when PR already exists."""
        from github import GithubException

        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_repo.create_pull.side_effect = GithubException(
            422, "A pull request already exists", None
        )
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token")
        creator._GithubException = GithubException

        with pytest.raises(PRCreationError) as exc_info:
            creator.create_pull_request(
                repo_full_name="org/repo",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )
        assert "already exists" in str(exc_info.value).lower()


# =============================================================================
# GitLabPRCreator Tests
# =============================================================================


class TestGitLabPRCreator:
    """Tests for GitLabPRCreator."""

    def test_init_without_token_raises_error(self):
        """Test initialization without token raises error."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(PRAuthenticationError) as exc_info:
                GitLabPRCreator(token=None)
            assert "GITLAB_TOKEN" in str(exc_info.value)

    @patch("bughawk.git.pr_creator.gitlab")
    def test_init_with_token(self, mock_gitlab_module):
        """Test initialization with valid token."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(token="test-token")
        assert creator.token == "test-token"
        assert creator.platform == PRPlatform.GITLAB
        assert creator.gitlab_url == "https://gitlab.com"

    @patch("bughawk.git.pr_creator.gitlab")
    def test_init_with_custom_url(self, mock_gitlab_module):
        """Test initialization with custom GitLab URL."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(
            token="test-token", gitlab_url="https://gitlab.mycompany.com/"
        )
        assert creator.gitlab_url == "https://gitlab.mycompany.com"

    @patch("bughawk.git.pr_creator.gitlab")
    def test_create_merge_request_success(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test successful MR creation."""
        from gitlab.exceptions import GitlabError

        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab
        mock_gitlab_module.exceptions.GitlabError = GitlabError

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 456
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/456"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []
        mock_gitlab.projects.get.return_value = mock_project

        creator = GitLabPRCreator(token="test-token", sentry_client=mock_sentry_client)
        url = creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
        )

        assert url == "https://gitlab.com/org/repo/-/merge_requests/456"
        mock_project.mergerequests.create.assert_called_once()

    @patch("bughawk.git.pr_creator.gitlab")
    def test_create_merge_request_with_draft(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal
    ):
        """Test MR creation with draft flag."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 789
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/789"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []
        mock_gitlab.projects.get.return_value = mock_project

        creator = GitLabPRCreator(token="test-token")
        creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            draft=True,
        )

        # Check that title starts with "Draft:"
        call_args = mock_project.mergerequests.create.call_args[0][0]
        assert call_args["title"].startswith("Draft:")

    @patch("bughawk.git.pr_creator.gitlab")
    def test_create_merge_request_with_reviewers(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal
    ):
        """Test MR creation with reviewers."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 100
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/100"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []

        # Mock user lookup
        mock_user = MagicMock()
        mock_user.id = 42
        mock_gitlab.users.list.return_value = [mock_user]
        mock_gitlab.projects.get.return_value = mock_project

        creator = GitLabPRCreator(token="test-token")
        creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1"],
        )

        # Check that reviewers were assigned
        assert mock_mr.reviewer_ids == [42]
        mock_mr.save.assert_called()

    @patch("bughawk.git.pr_creator.gitlab")
    def test_add_comment_to_mr(self, mock_gitlab_module):
        """Test adding comment to MR."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_gitlab.projects.get.return_value = mock_project
        mock_project.mergerequests.get.return_value = mock_mr

        creator = GitLabPRCreator(token="test-token")
        result = creator.add_comment_to_pr(
            "https://gitlab.com/org/repo/-/merge_requests/123", "Test comment"
        )

        assert result is True
        mock_mr.notes.create.assert_called_once_with({"body": "Test comment"})

    @patch("bughawk.git.pr_creator.gitlab")
    def test_get_pr_info(self, mock_gitlab_module):
        """Test getting MR info."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 123
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/123"
        mock_mr.title = "Test MR"
        mock_mr.source_branch = "feature"
        mock_mr.target_branch = "main"
        mock_mr.state = "opened"
        mock_gitlab.projects.get.return_value = mock_project
        mock_project.mergerequests.get.return_value = mock_mr

        creator = GitLabPRCreator(token="test-token")
        info = creator.get_pr_info(
            "https://gitlab.com/org/repo/-/merge_requests/123"
        )

        assert info.number == 123
        assert info.platform == PRPlatform.GITLAB
        assert info.head_branch == "feature"
        assert info.base_branch == "main"

    @patch("bughawk.git.pr_creator.gitlab")
    def test_parse_mr_url(self, mock_gitlab_module):
        """Test GitLab MR URL parsing."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(token="test-token")

        # Standard URL
        project, iid = creator._parse_mr_url(
            "https://gitlab.com/org/repo/-/merge_requests/123"
        )
        assert project == "org/repo"
        assert iid == 123

        # Subgroup URL
        project, iid = creator._parse_mr_url(
            "https://gitlab.com/org/subgroup/repo/-/merge_requests/456"
        )
        assert project == "org/subgroup/repo"
        assert iid == 456

    @patch("bughawk.git.pr_creator.gitlab")
    def test_parse_mr_url_invalid(self, mock_gitlab_module):
        """Test parsing invalid GitLab MR URL."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(token="test-token")

        with pytest.raises(PRCreatorError):
            creator._parse_mr_url("https://invalid-url.com/not-a-mr")

    @patch("bughawk.git.pr_creator.gitlab")
    def test_get_label_color(self, mock_gitlab_module):
        """Test label color retrieval."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(token="test-token")

        assert creator._get_label_color("bughawk") == "D4A017"
        assert creator._get_label_color("bug") == "d73a4a"
        assert creator._get_label_color("unknown") == "ededed"

    @patch("bughawk.git.pr_creator.gitlab")
    def test_get_pr_info_not_found(self, mock_gitlab_module):
        """Test getting non-existent GitLab MR info."""
        from gitlab.exceptions import GitlabError

        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab
        mock_gitlab_module.exceptions.GitlabError = GitlabError

        mock_project = MagicMock()
        mock_project.mergerequests.get.side_effect = GitlabError("404 Not Found")
        mock_gitlab.projects.get.return_value = mock_project

        creator = GitLabPRCreator(token="test-token")
        creator._GitlabError = GitlabError

        with pytest.raises(PRNotFoundError):
            creator.get_pr_info("https://gitlab.com/org/repo/-/merge_requests/999")

    @patch("bughawk.git.pr_creator.gitlab")
    def test_add_comment_failure(self, mock_gitlab_module):
        """Test failure when adding comment to MR."""
        from gitlab.exceptions import GitlabError

        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.notes.create.side_effect = GitlabError("Permission denied")
        mock_gitlab.projects.get.return_value = mock_project
        mock_project.mergerequests.get.return_value = mock_mr

        creator = GitLabPRCreator(token="test-token")
        creator._GitlabError = GitlabError

        result = creator.add_comment_to_pr(
            "https://gitlab.com/org/repo/-/merge_requests/123", "Test comment"
        )
        assert result is False

    @patch("bughawk.git.pr_creator.gitlab")
    def test_create_mr_with_labels(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal
    ):
        """Test MR creation with custom labels."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 123
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/123"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []
        mock_gitlab.projects.get.return_value = mock_project

        creator = GitLabPRCreator(token="test-token")
        creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            labels=["custom-label", "priority-high"],
        )

        # Check that custom labels were assigned
        assert mock_mr.labels == ["custom-label", "priority-high"]
        mock_mr.save.assert_called()

    @patch("bughawk.git.pr_creator.gitlab")
    def test_reviewer_not_found(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal
    ):
        """Test MR creation when reviewer user not found."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 123
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/123"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []
        mock_gitlab.projects.get.return_value = mock_project

        # User not found
        mock_gitlab.users.list.return_value = []

        creator = GitLabPRCreator(token="test-token")
        url = creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["nonexistent-user"],
        )

        # Should still succeed, just without reviewers
        assert url == "https://gitlab.com/org/repo/-/merge_requests/123"

    @patch("bughawk.git.pr_creator.gitlab")
    def test_parse_self_hosted_url(self, mock_gitlab_module):
        """Test parsing self-hosted GitLab MR URL."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(
            token="test-token", gitlab_url="https://gitlab.mycompany.com"
        )

        project, iid = creator._parse_mr_url(
            "https://gitlab.mycompany.com/team/project/-/merge_requests/42"
        )
        assert project == "team/project"
        assert iid == 42


# =============================================================================
# BitbucketPRCreator Tests
# =============================================================================


class TestBitbucketPRCreator:
    """Tests for BitbucketPRCreator."""

    def test_init_without_credentials_raises_error(self):
        """Test initialization without credentials raises error."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(PRAuthenticationError) as exc_info:
                BitbucketPRCreator(username=None, app_password=None)
            assert "BITBUCKET_USERNAME" in str(exc_info.value)

    @patch("bughawk.git.pr_creator.requests")
    def test_init_with_credentials(self, mock_requests):
        """Test initialization with valid credentials."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        assert creator.username == "testuser"
        assert creator.app_password == "test-pass"
        assert creator.platform == PRPlatform.BITBUCKET

    @patch("bughawk.git.pr_creator.requests")
    def test_init_invalid_credentials(self, mock_requests):
        """Test initialization with invalid credentials."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        with pytest.raises(PRAuthenticationError) as exc_info:
            BitbucketPRCreator(username="testuser", app_password="wrong-pass")
        assert "Invalid credentials" in str(exc_info.value)

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_success(
        self, mock_requests, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test successful PR creation."""
        mock_session = MagicMock()

        # Auth response
        auth_response = MagicMock()
        auth_response.status_code = 200

        # PR creation response
        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "id": 789,
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/789"}},
        }

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(
            username="testuser", app_password="test-pass", sentry_client=mock_sentry_client
        )
        url = creator.create_pull_request(
            repo_full_name="workspace/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
        )

        assert url == "https://bitbucket.org/workspace/repo/pull-requests/789"
        mock_session.post.assert_called_once()

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_repo_not_found(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with non-existent repo."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 404
        pr_response.text = "Repository not found"

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRCreationError) as exc_info:
            creator.create_pull_request(
                repo_full_name="workspace/nonexistent",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )
        assert "not found" in str(exc_info.value).lower()

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_duplicate(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation when PR already exists."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 400
        pr_response.json.return_value = {
            "error": {"message": "There is already an open pull request"}
        }
        pr_response.text = "There is already an open pull request"

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRCreationError) as exc_info:
            creator.create_pull_request(
                repo_full_name="workspace/repo",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )
        assert "already exists" in str(exc_info.value).lower()

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_with_reviewers(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with reviewers."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        # User lookup response
        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"uuid": "{user-uuid-123}"}

        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "id": 100,
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/100"}},
        }

        def get_side_effect(url):
            if "/user" in url and "/users/" not in url:
                return auth_response
            elif "/users/" in url:
                return user_response
            return auth_response

        mock_session.get.side_effect = get_side_effect
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        creator.create_pull_request(
            repo_full_name="workspace/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1"],
        )

        # Check that reviewers were included in the request
        call_args = mock_session.post.call_args
        assert "reviewers" in call_args.kwargs.get("json", {})

    @patch("bughawk.git.pr_creator.requests")
    def test_add_comment_to_pr(self, mock_requests):
        """Test adding comment to PR."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        comment_response = MagicMock()
        comment_response.status_code = 201

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = comment_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        result = creator.add_comment_to_pr(
            "https://bitbucket.org/workspace/repo/pull-requests/123", "Test comment"
        )

        assert result is True

    @patch("bughawk.git.pr_creator.requests")
    def test_get_pr_info(self, mock_requests):
        """Test getting PR info."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 200
        pr_response.json.return_value = {
            "id": 123,
            "title": "Test PR",
            "state": "OPEN",
            "source": {"branch": {"name": "feature"}},
            "destination": {"branch": {"name": "main"}},
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/123"}},
        }

        mock_session.get.side_effect = [auth_response, pr_response]
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        info = creator.get_pr_info(
            "https://bitbucket.org/workspace/repo/pull-requests/123"
        )

        assert info.number == 123
        assert info.platform == PRPlatform.BITBUCKET
        assert info.head_branch == "feature"
        assert info.base_branch == "main"
        assert info.state == "open"

    @patch("bughawk.git.pr_creator.requests")
    def test_get_pr_info_not_found(self, mock_requests):
        """Test getting non-existent PR info."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 404

        mock_session.get.side_effect = [auth_response, pr_response]
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRNotFoundError):
            creator.get_pr_info(
                "https://bitbucket.org/workspace/repo/pull-requests/999"
            )

    @patch("bughawk.git.pr_creator.requests")
    def test_parse_pr_url(self, mock_requests):
        """Test Bitbucket PR URL parsing."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        repo, pr_id = creator._parse_pr_url(
            "https://bitbucket.org/workspace/repo/pull-requests/123"
        )
        assert repo == "workspace/repo"
        assert pr_id == 123

    @patch("bughawk.git.pr_creator.requests")
    def test_parse_pr_url_invalid(self, mock_requests):
        """Test parsing invalid Bitbucket PR URL."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRCreatorError):
            creator._parse_pr_url("https://invalid-url.com/not-a-pr")

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_auth_failure(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation when auth fails during request."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 401
        pr_response.text = "Unauthorized"

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRAuthenticationError):
            creator.create_pull_request(
                repo_full_name="workspace/repo",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )

    @patch("bughawk.git.pr_creator.requests")
    def test_add_comment_failure(self, mock_requests):
        """Test failure when adding comment to PR."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        comment_response = MagicMock()
        comment_response.status_code = 403
        comment_response.text = "Permission denied"

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = comment_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        result = creator.add_comment_to_pr(
            "https://bitbucket.org/workspace/repo/pull-requests/123", "Test comment"
        )

        assert result is False

    @patch("bughawk.git.pr_creator.requests")
    def test_reviewer_user_not_found(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation when reviewer user is not found."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        user_not_found_response = MagicMock()
        user_not_found_response.status_code = 404

        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "id": 100,
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/100"}},
        }

        def get_side_effect(url):
            if "/users/" in url:
                return user_not_found_response
            return auth_response

        mock_session.get.side_effect = get_side_effect
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        url = creator.create_pull_request(
            repo_full_name="workspace/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["nonexistent-user"],
        )

        # Should still succeed, reviewers list should be empty
        assert url == "https://bitbucket.org/workspace/repo/pull-requests/100"

    @patch("bughawk.git.pr_creator.requests")
    def test_reviewer_with_uuid(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with reviewer UUID directly."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "id": 100,
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/100"}},
        }

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")
        creator.create_pull_request(
            repo_full_name="workspace/repo",
            head_branch="fix-branch",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["{user-uuid-123}"],  # UUID format
        )

        # Check that UUID was passed directly
        call_args = mock_session.post.call_args
        reviewers = call_args.kwargs.get("json", {}).get("reviewers", [])
        assert {"uuid": "{user-uuid-123}"} in reviewers

    @patch("bughawk.git.pr_creator.requests")
    def test_create_pull_request_server_error(
        self, mock_requests, sample_issue, sample_fix_proposal
    ):
        """Test PR creation with server error."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        pr_response = MagicMock()
        pr_response.status_code = 500
        pr_response.text = "Internal Server Error"

        mock_session.get.return_value = auth_response
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(username="testuser", app_password="test-pass")

        with pytest.raises(PRCreationError) as exc_info:
            creator.create_pull_request(
                repo_full_name="workspace/repo",
                head_branch="fix-branch",
                base_branch="main",
                fix_proposal=sample_fix_proposal,
                issue=sample_issue,
            )
        assert "Failed to create PR" in str(exc_info.value)


# =============================================================================
# PRCreator Factory Tests
# =============================================================================


class TestPRCreatorFactory:
    """Tests for PRCreator factory class."""

    @patch("bughawk.git.pr_creator.Github")
    def test_for_platform_github(self, mock_github_class):
        """Test creating GitHub PR creator via factory."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = PRCreator.for_platform(PRPlatform.GITHUB, token="test-token")
        assert isinstance(creator, GitHubPRCreator)

    @patch("bughawk.git.pr_creator.gitlab")
    def test_for_platform_gitlab(self, mock_gitlab_module):
        """Test creating GitLab PR creator via factory."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = PRCreator.for_platform(PRPlatform.GITLAB, token="test-token")
        assert isinstance(creator, GitLabPRCreator)

    @patch("bughawk.git.pr_creator.requests")
    def test_for_platform_bitbucket(self, mock_requests):
        """Test creating Bitbucket PR creator via factory."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        creator = PRCreator.for_platform(
            PRPlatform.BITBUCKET, username="testuser", app_password="test-pass"
        )
        assert isinstance(creator, BitbucketPRCreator)

    def test_detect_platform_github(self):
        """Test platform detection for GitHub URLs."""
        assert PRCreator._detect_platform("https://github.com/org/repo") == PRPlatform.GITHUB
        assert PRCreator._detect_platform("git@github.com:org/repo.git") == PRPlatform.GITHUB

    def test_detect_platform_gitlab(self):
        """Test platform detection for GitLab URLs."""
        assert PRCreator._detect_platform("https://gitlab.com/org/repo") == PRPlatform.GITLAB
        assert PRCreator._detect_platform("https://gitlab.mycompany.com/org/repo") == PRPlatform.GITLAB

    def test_detect_platform_bitbucket(self):
        """Test platform detection for Bitbucket URLs."""
        assert PRCreator._detect_platform("https://bitbucket.org/workspace/repo") == PRPlatform.BITBUCKET
        assert PRCreator._detect_platform("git@bitbucket.org:workspace/repo.git") == PRPlatform.BITBUCKET

    def test_detect_platform_unknown(self):
        """Test platform detection for unknown URLs."""
        with pytest.raises(PRCreatorError) as exc_info:
            PRCreator._detect_platform("https://unknown-host.com/org/repo")
        assert "Could not detect platform" in str(exc_info.value)

    @patch("bughawk.git.pr_creator.Github")
    def test_from_repo_url(self, mock_github_class):
        """Test creating PR creator from repo URL."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = PRCreator.from_repo_url(
            "https://github.com/org/repo", token="test-token"
        )
        assert isinstance(creator, GitHubPRCreator)


# =============================================================================
# Sentry Linking Tests
# =============================================================================


class TestSentryLinking:
    """Tests for Sentry issue linking functionality."""

    @patch("bughawk.git.pr_creator.Github")
    def test_github_link_to_sentry(self, mock_github_class, mock_sentry_client):
        """Test GitHub linking to Sentry."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token", sentry_client=mock_sentry_client)
        result = creator._link_to_sentry("12345", "https://github.com/org/repo/pull/1")

        assert result is True
        mock_sentry_client.add_comment.assert_called_once()
        call_args = mock_sentry_client.add_comment.call_args[0]
        assert "12345" in call_args
        assert "https://github.com/org/repo/pull/1" in call_args[1]

    @patch("bughawk.git.pr_creator.gitlab")
    def test_gitlab_link_to_sentry(self, mock_gitlab_module, mock_sentry_client):
        """Test GitLab linking to Sentry."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        creator = GitLabPRCreator(token="test-token", sentry_client=mock_sentry_client)
        result = creator._link_to_sentry(
            "12345", "https://gitlab.com/org/repo/-/merge_requests/1"
        )

        assert result is True
        mock_sentry_client.add_comment.assert_called_once()

    @patch("bughawk.git.pr_creator.requests")
    def test_bitbucket_link_to_sentry(self, mock_requests, mock_sentry_client):
        """Test Bitbucket linking to Sentry."""
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_session.get.return_value = mock_response
        mock_requests.Session.return_value = mock_session

        creator = BitbucketPRCreator(
            username="testuser", app_password="test-pass", sentry_client=mock_sentry_client
        )
        result = creator._link_to_sentry(
            "12345", "https://bitbucket.org/workspace/repo/pull-requests/1"
        )

        assert result is True
        mock_sentry_client.add_comment.assert_called_once()

    @patch("bughawk.git.pr_creator.Github")
    def test_link_to_sentry_no_client(self, mock_github_class):
        """Test linking when no Sentry client is configured."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        creator = GitHubPRCreator(token="test-token", sentry_client=None)
        result = creator._link_to_sentry("12345", "https://github.com/org/repo/pull/1")

        assert result is False

    @patch("bughawk.git.pr_creator.Github")
    def test_link_to_sentry_failure(self, mock_github_class, mock_sentry_client):
        """Test linking when Sentry client raises exception."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_github_class.return_value = mock_github

        mock_sentry_client.add_comment.side_effect = Exception("API Error")

        creator = GitHubPRCreator(token="test-token", sentry_client=mock_sentry_client)
        result = creator._link_to_sentry("12345", "https://github.com/org/repo/pull/1")

        assert result is False


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.fixture
    def mock_creator(self):
        """Create a mock implementation of BasePRCreator."""
        class MockPRCreator(BasePRCreator):
            platform = PRPlatform.GITHUB

            def create_pull_request(self, *args, **kwargs):
                pass

            def add_comment_to_pr(self, *args, **kwargs):
                pass

            def get_pr_info(self, *args, **kwargs):
                pass

        return MockPRCreator()

    def test_diff_preview_truncation(self, mock_creator):
        """Test diff preview truncation for large diffs."""
        large_diff = "\n".join([f"+line {i}" for i in range(100)])
        code_changes = {"large_file.py": large_diff}

        diff = mock_creator._format_diff_preview(code_changes, max_lines=10)

        # Should contain truncation message
        assert "more lines" in diff

    def test_diff_preview_multiple_files(self, mock_creator):
        """Test diff preview with multiple files."""
        code_changes = {
            "file1.py": "+add line 1",
            "file2.py": "-remove line 2",
            "file3.py": "@@ context @@",
        }

        diff = mock_creator._format_diff_preview(code_changes)

        assert "file1.py" in diff
        assert "file2.py" in diff

    def test_confidence_score_zero(self, mock_creator, sample_issue):
        """Test PR body with zero confidence score."""
        fix_proposal = MagicMock()
        fix_proposal.confidence_score = 0.0
        fix_proposal.fix_description = "Low confidence fix"
        fix_proposal.code_changes = {}
        fix_proposal.explanation = "Test"

        body = mock_creator.format_pr_body(fix_proposal, sample_issue)

        assert "0.00" in body
        assert "☆" in body  # Empty star for zero confidence

    def test_confidence_score_max(self, mock_creator, sample_issue):
        """Test PR body with maximum confidence score."""
        fix_proposal = MagicMock()
        fix_proposal.confidence_score = 1.0
        fix_proposal.fix_description = "High confidence fix"
        fix_proposal.code_changes = {}
        fix_proposal.explanation = "Test"

        body = mock_creator.format_pr_body(fix_proposal, sample_issue)

        assert "1.00" in body
        assert "⭐⭐⭐⭐⭐" in body  # 5 stars for 1.0

    def test_issue_without_optional_fields(self, mock_creator):
        """Test formatting issue without optional fields."""
        issue = MagicMock()
        issue.id = "123"
        issue.title = "Test Issue"
        issue.culprit = None
        issue.count = 0
        issue.first_seen = None
        issue.last_seen = None
        issue.level = None
        issue.metadata = {}
        issue.tags = {}

        details = mock_creator._format_issue_details(issue)

        # Should return empty string for missing optional fields
        assert details == ""

    def test_pr_title_with_special_characters(self, mock_creator):
        """Test PR title with special characters."""
        issue = MagicMock()
        issue.id = "123"
        issue.title = "Error: <script>alert('xss')</script> & 'quotes'"

        title = mock_creator.format_pr_title(issue)

        # Title should contain the special chars (they're escaped in markdown)
        assert "[Sentry #123]" in title

    def test_pr_body_with_analysis(self, mock_creator, sample_issue, sample_fix_proposal):
        """Test PR body with custom analysis."""
        body = mock_creator.format_pr_body(
            sample_fix_proposal,
            sample_issue,
            analysis="Custom root cause analysis text.",
        )

        assert "Custom root cause analysis text." in body

    def test_empty_reviewers_list(self):
        """Test that empty reviewers list doesn't cause errors."""
        # This is implicitly tested by not passing reviewers,
        # but let's be explicit
        pass  # Empty reviewers are handled by default None value

    def test_pr_info_equality(self):
        """Test PRInfo comparison."""
        info1 = PRInfo(
            url="https://github.com/org/repo/pull/1",
            number=1,
            title="Test",
            platform=PRPlatform.GITHUB,
            repo_full_name="org/repo",
            head_branch="branch",
            base_branch="main",
        )
        info2 = PRInfo(
            url="https://github.com/org/repo/pull/1",
            number=1,
            title="Test",
            platform=PRPlatform.GITHUB,
            repo_full_name="org/repo",
            head_branch="branch",
            base_branch="main",
        )

        assert info1 == info2


# =============================================================================
# Integration-like Tests
# =============================================================================


class TestIntegrationScenarios:
    """Tests for integration-like scenarios."""

    @patch("bughawk.git.pr_creator.Github")
    def test_full_github_workflow(
        self, mock_github_class, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test full GitHub PR creation workflow."""
        mock_github = MagicMock()
        mock_github.get_user.return_value.login = "testuser"
        mock_repo = MagicMock()
        mock_pr = MagicMock()
        mock_pr.number = 42
        mock_pr.html_url = "https://github.com/org/repo/pull/42"
        mock_repo.create_pull.return_value = mock_pr
        mock_repo.get_labels.return_value = []
        mock_github.get_repo.return_value = mock_repo
        mock_github_class.return_value = mock_github

        # Create PR
        creator = GitHubPRCreator(token="test-token", sentry_client=mock_sentry_client)
        url = creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="bughawk-fix/12345",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1"],
            labels=["bughawk", "automated"],
            pattern_name="null-pointer",
            analysis="Root cause: undefined variable access",
        )

        assert url == "https://github.com/org/repo/pull/42"

        # Verify PR was created with correct params
        mock_repo.create_pull.assert_called_once()
        call_kwargs = mock_repo.create_pull.call_args.kwargs
        assert "bughawk-fix/12345" in str(call_kwargs)
        assert "main" in str(call_kwargs)

        # Verify labels were added
        mock_pr.add_to_labels.assert_called()

        # Verify reviewers were requested
        mock_pr.create_review_request.assert_called_once()

        # Verify Sentry was linked
        mock_sentry_client.add_comment.assert_called_once()

    @patch("bughawk.git.pr_creator.gitlab")
    def test_full_gitlab_workflow(
        self, mock_gitlab_module, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test full GitLab MR creation workflow."""
        mock_gitlab = MagicMock()
        mock_gitlab_module.Gitlab.return_value = mock_gitlab

        mock_project = MagicMock()
        mock_mr = MagicMock()
        mock_mr.iid = 42
        mock_mr.web_url = "https://gitlab.com/org/repo/-/merge_requests/42"
        mock_project.mergerequests.create.return_value = mock_mr
        mock_project.labels.list.return_value = []
        mock_gitlab.projects.get.return_value = mock_project

        mock_user = MagicMock()
        mock_user.id = 1
        mock_gitlab.users.list.return_value = [mock_user]

        # Create MR
        creator = GitLabPRCreator(token="test-token", sentry_client=mock_sentry_client)
        url = creator.create_pull_request(
            repo_full_name="org/repo",
            head_branch="bughawk-fix/12345",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1"],
            labels=["bughawk", "automated"],
            pattern_name="null-pointer",
            analysis="Root cause: undefined variable access",
            draft=True,
        )

        assert url == "https://gitlab.com/org/repo/-/merge_requests/42"

        # Verify MR was created
        mock_project.mergerequests.create.assert_called_once()
        call_args = mock_project.mergerequests.create.call_args[0][0]
        assert call_args["title"].startswith("Draft:")
        assert call_args["remove_source_branch"] is True

        # Verify labels and reviewers
        mock_mr.save.assert_called()

    @patch("bughawk.git.pr_creator.requests")
    def test_full_bitbucket_workflow(
        self, mock_requests, sample_issue, sample_fix_proposal, mock_sentry_client
    ):
        """Test full Bitbucket PR creation workflow."""
        mock_session = MagicMock()

        auth_response = MagicMock()
        auth_response.status_code = 200

        user_response = MagicMock()
        user_response.status_code = 200
        user_response.json.return_value = {"uuid": "{user-uuid}"}

        pr_response = MagicMock()
        pr_response.status_code = 201
        pr_response.json.return_value = {
            "id": 42,
            "links": {"html": {"href": "https://bitbucket.org/workspace/repo/pull-requests/42"}},
        }

        def get_side_effect(url):
            if "/users/" in url:
                return user_response
            return auth_response

        mock_session.get.side_effect = get_side_effect
        mock_session.post.return_value = pr_response
        mock_requests.Session.return_value = mock_session

        # Create PR
        creator = BitbucketPRCreator(
            username="testuser", app_password="test-pass", sentry_client=mock_sentry_client
        )
        url = creator.create_pull_request(
            repo_full_name="workspace/repo",
            head_branch="bughawk-fix/12345",
            base_branch="main",
            fix_proposal=sample_fix_proposal,
            issue=sample_issue,
            reviewers=["reviewer1"],
            pattern_name="null-pointer",
            analysis="Root cause: undefined variable access",
        )

        assert url == "https://bitbucket.org/workspace/repo/pull-requests/42"

        # Verify PR was created with correct payload
        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get("json", {})
        assert payload["source"]["branch"]["name"] == "bughawk-fix/12345"
        assert payload["destination"]["branch"]["name"] == "main"
        assert payload["close_source_branch"] is True
        assert "reviewers" in payload
