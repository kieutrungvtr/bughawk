"""Notification system for BugHawk - sends alerts when PRs are created.

This module provides notification capabilities for BugHawk to alert teams
when automated fix PRs are created. Supports multiple notification channels:

- **Slack**: Rich Block Kit messages with action buttons
- **Microsoft Teams**: Adaptive Cards with review actions
- **Discord**: Embedded messages with PR details
- **Custom Webhooks**: Generic JSON payload for custom integrations (e.g., n8n -> MS Teams)

Custom Webhook Payload Structure:
    {
        "event": "pr_created",
        "channel_name": "<configured channel name>",
        "environment": "dev|staging|production",
        "pr_url": "<PR URL>",
        "pr_title": "<PR title>",
        "issue_id": "<Sentry issue ID>",
        "issue_title": "<Sentry issue title>",
        "repo_name": "<repository name>",
        "branch_name": "<branch name>",
        "confidence_score": <0.0-1.0>,
        "fix_description": "<fix description>",
        "sentry_url": "<Sentry issue URL or null>",
        "mention_users": ["<user_id>", ...],
        "mention_groups": ["<group_id>", ...]
    }

The `environment` field allows downstream systems (like n8n workflows) to route
notifications to different channels based on the environment (dev, staging, production).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import requests

from bughawk.core.config import NotificationChannelConfig, NotificationsConfig
from bughawk.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PRNotification:
    """Data for PR created notification."""

    pr_url: str
    pr_title: str
    issue_id: str
    issue_title: str
    repo_name: str
    branch_name: str
    confidence_score: float
    fix_description: str
    sentry_url: Optional[str] = None


class BaseNotifier(ABC):
    """Abstract base class for notification channels."""

    def __init__(self, config: NotificationChannelConfig):
        self.config = config

    @abstractmethod
    def send_pr_created(self, notification: PRNotification) -> bool:
        """Send notification when a PR is created.

        Args:
            notification: PR notification data.

        Returns:
            True if notification was sent successfully.
        """
        pass

    def is_enabled(self) -> bool:
        """Check if this notifier is enabled and configured."""
        return self.config.enabled and bool(self.config.webhook_url)


class SlackNotifier(BaseNotifier):
    """Slack notification sender using incoming webhooks."""

    def send_pr_created(self, notification: PRNotification) -> bool:
        """Send Slack notification when a PR is created."""
        if not self.is_enabled():
            return False

        try:
            # Build mention string
            mentions = self._build_mentions()

            # Build Slack message with blocks
            payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🦅 BugHawk: New Fix PR Created",
                            "emoji": True,
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Issue:*\n<{notification.sentry_url or '#'}|#{notification.issue_id}> {notification.issue_title[:50]}",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Confidence:*\n{self._format_confidence(notification.confidence_score)}",
                            },
                        ],
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Repository:*\n`{notification.repo_name}`",
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Branch:*\n`{notification.branch_name}`",
                            },
                        ],
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Fix:*\n{notification.fix_description[:200]}{'...' if len(notification.fix_description) > 200 else ''}",
                        },
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {
                                    "type": "plain_text",
                                    "text": "📝 Review PR",
                                    "emoji": True,
                                },
                                "url": notification.pr_url,
                                "style": "primary",
                            },
                        ],
                    },
                ],
            }

            # Add mentions if configured
            if mentions:
                payload["blocks"].insert(1, {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"👋 {mentions} - Please review this automated fix",
                    },
                })

            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )

            if response.status_code == 200:
                logger.info(f"Slack notification sent for PR: {notification.pr_url}")
                return True
            else:
                logger.error(f"Slack notification failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False

    def _build_mentions(self) -> str:
        """Build mention string for users and groups."""
        mentions = []
        for user_id in self.config.mention_users:
            mentions.append(f"<@{user_id}>")
        for group_id in self.config.mention_groups:
            mentions.append(f"<!subteam^{group_id}>")
        return " ".join(mentions)

    def _format_confidence(self, score: float) -> str:
        """Format confidence score with emoji."""
        percentage = int(score * 100)
        if score >= 0.8:
            return f"🟢 {percentage}% (High)"
        elif score >= 0.5:
            return f"🟡 {percentage}% (Medium)"
        else:
            return f"🔴 {percentage}% (Low)"


class TeamsNotifier(BaseNotifier):
    """Microsoft Teams notification sender using incoming webhooks."""

    def send_pr_created(self, notification: PRNotification) -> bool:
        """Send Teams notification when a PR is created."""
        if not self.is_enabled():
            return False

        try:
            # Build mention string
            mentions = self._build_mentions()

            # Build Teams Adaptive Card
            payload = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "type": "AdaptiveCard",
                            "version": "1.4",
                            "body": [
                                {
                                    "type": "TextBlock",
                                    "text": "🦅 BugHawk: New Fix PR Created",
                                    "weight": "bolder",
                                    "size": "large",
                                },
                                {
                                    "type": "FactSet",
                                    "facts": [
                                        {
                                            "title": "Issue",
                                            "value": f"#{notification.issue_id} - {notification.issue_title[:50]}",
                                        },
                                        {
                                            "title": "Repository",
                                            "value": notification.repo_name,
                                        },
                                        {
                                            "title": "Branch",
                                            "value": notification.branch_name,
                                        },
                                        {
                                            "title": "Confidence",
                                            "value": f"{int(notification.confidence_score * 100)}%",
                                        },
                                    ],
                                },
                                {
                                    "type": "TextBlock",
                                    "text": f"**Fix:** {notification.fix_description[:200]}",
                                    "wrap": True,
                                },
                            ],
                            "actions": [
                                {
                                    "type": "Action.OpenUrl",
                                    "title": "📝 Review PR",
                                    "url": notification.pr_url,
                                },
                            ],
                        },
                    },
                ],
            }

            # Add mentions if configured
            if mentions:
                payload["attachments"][0]["content"]["body"].insert(1, {
                    "type": "TextBlock",
                    "text": f"👋 {mentions} - Please review this automated fix",
                })

            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )

            if response.status_code in (200, 202):
                logger.info(f"Teams notification sent for PR: {notification.pr_url}")
                return True
            else:
                logger.error(f"Teams notification failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Teams notification: {e}")
            return False

    def _build_mentions(self) -> str:
        """Build mention string for users."""
        mentions = []
        for user_id in self.config.mention_users:
            mentions.append(f"<at>{user_id}</at>")
        return " ".join(mentions)


class DiscordNotifier(BaseNotifier):
    """Discord notification sender using webhooks."""

    def send_pr_created(self, notification: PRNotification) -> bool:
        """Send Discord notification when a PR is created."""
        if not self.is_enabled():
            return False

        try:
            # Build mention string
            mentions = self._build_mentions()

            # Build Discord embed
            payload = {
                "embeds": [
                    {
                        "title": "🦅 BugHawk: New Fix PR Created",
                        "color": 0xD4A017,  # Hawk gold
                        "fields": [
                            {
                                "name": "Issue",
                                "value": f"[#{notification.issue_id}]({notification.sentry_url or '#'}) {notification.issue_title[:50]}",
                                "inline": True,
                            },
                            {
                                "name": "Confidence",
                                "value": f"{int(notification.confidence_score * 100)}%",
                                "inline": True,
                            },
                            {
                                "name": "Repository",
                                "value": f"`{notification.repo_name}`",
                                "inline": True,
                            },
                            {
                                "name": "Branch",
                                "value": f"`{notification.branch_name}`",
                                "inline": True,
                            },
                            {
                                "name": "Fix Description",
                                "value": notification.fix_description[:200],
                                "inline": False,
                            },
                            {
                                "name": "Review",
                                "value": f"[📝 Open PR]({notification.pr_url})",
                                "inline": False,
                            },
                        ],
                        "footer": {
                            "text": "BugHawk Automated Fix",
                        },
                    },
                ],
            }

            # Add mentions if configured
            if mentions:
                payload["content"] = f"👋 {mentions} - Please review this automated fix"

            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )

            if response.status_code in (200, 204):
                logger.info(f"Discord notification sent for PR: {notification.pr_url}")
                return True
            else:
                logger.error(f"Discord notification failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False

    def _build_mentions(self) -> str:
        """Build mention string for users and roles."""
        mentions = []
        for user_id in self.config.mention_users:
            mentions.append(f"<@{user_id}>")
        for role_id in self.config.mention_groups:
            mentions.append(f"<@&{role_id}>")
        return " ".join(mentions)


class CustomWebhookNotifier(BaseNotifier):
    """Generic webhook notifier for custom integrations (e.g., n8n -> MS Teams).

    This notifier sends a JSON payload to a custom webhook endpoint, allowing
    integration with workflow automation tools like n8n, Zapier, or custom services.

    The payload includes `channel_name` and `environment` fields that can be used
    by the receiving system to route notifications to appropriate channels.

    Example n8n workflow:
        1. Receive BugHawk webhook
        2. Check `environment` field (dev/staging/production)
        3. Route to corresponding MS Teams channel
    """

    def send_pr_created(self, notification: PRNotification) -> bool:
        """Send notification to custom webhook endpoint.

        Sends a JSON payload containing PR details and channel metadata.
        The `environment` field can be used for routing to different channels.

        Args:
            notification: PR notification data.

        Returns:
            True if notification was sent successfully (HTTP 200-204).
        """
        if not self.is_enabled():
            return False

        try:
            # Build JSON payload with channel metadata for routing
            # The `environment` field allows n8n/downstream systems to route
            # notifications to appropriate channels (e.g., dev -> dev-team channel)
            payload = {
                "event": "pr_created",
                "channel_name": self.config.name,  # e.g., "n8n-msteams"
                "environment": self.config.environment,  # e.g., "dev", "production"
                "pr_url": notification.pr_url,
                "pr_title": notification.pr_title,
                "issue_id": notification.issue_id,
                "issue_title": notification.issue_title,
                "repo_name": notification.repo_name,
                "branch_name": notification.branch_name,
                "confidence_score": notification.confidence_score,
                "fix_description": notification.fix_description,
                "sentry_url": notification.sentry_url,
                "mention_users": self.config.mention_users,
                "mention_groups": self.config.mention_groups,
            }

            response = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )

            if response.status_code in (200, 201, 202, 204):
                logger.info(f"Custom webhook notification sent for PR: {notification.pr_url}")
                return True
            else:
                logger.error(f"Custom webhook failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Failed to send custom webhook notification: {e}")
            return False


class NotificationManager:
    """Manages all notification channels."""

    def __init__(self, config: NotificationsConfig):
        self.config = config
        self.notifiers: list[BaseNotifier] = []
        self._init_notifiers()

    def _init_notifiers(self) -> None:
        """Initialize all configured notifiers."""
        if self.config.slack.enabled and self.config.slack.webhook_url:
            self.notifiers.append(SlackNotifier(self.config.slack))

        if self.config.teams.enabled and self.config.teams.webhook_url:
            self.notifiers.append(TeamsNotifier(self.config.teams))

        if self.config.discord.enabled and self.config.discord.webhook_url:
            self.notifiers.append(DiscordNotifier(self.config.discord))

        for custom in self.config.custom_webhooks:
            if custom.enabled and custom.webhook_url:
                self.notifiers.append(CustomWebhookNotifier(custom))

    def send_pr_created(self, notification: PRNotification) -> dict[str, bool]:
        """Send PR created notification to all enabled channels.

        Args:
            notification: PR notification data.

        Returns:
            Dict mapping channel names to success status.
        """
        results = {}
        for notifier in self.notifiers:
            channel_name = notifier.__class__.__name__.replace("Notifier", "").lower()
            try:
                results[channel_name] = notifier.send_pr_created(notification)
            except Exception as e:
                logger.error(f"Notification failed for {channel_name}: {e}")
                results[channel_name] = False
        return results

    def has_enabled_channels(self) -> bool:
        """Check if any notification channels are enabled."""
        return len(self.notifiers) > 0


def send_pr_created_notification(
    config: NotificationsConfig,
    pr_url: str,
    pr_title: str,
    issue_id: str,
    issue_title: str,
    repo_name: str,
    branch_name: str,
    confidence_score: float,
    fix_description: str,
    sentry_url: Optional[str] = None,
) -> dict[str, bool]:
    """Convenience function to send PR created notification.

    Args:
        config: Notifications configuration.
        pr_url: URL of the created PR.
        pr_title: Title of the PR.
        issue_id: Sentry issue ID.
        issue_title: Sentry issue title.
        repo_name: Repository name.
        branch_name: Branch name.
        confidence_score: Fix confidence score (0-1).
        fix_description: Description of the fix.
        sentry_url: Optional Sentry issue URL.

    Returns:
        Dict mapping channel names to success status.
    """
    notification = PRNotification(
        pr_url=pr_url,
        pr_title=pr_title,
        issue_id=issue_id,
        issue_title=issue_title,
        repo_name=repo_name,
        branch_name=branch_name,
        confidence_score=confidence_score,
        fix_description=fix_description,
        sentry_url=sentry_url,
    )

    manager = NotificationManager(config)
    return manager.send_pr_created(notification)
