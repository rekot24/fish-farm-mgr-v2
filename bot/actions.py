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



def _tap_continue_dialog(
    serial: str,
    timeout_s: float = 12.0,
    poll_interval_s: float = 0.5,
) -> bool:
    """
    Poll for the Continue to Roblox dialog and tap Continue as soon as it appears.
    Uses template matching against the continue_dialog detector image.
    Returns True if tapped successfully.
    """
    import cv2
    import numpy as np
    from config.devices import load_devices
    from config.paths import project_root, adb_exe as _adb_exe

    deadline = time.monotonic() + timeout_s
    devices = load_devices()
    cfg = devices.get(serial)

    # Load continue_dialog template if assigned
    template = None
    tap_offset = None
    if cfg and "continue_dialog" in cfg.detector_assignments:
        assignment = cfg.detector_assignments["continue_dialog"]
        if assignment.image_filename:
            img_path = (
                project_root() / "assets" / "detectors" /
                "continue_dialog" / assignment.image_filename
            )
            if img_path.exists():
                template = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
                if assignment.tap_offset_x is not None:
                    tap_offset = (assignment.tap_offset_x, assignment.tap_offset_y)

    if template is None:
        app_logger.log(
            "[actions] No continue_dialog detector assigned — "
            "capture the Continue button in the Capture tab for auto-tap",
            "WARNING",
        )
        return False

    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [_adb_exe(), "-s", serial, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=5.0,
            )
            if not result.stdout:
                time.sleep(poll_interval_s)
                continue
            arr = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                time.sleep(poll_interval_s)
                continue
            match = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(match)
            if max_val >= 0.75:
                th, tw = template.shape[:2]
                if tap_offset:
                    tx = max_loc[0] + tap_offset[0]
                    ty = max_loc[1] + tap_offset[1]
                else:
                    tx = max_loc[0] + tw // 2
                    ty = max_loc[1] + th // 2
                app_logger.log(
                    f"[actions] Continue dialog found (score={max_val:.2f}) — tapping",
                    "INFO",
                )
                tap(serial, tx, ty)
                return True
        except Exception as e:
            app_logger.log(f"[actions] Continue dialog poll error: {e}", "WARNING")
        time.sleep(poll_interval_s)

    app_logger.log("[actions] Continue dialog not found within timeout", "WARNING")
    return False


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
    app_logger.log(f"[actions] Joining via Chrome → Roblox: {server_link}", "INFO")

    # 1. Force-stop both Chrome and Roblox for a clean start
    _adb(serial, "shell", "am", "force-stop", "com.android.chrome")
    force_stop_roblox(serial)
    time.sleep(1.0)

    # 2. Open Chrome with the share link — this loads the Roblox share page
    #    which triggers the "Continue to Roblox?" system dialog
    result = _adb(
        serial,
        "shell", "am", "start",
        "-n", "com.android.chrome/com.google.android.apps.chrome.Main",
        "--activity-clear-task",
        "-d", server_link,
    )

    # 3. Wait for Chrome to load the page and show the Continue dialog
    time.sleep(6.0)

    # 4. Tap the Continue button — it appears as a system dialog.
    #    KEYCODE_ENTER confirms the focused button in Android dialogs.
    #    We also try tapping the typical button position as a fallback.
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_ENTER")
    time.sleep(0.5)
    # Fallback tap — Continue button is typically in the lower-center of the dialog
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_DPAD_RIGHT")
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_ENTER")

    app_logger.log("[actions] Tapped Continue on Roblox dialog", "INFO")
    return result


def press_back(serial: str) -> bool:
    return _adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")


def force_stop_roblox(serial: str) -> bool:
    return _adb(serial, "shell", "am", "force-stop", "com.roblox.client")
