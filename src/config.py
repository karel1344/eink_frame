"""Configuration management module."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Union

import yaml


class Config:
    """Configuration manager for E-Ink Photo Frame."""

    DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.yaml"

    def __init__(self, config_path: Path | str | None = None):
        """Initialize configuration manager.

        Args:
            config_path: Path to settings.yaml. Uses default if not specified.
        """
        self._config_path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH
        self._config: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from YAML file."""
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
        else:
            self._config = {}

    def save(self) -> None:
        """Save configuration to YAML file."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_path, "w", encoding="utf-8") as f:
            yaml.dump(self._config, f, default_flow_style=False, allow_unicode=True)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., "wifi.ssid", "display.model")
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split(".")
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., "wifi.ssid", "display.model")
            value: Value to set
        """
        keys = key.split(".")
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def get_section(self, section: str) -> dict[str, Any]:
        """Get entire configuration section.

        Args:
            section: Section name (e.g., "wifi", "display")

        Returns:
            Section dictionary or empty dict
        """
        return self._config.get(section, {})

    def set_section(self, section: str, data: dict[str, Any]) -> None:
        """Set entire configuration section.

        Args:
            section: Section name (e.g., "wifi", "display")
            data: Section data dictionary
        """
        self._config[section] = data

    def to_dict(self) -> dict[str, Any]:
        """Get entire configuration as dictionary.

        Returns:
            Complete configuration dictionary
        """
        return self._config.copy()

    def update(self, data: dict[str, Any]) -> None:
        """Update configuration with dictionary (deep merge).

        Args:
            data: Dictionary to merge into configuration
        """
        self._deep_merge(self._config, data)

    def _deep_merge(self, base: dict, update: dict) -> None:
        """Deep merge update into base dictionary."""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    # Convenience properties for common settings
    @property
    def wifi_enabled(self) -> bool:
        return self.get("wifi.enabled", True)

    @property
    def wifi_ssid(self) -> str:
        return self.get("wifi.ssid", "")

    @property
    def wifi_password(self) -> str:
        return self.get("wifi.password", "")

    @property
    def ap_ssid_prefix(self) -> str:
        return self.get("web_ui.ap_ssid_prefix", "EinkFrame")

    @property
    def ap_timeout(self) -> int:
        return self.get("web_ui.timeout", 600)

    @property
    def ap_execution_mode(self) -> str:
        return self.get("web_ui.ap_execution_mode", "normal")

    @property
    def ap_safe_timeout(self) -> int:
        return self.get("web_ui.ap_safe_timeout", 60)

    @property
    def ap_password(self) -> str:
        return self.get("web_ui.ap_password", "")

    @property
    def recovery_enabled(self) -> bool:
        return self.get("web_ui.recovery_enabled", True)

    @property
    def captive_portal_enabled(self) -> bool:
        return self.get("web_ui.captive_portal_enabled", True)

    @property
    def display_model(self) -> str:
        return self.get("display.model", "spectra6_7in3")

    @property
    def photo_selection_mode(self) -> str:
        return self.get("photo_selection.mode", "random")

    @property
    def update_time(self) -> str:
        return self.get("schedule.update_time", "06:00")


# Global config instance
_config: Config | None = None


def get_config() -> Config:
    """Get global configuration instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """Reload global configuration from file."""
    global _config
    _config = Config()
    return _config
