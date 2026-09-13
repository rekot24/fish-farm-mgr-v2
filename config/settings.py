"""
config/settings.py

Global settings schema, loader, and saver.
Single source of truth for all app-wide configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from config.paths import settings_path, project_root
from config.constants import (
    DOUBLE_CLICK_DELAY_S,
    LOBBY_STUCK_THRESHOLD_S,
    DISCONNECT_TIMEOUT_S,
    LOOP_INTERVAL_S,
)


@dataclass
class LoggingConfig:
    """Controls persistent log output to file."""
    log_to_file: bool = True
    level: str = "INFO"            # DEBUG / INFO / WARNING / ERROR / CRITICAL
    max_file_size_mb: int = 10
    backup_count: int = 3

    # When log_to_file is False, only CRITICAL/ERROR still write to errors.log.
    # The four sub-categories below are suppressed entirely when log_to_file is False.


@dataclass
class DebugConfig:
    """
    Debug panel and debug-level output settings.
    All categories are additive — turning one on never silences normal logging.
    """
    enabled: bool = False              # master switch — controls debug panel visibility
    show_in_panel: bool = True         # route log output to the in-app debug panel
    log_debug_messages: bool = False   # enable DEBUG-level messages (suppresses if off)
    log_state_changes: bool = True
    log_detections: bool = False
    log_actions: bool = True
    log_config_reads: bool = False


@dataclass
class Settings:
    """All global app settings."""

    private_server_link: str = ""
    double_click_delay_s: float = DOUBLE_CLICK_DELAY_S
    lobby_stuck_threshold_s: float = LOBBY_STUCK_THRESHOLD_S
    disconnect_timeout_s: float = DISCONNECT_TIMEOUT_S
    loop_interval_s: float = LOOP_INTERVAL_S
    development_mode: bool = False

    logging: LoggingConfig = field(default_factory=LoggingConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    def log_file_path(self) -> Path:
        """Return the resolved path to the main log file."""
        return project_root() / "logs" / "app.log"


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    result = dict(defaults)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings() -> Settings:
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        defaults = asdict(Settings())
        merged = _deep_merge(defaults, raw)

        # Strip legacy keys that no longer exist in LoggingConfig
        logging_raw = merged.pop("logging", {})
        for old_key in ("enabled", "log_to_console"):
            logging_raw.pop(old_key, None)
        logging_cfg = LoggingConfig(**_deep_merge(asdict(LoggingConfig()), logging_raw))

        debug_raw = merged.pop("debug", {})
        # Migrate old key names
        if "enabled" in debug_raw and "enabled" not in asdict(DebugConfig()):
            debug_raw.pop("enabled", None)
        debug_cfg = DebugConfig(**_deep_merge(asdict(DebugConfig()), debug_raw))

        # Strip keys not in Settings
        valid_keys = {f.name for f in Settings.__dataclass_fields__.values()}
        merged = {k: v for k, v in merged.items() if k in valid_keys}

        return Settings(logging=logging_cfg, debug=debug_cfg, **merged)
    except Exception as e:
        print(f"[WARNING] Failed to load settings.json: {e} — using defaults")
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)
