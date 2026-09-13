"""
bot/actions.py

All actions the bot can take on a device. Nothing but ADB calls.
No state logic lives here — only the physical actions themselves.
"""

from __future__ import annotations

import subprocess
import time

from bot import app_logger
from config.constants import (
    ADB_TIMEOUT_S,
    DOUBLE_CLICK_DELAY_S,
    STAY_AWAKE_TAP_X,
    STAY_AWAKE_TAP_Y,
)
from config.paths import adb_exe


def _adb(serial: str, *args: str, timeout: float = ADB_TIMEOUT_S) -> bool:
    """Run a bundled ADB command for a specific device. Returns True on success."""
    cmd = [adb_exe(), "-s", serial] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            app_logger.log(
                f"[actions] ADB command failed for {serial}: {' '.join(args)} — {stderr}",
                "WARNING",
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        app_logger.log(
            f"[actions] ADB command timed out for {serial}: {' '.join(args)}", "WARNING"
        )
        return False
    except FileNotFoundError:
        app_logger.log(
            f"[actions] adb.exe not found at: {adb_exe()}", "ERROR"
        )
        return False
    except Exception as e:
        app_logger.log(
            f"[actions] Unexpected ADB error for {serial}: {type(e).__name__}: {e}", "ERROR"
        )
        return False


def tap(serial: str, x: int, y: int) -> bool:
    return _adb(serial, "shell", "input", "tap", str(x), str(y))


def double_tap(serial: str, x: int, y: int, delay_s: float = DOUBLE_CLICK_DELAY_S) -> bool:
    first = tap(serial, x, y)
    time.sleep(delay_s)
    second = tap(serial, x, y)
    return first and second


def stay_awake_tap(serial: str) -> bool:
    return tap(serial, STAY_AWAKE_TAP_X, STAY_AWAKE_TAP_Y)


def launch_roblox(serial: str) -> bool:
    return _adb(
        serial,
        "shell", "monkey",
        "-p", "com.roblox.client",
        "-c", "android.intent.category.LAUNCHER",
        "1",
    )


def join_private_server(serial: str, server_link: str) -> bool:
    """
    Join a Roblox private server using the share link from the server panel.

    Passes the https://www.roblox.com/share?code=...&type=Server URL
    directly to Roblox using an explicit intent with the Roblox package
    and its URL-handling activity. This bypasses the Android browser
    entirely and hands the link straight to the app.
    """
    if not server_link:
        app_logger.log(
            f"[actions] join_private_server called with empty link for {serial}. "
            "Set the private server link in Settings.", "WARNING"
        )
        return False
    app_logger.log(f"[actions] Joining via: {server_link}", "INFO")
    return _adb(
        serial,
        "shell", "am", "start",
        "-n", "com.roblox.client/.ActivityProtocolLaunch",
        "-a", "android.intent.action.VIEW",
        "-c", "android.intent.category.BROWSABLE",
        "-d", server_link,
    )


def press_back(serial: str) -> bool:
    return _adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")


def force_stop_roblox(serial: str) -> bool:
    return _adb(serial, "shell", "am", "force-stop", "com.roblox.client")
