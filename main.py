"""
main.py

Entry point only. Wires settings, logger, DeviceManager, and UI.
"""

from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys

from config.constants import (
    ELEVATION_STATUS_ADMIN,
    ELEVATION_STATUS_LAUNCH_FAILED,
    ELEVATION_STATUS_NOT_WINDOWS,
    ELEVATION_STATUS_OPTED_OUT,
    ELEVATION_STATUS_UNKNOWN,
    NO_ELEVATE_FLAG,
    PLATFORM_WINDOWS,
    SHELLEXECUTE_MAX_ERROR_CODE,
    SHELLEXECUTE_VERB_RUNAS,
    WIN_SW_HIDE,
    WIN_SW_SHOWNORMAL,
)


def _launcher_show_command() -> int:
    """
    Return the ShellExecuteW nShowCmd for the elevated relaunch, chosen by the
    suppress_launcher_console setting: WIN_SW_HIDE (hide the extra console window)
    when True, WIN_SW_SHOWNORMAL when False. Read straight from settings.json
    because this runs before the settings store is wired up; if the settings
    cannot be read, fall back to WIN_SW_HIDE, the setting's default.
    """
    try:
        from config.settings import load_settings
        hide_console = load_settings().suppress_launcher_console
    except Exception:
        return WIN_SW_HIDE
    return WIN_SW_HIDE if hide_console else WIN_SW_SHOWNORMAL


def _ensure_admin() -> str:
    """
    Relaunch this process with UAC elevation if it is not already running as admin.

    Windows only; skipped on other platforms and when NO_ELEVATE_FLAG is in argv.
    If elevation is dispatched successfully this does not return - the original
    process exits with code 0 and the elevated copy takes over. In every other
    case the app keeps running (unelevated) and USB reset fails gracefully later.

    Returns:
        One of the ELEVATION_STATUS_* constants describing the outcome. The caller
        logs it once the logger is configured; nothing can be logged here because
        this runs before settings and logging exist.
    """
    if platform.system() != PLATFORM_WINDOWS:
        return ELEVATION_STATUS_NOT_WINDOWS
    if NO_ELEVATE_FLAG in sys.argv:
        return ELEVATION_STATUS_OPTED_OUT

    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return ELEVATION_STATUS_UNKNOWN  # cannot determine - proceed, fail gracefully later
    if is_admin:
        return ELEVATION_STATUS_ADMIN

    try:
        shell_execute = ctypes.windll.shell32.ShellExecuteW
        # ShellExecuteW returns an HINSTANCE; read it pointer-sized so a 64-bit
        # value is not truncated by ctypes' default c_int return type.
        shell_execute.restype = ctypes.c_void_p
        # Absolute script path + explicit cwd: the elevated process must not
        # depend on a relative "main.py" resolving from wherever UAC starts it.
        # list2cmdline (not a naive quote-join) round-trips backslashes and quotes.
        params = subprocess.list2cmdline(
            [os.path.abspath(sys.argv[0])] + sys.argv[1:])
        result = shell_execute(
            None,
            SHELLEXECUTE_VERB_RUNAS,
            sys.executable,
            params,
            os.getcwd(),
            _launcher_show_command(),
        )
    except Exception:
        return ELEVATION_STATUS_LAUNCH_FAILED

    if (result or 0) <= SHELLEXECUTE_MAX_ERROR_CODE:
        # UAC declined (or the launch failed): keep running rather than vanish.
        return ELEVATION_STATUS_LAUNCH_FAILED
    sys.exit(0)  # elevated copy is starting; this unelevated process is done


# USB port reset (Level 4 recovery) requires admin elevation on Windows.
# Self-elevate now so UAC fires once at startup rather than mid-recovery.
# On Linux this is skipped - uhubctl does not require elevation.
# Deliberately placed before the remaining project imports so an unelevated
# process exits before doing any other initialization.
_ELEVATION_STATUS = _ensure_admin()

from config.devices import load_devices, save_devices  # noqa: E402
from config.paths import project_root  # noqa: E402
from config.settings import load_settings, save_settings  # noqa: E402
from bot import app_logger  # noqa: E402
from bot.device_manager import DeviceManager  # noqa: E402


def _log_elevation_status(status: str) -> None:
    """
    Log the outcome of _ensure_admin() once the logger is configured.
    INFO when elevated (or not applicable); WARNING whenever the app is running
    unelevated on Windows, since Level 4 USB port reset will then be unavailable.
    """
    unelevated_note = "Level 4 USB port reset will be unavailable"
    if status == ELEVATION_STATUS_ADMIN:
        app_logger.log("Running with administrator privileges", "INFO")
    elif status == ELEVATION_STATUS_NOT_WINDOWS:
        app_logger.log("Admin elevation not applicable on this platform", "INFO")
    elif status == ELEVATION_STATUS_OPTED_OUT:
        app_logger.log(
            f"{NO_ELEVATE_FLAG} given - running without administrator "
            f"privileges; {unelevated_note}", "WARNING")
    elif status == ELEVATION_STATUS_UNKNOWN:
        app_logger.log(
            f"Could not determine administrator status - continuing; "
            f"{unelevated_note} if not elevated", "WARNING")
    elif status == ELEVATION_STATUS_LAUNCH_FAILED:
        app_logger.log(
            f"Elevation was declined or failed - running without administrator "
            f"privileges; {unelevated_note}", "WARNING")


def main() -> None:
    settings = load_settings()
    devices = load_devices()

    _settings_box = [settings]
    _devices_box  = [devices]

    def get_settings(): return _settings_box[0]
    def get_devices():  return _devices_box[0]

    def reload_settings():
        _settings_box[0] = load_settings()
        app_logger.configure(_settings_box[0], project_root())
        app_logger.log("Settings reloaded", "INFO")

    def reload_devices():
        _devices_box[0] = load_devices()
        app_logger.log("Device configs reloaded", "INFO")

    def save_settings_fn(s):
        _settings_box[0] = s
        save_settings(s)
        app_logger.configure(s, project_root())

    def save_devices_fn(d):
        _devices_box[0] = d
        save_devices(d)

    # Pass full Settings object (app_logger.configure now takes Settings, not LoggingConfig)
    app_logger.configure(settings, project_root())
    app_logger.log("Fish Farm Manager v2 starting", "INFO")
    _log_elevation_status(_ELEVATION_STATUS)

    manager = DeviceManager(get_settings=get_settings, get_devices=get_devices)

    from ui.app import App
    app = App(
        manager=manager,
        get_settings=get_settings,
        get_devices=get_devices,
        reload_settings=reload_settings,
        reload_devices=reload_devices,
        save_settings_fn=save_settings_fn,
        save_devices_fn=save_devices_fn,
    )
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
