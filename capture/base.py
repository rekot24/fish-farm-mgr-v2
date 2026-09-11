"""
capture/base.py

Abstract base class for all screen capture backends.

Every backend must implement three methods:
  connect()      — set up the connection to the device
  get_frame()    — return a BGR numpy array of the current screen
  disconnect()   — cleanly tear down the connection

The DeviceWorker instantiates the correct backend based on the device's
capture_backend setting ("scrcpy" or "adb") and calls connect() once
at startup. get_frame() is called every scan loop iteration.

Adding a new backend later:
  1. Create a new file in capture/ that subclasses CaptureBackend
  2. Implement the three methods
  3. Add it to the factory function in capture/__init__.py
  No other files need to change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import numpy as np


class CaptureBackend(ABC):
    """
    Abstract base for device screen capture.
    Subclasses must implement connect(), get_frame(), and disconnect().
    """

    def __init__(self, serial: str):
        """
        Args:
            serial: ADB device serial (e.g. "XXXXXXXXXXXXXXXX").
                    Used by all backends since ADB is always the transport layer.
        """
        self.serial = serial
        self._connected = False

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish the capture connection.

        Returns:
            True if connection succeeded, False otherwise.
            Should not raise — return False on failure and log internally.
        """
        ...

    @abstractmethod
    def get_frame(self) -> np.ndarray | None:
        """
        Capture and return the current device screen as a BGR numpy array.

        Returns:
            np.ndarray of shape (H, W, 3) in BGR color order, or
            None if capture failed (caller should handle gracefully).
        """
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """
        Cleanly tear down the capture connection.
        Should not raise even if already disconnected.
        """
        ...

    @property
    def is_connected(self) -> bool:
        return self._connected

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(serial={self.serial!r}, connected={self._connected})"
