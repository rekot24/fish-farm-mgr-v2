"""
bot/app_logger.py

Central logging with two independent output streams:

  Stream 1 — Log data (INFO/WARNING/ERROR)
    Always written to errors.log for ERROR+.
    Written to app.log when LoggingConfig.log_to_file is True.
    Routed to the debug panel when DebugConfig.show_log_in_panel is True.
    Called via: log(msg, level)

  Stream 2 — Debug data (verbose, cycle-by-cycle, DEBUG level)
    Never written to file — panel only.
    Routed to the debug panel when DebugConfig.show_debug_in_panel is True.
    Gated per-category by log_state_changes, log_detections, etc.
    Called via: debug(cfg, category, msg, log_fn)

Two separate panel callbacks allow the panel to color or filter the streams
independently if needed. In practice one callback handles both, since the
panel already colors by level.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from config.settings import Settings, LoggingConfig, DebugConfig

_logger = logging.getLogger("befish")
_logger.setLevel(logging.DEBUG)
_logger.propagate = False

_configured = False

# Separate routing flags for each stream
_route_log_to_panel: bool = False
_route_debug_to_panel: bool = False

# Single panel callback — receives (msg, level) for both streams
_panel_callback: Optional[Callable[[str, str], None]] = None

_LOG_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)


def register_panel_callback(fn: Callable[[str, str], None]) -> None:
    """
    Register the debug panel's message receiver.
    Called once from App after UI is built.
    fn(msg, level) — called from any thread; panel handles thread-safety.
    """
    global _panel_callback
    _panel_callback = fn


def configure(settings: Settings, root: Path, stdout: bool = False) -> None:
    """
    (Re)build logger handlers and routing flags from current settings.
    Safe to call multiple times — clears existing handlers first.

    stdout=True (headless server only) also writes every record to stdout as plain
    lines at the configured log level, so journald / an SSH terminal can follow the run.
    The Windows GUI never sets it, so its logging is unchanged.
    """
    global _configured, _route_log_to_panel, _route_debug_to_panel

    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    cfg = settings.logging
    max_bytes = cfg.max_file_size_mb * 1024 * 1024

    # errors.log — ERROR+ always, never gated
    error_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "errors.log", maxBytes=max_bytes,
        backupCount=cfg.backup_count, encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(_LOG_FORMAT)
    _logger.addHandler(error_handler)

    # app.log — Stream 1 to file, gated by log_to_file
    if cfg.log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "app.log", maxBytes=max_bytes,
            backupCount=cfg.backup_count, encoding="utf-8",
        )
        file_handler.setLevel(_level_from_name(cfg.level))
        file_handler.setFormatter(_LOG_FORMAT)
        _logger.addHandler(file_handler)

    # stdout — headless server only; same format and level as app.log, never gated
    # by log_to_file (the terminal / journald is the log viewer there)
    if stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(_level_from_name(cfg.level))
        stdout_handler.setFormatter(_LOG_FORMAT)
        _logger.addHandler(stdout_handler)

    # Panel routing flags — independent of each other and of log_to_file
    _route_log_to_panel = (
        settings.development_mode and settings.debug.show_log_in_panel
    )
    _route_debug_to_panel = (
        settings.development_mode and settings.debug.show_debug_in_panel
    )

    _configured = True


def log(msg: str, level: str = "INFO") -> None:
    """
    Stream 1 — log data. Always goes to file (if enabled).
    Also routed to panel when show_log_in_panel is True.
    """
    if _configured:
        _logger.log(_level_from_name(level), msg)
    else:
        print(f"[{level}] {msg}")

    if _route_log_to_panel and _panel_callback is not None:
        try:
            _panel_callback(msg, level)
        except Exception:
            pass


def debug(
    cfg: DebugConfig,
    category: str,
    msg: str,
    log_fn: Callable[[str, str], None],
) -> None:
    """
    Stream 2 — debug data. Panel only, never written to file.
    Gated by show_debug_in_panel and the per-category toggle.
    """
    if not _route_debug_to_panel:
        return
    if not getattr(cfg, f"log_{category}", False):
        return
    if _panel_callback is not None:
        try:
            _panel_callback(f"[{category}] {msg}", "DEBUG")
        except Exception:
            pass


def _level_from_name(level: str) -> int:
    return getattr(logging, level.upper(), logging.INFO)
