"""
config/paths.py

Shared path resolution for every config file the app reads or writes.
All paths are resolved relative to the project root (the folder containing
main.py), regardless of the process's current working directory.

Bundled tool paths:
  adb_exe()           → tools/adb/adb.exe
  scrcpy_jar_path()   → tools/scrcpy/scrcpy-server.jar

All ADB calls throughout the codebase use adb_exe() — never the string
"adb" — so the app works without ADB on the system PATH.
"""

from __future__ import annotations
import sys
from pathlib import Path


def project_root() -> Path:
    """Returns the project root: the folder containing main.py."""
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    return project_root() / "config"


def assets_dir() -> Path:
    return project_root() / "assets"


def detectors_dir() -> Path:
    return assets_dir() / "detectors"


def detector_dir(detector_name: str) -> Path:
    return detectors_dir() / detector_name


def settings_path() -> Path:
    return config_dir() / "settings.json"


def devices_path() -> Path:
    return config_dir() / "devices.json"


def logs_dir() -> Path:
    return project_root() / "logs"


def app_log_path() -> Path:
    return logs_dir() / "app.log"


def errors_log_path() -> Path:
    return logs_dir() / "errors.log"


# ---------------------------------------------------------------------------
# Bundled tool paths
# ---------------------------------------------------------------------------

def adb_exe() -> str:
    """
    Returns the path to the bundled adb.exe as a string.
    Always use this instead of the bare string "adb" so the app works
    without ADB installed on the system PATH.
    """
    exe = project_root() / "tools" / "adb" / "adb.exe"
    return str(exe)


def scrcpy_jar_path() -> Path:
    """
    Returns the path to the bundled scrcpy-server.jar.
    Used by ScrcpySocketBackend on connect().
    """
    return project_root() / "tools" / "scrcpy" / "scrcpy-server.jar"
