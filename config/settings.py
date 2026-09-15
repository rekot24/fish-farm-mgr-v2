"""
config/settings.py

Global settings schema, loader, and saver.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from config.paths import settings_path, project_root
from config.constants import (
    DOUBLE_CLICK_DELAY_S,
    LOBBY_STUCK_THRESHOLD_S,
    LOOP_INTERVAL_S,
)


@dataclass
class LoggingConfig:
    """
    Controls Stream 1 — the persistent log record.
    Completely independent of development mode.
    """
    log_to_file: bool = True
    level: str = "INFO"
    max_file_size_mb: int = 10
    backup_count: int = 3


@dataclass
class DebugConfig:
    """
    Controls the debug panel and its two independent streams.
    The panel master switch is Settings.development_mode — not here.

    Stream 1 — log data (INFO/WARNING/ERROR):
        show_log_in_panel: routes log() output to the debug panel

    Stream 2 — debug data (verbose, cycle-by-cycle):
        show_debug_in_panel: routes debug() output to the debug panel
        log_state_changes / log_detections / log_actions / log_config_reads:
            per-category gates for Stream 2 only
    """
    show_log_in_panel: bool = True
    show_debug_in_panel: bool = False
    log_state_changes: bool = True
    log_detections: bool = False
    log_actions: bool = True
    log_config_reads: bool = False


@dataclass
class Settings:
    """All global app settings."""

    double_click_delay_s: float = DOUBLE_CLICK_DELAY_S
    lobby_stuck_threshold_s: float = LOBBY_STUCK_THRESHOLD_S
    unknown_stuck_threshold_s: float = 60.0
    loop_interval_s: float = LOOP_INTERVAL_S
    development_mode: bool = False   # master switch for the debug panel

    logging: LoggingConfig = field(default_factory=LoggingConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)

    def log_file_path(self) -> Path:
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

        # Strip legacy/stale keys from logging
        logging_raw = merged.pop("logging", {})
        for old in ("enabled", "log_to_console", "log_debug_messages"):
            logging_raw.pop(old, None)
        logging_cfg = LoggingConfig(**{
            k: v for k, v in _deep_merge(asdict(LoggingConfig()), logging_raw).items()
            if k in LoggingConfig.__dataclass_fields__
        })

        # Strip legacy/stale keys from debug
        debug_raw = merged.pop("debug", {})
        for old in ("enabled", "log_debug_messages"):
            debug_raw.pop(old, None)
        if "show_in_panel" in debug_raw:
            debug_raw.setdefault("show_log_in_panel", debug_raw.pop("show_in_panel"))
        debug_cfg = DebugConfig(**{
            k: v for k, v in _deep_merge(asdict(DebugConfig()), debug_raw).items()
            if k in DebugConfig.__dataclass_fields__
        })

        valid = set(Settings.__dataclass_fields__)
        merged = {k: v for k, v in merged.items() if k in valid}
        return Settings(logging=logging_cfg, debug=debug_cfg, **merged)

    except Exception as e:
        print(f"[WARNING] Failed to load settings.json: {e} — using defaults")
        return Settings()


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=2)
