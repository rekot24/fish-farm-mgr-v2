"""
capture/adb_screencap.py

ADB screencap capture backend.

This is the fallback backend for devices that have trouble with scrcpy.
Expected capture time: 300-500ms per frame.

How it works:
  adb exec-out screencap -p
  → streams a PNG directly to stdout
  → we decode it with OpenCV

This is slower than scrcpy socket but has zero setup requirements
beyond ADB being connected.
"""

from __future__ import annotations

import subprocess
import numpy as np
import cv2

from capture.base import CaptureBackend
from config.constants import ADB_QUICK_TIMEOUT_S, ADB_SCREENCAP_TIMEOUT_S
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
        adb_path: str = "adb",
        timeout_s: float = ADB_SCREENCAP_TIMEOUT_S,
        development_mode: bool = False,
    ):
        """
        Args:
            serial          : ADB device serial
            adb_path        : path to the adb executable (default "adb" = on PATH)
            timeout_s       : max seconds to wait for screencap command
            development_mode: accepted for interface parity with
                               ScrcpySocketBackend (make_backend() passes it
                               to whichever backend gets selected) — unused
                               here since this backend has no background
                               thread of its own to crash loudly in.
        """
        super().__init__(serial)
        self.adb_path = adb_path
        self.timeout_s = timeout_s
        self.development_mode = development_mode

    def connect(self) -> bool:
        """
        ADB screencap has no persistent connection.
        We verify the device is reachable by checking adb devices.
        """
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "get-state"],
                capture_output=True,
                timeout=ADB_QUICK_TIMEOUT_S,
                text=True,
            )
            if result.returncode == 0 and "device" in result.stdout:
                self._connected = True
                return True
            return False
        except Exception as e:
            app_logger.log(f"[adb_screencap] connect failed for {self.serial}: {e}", "ERROR")
            return False

    def get_frame(self) -> np.ndarray | None:
        """
        Run screencap and decode the PNG output to a BGR numpy array.
        Returns None on any failure — caller handles gracefully.
        """
        try:
            result = subprocess.run(
                [self.adb_path, "-s", self.serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=self.timeout_s,
            )

            if result.returncode != 0 or not result.stdout:
                return None

            img_array = np.frombuffer(result.stdout, dtype=np.uint8)
            frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            return frame  # BGR, or None if decode failed

        except subprocess.TimeoutExpired:
            app_logger.log(f"[adb_screencap] screencap timed out for {self.serial}", "WARNING")
            return None
        except Exception as e:
            app_logger.log(f"[adb_screencap] get_frame error for {self.serial}: {e}", "ERROR")
            return None

    def disconnect(self) -> None:
        """No persistent connection to tear down."""
        self._connected = False
