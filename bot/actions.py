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
                    f"[actions] Continue dialog found (score={max_val:.2f}) bbox={max_loc} tap=({tx},{ty})",
                    "INFO",
                )
                tap_ok = tap(serial, tx, ty)
                app_logger.log(f"[actions] Tap result={tap_ok} at ({tx},{ty})", "INFO")
                return True
        except Exception as e:
            app_logger.log(f"[actions] Continue dialog poll error: {e}", "WARNING")
        time.sleep(poll_interval_s)

    app_logger.log("[actions] Continue dialog not found within timeout", "WARNING")
    return False


def join_private_server(serial: str, server_link: str) -> bool:
    """
    Join a Roblox private server by typing the URL into Chrome's address bar.
    This mimics exactly what a user does manually — which is confirmed to work.
    Opening Chrome via intent produces a different result than typing the URL.
    """
    if not server_link:
        app_logger.log(
            f"[actions] join_private_server called with empty link for {serial}. "
            "Set the private server link in Settings.", "WARNING"
        )
        return False

    app_logger.log(f"[actions] Joining via Chrome address bar: {server_link}", "INFO")

    # 1. Force-stop Chrome and Roblox for a clean state
    _adb(serial, "shell", "am", "force-stop", "com.android.chrome")
    force_stop_roblox(serial)
    time.sleep(1.5)

    # 2. Open Chrome to a blank page
    _adb(
        serial,
        "shell", "am", "start",
        "-n", "com.android.chrome/com.google.android.apps.chrome.Main",
        "--activity-clear-task",
        "-d", "about:blank",
    )
    time.sleep(3.0)

    # 3. Get screen dimensions to calculate address bar position
    screen_w, screen_h = 1080, 2400
    try:
        import subprocess as _sp
        sr = _sp.run(
            [adb_exe(), "-s", serial, "shell", "wm", "size"],
            capture_output=True, text=True, timeout=5.0
        )
        parts = sr.stdout.strip().split(":")[-1].strip().split("x")
        screen_w, screen_h = int(parts[0]), int(parts[1])
    except Exception:
        pass
    app_logger.log(f"[actions] Screen size: {screen_w}x{screen_h}", "INFO")

    # 4. Tap the Chrome address bar (omnibox) — top ~5.5% of screen
    bar_x = screen_w // 2
    bar_y = int(screen_h * 0.055)
    app_logger.log(f"[actions] Tapping address bar at ({bar_x}, {bar_y})", "INFO")
    tap(serial, bar_x, bar_y)
    time.sleep(1.0)

    # 5. Select all existing text and clear it
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_CTRL_A")
    time.sleep(0.2)
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_DEL")
    time.sleep(0.2)

    # 6. Type the URL into the address bar.
    #    ADB subprocess.run with a list doesn't use a shell so & is safe.
    #    _adb() uses subprocess.run with a list — no shell interpretation.
    _adb(serial, "shell", "input", "text", server_link)
    time.sleep(0.5)

    # 7. Press Enter to navigate
    _adb(serial, "shell", "input", "keyevent", "KEYCODE_ENTER")
    app_logger.log("[actions] URL entered — waiting for Continue to Roblox dialog", "INFO")

    # 8. Poll for the Continue dialog and tap it
    result = _tap_continue_dialog(serial, timeout_s=15.0)
    return result


def press_back(serial: str) -> bool:
    return _adb(serial, "shell", "input", "keyevent", "KEYCODE_BACK")


def force_stop_roblox(serial: str) -> bool:
    return _adb(serial, "shell", "am", "force-stop", "com.roblox.client")
