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


def adb_reconnect(serial: str) -> bool:
    """
    Issue 'adb reconnect' for a specific device — restarts the ADB transport
    layer without touching the USB connection or any running apps.

    Used as Level 1 recovery when the ADB command channel is frozen but the
    scrcpy video stream is still alive. Fast and non-disruptive to the game.
    """
    return _adb(serial, "reconnect", timeout=15.0)


def launch_roblox(serial: str) -> bool:
    return _adb(
        serial,
        "shell", "monkey",
        "-p", "com.roblox.client",
        "-c", "android.intent.category.LAUNCHER",
        "1",
    )


def expand_and_scroll_game_page(
    serial: str,
    focus_x: int,
    focus_y: int,
    scroll_count: int = 2,
) -> bool:
    """
    Expand the Be Fish game page bottom-sheet and scroll to reveal Servers.

    After tapping the Be Fish game icon, Roblox shows a half-screen bottom-sheet
    card. Getting to the Servers button requires two steps:

    1. Swipe up from the detected game_page center to near the top of the screen
       to expand the bottom-sheet to full screen. 400ms duration is slow enough
       for the sheet to register the drag gesture but fast enough to fling it open.
    2. Swipe up multiple times (fast, 300ms) on the now-full-screen page to
       scroll content far enough to reveal the Servers button.

    focus_x/y is detect_result.center — the center of the detected game_page bbox.
    Both the expand swipe and the scroll swipes start from that point. Adjust the
    swipe anchor via the tap offset on the game_page detector assignment without
    touching this function.

    Verified working on Pixel 6 Pro (1440x3120). 2 scroll swipes reaches Servers.

    Args:
        serial       : ADB device serial
        focus_x      : x coordinate of detected game_page center
        focus_y      : y coordinate of detected game_page center
        scroll_count : number of upward swipes after expanding (default 2)
    """
    # Step 1: swipe up from card center to expand bottom-sheet to full screen
    _adb(serial, "shell", "input", "swipe",
         str(focus_x), str(focus_y), str(focus_x), "400", "400")
    time.sleep(0.6)

    # Step 2: fast swipes up to scroll content to reveal Servers button
    success = True
    for _ in range(scroll_count):
        success = _adb(
            serial,
            "shell", "input", "swipe",
            str(focus_x), str(focus_y), str(focus_x), "400", "300",
        )
        time.sleep(0.2)

    return success


def swipe_down_full(serial: str) -> bool:
    """
    Swipe from bottom to top of screen — maximum scroll.
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
