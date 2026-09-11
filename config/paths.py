"""
config/paths.py

Shared path resolution for every config file the app reads or writes.
All paths are resolved relative to the project root (the folder containing
main.py), regardless of the process's current working directory.
"""

from __future__ import annotations
from pathlib import Path


def project_root() -> Path:
    """Returns the project root: the folder containing main.py."""
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    """Returns the config/ directory."""
    return project_root() / "config"


def assets_dir() -> Path:
    """Returns the assets/ directory."""
    return project_root() / "assets"


def detectors_dir() -> Path:
    """Returns assets/detectors/ — root of all detector image folders."""
    return assets_dir() / "detectors"


def detector_dir(detector_name: str) -> Path:
    """Returns the folder for a specific detector's images."""
    return detectors_dir() / detector_name


def settings_path() -> Path:
    """Returns the path to config/settings.json."""
    return config_dir() / "settings.json"


def devices_path() -> Path:
    """Returns the path to config/devices.json."""
    return config_dir() / "devices.json"


def logs_dir() -> Path:
    """Returns the logs/ directory."""
    return project_root() / "logs"


def app_log_path() -> Path:
    """Returns the path to logs/app.log."""
    return logs_dir() / "app.log"


def errors_log_path() -> Path:
    """Returns the path to logs/errors.log."""
    return logs_dir() / "errors.log"
