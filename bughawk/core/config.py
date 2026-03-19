"""Configuration management for BugHawk.

Loads configuration from multiple sources with the following priority (highest to lowest):
1. Command-line arguments (passed via CLIOverrides)
2. Environment variables (prefixed with BUGHAWK_)
3. .bughawk.yml file
4. Default values
"""

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


load_dotenv()


class Severity(str, Enum):
    """Issue severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CLAUDE = "claude"  # Alias for anthropic
    AZURE = "azure"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    GROQ = "groq"
    MISTRAL = "mistral"
    COHERE = "cohere"


class GitProvider(str, Enum):
    """Supported Git providers."""

    GITHUB = "github"
    GITLAB = "gitlab"
    BITBUCKET = "bitbucket"


class MonitorType(str, Enum):
    """Supported error monitoring platforms."""

    SENTRY = "sentry"
    DATADOG = "datadog"
    ROLLBAR = "rollbar"
    BUGSNAG = "bugsnag"


class SentryConfig(BaseModel):
    """Sentry-specific configuration."""

    auth_token: str = Field(default="", description="Sentry authentication token")
    org: str = Field(default="", description="Sentry organization slug")
    projects: list[str] = Field(default_factory=list, description="List of project slugs to monitor")
    base_url: str = Field(default="https://sentry.io/api/0", description="Sentry API base URL")


class DatadogConfig(BaseModel):
    """Datadog-specific configuration."""

    api_key: str = Field(default="", description="Datadog API key")
    app_key: str = Field(default="", description="Datadog Application key")
    site: str = Field(default="datadoghq.com", description="Datadog site (e.g., datadoghq.com, datadoghq.eu)")
    service: str = Field(default="", description="Default service name to filter by")
    env: str = Field(default="", description="Default environment to filter by")


class RollbarConfig(BaseModel):
    """Rollbar-specific configuration."""

    access_token: str = Field(default="", description="Rollbar project or account access token")
    account_slug: str = Field(default="", description="Account slug for account-level operations")
    project_slug: str = Field(default="", description="Default project slug")


class BugsnagConfig(BaseModel):
    """Bugsnag-specific configuration."""

    auth_token: str = Field(default="", description="Bugsnag Personal Auth Token")
    org_id: str = Field(default="", description="Organization ID")
    project_id: str = Field(default="", description="Default project ID")


class FilterConfig(BaseModel):
    """Filtering configuration for issues."""

    min_events: int = Field(default=1, ge=1, description="Minimum number of events to consider an issue")
    severity_levels: list[Severity] = Field(
        default_factory=lambda: [Severity.ERROR, Severity.FATAL],
        description="Severity levels to include",
    )
    max_age_days: int = Field(default=30, ge=1, description="Maximum age of issues in days")
    ignored_issues: list[str] = Field(default_factory=list, description="List of issue IDs to ignore")


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: LLMProvider = Field(default=LLMProvider.OPENAI, description="LLM provider name")
    api_key: str = Field(default="", description="API key for LLM provider")
    model: str = Field(default="", description="Model name to use (defaults based on provider)")
    max_tokens: int = Field(default=4096, ge=1, description="Maximum tokens for responses")
    temperature: float = Field(default=0.1, ge=0.0, le=2.0, description="Temperature for generation")

    # Azure-specific settings
    azure_endpoint: str = Field(default="", description="Azure OpenAI endpoint URL")
    azure_deployment: str = Field(default="", description="Azure OpenAI deployment name")
    azure_api_version: str = Field(default="2024-02-15-preview", description="Azure API version")

    # Ollama-specific settings
    ollama_base_url: str = Field(default="http://localhost:11434", description="Ollama server URL")

    # Groq-specific settings (uses standard api_key)

    # Mistral-specific settings (uses standard api_key)

    # Cohere-specific settings (uses standard api_key)


class GitConfig(BaseModel):
    """Git provider configuration."""

    provider: GitProvider = Field(default=GitProvider.GITHUB, description="Git provider")
    token: str = Field(default="", description="Git provider authentication token")
    branch_prefix: str = Field(default="bughawk/fix-", description="Prefix for auto-created branches")
    auto_pr: bool = Field(default=False, description="Automatically create pull requests")
    base_branch: str = Field(default="main", description="Base branch for PRs")
    remote: str = Field(default="origin", description="Git remote to push to (e.g., origin, upstream)")


class NotificationChannelConfig(BaseModel):
    """Configuration for a single notification channel."""

    name: str = Field(default="", description="Channel name for identification")
    enabled: bool = Field(default=True, description="Enable this channel")
    webhook_url: str = Field(default="", description="Webhook URL")
    environment: str = Field(default="production", description="Environment: dev, staging, production")
    mention_users: list[str] = Field(default_factory=list, description="User IDs to mention")
    mention_groups: list[str] = Field(default_factory=list, description="Group IDs to mention")


class NotificationsConfig(BaseModel):
    """Notifications configuration - supports multiple channels."""

    slack: NotificationChannelConfig = Field(default_factory=NotificationChannelConfig)
    teams: NotificationChannelConfig = Field(default_factory=NotificationChannelConfig)
    discord: NotificationChannelConfig = Field(default_factory=NotificationChannelConfig)
    custom_webhooks: list[NotificationChannelConfig] = Field(
        default_factory=list, description="Additional custom webhook endpoints"
    )


class BugHawkConfig(BaseModel):
    """Main BugHawk configuration."""

    # Monitor configuration - defaults to sentry for backward compatibility
    monitor: MonitorType = Field(default=MonitorType.SENTRY, description="Active error monitoring platform")

    # Platform-specific configurations
    sentry: SentryConfig = Field(default_factory=SentryConfig)
    datadog: DatadogConfig = Field(default_factory=DatadogConfig)
    rollbar: RollbarConfig = Field(default_factory=RollbarConfig)
    bugsnag: BugsnagConfig = Field(default_factory=BugsnagConfig)

    # Common configurations
    filters: FilterConfig = Field(default_factory=FilterConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    git: GitConfig = Field(default_factory=GitConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    debug: bool = Field(default=False, description="Enable debug mode")
    output_dir: Path = Field(default=Path(".bughawk"), description="Output directory for reports")

    @model_validator(mode="after")
    def validate_required_for_operations(self) -> "BugHawkConfig":
        """Validate that required fields are present for operations."""
        return self

    def get_active_monitor_config(self) -> dict:
        """Get the configuration for the active monitor.

        Returns:
            Dictionary with monitor-specific configuration
        """
        if self.monitor == MonitorType.SENTRY:
            return {
                "auth_token": self.sentry.auth_token,
                "org": self.sentry.org,
                "project": self.sentry.projects[0] if self.sentry.projects else "",
                "base_url": self.sentry.base_url,
            }
        elif self.monitor == MonitorType.DATADOG:
            return {
                "api_key": self.datadog.api_key,
                "app_key": self.datadog.app_key,
                "site": self.datadog.site,
                "service": self.datadog.service,
                "env": self.datadog.env,
            }
        elif self.monitor == MonitorType.ROLLBAR:
            return {
                "access_token": self.rollbar.access_token,
                "account_slug": self.rollbar.account_slug,
                "project_slug": self.rollbar.project_slug,
            }
        elif self.monitor == MonitorType.BUGSNAG:
            return {
                "auth_token": self.bugsnag.auth_token,
                "org_id": self.bugsnag.org_id,
                "project_id": self.bugsnag.project_id,
            }
        else:
            raise ValueError(f"Unknown monitor type: {self.monitor}")


class CLIOverrides(BaseModel):
    """Command-line argument overrides."""

    sentry_auth_token: str | None = None
    sentry_org: str | None = None
    sentry_projects: list[str] | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    git_token: str | None = None
    debug: bool | None = None


class ConfigurationError(Exception):
    """Raised when configuration is invalid or incomplete."""

    pass


def _find_config_file() -> Path | None:
    """Find .bughawk.yml in current directory or parents."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        config_file = directory / ".bughawk.yml"
        if config_file.exists():
            return config_file
        config_file = directory / ".bughawk.yaml"
        if config_file.exists():
            return config_file
    return None


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return data or {}


def _load_env_config() -> dict[str, Any]:
    """Load configuration from environment variables."""
    config: dict[str, Any] = {}

    env_mapping = {
        # Monitor type selection
        "BUGHAWK_MONITOR": ("monitor",),

        # Sentry configuration
        "BUGHAWK_SENTRY_AUTH_TOKEN": ("sentry", "auth_token"),
        "BUGHAWK_SENTRY_ORG": ("sentry", "org"),
        "BUGHAWK_SENTRY_PROJECTS": ("sentry", "projects"),
        "BUGHAWK_SENTRY_BASE_URL": ("sentry", "base_url"),

        # Datadog configuration
        "BUGHAWK_DATADOG_API_KEY": ("datadog", "api_key"),
        "BUGHAWK_DATADOG_APP_KEY": ("datadog", "app_key"),
        "BUGHAWK_DATADOG_SITE": ("datadog", "site"),
        "BUGHAWK_DATADOG_SERVICE": ("datadog", "service"),
        "BUGHAWK_DATADOG_ENV": ("datadog", "env"),

        # Rollbar configuration
        "BUGHAWK_ROLLBAR_ACCESS_TOKEN": ("rollbar", "access_token"),
        "BUGHAWK_ROLLBAR_ACCOUNT_SLUG": ("rollbar", "account_slug"),
        "BUGHAWK_ROLLBAR_PROJECT_SLUG": ("rollbar", "project_slug"),

        # Bugsnag configuration
        "BUGHAWK_BUGSNAG_AUTH_TOKEN": ("bugsnag", "auth_token"),
        "BUGHAWK_BUGSNAG_ORG_ID": ("bugsnag", "org_id"),
        "BUGHAWK_BUGSNAG_PROJECT_ID": ("bugsnag", "project_id"),

        # Filter configuration
        "BUGHAWK_FILTER_MIN_EVENTS": ("filters", "min_events"),
        "BUGHAWK_FILTER_MAX_AGE_DAYS": ("filters", "max_age_days"),

        # LLM configuration
        "BUGHAWK_LLM_PROVIDER": ("llm", "provider"),
        "BUGHAWK_LLM_API_KEY": ("llm", "api_key"),
        "BUGHAWK_LLM_MODEL": ("llm", "model"),
        "BUGHAWK_LLM_MAX_TOKENS": ("llm", "max_tokens"),
        "BUGHAWK_LLM_TEMPERATURE": ("llm", "temperature"),

        # Azure OpenAI specific
        "BUGHAWK_LLM_AZURE_ENDPOINT": ("llm", "azure_endpoint"),
        "BUGHAWK_LLM_AZURE_DEPLOYMENT": ("llm", "azure_deployment"),
        "BUGHAWK_LLM_AZURE_API_VERSION": ("llm", "azure_api_version"),

        # Ollama specific
        "BUGHAWK_LLM_OLLAMA_BASE_URL": ("llm", "ollama_base_url"),

        # Git configuration
        "BUGHAWK_GIT_PROVIDER": ("git", "provider"),
        "BUGHAWK_GIT_TOKEN": ("git", "token"),
        "BUGHAWK_GIT_BRANCH_PREFIX": ("git", "branch_prefix"),
        "BUGHAWK_GIT_AUTO_PR": ("git", "auto_pr"),
        "BUGHAWK_GIT_BASE_BRANCH": ("git", "base_branch"),

        # Notification configuration
        "BUGHAWK_SLACK_WEBHOOK_URL": ("notifications", "slack", "webhook_url"),
        "BUGHAWK_SLACK_ENABLED": ("notifications", "slack", "enabled"),
        "BUGHAWK_TEAMS_WEBHOOK_URL": ("notifications", "teams", "webhook_url"),
        "BUGHAWK_TEAMS_ENABLED": ("notifications", "teams", "enabled"),
        "BUGHAWK_DISCORD_WEBHOOK_URL": ("notifications", "discord", "webhook_url"),
        "BUGHAWK_DISCORD_ENABLED": ("notifications", "discord", "enabled"),

        # General configuration
        "BUGHAWK_DEBUG": ("debug",),
        "BUGHAWK_OUTPUT_DIR": ("output_dir",),
    }

    for env_var, path in env_mapping.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Handle type conversions
            if env_var == "BUGHAWK_SENTRY_PROJECTS":
                value = [p.strip() for p in value.split(",")]
            elif env_var in ("BUGHAWK_FILTER_MIN_EVENTS", "BUGHAWK_FILTER_MAX_AGE_DAYS", "BUGHAWK_LLM_MAX_TOKENS"):
                value = int(value)
            elif env_var == "BUGHAWK_LLM_TEMPERATURE":
                value = float(value)
            elif env_var in ("BUGHAWK_DEBUG", "BUGHAWK_GIT_AUTO_PR", "BUGHAWK_SLACK_ENABLED", "BUGHAWK_TEAMS_ENABLED", "BUGHAWK_DISCORD_ENABLED"):
                value = value.lower() in ("true", "1", "yes")

            # Set nested value (supports up to 3 levels)
            if len(path) == 1:
                config[path[0]] = value
            elif len(path) == 2:
                if path[0] not in config:
                    config[path[0]] = {}
                config[path[0]][path[1]] = value
            elif len(path) == 3:
                if path[0] not in config:
                    config[path[0]] = {}
                if path[1] not in config[path[0]]:
                    config[path[0]][path[1]] = {}
                config[path[0]][path[1]][path[2]] = value

    return config


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_cli_overrides(config: dict[str, Any], overrides: CLIOverrides) -> dict[str, Any]:
    """Apply CLI overrides to configuration."""
    if overrides.sentry_auth_token is not None:
        config.setdefault("sentry", {})["auth_token"] = overrides.sentry_auth_token
    if overrides.sentry_org is not None:
        config.setdefault("sentry", {})["org"] = overrides.sentry_org
    if overrides.sentry_projects is not None:
        config.setdefault("sentry", {})["projects"] = overrides.sentry_projects
    if overrides.llm_api_key is not None:
        config.setdefault("llm", {})["api_key"] = overrides.llm_api_key
    if overrides.llm_model is not None:
        config.setdefault("llm", {})["model"] = overrides.llm_model
    if overrides.git_token is not None:
        config.setdefault("git", {})["token"] = overrides.git_token
    if overrides.debug is not None:
        config["debug"] = overrides.debug
    return config


def load_config(
    config_path: Path | None = None,
    cli_overrides: CLIOverrides | None = None,
) -> BugHawkConfig:
    """Load configuration from all sources.

    Priority (highest to lowest):
    1. CLI overrides
    2. Environment variables
    3. YAML config file
    4. Default values

    Args:
        config_path: Optional explicit path to config file
        cli_overrides: Optional CLI argument overrides

    Returns:
        Validated BugHawkConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    # Start with empty config (defaults come from Pydantic models)
    config: dict[str, Any] = {}

    # Load YAML config (lowest priority)
    yaml_path = config_path or _find_config_file()
    if yaml_path is not None:
        try:
            yaml_config = _load_yaml_config(yaml_path)
            config = _deep_merge(config, yaml_config)
        except yaml.YAMLError as e:
            raise ConfigurationError(f"Invalid YAML in config file: {e}") from e
        except OSError as e:
            raise ConfigurationError(f"Cannot read config file: {e}") from e

    # Apply environment variables
    env_config = _load_env_config()
    config = _deep_merge(config, env_config)

    # Apply CLI overrides (highest priority)
    if cli_overrides is not None:
        config = _apply_cli_overrides(config, cli_overrides)

    # Create and validate config
    try:
        return BugHawkConfig(**config)
    except Exception as e:
        raise ConfigurationError(f"Invalid configuration: {e}") from e


def validate_config_for_fetch(config: BugHawkConfig) -> None:
    """Validate that config has required fields for fetching issues.

    Validates based on the active monitor type.

    Args:
        config: Configuration to validate

    Raises:
        ConfigurationError: If required fields are missing
    """
    errors: list[str] = []

    if config.monitor == MonitorType.SENTRY:
        if not config.sentry.auth_token:
            errors.append("Sentry auth token is required (set BUGHAWK_SENTRY_AUTH_TOKEN or sentry.auth_token in config)")
        if not config.sentry.org:
            errors.append("Sentry organization is required (set BUGHAWK_SENTRY_ORG or sentry.org in config)")
        if not config.sentry.projects:
            errors.append("At least one Sentry project is required (set BUGHAWK_SENTRY_PROJECTS or sentry.projects in config)")

    elif config.monitor == MonitorType.DATADOG:
        if not config.datadog.api_key:
            errors.append("Datadog API key is required (set BUGHAWK_DATADOG_API_KEY or datadog.api_key in config)")
        if not config.datadog.app_key:
            errors.append("Datadog Application key is required (set BUGHAWK_DATADOG_APP_KEY or datadog.app_key in config)")

    elif config.monitor == MonitorType.ROLLBAR:
        if not config.rollbar.access_token:
            errors.append("Rollbar access token is required (set BUGHAWK_ROLLBAR_ACCESS_TOKEN or rollbar.access_token in config)")

    elif config.monitor == MonitorType.BUGSNAG:
        if not config.bugsnag.auth_token:
            errors.append("Bugsnag auth token is required (set BUGHAWK_BUGSNAG_AUTH_TOKEN or bugsnag.auth_token in config)")
        if not config.bugsnag.org_id:
            errors.append("Bugsnag organization ID is required (set BUGHAWK_BUGSNAG_ORG_ID or bugsnag.org_id in config)")

    if errors:
        raise ConfigurationError("Missing required configuration:\n  - " + "\n  - ".join(errors))


def validate_config_for_fix(config: BugHawkConfig) -> None:
    """Validate that config has required fields for fixing issues.

    Args:
        config: Configuration to validate

    Raises:
        ConfigurationError: If required fields are missing
    """
    validate_config_for_fetch(config)

    errors: list[str] = []

    if not config.llm.api_key:
        errors.append("LLM API key is required for fixing (set BUGHAWK_LLM_API_KEY or llm.api_key in config)")

    if errors:
        raise ConfigurationError("Missing required configuration:\n  - " + "\n  - ".join(errors))


@lru_cache(maxsize=1)
def get_config() -> BugHawkConfig:
    """Get cached configuration singleton.

    Returns:
        Cached BugHawkConfig instance
    """
    return load_config()


# Legacy Settings class for backward compatibility with SentryClient


class Settings(BaseModel):
    """Legacy settings class for SentryClient compatibility.

    This class provides a simplified interface expected by the SentryClient.
    It wraps the main BugHawkConfig for backward compatibility.
    """

    sentry_auth_token: str = ""
    sentry_org: str = ""
    sentry_project: str = ""

    @classmethod
    def from_config(cls, config: BugHawkConfig) -> "Settings":
        """Create Settings from BugHawkConfig.

        Args:
            config: The main configuration object

        Returns:
            Settings instance with values from config
        """
        return cls(
            sentry_auth_token=config.sentry.auth_token,
            sentry_org=config.sentry.org,
            sentry_project=config.sentry.projects[0] if config.sentry.projects else "",
        )


def get_settings() -> Settings:
    """Get legacy settings for SentryClient.

    Returns:
        Settings instance with current configuration values
    """
    config = get_config()
    return Settings.from_config(config)


def create_monitor_client(config: BugHawkConfig):
    """Create a monitor client based on the active configuration.

    Args:
        config: BugHawk configuration

    Returns:
        An instance of the appropriate MonitorClient subclass

    Raises:
        ConfigurationError: If the monitor type is not supported
    """
    from bughawk.monitors import get_monitor_client

    monitor_type = config.monitor.value

    if monitor_type == "sentry":
        return get_monitor_client(
            "sentry",
            auth_token=config.sentry.auth_token,
            org=config.sentry.org,
            project=config.sentry.projects[0] if config.sentry.projects else "",
            base_url=config.sentry.base_url,
        )
    elif monitor_type == "datadog":
        return get_monitor_client(
            "datadog",
            api_key=config.datadog.api_key,
            app_key=config.datadog.app_key,
            site=config.datadog.site,
            service=config.datadog.service,
            env=config.datadog.env,
        )
    elif monitor_type == "rollbar":
        return get_monitor_client(
            "rollbar",
            access_token=config.rollbar.access_token,
            account_slug=config.rollbar.account_slug,
            project_slug=config.rollbar.project_slug,
        )
    elif monitor_type == "bugsnag":
        return get_monitor_client(
            "bugsnag",
            auth_token=config.bugsnag.auth_token,
            org_id=config.bugsnag.org_id,
            project_id=config.bugsnag.project_id,
        )
    else:
        raise ConfigurationError(f"Unsupported monitor type: {monitor_type}")
