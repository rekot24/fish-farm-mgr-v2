"""
capture/adb_screencap.py

ADB screencap capture backend — fallback when scrcpy is unavailable.
Uses the bundled adb.exe from tools/adb/.
"""

from __future__ import annotations

import subprocess
import numpy as np
import cv2

from capture.base import CaptureBackend
from config.constants import ADB_QUICK_TIMEOUT_S, ADB_SCREENCAP_TIMEOUT_S
from config.paths import adb_exe
from bot import app_logger


class ADBScreencapBackend(CaptureBackend):
    """
    Capture backend using 'adb exec-out screencap -p'.
    Simple, reliable, slow (~300-500ms per frame).
    Use as fallback when scrcpy socket is not available.
    """

    def __init__(
        self,
        serial: str,
        timeout_s: float = ADB_SCREENCAP_TIMEOUT_S,
        development_mode: bool = False,
    ):
        super().__init__(serial)
        self.timeout_s = timeout_s
        self.development_mode = development_mode

    def connect(self) -> bool:
        try:
            result = subprocess.run(
                [adb_exe(), "-s", self.serial, "get-state"],
                capture_output=True,
                timeout=ADB_QUICK_TIMEOUT_S,
                text=True,
            )
            if result.returncode == 0 and "device" in result.stdout:
                self._connected = True
                return True
            return False
        except Exception as e:
            app_logger.log(
                f"[adb_screencap] connect failed for {self.serial}: {e}", "ERROR")
            return False

    def get_frame(self) -> np.ndarray | None:
        try:
            result = subprocess.run(
                [adb_exe(), "-s", self.serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=self.timeout_s,
            )
            if result.returncode != 0 or not result.stdout:
                return None
            img_array = np.frombuffer(result.stdout, dtype=np.uint8)
            return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        except subprocess.TimeoutExpired:
            app_logger.log(
                f"[adb_screencap] screencap timed out for {self.serial}", "WARNING")
            return None
        except Exception as e:
            app_logger.log(
                f"[adb_screencap] get_frame error for {self.serial}: {e}", "ERROR")
            return None

    def disconnect(self) -> None:
        self._connected = False
