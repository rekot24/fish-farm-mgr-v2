"""
bot/actions.py

All actions the bot can take on a device. Nothing but ADB calls.
No state logic lives here — only the physical actions themselves.

Every function takes a serial (ADB device ID) and any required
parameters. All timing constants come from config/constants.py.
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


# ---------------------------------------------------------------------------
# Internal ADB helper
# ---------------------------------------------------------------------------

def _adb(serial: str, *args: str, timeout: float = ADB_TIMEOUT_S) -> bool:
    """
    Run an ADB shell command for a specific device.

    Returns True if the command exited cleanly, False otherwise.
    Errors are logged but never raised — actions fail gracefully.
    """
    cmd = ["adb", "-s", serial] + list(args)
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
            "[actions] 'adb' not found on PATH. Is ADB installed?", "ERROR"
        )
        return False
    except Exception as e:
        app_logger.log(
            f"[actions] Unexpected ADB error for {serial}: {type(e).__name__}: {e}", "ERROR"
        )
        return False


# ---------------------------------------------------------------------------
# Tap actions
# ---------------------------------------------------------------------------

def tap(serial: str, x: int, y: int) -> bool:
    """
    Send a single tap to the device at (x, y).

    Args:
        serial : ADB device serial
        x, y   : screen coordinates to tap

    Returns:
        True if the ADB command succeeded.
    """
    return _adb(serial, "shell", "input", "tap", str(x), str(y))


def double_tap(serial: str, x: int, y: int, delay_s: float = DOUBLE_CLICK_DELAY_S) -> bool:
    """
    Send a double-tap to the device at (x, y).

    Fires two taps separated by delay_s. The delay comes from
    config/constants.py (DOUBLE_CLICK_DELAY_S) by default, ensuring
    the game registers both taps as a double-click rather than two singles.

    Args:
        serial  : ADB device serial
        x, y    : screen coordinates to double-tap
        delay_s : pause between the two taps (seconds)

    Returns:
        True if both ADB commands succeeded.
    """
    first = tap(serial, x, y)
    time.sleep(delay_s)
    second = tap(serial, x, y)
    return first and second


def stay_awake_tap(serial: str) -> bool:
    """
    Send the stay-awake tap to coordinate (1, 1).

    Prevents screen sleep on devices that ignore the ADB screen-off
    timeout override. Coordinate (1, 1) is a safe corner that does
    not interact with any game UI element.

    Args:
        serial : ADB device serial

    Returns:
        True if the ADB command succeeded.
    """
    return tap(serial, STAY_AWAKE_TAP_X, STAY_AWAKE_TAP_Y)


# ---------------------------------------------------------------------------
# App / navigation actions
# ---------------------------------------------------------------------------

def launch_roblox(serial: str) -> bool:
    """
    Launch the Roblox app on the device.

    Uses the standard Android intent for the Roblox main activity.
    Safe to call if Roblox is already open — Android will bring it to
    the foreground rather than launching a second instance.

    Args:
        serial : ADB device serial

    Returns:
        True if the ADB command succeeded.
    """
    return _adb(
        serial,
        "shell", "monkey",
        "-p", "com.roblox.client",
        "-c", "android.intent.category.LAUNCHER",
        "1",
    )


def join_private_server(serial: str, server_link: str) -> bool:
    """
    Open the private server link on the device using Android's URL intent.

    The link is a Roblox deep-link URL (roblox:// or https://www.roblox.com/games/...)
    that opens directly into the private server. Android routes it to Roblox.

    Args:
        serial      : ADB device serial
        server_link : the private server URL from global settings

    Returns:
        True if the ADB command succeeded. Does NOT confirm that Roblox
        actually joined — that is confirmed by the next detection cycle.
    """
    if not server_link:
        app_logger.log(
            f"[actions] join_private_server called with empty link for {serial}. "
            "Set the private server link in Settings.", "WARNING"
        )
        return False

    return _adb(
        serial,
        "shell", "am", "start",
        "-a", "android.intent.action.VIEW",
        "-d", server_link,
    )


def press_back(serial: str) -> bool:
    """
    Send the Android back button press to the device.

    Used to dismiss dialogs or navigate back when needed.

    Args:
        serial : ADB device serial

    Returns:
        True if the ADB command succeeded.
    """
    return _adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")


def force_stop_roblox(serial: str) -> bool:
    """
    Force-stop the Roblox app on the device.

    Used as part of the CRASHED recovery sequence to ensure a clean
    app restart. After force-stop, call launch_roblox() to reopen.

    Args:
        serial : ADB device serial

    Returns:
        True if the ADB command succeeded.
    """
    return _adb(serial, "shell", "am", "force-stop", "com.roblox.client")
