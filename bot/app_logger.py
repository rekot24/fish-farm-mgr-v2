"""
bot/app_logger.py

Central logging setup and the single unified log function.

Two output destinations:
  1. File (app.log / errors.log) — always on for ERROR/CRITICAL;
     app.log gated by LoggingConfig.log_to_file
  2. Debug panel — in-app scrollable panel on the Main tab, visible only
     when development_mode is on and DebugConfig.show_in_panel is True

Panel routing:
  A UI callback is registered via register_panel_callback(fn) at startup.
  log() calls it on every message when panel routing is active.
  The callback is always called from whatever thread log() is called from —
  the panel widget uses .after() to marshal to the Tkinter main thread.

Usage:
    configure(settings, project_root)     # once at startup, again on reload
    log("worker started", "INFO")         # from anywhere
    debug(settings.debug, "detections", "...", self._log)  # opt-in detail
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings, LoggingConfig, DebugConfig

_logger = logging.getLogger("befish")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

_configured = False
_panel_callback: Optional[Callable[[str, str], None]] = None
_route_to_panel: bool = False

_LOG_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)


def register_panel_callback(fn: Callable[[str, str], None]) -> None:
    """
    Register the debug panel's message receiver.
    Called once from App after the UI is built.

    fn(msg, level) is called on every log() invocation when panel routing
    is active. The panel widget is responsible for thread-safety.
    """
    global _panel_callback
    _panel_callback = fn


def configure(settings: Settings, root: Path) -> None:
    """
    (Re)build logger handlers from current settings.
    Safe to call multiple times — clears existing handlers first.
    """
    global _configured, _route_to_panel

    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    cfg = settings.logging
    max_bytes = cfg.max_file_size_mb * 1024 * 1024

    # errors.log — always on, ERROR and above only, never gated
    error_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "errors.log", maxBytes=max_bytes, backupCount=cfg.backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(_LOG_FORMAT)
    _logger.addHandler(error_handler)

    # app.log — gated by log_to_file
    if cfg.log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "app.log", maxBytes=max_bytes, backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(_level_from_name(cfg.level))
        file_handler.setFormatter(_LOG_FORMAT)
        _logger.addHandler(file_handler)

    # Panel routing — active when dev mode on and show_in_panel on
    _route_to_panel = (
        settings.development_mode and settings.debug.show_in_panel
    )

    _configured = True


def log(msg: str, level: str = "INFO") -> None:
    """Single unified log function called by every component."""
    if _configured:
        _logger.log(_level_from_name(level), msg)
    else:
        print(f"[{level}] {msg}")

    # Route to debug panel if active
    if _route_to_panel and _panel_callback is not None:
        try:
            _panel_callback(msg, level)
        except Exception:
            pass  # never let panel errors crash the worker


def debug(
    cfg: DebugConfig,
    category: str,
    msg: str,
    log_fn: Callable[[str, str], None],
) -> None:
    """
    Layer 3 debug function. Emits msg only when:
      1. cfg.log_debug_messages is True (master debug switch)
      2. cfg.log_<category> is True (per-category gate)
    Always additive — never silences normal log() calls.
    """
    if not cfg.log_debug_messages:
        return
    if not getattr(cfg, f"log_{category}", False):
        return
    log_fn(f"[DEBUG:{category}] {msg}", "DEBUG")


def _level_from_name(level: str) -> int:
    return getattr(logging, level.upper(), logging.INFO)
