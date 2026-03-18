"""Git module for BugHawk - Repository management and Git operations."""

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

__all__ = [
    # Repo Manager
    "AuthenticationError",
    "BranchError",
    "CloneError",
    "CommitError",
    "CommitInfo",
    "PushError",
    "RepoInfo",
    "RepoManager",
    "RepoManagerError",
    # PR Creator
    "BasePRCreator",
    "BitbucketPRCreator",
    "GitHubPRCreator",
    "GitLabPRCreator",
    "PRAuthenticationError",
    "PRCreationError",
    "PRCreator",
    "PRCreatorError",
    "PRInfo",
    "PRNotFoundError",
    "PRPlatform",
]
