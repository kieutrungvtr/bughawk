"""Tests for BugHawk Configuration Management.

This test file is organized by feature groups:

Feature Groups:
1. Enums and Constants
2. Pydantic Config Models
3. Configuration Loading
4. Environment Variable Loading
5. YAML Configuration
6. CLI Overrides
7. Configuration Validation
8. Legacy Settings Compatibility
9. Monitor Client Creation
10. Deep Merge Utility
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch, mock_open

import pytest


# =============================================================================
# Feature Group 1: Enums and Constants
# =============================================================================


class TestEnums:
    """Tests for configuration enums."""

    def test_severity_enum_values(self):
        """Test Severity enum has all expected values."""
        from bughawk.core.config import Severity

        assert Severity.DEBUG.value == "debug"
        assert Severity.INFO.value == "info"
        assert Severity.WARNING.value == "warning"
        assert Severity.ERROR.value == "error"
        assert Severity.FATAL.value == "fatal"

    def test_llm_provider_enum_values(self):
        """Test LLMProvider enum has all supported providers."""
        from bughawk.core.config import LLMProvider

        expected = ["openai", "anthropic", "claude", "azure", "gemini", "ollama", "groq", "mistral", "cohere"]
        values = [p.value for p in LLMProvider]

        for provider in expected:
            assert provider in values

    def test_git_provider_enum_values(self):
        """Test GitProvider enum has all supported providers."""
        from bughawk.core.config import GitProvider

        assert GitProvider.GITHUB.value == "github"
        assert GitProvider.GITLAB.value == "gitlab"
        assert GitProvider.BITBUCKET.value == "bitbucket"

    def test_monitor_type_enum_values(self):
        """Test MonitorType enum has all supported monitors."""
        from bughawk.core.config import MonitorType

        assert MonitorType.SENTRY.value == "sentry"
        assert MonitorType.DATADOG.value == "datadog"
        assert MonitorType.ROLLBAR.value == "rollbar"
        assert MonitorType.BUGSNAG.value == "bugsnag"


# =============================================================================
# Feature Group 2: Pydantic Config Models
# =============================================================================


class TestSentryConfig:
    """Tests for SentryConfig model."""

    def test_default_values(self):
        """Test SentryConfig default values."""
        from bughawk.core.config import SentryConfig

        config = SentryConfig()

        assert config.auth_token == ""
        assert config.org == ""
        assert config.projects == []
        assert config.base_url == "https://sentry.io/api/0"

    def test_custom_values(self):
        """Test SentryConfig with custom values."""
        from bughawk.core.config import SentryConfig

        config = SentryConfig(
            auth_token="test-token",
            org="test-org",
            projects=["project1", "project2"],
            base_url="https://custom.sentry.io/api/0",
        )

        assert config.auth_token == "test-token"
        assert config.org == "test-org"
        assert config.projects == ["project1", "project2"]


class TestDatadogConfig:
    """Tests for DatadogConfig model."""

    def test_default_values(self):
        """Test DatadogConfig default values."""
        from bughawk.core.config import DatadogConfig

        config = DatadogConfig()

        assert config.api_key == ""
        assert config.app_key == ""
        assert config.site == "datadoghq.com"
        assert config.service == ""
        assert config.env == ""


class TestRollbarConfig:
    """Tests for RollbarConfig model."""

    def test_default_values(self):
        """Test RollbarConfig default values."""
        from bughawk.core.config import RollbarConfig

        config = RollbarConfig()

        assert config.access_token == ""
        assert config.account_slug == ""
        assert config.project_slug == ""


class TestBugsnagConfig:
    """Tests for BugsnagConfig model."""

    def test_default_values(self):
        """Test BugsnagConfig default values."""
        from bughawk.core.config import BugsnagConfig

        config = BugsnagConfig()

        assert config.auth_token == ""
        assert config.org_id == ""
        assert config.project_id == ""


class TestFilterConfig:
    """Tests for FilterConfig model."""

    def test_default_values(self):
        """Test FilterConfig default values."""
        from bughawk.core.config import FilterConfig, Severity

        config = FilterConfig()

        assert config.min_events == 1
        assert config.max_age_days == 30
        assert config.ignored_issues == []
        assert Severity.ERROR in config.severity_levels
        assert Severity.FATAL in config.severity_levels

    def test_min_events_validation(self):
        """Test min_events must be >= 1."""
        from bughawk.core.config import FilterConfig
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FilterConfig(min_events=0)


class TestLLMConfig:
    """Tests for LLMConfig model."""

    def test_default_values(self):
        """Test LLMConfig default values."""
        from bughawk.core.config import LLMConfig, LLMProvider

        config = LLMConfig()

        assert config.provider == LLMProvider.OPENAI
        assert config.api_key == ""
        assert config.model == ""
        assert config.max_tokens == 4096
        assert config.temperature == 0.1
        assert config.ollama_base_url == "http://localhost:11434"

    def test_temperature_validation(self):
        """Test temperature must be 0.0-2.0."""
        from bughawk.core.config import LLMConfig
        from pydantic import ValidationError

        # Valid temperatures
        LLMConfig(temperature=0.0)
        LLMConfig(temperature=1.0)
        LLMConfig(temperature=2.0)

        # Invalid temperature
        with pytest.raises(ValidationError):
            LLMConfig(temperature=3.0)


class TestGitConfig:
    """Tests for GitConfig model."""

    def test_default_values(self):
        """Test GitConfig default values."""
        from bughawk.core.config import GitConfig, GitProvider

        config = GitConfig()

        assert config.provider == GitProvider.GITHUB
        assert config.token == ""
        assert config.branch_prefix == "bughawk/fix-"
        assert config.auto_pr is False
        assert config.base_branch == "main"


class TestBugHawkConfig:
    """Tests for main BugHawkConfig model."""

    def test_default_values(self):
        """Test BugHawkConfig default values."""
        from bughawk.core.config import BugHawkConfig, MonitorType

        config = BugHawkConfig()

        assert config.monitor == MonitorType.SENTRY
        assert config.debug is False
        assert config.output_dir == Path(".bughawk")

    def test_get_active_monitor_config_sentry(self):
        """Test get_active_monitor_config for Sentry."""
        from bughawk.core.config import BugHawkConfig, MonitorType, SentryConfig

        config = BugHawkConfig(
            monitor=MonitorType.SENTRY,
            sentry=SentryConfig(
                auth_token="token",
                org="org",
                projects=["proj1"],
            ),
        )

        result = config.get_active_monitor_config()

        assert result["auth_token"] == "token"
        assert result["org"] == "org"
        assert result["project"] == "proj1"

    def test_get_active_monitor_config_datadog(self):
        """Test get_active_monitor_config for Datadog."""
        from bughawk.core.config import BugHawkConfig, MonitorType, DatadogConfig

        config = BugHawkConfig(
            monitor=MonitorType.DATADOG,
            datadog=DatadogConfig(
                api_key="api-key",
                app_key="app-key",
                site="datadoghq.eu",
            ),
        )

        result = config.get_active_monitor_config()

        assert result["api_key"] == "api-key"
        assert result["app_key"] == "app-key"
        assert result["site"] == "datadoghq.eu"


class TestCLIOverrides:
    """Tests for CLIOverrides model."""

    def test_all_fields_optional(self):
        """Test all CLIOverrides fields are optional."""
        from bughawk.core.config import CLIOverrides

        overrides = CLIOverrides()

        assert overrides.sentry_auth_token is None
        assert overrides.sentry_org is None
        assert overrides.debug is None

    def test_with_values(self):
        """Test CLIOverrides with values."""
        from bughawk.core.config import CLIOverrides

        overrides = CLIOverrides(
            sentry_auth_token="cli-token",
            debug=True,
        )

        assert overrides.sentry_auth_token == "cli-token"
        assert overrides.debug is True


# =============================================================================
# Feature Group 3: Configuration Loading
# =============================================================================


class TestConfigurationLoading:
    """Tests for configuration loading."""

    @patch("bughawk.core.config._find_config_file")
    @patch("bughawk.core.config._load_env_config")
    def test_load_config_defaults(self, mock_env, mock_find):
        """Test load_config with no config file or env vars."""
        from bughawk.core.config import load_config

        mock_find.return_value = None
        mock_env.return_value = {}

        config = load_config()

        assert config is not None
        assert config.debug is False

    @patch("bughawk.core.config._find_config_file")
    @patch("bughawk.core.config._load_env_config")
    @patch("bughawk.core.config._load_yaml_config")
    def test_load_config_from_yaml(self, mock_yaml, mock_env, mock_find):
        """Test load_config from YAML file."""
        from bughawk.core.config import load_config

        mock_find.return_value = Path(".bughawk.yml")
        mock_yaml.return_value = {
            "debug": True,
            "sentry": {"org": "yaml-org"},
        }
        mock_env.return_value = {}

        config = load_config()

        assert config.debug is True
        assert config.sentry.org == "yaml-org"


# =============================================================================
# Feature Group 4: Environment Variable Loading
# =============================================================================


class TestEnvConfigLoading:
    """Tests for environment variable loading."""

    @patch.dict(os.environ, {"BUGHAWK_DEBUG": "true"}, clear=True)
    def test_load_debug_from_env(self):
        """Test loading debug flag from environment."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        assert result.get("debug") is True

    @patch.dict(os.environ, {"BUGHAWK_SENTRY_ORG": "env-org"}, clear=True)
    def test_load_nested_from_env(self):
        """Test loading nested config from environment."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        assert result.get("sentry", {}).get("org") == "env-org"

    @patch.dict(os.environ, {"BUGHAWK_SENTRY_PROJECTS": "proj1, proj2, proj3"}, clear=True)
    def test_load_list_from_env(self):
        """Test loading list from comma-separated environment variable."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        projects = result.get("sentry", {}).get("projects")
        assert projects == ["proj1", "proj2", "proj3"]

    @patch.dict(os.environ, {"BUGHAWK_FILTER_MIN_EVENTS": "10"}, clear=True)
    def test_load_int_from_env(self):
        """Test loading integer from environment."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        assert result.get("filters", {}).get("min_events") == 10

    @patch.dict(os.environ, {"BUGHAWK_LLM_TEMPERATURE": "0.5"}, clear=True)
    def test_load_float_from_env(self):
        """Test loading float from environment."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        assert result.get("llm", {}).get("temperature") == 0.5

    @patch.dict(os.environ, {"BUGHAWK_GIT_AUTO_PR": "yes"}, clear=True)
    def test_load_bool_yes_from_env(self):
        """Test loading bool 'yes' value from environment."""
        from bughawk.core.config import _load_env_config

        result = _load_env_config()

        assert result.get("git", {}).get("auto_pr") is True


# =============================================================================
# Feature Group 5: YAML Configuration
# =============================================================================


class TestYAMLConfiguration:
    """Tests for YAML configuration loading."""

    def test_find_config_file_current_dir(self, tmp_path):
        """Test finding config file in current directory."""
        config_file = tmp_path / ".bughawk.yml"
        config_file.write_text("debug: true\n")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            from bughawk.core.config import _find_config_file

            result = _find_config_file()

            assert result == config_file

    def test_find_config_file_yaml_extension(self, tmp_path):
        """Test finding config file with .yaml extension."""
        config_file = tmp_path / ".bughawk.yaml"
        config_file.write_text("debug: true\n")

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            from bughawk.core.config import _find_config_file

            result = _find_config_file()

            assert result == config_file

    def test_find_config_file_not_found(self, tmp_path):
        """Test when no config file exists."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            from bughawk.core.config import _find_config_file

            result = _find_config_file()

            assert result is None

    def test_load_yaml_config(self, tmp_path):
        """Test loading YAML configuration."""
        config_file = tmp_path / ".bughawk.yml"
        config_file.write_text("""
sentry:
  auth_token: yaml-token
  org: yaml-org
debug: true
""")

        from bughawk.core.config import _load_yaml_config

        result = _load_yaml_config(config_file)

        assert result["debug"] is True
        assert result["sentry"]["auth_token"] == "yaml-token"
        assert result["sentry"]["org"] == "yaml-org"

    def test_load_yaml_config_empty(self, tmp_path):
        """Test loading empty YAML file."""
        config_file = tmp_path / ".bughawk.yml"
        config_file.write_text("")

        from bughawk.core.config import _load_yaml_config

        result = _load_yaml_config(config_file)

        assert result == {}


# =============================================================================
# Feature Group 6: CLI Overrides
# =============================================================================


class TestCLIOverridesApplication:
    """Tests for CLI overrides application."""

    def test_apply_sentry_auth_token_override(self):
        """Test applying sentry_auth_token CLI override."""
        from bughawk.core.config import _apply_cli_overrides, CLIOverrides

        config = {}
        overrides = CLIOverrides(sentry_auth_token="cli-token")

        result = _apply_cli_overrides(config, overrides)

        assert result["sentry"]["auth_token"] == "cli-token"

    def test_apply_debug_override(self):
        """Test applying debug CLI override."""
        from bughawk.core.config import _apply_cli_overrides, CLIOverrides

        config = {"debug": False}
        overrides = CLIOverrides(debug=True)

        result = _apply_cli_overrides(config, overrides)

        assert result["debug"] is True

    def test_apply_multiple_overrides(self):
        """Test applying multiple CLI overrides."""
        from bughawk.core.config import _apply_cli_overrides, CLIOverrides

        config = {}
        overrides = CLIOverrides(
            sentry_auth_token="token",
            sentry_org="org",
            llm_api_key="llm-key",
            debug=True,
        )

        result = _apply_cli_overrides(config, overrides)

        assert result["sentry"]["auth_token"] == "token"
        assert result["sentry"]["org"] == "org"
        assert result["llm"]["api_key"] == "llm-key"
        assert result["debug"] is True


# =============================================================================
# Feature Group 7: Configuration Validation
# =============================================================================


class TestConfigurationValidation:
    """Tests for configuration validation."""

    def test_validate_config_for_fetch_sentry_valid(self):
        """Test validation for fetch with valid Sentry config."""
        from bughawk.core.config import (
            validate_config_for_fetch,
            BugHawkConfig,
            SentryConfig,
            MonitorType,
        )

        config = BugHawkConfig(
            monitor=MonitorType.SENTRY,
            sentry=SentryConfig(
                auth_token="token",
                org="org",
                projects=["project"],
            ),
        )

        # Should not raise
        validate_config_for_fetch(config)

    def test_validate_config_for_fetch_sentry_missing_token(self):
        """Test validation fails without Sentry auth token."""
        from bughawk.core.config import (
            validate_config_for_fetch,
            BugHawkConfig,
            SentryConfig,
            MonitorType,
            ConfigurationError,
        )

        config = BugHawkConfig(
            monitor=MonitorType.SENTRY,
            sentry=SentryConfig(
                org="org",
                projects=["project"],
            ),
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validate_config_for_fetch(config)
        assert "auth token" in str(exc_info.value).lower()

    def test_validate_config_for_fetch_datadog_valid(self):
        """Test validation for fetch with valid Datadog config."""
        from bughawk.core.config import (
            validate_config_for_fetch,
            BugHawkConfig,
            DatadogConfig,
            MonitorType,
        )

        config = BugHawkConfig(
            monitor=MonitorType.DATADOG,
            datadog=DatadogConfig(
                api_key="api-key",
                app_key="app-key",
            ),
        )

        # Should not raise
        validate_config_for_fetch(config)

    def test_validate_config_for_fetch_datadog_missing_app_key(self):
        """Test validation fails without Datadog app key."""
        from bughawk.core.config import (
            validate_config_for_fetch,
            BugHawkConfig,
            DatadogConfig,
            MonitorType,
            ConfigurationError,
        )

        config = BugHawkConfig(
            monitor=MonitorType.DATADOG,
            datadog=DatadogConfig(
                api_key="api-key",
            ),
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validate_config_for_fetch(config)
        assert "Application key" in str(exc_info.value)

    def test_validate_config_for_fix_missing_llm_key(self):
        """Test validation for fix fails without LLM API key."""
        from bughawk.core.config import (
            validate_config_for_fix,
            BugHawkConfig,
            SentryConfig,
            MonitorType,
            ConfigurationError,
        )

        config = BugHawkConfig(
            monitor=MonitorType.SENTRY,
            sentry=SentryConfig(
                auth_token="token",
                org="org",
                projects=["project"],
            ),
        )

        with pytest.raises(ConfigurationError) as exc_info:
            validate_config_for_fix(config)
        assert "LLM API key" in str(exc_info.value)


class TestConfigurationError:
    """Tests for ConfigurationError exception."""

    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        from bughawk.core.config import ConfigurationError

        error = ConfigurationError("Test error message")

        assert str(error) == "Test error message"
        assert isinstance(error, Exception)


# =============================================================================
# Feature Group 8: Legacy Settings Compatibility
# =============================================================================


class TestLegacySettings:
    """Tests for legacy Settings class compatibility."""

    def test_settings_default_values(self):
        """Test Settings default values."""
        from bughawk.core.config import Settings

        settings = Settings()

        assert settings.sentry_auth_token == ""
        assert settings.sentry_org == ""
        assert settings.sentry_project == ""

    def test_settings_from_config(self):
        """Test creating Settings from BugHawkConfig."""
        from bughawk.core.config import Settings, BugHawkConfig, SentryConfig

        config = BugHawkConfig(
            sentry=SentryConfig(
                auth_token="token",
                org="org",
                projects=["project1", "project2"],
            ),
        )

        settings = Settings.from_config(config)

        assert settings.sentry_auth_token == "token"
        assert settings.sentry_org == "org"
        assert settings.sentry_project == "project1"  # First project

    def test_settings_from_config_no_projects(self):
        """Test creating Settings when no projects configured."""
        from bughawk.core.config import Settings, BugHawkConfig, SentryConfig

        config = BugHawkConfig(
            sentry=SentryConfig(
                auth_token="token",
                org="org",
            ),
        )

        settings = Settings.from_config(config)

        assert settings.sentry_project == ""


# =============================================================================
# Feature Group 9: Monitor Client Creation
# =============================================================================


class TestMonitorClientCreation:
    """Tests for monitor client creation."""

    @patch("bughawk.core.config.get_monitor_client")
    def test_create_monitor_client_sentry(self, mock_get_client):
        """Test creating Sentry monitor client."""
        from bughawk.core.config import (
            create_monitor_client,
            BugHawkConfig,
            SentryConfig,
            MonitorType,
        )

        mock_get_client.return_value = MagicMock()

        config = BugHawkConfig(
            monitor=MonitorType.SENTRY,
            sentry=SentryConfig(
                auth_token="token",
                org="org",
                projects=["project"],
            ),
        )

        create_monitor_client(config)

        mock_get_client.assert_called_once_with(
            "sentry",
            auth_token="token",
            org="org",
            project="project",
            base_url="https://sentry.io/api/0",
        )

    @patch("bughawk.core.config.get_monitor_client")
    def test_create_monitor_client_datadog(self, mock_get_client):
        """Test creating Datadog monitor client."""
        from bughawk.core.config import (
            create_monitor_client,
            BugHawkConfig,
            DatadogConfig,
            MonitorType,
        )

        mock_get_client.return_value = MagicMock()

        config = BugHawkConfig(
            monitor=MonitorType.DATADOG,
            datadog=DatadogConfig(
                api_key="api-key",
                app_key="app-key",
                site="datadoghq.eu",
            ),
        )

        create_monitor_client(config)

        mock_get_client.assert_called_once_with(
            "datadog",
            api_key="api-key",
            app_key="app-key",
            site="datadoghq.eu",
            service="",
            env="",
        )


# =============================================================================
# Feature Group 10: Deep Merge Utility
# =============================================================================


class TestDeepMerge:
    """Tests for deep merge utility."""

    def test_deep_merge_flat(self):
        """Test deep merge with flat dictionaries."""
        from bughawk.core.config import _deep_merge

        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}

        result = _deep_merge(base, override)

        assert result == {"a": 1, "b": 3, "c": 4}

    def test_deep_merge_nested(self):
        """Test deep merge with nested dictionaries."""
        from bughawk.core.config import _deep_merge

        base = {"sentry": {"org": "base-org", "token": "base-token"}}
        override = {"sentry": {"org": "override-org"}}

        result = _deep_merge(base, override)

        assert result["sentry"]["org"] == "override-org"
        assert result["sentry"]["token"] == "base-token"

    def test_deep_merge_empty_base(self):
        """Test deep merge with empty base."""
        from bughawk.core.config import _deep_merge

        base = {}
        override = {"key": "value"}

        result = _deep_merge(base, override)

        assert result == {"key": "value"}

    def test_deep_merge_empty_override(self):
        """Test deep merge with empty override."""
        from bughawk.core.config import _deep_merge

        base = {"key": "value"}
        override = {}

        result = _deep_merge(base, override)

        assert result == {"key": "value"}

    def test_deep_merge_original_not_modified(self):
        """Test that deep merge doesn't modify original dicts."""
        from bughawk.core.config import _deep_merge

        base = {"a": 1}
        override = {"b": 2}

        _deep_merge(base, override)

        assert base == {"a": 1}
        assert override == {"b": 2}
