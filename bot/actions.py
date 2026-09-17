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


def swipe_card_up(
    serial: str,
    start_y: int,
    end_y: int,
    x: int = 540,
) -> bool:
    """
    Fast upward flick within the game page bottom-sheet card.

    Coordinates are calculated from the detected game_page image bbox so
    the swipe is always relative to where the card actually is on screen —
    works correctly across all device screen sizes without hardcoding.

    Args:
        serial  : ADB device serial
        start_y : Y coordinate to start the swipe (bottom of detected bbox + offset)
        end_y   : Y coordinate to end the swipe (above the detected bbox)
        x       : horizontal center of the swipe (defaults to 540 for 1080-wide screens)

    Duration 150ms makes it a flick rather than a drag — critical for bottom
    sheets which dismiss on slow drags but scroll on fast flicks.
    """
    return _adb(
        serial,
        "shell", "input", "swipe",
        str(x), str(start_y), str(x), str(end_y), "150",
    )


def swipe_down_full(serial: str) -> bool:
    """
    Swipe from bottom to top of screen — maximum scroll.
    Used for full-page scrolling where the card is already fully expanded.
    x=540 targets center of a 1080-wide screen.
    """
    return _adb(
        serial,
        "shell", "input", "swipe",
        "540", "1800", "540", "300", "600",
    )


def press_back(serial: str) -> bool:
    return _adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")


def force_stop_roblox(serial: str) -> bool:
    return _adb(serial, "shell", "am", "force-stop", "com.roblox.client")
