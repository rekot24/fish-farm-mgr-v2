"""
bot/app_logger.py

Central logging setup and the single unified log function every component
in the app calls through (dev-standards app-framework.md, Layer 7).

Persistent record vs. live output:
  Debug output (DebugConfig, Layer 3) answers "what is the app doing right
  now" and disappears when the session ends. This module answers "what
  happened, when" — a durable record that survives past the session, which
  is what you need when something breaks overnight while the farm runs
  unattended and nobody was watching.

One function handles all output:
  log(msg, level) is the single call site. It always writes to the rotating
  app.log (if logging is enabled and log_to_file is on), always writes
  ERROR/CRITICAL to errors.log regardless of the enabled/level settings (a
  durable failure record must not depend on the same switch that silences
  routine noise), and optionally writes to the console. The UI display path
  is separate (App.log() calls this, then puts the message on its own
  thread-safe queue) — there's only one caller of this module today, so a
  callback-registration layer for the UI would be indirection with nothing
  behind it.

Also home to debug() — the Layer 3 debug function (see its own docstring
below). Distinct concern from log() above: log() is the persistent record;
debug() is opt-in, additive diagnostic detail gated by DebugConfig, routed
through the caller's own log_fn so it still reaches every normal
destination once enabled.

Usage:
    configure(settings.logging, project_root)   # once, at startup, and again
                                                 # on every settings reload —
                                                 # changes take effect immediately
    log("worker started", level="INFO")         # from anywhere in the app
    debug(settings.debug, "detections", "...", self._log)  # opt-in detail
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only: config/settings.py itself needs to call log()/debug() (Phase
    # 5, routing its own print()s through here), which would make a runtime
    # import of LoggingConfig/DebugConfig from here a circular import.
    # Neither is ever constructed or isinstance-checked below — only their
    # attributes are read — so this costs nothing at runtime.
    from config.settings import LoggingConfig, DebugConfig


# Module-level singleton logger — one process, one log stream.
_logger = logging.getLogger("befish")
_logger.setLevel(logging.DEBUG)  # let everything through to handlers; handlers filter
_logger.propagate = False

_configured = False

_LOG_FORMAT = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)


def configure(cfg: LoggingConfig, project_root: Path) -> None:
    """
    (Re)build the logger's handlers from a LoggingConfig.

    Safe to call more than once — clears existing handlers first, so a live
    settings change (e.g. toggling log_to_console, or raising the level)
    takes effect on the next log() call with no restart, matching the rest
    of the app's settings pattern.
    """
    global _configured

    for handler in list(_logger.handlers):
        _logger.removeHandler(handler)
        handler.close()

    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = cfg.max_file_size_mb * 1024 * 1024

    # errors.log: errors and criticals only, always on. Deliberately not
    # gated by cfg.enabled — the whole point is a record that exists even
    # when routine logging has been turned down or off.
    error_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "errors.log", maxBytes=max_bytes, backupCount=cfg.backup_count,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(_LOG_FORMAT)
    _logger.addHandler(error_handler)

    if cfg.enabled and cfg.log_to_file:
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / "app.log", maxBytes=max_bytes, backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(_level_from_name(cfg.level))
        file_handler.setFormatter(_LOG_FORMAT)
        _logger.addHandler(file_handler)

    if cfg.enabled and cfg.log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(_level_from_name(cfg.level))
        console_handler.setFormatter(_LOG_FORMAT)
        _logger.addHandler(console_handler)

    _configured = True


def log(msg: str, level: str = "INFO") -> None:
    """
    The single unified log function. Every component's _log()/log() wrapper
    calls this instead of print() or writing to a handler directly.
    """
    if _configured:
        _logger.log(_level_from_name(level), msg)
    else:
        # Called before configure() has run (shouldn't normally happen past
        # very early startup) — fall back to console so nothing is silently
        # lost rather than raising or dropping it.
        print(f"[{level}] {msg}")


def debug(cfg: DebugConfig, category: str, msg: str, log_fn: Callable[[str, str], None]) -> None:
    """
    The central Layer 3 debug function (dev-standards app-framework.md).

    Emits msg at DEBUG level through log_fn — the caller's own _log()/log(),
    so debug output reaches the same file/console/UI destinations as
    everything else — but only if both gates pass:
      1. cfg.enabled (the master switch)
      2. cfg.log_<category> (the per-category flag)

    This is always ADDITIVE: it supplements the always-on INFO/WARNING/
    ERROR logs elsewhere in the app with extra, opt-in diagnostic detail.
    It never gates or replaces an existing log line — see DebugConfig's
    docstring in config/settings.py.

    Args:
        cfg      : settings.debug (a DebugConfig)
        category : e.g. "detections" — checked against cfg.log_detections
        msg      : the debug message
        log_fn   : the caller's own log(msg, level) — e.g. DeviceWorker._log
    """
    if not cfg.enabled:
        return
    if not getattr(cfg, f"log_{category}", False):
        return
    log_fn(f"[DEBUG:{category}] {msg}", "DEBUG")


def _level_from_name(level: str) -> int:
    """Map a level name string to logging's numeric level. Unknown names default to INFO."""
    return getattr(logging, level.upper(), logging.INFO)
