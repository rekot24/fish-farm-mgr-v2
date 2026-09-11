"""
config/settings.py

Global settings schema, loader, and saver.
Single source of truth for all app-wide configuration.

Loads from config/settings.json on startup, falls back to defaults
for any missing keys. Saves back to disk when updated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict

from config.paths import settings_path
from config.constants import (
    DOUBLE_CLICK_DELAY_S,
    LOBBY_STUCK_THRESHOLD_S,
    DISCONNECT_TIMEOUT_S,
    LOOP_INTERVAL_S,
)


# ---------------------------------------------------------------------------
# Sub-configs
# ---------------------------------------------------------------------------

@dataclass
class LoggingConfig:
    """Controls persistent log output."""
    enabled: bool = True
    level: str = "INFO"            # DEBUG / INFO / WARNING / ERROR / CRITICAL
    log_to_file: bool = True
    log_to_console: bool = True
    max_file_size_mb: int = 10
    backup_count: int = 3


@dataclass
class DebugConfig:
    """
    Debug output layer (Layer 3 of dev-standards).
    All categories are additive — turning one on never silences normal logging.
    """
    enabled: bool = False
    log_state_changes: bool = True
    log_detections: bool = False
    log_actions: bool = True
    log_config_reads: bool = False


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    """
    All global app settings. Every field has a safe default so the app
    runs correctly even with an empty or missing settings.json.
    """

    # Private server link — used for all rejoin/recovery actions.
    private_server_link: str = ""

    # Delay between the two taps of every double-click (seconds).
    double_click_delay_s: float = DOUBLE_CLICK_DELAY_S

    # How long a device can sit in the lobby before it is considered stuck.
    lobby_stuck_threshold_s: float = LOBBY_STUCK_THRESHOLD_S

    # How long to wait for a reconnect before giving up and tapping Leave.
    disconnect_timeout_s: float = DISCONNECT_TIMEOUT_S

    # Worker loop interval — how often each device captures and checks state.
    loop_interval_s: float = LOOP_INTERVAL_S

    # Development mode: fail loudly (raise) vs gracefully (log + continue).
    development_mode: bool = False

    logging: LoggingConfig = field(default_factory=LoggingConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def _deep_merge(defaults: dict, overrides: dict) -> dict:
    """
    Deep-merge overrides into defaults. Keys in overrides win;
    keys missing from overrides keep their default value.
    """
    result = dict(defaults)
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_settings() -> Settings:
    """
    Load settings from config/settings.json.
    Returns defaults for any missing keys. Returns full defaults if file is absent.
    """
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        defaults = asdict(Settings())
        merged = _deep_merge(defaults, raw)
        logging_cfg = LoggingConfig(**_deep_merge(asdict(LoggingConfig()), merged.pop("logging", {})))
        debug_cfg = DebugConfig(**_deep_merge(asdict(DebugConfig()), merged.pop("debug", {})))
        return Settings(logging=logging_cfg, debug=debug_cfg, **{k: v for k, v in merged.items()})
    except Exception as e:
        print(f"[WARNING] Failed to load settings.json: {e} — using defaults")
        return Settings()


def save_settings(settings: Settings) -> None:
    """
    Persist settings to config/settings.json.
    Creates the file if it does not exist.
    """
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)
