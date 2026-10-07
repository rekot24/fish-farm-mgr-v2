"""
tools/usb_recovery.py

The one interface DeviceManager uses for Level 4 (USB port reset) recovery. The backend is
chosen by platform on first use:

  Windows -> WindowsUsbRecovery: thin wrapper over tools/usb_pnp.py (PowerShell PnP).
             usb_pnp is imported lazily, inside the Windows backend, so importing this
             module (or the core) never loads Windows-only code.
  other   -> StubUsbRecovery: reports "not supported" and fails, so the worker falls
             through to its existing "stop the device" behaviour. Real Linux recovery
             (sysfs unbind/rebind, uhubctl) arrives in milestone S3 behind this same
             interface.

Nothing here logs: it returns values and the caller (DeviceManager) decides what to log.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from typing import Optional, Protocol

from config.constants import PLATFORM_WINDOWS

# Message returned by the stub backend; also what DeviceManager logs when unsupported.
UNSUPPORTED_MESSAGE = "USB reset not supported on this platform"


@dataclass(frozen=True)
class RecoveryResult:
    """Outcome of a power cycle. message is human-readable and safe to log."""
    ok: bool
    message: str = ""


class UsbRecovery(Protocol):
    """What a USB recovery backend offers. DeviceManager calls these in this order."""

    def is_supported(self) -> bool:
        """True if this platform can power-cycle a phone's USB port at all."""
        ...

    def is_valid_instance_id(self, value: str) -> bool:
        """True if value is a well-formed per-device USB identifier for this backend."""
        ...

    def is_elevated(self) -> bool:
        """True if the process has the privileges the backend needs."""
        ...

    def power_cycle(self, instance_id: str) -> RecoveryResult:
        """Power-cycle the device's USB port. Does not wait for ADB to see it again."""
        ...


class WindowsUsbRecovery:
    """Windows backend: delegates to tools/usb_pnp.py, unchanged, imported lazily."""

    def is_supported(self) -> bool:
        """Always True: this backend is only selected on Windows."""
        return True

    def is_valid_instance_id(self, value: str) -> bool:
        """Delegates to usb_pnp.is_valid_instance_id."""
        from tools import usb_pnp
        return usb_pnp.is_valid_instance_id(value)

    def is_elevated(self) -> bool:
        """Delegates to usb_pnp.is_elevated (administrator check)."""
        from tools import usb_pnp
        return usb_pnp.is_elevated()

    def power_cycle(self, instance_id: str) -> RecoveryResult:
        """Delegates to usb_pnp.power_cycle_device (Disable/Enable-PnpDevice)."""
        from tools import usb_pnp
        result = usb_pnp.power_cycle_device(instance_id)
        return RecoveryResult(ok=result.ok, message=result.message)


class StubUsbRecovery:
    """Non-Windows placeholder until S3: supports nothing and always fails."""

    def is_supported(self) -> bool:
        """Always False."""
        return False

    def is_valid_instance_id(self, value: str) -> bool:
        """Always False: no identifier format exists yet on this platform."""
        return False

    def is_elevated(self) -> bool:
        """Always False."""
        return False

    def power_cycle(self, instance_id: str) -> RecoveryResult:
        """Always fails with UNSUPPORTED_MESSAGE."""
        return RecoveryResult(ok=False, message=UNSUPPORTED_MESSAGE)


_backend: Optional[UsbRecovery] = None


def get_backend() -> UsbRecovery:
    """Return the USB recovery backend for this platform (chosen once, then reused)."""
    global _backend
    if _backend is None:
        _backend = (WindowsUsbRecovery() if platform.system() == PLATFORM_WINDOWS
                    else StubUsbRecovery())
    return _backend
