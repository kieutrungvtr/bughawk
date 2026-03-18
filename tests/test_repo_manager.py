"""Tests for repository manager module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bughawk.git.repo_manager import (
    AuthenticationError,
    BranchError,
    CloneError,
    CommitError,
    CommitInfo,
    PushError,
    RepoInfo,
    RepoManager,
    RepoManagerError,
)


class TestRepoManagerInitialization:
    """Tests for RepoManager initialization."""

    def test_default_initialization(self, temp_dir: Path) -> None:
        """Test default initialization."""
        manager = RepoManager(work_dir=str(temp_dir))

        assert manager.work_dir == temp_dir
        assert manager.work_dir.exists()

    def test_initialization_with_tokens(self, temp_dir: Path) -> None:
        """Test initialization with authentication tokens."""
        manager = RepoManager(
            work_dir=str(temp_dir),
            github_token="gh-token-123",
            gitlab_token="gl-token-456",
        )

        assert manager.github_token == "gh-token-123"
        assert manager.gitlab_token == "gl-token-456"

    def test_initialization_creates_work_dir(self, temp_dir: Path) -> None:
        """Test that initialization creates work directory if needed."""
        new_work_dir = temp_dir / "new_work_dir"
        manager = RepoManager(work_dir=str(new_work_dir))

        assert new_work_dir.exists()


class TestRepoManagerPrepareRepository:
    """Tests for prepare_repository method."""

    def test_prepare_repository_success(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test successful repository preparation (cloning)."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Create a bare repo to clone from
        bare_repo = temp_dir / "bare_repo.git"
        subprocess.run(
            ["git", "clone", "--bare", str(temp_repo), str(bare_repo)],
            capture_output=True,
        )

        cloned_path = manager.prepare_repository(
            repo_url=str(bare_repo),
            base_branch="master",
        )

        assert cloned_path.exists()
        assert (cloned_path / ".git").exists()

    def test_prepare_repository_invalid_url(self, temp_dir: Path) -> None:
        """Test repository preparation with invalid URL."""
        manager = RepoManager(work_dir=str(temp_dir))

        with pytest.raises(CloneError):
            manager.prepare_repository(
                repo_url="https://invalid-url.example.com/repo.git",
            )


class TestRepoManagerCreateFixBranch:
    """Tests for create_fix_branch method."""

    def test_create_fix_branch_success(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test successful branch creation."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Register the temp repo with manager
        manager._repos[temp_repo] = RepoInfo(
            path=temp_repo,
            url="https://github.com/test/repo.git",
            branch="master",
        )

        branch_name = manager.create_fix_branch(temp_repo, "SENTRY-123")

        assert branch_name.startswith("bughawk-fix/")
        assert "sentry-123" in branch_name.lower()

    def test_create_fix_branch_custom_prefix(
        self, temp_dir: Path, temp_repo: Path
    ) -> None:
        """Test branch creation with custom prefix."""
        manager = RepoManager(work_dir=str(temp_dir))

        branch_name = manager.create_fix_branch(
            temp_repo,
            "ISSUE-456",
            prefix="custom-fix",
        )

        assert branch_name.startswith("custom-fix/")

    def test_create_fix_branch_invalid_repo(self, temp_dir: Path) -> None:
        """Test branch creation with invalid repository path."""
        manager = RepoManager(work_dir=str(temp_dir))

        with pytest.raises(BranchError):
            manager.create_fix_branch(
                temp_dir / "nonexistent",
                "ISSUE-123",
            )


class TestRepoManagerApplyChanges:
    """Tests for apply_changes method."""

    def test_apply_changes_success(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test successful change application."""
        manager = RepoManager(work_dir=str(temp_dir))

        changes = {
            "src/app.py": '''def main():
    print("Updated!")

if __name__ == "__main__":
    main()
''',
        }

        modified_files = manager.apply_changes(temp_repo, changes)

        assert len(modified_files) == 1
        assert (temp_repo / "src" / "app.py").read_text() == changes["src/app.py"]

    def test_apply_changes_new_file(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test applying changes that create new files."""
        manager = RepoManager(work_dir=str(temp_dir))

        changes = {
            "src/new_file.py": "# New file\nprint('Hello')\n",
        }

        modified_files = manager.apply_changes(temp_repo, changes)

        assert len(modified_files) == 1
        assert (temp_repo / "src" / "new_file.py").exists()

    def test_apply_changes_creates_directories(
        self, temp_dir: Path, temp_repo: Path
    ) -> None:
        """Test that apply_changes creates directories as needed."""
        manager = RepoManager(work_dir=str(temp_dir))

        changes = {
            "new_dir/sub_dir/file.py": "# New file in new directory\n",
        }

        modified_files = manager.apply_changes(temp_repo, changes)

        assert len(modified_files) == 1
        assert (temp_repo / "new_dir" / "sub_dir" / "file.py").exists()


class TestRepoManagerCommitChanges:
    """Tests for commit_changes method."""

    def test_commit_changes_success(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test successful commit."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Make a change first
        changes = {"src/app.py": "# Updated\nprint('test')\n"}
        manager.apply_changes(temp_repo, changes)

        commit_info = manager.commit_changes(
            repo_path=temp_repo,
            issue_id="12345",
            issue_title="Fix null pointer error",
            fix_explanation="Added null check before accessing property",
            sentry_url="https://sentry.io/issues/12345/",
        )

        assert isinstance(commit_info, CommitInfo)
        assert len(commit_info.sha) == 40  # Full SHA
        assert "12345" in commit_info.message
        assert "BugHawk" in commit_info.message

    def test_commit_changes_custom_author(
        self, temp_dir: Path, temp_repo: Path
    ) -> None:
        """Test commit with custom author."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Make a change
        changes = {"src/app.py": "# Test\n"}
        manager.apply_changes(temp_repo, changes)

        commit_info = manager.commit_changes(
            repo_path=temp_repo,
            issue_id="123",
            issue_title="Test",
            fix_explanation="Test fix",
            sentry_url="https://sentry.io/issues/123/",
            author="Custom Author",
            author_email="custom@example.com",
        )

        assert "Custom Author" in commit_info.author

    def test_commit_changes_no_changes(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test commit with no staged changes."""
        manager = RepoManager(work_dir=str(temp_dir))

        with pytest.raises(CommitError):
            manager.commit_changes(
                repo_path=temp_repo,
                issue_id="123",
                issue_title="Test",
                fix_explanation="Test",
                sentry_url="https://sentry.io/issues/123/",
            )


class TestRepoManagerCleanup:
    """Tests for cleanup methods."""

    def test_cleanup_success(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test successful cleanup."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Register repo
        manager._repos[temp_repo] = RepoInfo(
            path=temp_repo,
            url="https://github.com/test/repo.git",
            branch="master",
            is_temporary=True,
        )

        result = manager.cleanup(temp_repo, force=True)

        assert result is True
        assert not temp_repo.exists()
        assert temp_repo not in manager._repos

    def test_cleanup_with_uncommitted_changes(
        self, temp_dir: Path, temp_repo: Path
    ) -> None:
        """Test cleanup with uncommitted changes fails without force."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Make uncommitted change
        (temp_repo / "uncommitted.txt").write_text("uncommitted")

        # Should fail without force
        with pytest.raises(RepoManagerError):
            manager.cleanup(temp_repo, force=False)

        # Should succeed with force
        result = manager.cleanup(temp_repo, force=True)
        assert result is True

    def test_cleanup_all(self, temp_dir: Path) -> None:
        """Test cleanup_all method."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Create multiple temp repos
        for i in range(3):
            repo_path = temp_dir / f"repo_{i}"
            repo_path.mkdir()
            subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
            subprocess.run(
                ["git", "config", "user.email", "test@test.com"],
                cwd=repo_path,
                capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Test"],
                cwd=repo_path,
                capture_output=True,
            )

            manager._repos[repo_path] = RepoInfo(
                path=repo_path,
                url=f"https://github.com/test/repo_{i}.git",
                branch="master",
                is_temporary=True,
            )

        cleaned = manager.cleanup_all(force=True)

        assert cleaned == 3
        assert len(manager._repos) == 0


class TestRepoManagerGetStatus:
    """Tests for get_repo_status method."""

    def test_get_repo_status(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test getting repository status."""
        manager = RepoManager(work_dir=str(temp_dir))

        manager._repos[temp_repo] = RepoInfo(
            path=temp_repo,
            url="https://github.com/test/repo.git",
            branch="master",
        )

        status = manager.get_repo_status(temp_repo)

        assert status["path"] == str(temp_repo)
        assert "current_branch" in status
        assert "is_dirty" in status
        assert "head_commit" in status

    def test_get_repo_status_invalid_repo(self, temp_dir: Path) -> None:
        """Test status for invalid repository."""
        manager = RepoManager(work_dir=str(temp_dir))

        status = manager.get_repo_status(temp_dir / "nonexistent")

        assert "error" in status


class TestRepoManagerGetDiff:
    """Tests for get_diff method."""

    def test_get_diff_staged(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test getting staged diff."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Make and stage a change
        changes = {"src/app.py": "# Changed content\n"}
        manager.apply_changes(temp_repo, changes)

        diff = manager.get_diff(temp_repo, staged=True)

        assert "Changed content" in diff or "+#" in diff

    def test_get_diff_unstaged(self, temp_dir: Path, temp_repo: Path) -> None:
        """Test getting unstaged diff."""
        manager = RepoManager(work_dir=str(temp_dir))

        # Make unstaged change
        (temp_repo / "src" / "app.py").write_text("# Unstaged change\n")

        diff = manager.get_diff(temp_repo, staged=False)

        assert "Unstaged" in diff or len(diff) > 0


class TestRepoManagerHelpers:
    """Tests for helper methods."""

    def test_extract_repo_name_https(self, temp_dir: Path) -> None:
        """Test extracting repo name from HTTPS URL."""
        manager = RepoManager(work_dir=str(temp_dir))

        name = manager._extract_repo_name("https://github.com/owner/repo-name.git")
        assert name == "repo-name"

    def test_extract_repo_name_ssh(self, temp_dir: Path) -> None:
        """Test extracting repo name from SSH URL."""
        manager = RepoManager(work_dir=str(temp_dir))

        name = manager._extract_repo_name("git@github.com:owner/repo-name.git")
        assert name == "repo-name"

    def test_prepare_auth_url_github(self, temp_dir: Path) -> None:
        """Test URL preparation with GitHub token."""
        manager = RepoManager(
            work_dir=str(temp_dir),
            github_token="test-token",
        )

        auth_url = manager._prepare_auth_url("https://github.com/owner/repo.git")

        assert "test-token" in auth_url
        assert "@github.com" in auth_url

    def test_prepare_auth_url_ssh_unchanged(self, temp_dir: Path) -> None:
        """Test that SSH URLs are not modified."""
        manager = RepoManager(
            work_dir=str(temp_dir),
            github_token="test-token",
        )

        ssh_url = "git@github.com:owner/repo.git"
        auth_url = manager._prepare_auth_url(ssh_url)

        assert auth_url == ssh_url

    def test_build_commit_message(self, temp_dir: Path) -> None:
        """Test commit message building."""
        manager = RepoManager(work_dir=str(temp_dir))

        message = manager._build_commit_message(
            issue_id="12345",
            issue_title="Fix null pointer exception",
            fix_explanation="Added null check",
            sentry_url="https://sentry.io/issues/12345/",
        )

        assert "12345" in message
        assert "🦅" in message
        assert "BugHawk" in message
        assert "https://sentry.io/issues/12345/" in message

    def test_build_commit_message_truncates_long_title(self, temp_dir: Path) -> None:
        """Test that long titles are truncated in commit message."""
        manager = RepoManager(work_dir=str(temp_dir))

        long_title = "A" * 100  # Very long title

        message = manager._build_commit_message(
            issue_id="123",
            issue_title=long_title,
            fix_explanation="Fix",
            sentry_url="https://sentry.io/issues/123/",
        )

        # First line should be reasonably short
        first_line = message.split("\n")[0]
        assert len(first_line) < 80
        assert "..." in first_line
