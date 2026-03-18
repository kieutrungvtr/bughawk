"""Repository Manager for BugHawk - Git operations for fix application."""

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from git import Actor, GitCommandError, InvalidGitRepositoryError, Repo


class RepoManagerError(Exception):
    """Base exception for repository manager errors."""

    pass


class CloneError(RepoManagerError):
    """Error during repository cloning."""

    pass


class BranchError(RepoManagerError):
    """Error during branch operations."""

    pass


class CommitError(RepoManagerError):
    """Error during commit operations."""

    pass


class PushError(RepoManagerError):
    """Error during push operations."""

    pass


class AuthenticationError(RepoManagerError):
    """Error during authentication."""

    pass


@dataclass
class RepoInfo:
    """Information about a managed repository."""

    path: Path
    url: str
    branch: str
    fix_branch: Optional[str] = None
    is_temporary: bool = True


@dataclass
class CommitInfo:
    """Information about a commit."""

    sha: str
    message: str
    author: str
    timestamp: datetime


class RepoManager:
    """Manages Git repositories for applying fixes.

    Handles cloning, branching, committing, and pushing changes
    with support for both SSH and HTTPS authentication.

    Example:
        manager = RepoManager(work_dir="/tmp/bughawk")
        repo_path = manager.prepare_repository("https://github.com/org/repo.git")
        branch = manager.create_fix_branch(repo_path, "SENTRY-123")
        manager.apply_changes(repo_path, {"src/app.py": "fixed code..."})
        manager.commit_changes(
            repo_path,
            issue_id="SENTRY-123",
            issue_title="Fix null pointer",
            fix_explanation="Added null check",
            sentry_url="https://sentry.io/issues/123"
        )
        manager.push_branch(repo_path, branch)
        manager.cleanup(repo_path)
    """

    def __init__(
        self,
        work_dir: Optional[str] = None,
        github_token: Optional[str] = None,
        gitlab_token: Optional[str] = None,
        ssh_key_path: Optional[str] = None,
    ):
        """Initialize the repository manager.

        Args:
            work_dir: Directory for cloning repositories. Uses temp dir if not specified.
            github_token: GitHub personal access token for HTTPS auth.
            gitlab_token: GitLab personal access token for HTTPS auth.
            ssh_key_path: Path to SSH private key for SSH auth.
        """
        self.work_dir = Path(work_dir) if work_dir else Path(tempfile.gettempdir()) / "bughawk"
        self.work_dir.mkdir(parents=True, exist_ok=True)

        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.gitlab_token = gitlab_token or os.environ.get("GITLAB_TOKEN")
        self.ssh_key_path = ssh_key_path or os.environ.get("SSH_KEY_PATH")

        self._repos: Dict[Path, RepoInfo] = {}

    def prepare_repository(
        self,
        repo_url: str,
        base_branch: str = "main",
        depth: Optional[int] = None,
    ) -> Path:
        """Clone or prepare a repository for modifications.

        Args:
            repo_url: URL of the repository (SSH or HTTPS).
            base_branch: Branch to use as base for fixes.
            depth: Shallow clone depth. None for full clone.

        Returns:
            Path to the cloned repository.

        Raises:
            CloneError: If cloning fails.
            AuthenticationError: If authentication fails.
        """
        # Generate unique directory name
        repo_name = self._extract_repo_name(repo_url)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        repo_dir = self.work_dir / f"{repo_name}_{timestamp}"

        # Prepare URL with authentication if needed
        auth_url = self._prepare_auth_url(repo_url)

        # Prepare clone environment
        env = self._prepare_git_env()

        try:
            # Clone the repository
            clone_kwargs: dict = {
                "branch": base_branch,
                "single_branch": True,
                "env": env,
            }

            if depth:
                clone_kwargs["depth"] = depth

            repo = Repo.clone_from(auth_url, repo_dir, **clone_kwargs)

            # Store repo info
            self._repos[repo_dir] = RepoInfo(
                path=repo_dir,
                url=repo_url,
                branch=base_branch,
                is_temporary=True,
            )

            return repo_dir

        except GitCommandError as e:
            # Clean up partial clone
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)

            error_msg = str(e)
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                raise AuthenticationError(
                    f"Authentication failed for {repo_url}. "
                    "Check your credentials (GITHUB_TOKEN, GITLAB_TOKEN, or SSH key)."
                ) from e
            elif "not found" in error_msg.lower():
                raise CloneError(f"Repository not found: {repo_url}") from e
            elif "Could not resolve host" in error_msg:
                raise CloneError(f"Could not resolve host for {repo_url}. Check your network connection.") from e
            else:
                raise CloneError(f"Failed to clone repository: {error_msg}") from e

        except Exception as e:
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            raise CloneError(f"Unexpected error cloning repository: {e}") from e

    def create_fix_branch(
        self,
        repo_path: Path,
        issue_id: str,
        prefix: str = "bughawk-fix",
    ) -> str:
        """Create a new branch for the fix.

        Args:
            repo_path: Path to the repository.
            issue_id: Sentry issue ID (used in branch name).
            prefix: Prefix for the branch name.

        Returns:
            Name of the created branch.

        Raises:
            BranchError: If branch creation fails.
        """
        try:
            repo = Repo(repo_path)

            # Sanitize issue ID for branch name
            safe_issue_id = issue_id.replace("/", "-").replace(" ", "-").lower()
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            branch_name = f"{prefix}/{safe_issue_id}-{timestamp}"

            # Create and checkout the new branch
            new_branch = repo.create_head(branch_name)
            new_branch.checkout()

            # Update repo info
            if repo_path in self._repos:
                self._repos[repo_path].fix_branch = branch_name

            return branch_name

        except InvalidGitRepositoryError as e:
            raise BranchError(f"Invalid Git repository: {repo_path}") from e
        except GitCommandError as e:
            raise BranchError(f"Failed to create branch: {e}") from e
        except Exception as e:
            raise BranchError(f"Unexpected error creating branch: {e}") from e

    def apply_changes(
        self,
        repo_path: Path,
        changes: Dict[str, str],
        create_dirs: bool = True,
    ) -> List[Path]:
        """Apply code changes to files in the repository.

        Args:
            repo_path: Path to the repository.
            changes: Dictionary mapping file paths to new content.
            create_dirs: Whether to create directories if they don't exist.

        Returns:
            List of paths to modified files.

        Raises:
            RepoManagerError: If applying changes fails.
        """
        modified_files: List[Path] = []

        try:
            repo = Repo(repo_path)

            for file_path, content in changes.items():
                # Handle both absolute and relative paths
                if Path(file_path).is_absolute():
                    full_path = Path(file_path)
                else:
                    full_path = repo_path / file_path

                # Ensure parent directory exists
                if create_dirs:
                    full_path.parent.mkdir(parents=True, exist_ok=True)

                # Write the new content
                full_path.write_text(content, encoding="utf-8")
                modified_files.append(full_path)

                # Stage the file
                rel_path = full_path.relative_to(repo_path)
                repo.index.add([str(rel_path)])

            return modified_files

        except InvalidGitRepositoryError as e:
            raise RepoManagerError(f"Invalid Git repository: {repo_path}") from e
        except PermissionError as e:
            raise RepoManagerError(f"Permission denied writing to file: {e}") from e
        except Exception as e:
            raise RepoManagerError(f"Failed to apply changes: {e}") from e

    def commit_changes(
        self,
        repo_path: Path,
        issue_id: str,
        issue_title: str,
        fix_explanation: str,
        sentry_url: str,
        author: Optional[str] = None,
        author_email: Optional[str] = None,
    ) -> CommitInfo:
        """Commit the staged changes with BugHawk commit message format.

        Args:
            repo_path: Path to the repository.
            issue_id: Sentry issue ID.
            issue_title: Title of the issue being fixed.
            fix_explanation: Explanation of the fix.
            sentry_url: URL to the Sentry issue.
            author: Commit author name. Defaults to "BugHawk".
            author_email: Commit author email. Defaults to "bughawk@automated.fix".

        Returns:
            Information about the created commit.

        Raises:
            CommitError: If commit fails.
        """
        try:
            repo = Repo(repo_path)

            # Check if there are changes to commit
            if not repo.index.diff("HEAD") and not repo.untracked_files:
                raise CommitError("No changes to commit")

            # Build commit message with BugHawk format
            commit_message = self._build_commit_message(
                issue_id=issue_id,
                issue_title=issue_title,
                fix_explanation=fix_explanation,
                sentry_url=sentry_url,
            )

            # Set up author
            author_name = author or "BugHawk"
            author_mail = author_email or "bughawk@automated.fix"
            actor = Actor(author_name, author_mail)

            # Create the commit
            commit = repo.index.commit(
                commit_message,
                author=actor,
                committer=actor,
            )

            return CommitInfo(
                sha=commit.hexsha,
                message=commit_message,
                author=f"{author_name} <{author_mail}>",
                timestamp=datetime.fromtimestamp(commit.committed_date),
            )

        except InvalidGitRepositoryError as e:
            raise CommitError(f"Invalid Git repository: {repo_path}") from e
        except GitCommandError as e:
            raise CommitError(f"Failed to commit changes: {e}") from e
        except Exception as e:
            if isinstance(e, CommitError):
                raise
            raise CommitError(f"Unexpected error during commit: {e}") from e

    def push_branch(
        self,
        repo_path: Path,
        branch_name: Optional[str] = None,
        remote: str = "origin",
        force: bool = False,
        set_upstream: bool = True,
    ) -> bool:
        """Push the branch to the remote repository.

        Args:
            repo_path: Path to the repository.
            branch_name: Name of the branch to push. Uses current branch if not specified.
            remote: Name of the remote to push to.
            force: Whether to force push.
            set_upstream: Whether to set upstream tracking.

        Returns:
            True if push succeeded.

        Raises:
            PushError: If push fails.
            AuthenticationError: If authentication fails.
        """
        try:
            repo = Repo(repo_path)

            # Get branch name
            if branch_name is None:
                branch_name = repo.active_branch.name

            # Get remote
            if remote not in [r.name for r in repo.remotes]:
                raise PushError(f"Remote '{remote}' not found")

            remote_obj = repo.remote(remote)

            # Prepare push URL with authentication
            repo_info = self._repos.get(repo_path)
            if repo_info:
                auth_url = self._prepare_auth_url(repo_info.url)
                remote_obj.set_url(auth_url)

            # Prepare environment
            env = self._prepare_git_env()

            # Build push refspec
            refspec = f"{branch_name}:{branch_name}"
            if set_upstream:
                refspec = f"refs/heads/{branch_name}:refs/heads/{branch_name}"

            # Push
            push_kwargs = {"env": env}
            if force:
                push_kwargs["force"] = True

            push_info = remote_obj.push(refspec, **push_kwargs)

            # Check push result
            for info in push_info:
                if info.flags & info.ERROR:
                    raise PushError(f"Push failed: {info.summary}")
                if info.flags & info.REJECTED:
                    raise PushError(f"Push rejected: {info.summary}")

            return True

        except InvalidGitRepositoryError as e:
            raise PushError(f"Invalid Git repository: {repo_path}") from e
        except GitCommandError as e:
            error_msg = str(e)
            if "Authentication failed" in error_msg or "Permission denied" in error_msg:
                raise AuthenticationError(f"Authentication failed during push: {error_msg}") from e
            raise PushError(f"Failed to push branch: {error_msg}") from e
        except Exception as e:
            if isinstance(e, (PushError, AuthenticationError)):
                raise
            raise PushError(f"Unexpected error during push: {e}") from e

    def cleanup(self, repo_path: Path, force: bool = False) -> bool:
        """Clean up a cloned repository.

        Args:
            repo_path: Path to the repository to clean up.
            force: Force cleanup even if there are uncommitted changes.

        Returns:
            True if cleanup succeeded.

        Raises:
            RepoManagerError: If cleanup fails.
        """
        try:
            repo_info = self._repos.get(repo_path)

            # Only clean up temporary repos unless forced
            if repo_info and not repo_info.is_temporary and not force:
                return False

            # Check for uncommitted changes
            if repo_path.exists() and not force:
                try:
                    repo = Repo(repo_path)
                    if repo.is_dirty(untracked_files=True):
                        raise RepoManagerError(
                            f"Repository has uncommitted changes: {repo_path}. "
                            "Use force=True to clean up anyway."
                        )
                except InvalidGitRepositoryError:
                    pass  # Not a valid repo, safe to delete

            # Remove the directory
            if repo_path.exists():
                shutil.rmtree(repo_path)

            # Remove from tracking
            if repo_path in self._repos:
                del self._repos[repo_path]

            return True

        except Exception as e:
            if isinstance(e, RepoManagerError):
                raise
            raise RepoManagerError(f"Failed to clean up repository: {e}") from e

    def cleanup_all(self, force: bool = False) -> int:
        """Clean up all managed repositories.

        Args:
            force: Force cleanup even if there are uncommitted changes.

        Returns:
            Number of repositories cleaned up.
        """
        cleaned = 0
        repo_paths = list(self._repos.keys())

        for repo_path in repo_paths:
            try:
                if self.cleanup(repo_path, force=force):
                    cleaned += 1
            except RepoManagerError:
                pass  # Continue with other repos

        return cleaned

    def get_repo_status(self, repo_path: Path) -> dict:
        """Get the status of a repository.

        Args:
            repo_path: Path to the repository.

        Returns:
            Dictionary with repository status information.
        """
        try:
            repo = Repo(repo_path)
            repo_info = self._repos.get(repo_path)

            return {
                "path": str(repo_path),
                "url": repo_info.url if repo_info else None,
                "current_branch": repo.active_branch.name,
                "fix_branch": repo_info.fix_branch if repo_info else None,
                "is_dirty": repo.is_dirty(untracked_files=True),
                "untracked_files": repo.untracked_files,
                "modified_files": [item.a_path for item in repo.index.diff(None)],
                "staged_files": [item.a_path for item in repo.index.diff("HEAD")],
                "head_commit": repo.head.commit.hexsha[:8],
                "remotes": [r.name for r in repo.remotes],
            }

        except InvalidGitRepositoryError:
            return {"path": str(repo_path), "error": "Invalid Git repository"}
        except Exception as e:
            return {"path": str(repo_path), "error": str(e)}

    def get_diff(self, repo_path: Path, staged: bool = True) -> str:
        """Get the diff of changes in the repository.

        Args:
            repo_path: Path to the repository.
            staged: If True, get staged changes. Otherwise, get unstaged changes.

        Returns:
            Unified diff string.
        """
        try:
            repo = Repo(repo_path)

            if staged:
                diff = repo.git.diff("--cached")
            else:
                diff = repo.git.diff()

            return diff

        except Exception as e:
            raise RepoManagerError(f"Failed to get diff: {e}") from e

    def _extract_repo_name(self, repo_url: str) -> str:
        """Extract repository name from URL.

        Args:
            repo_url: Repository URL.

        Returns:
            Repository name.
        """
        # Handle SSH URLs
        if repo_url.startswith("git@"):
            # git@github.com:org/repo.git
            path = repo_url.split(":")[-1]
        else:
            # HTTPS URLs
            parsed = urlparse(repo_url)
            path = parsed.path

        # Remove .git suffix and get repo name
        name = path.rstrip("/").rstrip(".git").split("/")[-1]
        return name or "repo"

    def _prepare_auth_url(self, repo_url: str) -> str:
        """Prepare URL with authentication credentials.

        Args:
            repo_url: Original repository URL.

        Returns:
            URL with embedded credentials if applicable.
        """
        # SSH URLs don't need modification (use SSH key)
        if repo_url.startswith("git@"):
            return repo_url

        parsed = urlparse(repo_url)

        # Determine which token to use based on host
        token = None
        if "github.com" in parsed.netloc and self.github_token:
            token = self.github_token
        elif "gitlab" in parsed.netloc and self.gitlab_token:
            token = self.gitlab_token

        if token:
            # Embed token in URL: https://token@host/path
            auth_netloc = f"{token}@{parsed.netloc}"
            return parsed._replace(netloc=auth_netloc).geturl()

        return repo_url

    def _prepare_git_env(self) -> dict:
        """Prepare environment variables for Git commands.

        Returns:
            Dictionary of environment variables.
        """
        env = os.environ.copy()

        # Configure SSH if key path is specified
        if self.ssh_key_path:
            ssh_command = f'ssh -i {self.ssh_key_path} -o StrictHostKeyChecking=no'
            env["GIT_SSH_COMMAND"] = ssh_command

        # Disable interactive prompts
        env["GIT_TERMINAL_PROMPT"] = "0"

        return env

    def _build_commit_message(
        self,
        issue_id: str,
        issue_title: str,
        fix_explanation: str,
        sentry_url: str,
    ) -> str:
        """Build the BugHawk commit message.

        Args:
            issue_id: Sentry issue ID.
            issue_title: Title of the issue.
            fix_explanation: Explanation of the fix.
            sentry_url: URL to the Sentry issue.

        Returns:
            Formatted commit message.
        """
        # Truncate title if too long
        max_title_len = 50
        if len(issue_title) > max_title_len:
            issue_title = issue_title[: max_title_len - 3] + "..."

        message = f"""fix: 🦅 [Sentry #{issue_id}] {issue_title}

{fix_explanation}

Automatically generated by BugHawk
Sentry issue: {sentry_url}"""

        return message
