"""
tools/usb_pnp.py

Windows PnP helpers for the USB port reset (Level 4) recovery: look up a phone's USB
device InstanceId from its ADB serial, and power-cycle that device with PowerShell
Disable-PnpDevice / Enable-PnpDevice.

Nothing here logs or touches app state. Functions return result objects and the caller
(DeviceManager, the Device Settings dialog, or the CLI below) decides what to do.

Safety properties:
  - The InstanceId is user-entered config and this runs elevated. It is never
    interpolated into PowerShell source: it travels in an environment variable that the
    script reads as $env:NAME, and its format is validated before every use.
  - Disable/Enable-PnpDevice raise NON-terminating errors by default, so a failed call
    still exits 0. The scripts use -ErrorAction Stop and `exit 1` on any error so a
    failure is always visible to the caller.
  - A phone left disabled is worse than one left offline. power_cycle_device() always
    attempts Enable (with a retry), even if Disable failed or timed out.

CLI (run from the repo root; `reset` needs an elevated PowerShell):
    python -m tools.usb_pnp detect <adb_serial>
    python -m tools.usb_pnp reset  <adb_serial> [--instance-id <id>]
"""

from __future__ import annotations

import ctypes
import os
import platform
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from enum import Enum

from config.constants import (
    PLATFORM_WINDOWS,
    PNP_ID_ENV_VAR,
    PNP_INSTANCE_ID_PATTERN,
    PNP_LOOKUP_TIMEOUT_S,
    PNP_SERIAL_ENV_VAR,
    POWERSHELL_EXE,
    PS_DISABLE_PNP_SCRIPT,
    PS_ENABLE_PNP_SCRIPT,
    PS_FIND_PNP_SCRIPT,
    USB_RESET_ADB_POLL_INTERVAL_S,
    USB_RESET_ADB_REAPPEAR_TIMEOUT_S,
    USB_RESET_ENABLE_RETRIES,
    USB_RESET_REENUM_WAIT_S,
    USB_RESET_TIMEOUT_S,
)

# Stdlib flag (0 off Windows) — keeps a PowerShell child from flashing a console window.
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_INSTANCE_ID_RE = re.compile(PNP_INSTANCE_ID_PATTERN)


class LookupStatus(Enum):
    """Outcome of find_instance_id()."""
    FOUND = "found"              # exactly one matching USB device
    NOT_FOUND = "not_found"      # no present USB device ends with that serial
    AMBIGUOUS = "ambiguous"      # more than one match — refuse to guess
    ERROR = "error"              # PowerShell failed, timed out, or output was unusable
    UNSUPPORTED = "unsupported"  # not running on Windows


@dataclass(frozen=True)
class PnpResult:
    """Result of a PnP operation. message is human-readable and safe to log."""
    ok: bool
    message: str = ""


@dataclass(frozen=True)
class LookupResult:
    """Result of find_instance_id(): a status, the InstanceId when FOUND, and a message."""
    status: LookupStatus
    instance_id: str = ""
    message: str = ""


@dataclass(frozen=True)
class _PsRun:
    ok: bool
    stdout: str
    message: str


def is_windows() -> bool:
    """True when running on Windows (the only platform these helpers support)."""
    return platform.system() == PLATFORM_WINDOWS


def is_elevated() -> bool:
    """True if this process is running as administrator. Always False off Windows or if unknown."""
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def is_valid_instance_id(value: str) -> bool:
    """True if value has the shape of a PnP InstanceId (see PNP_INSTANCE_ID_PATTERN)."""
    return bool(_INSTANCE_ID_RE.match(value or ""))


def _run_powershell(script: str, env_extra: dict[str, str], timeout_s: float) -> _PsRun:
    """
    Run one PowerShell script with extra environment variables and no console window.
    Never raises: any failure (non-zero exit, timeout, missing PowerShell) is returned
    as ok=False with a message. A non-zero exit carries PowerShell's own error text.
    """
    env = os.environ.copy()
    env.update(env_extra)
    try:
        completed = subprocess.run(
            [POWERSHELL_EXE, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=timeout_s,
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return _PsRun(False, "", f"PowerShell timed out after {timeout_s:.0f}s")
    except FileNotFoundError:
        return _PsRun(False, "", f"'{POWERSHELL_EXE}' was not found on PATH")
    except Exception as e:
        return _PsRun(False, "", f"{type(e).__name__}: {e}")

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    if completed.returncode != 0:
        detail = stderr.strip() or stdout.strip() or f"exit code {completed.returncode}"
        return _PsRun(False, stdout, detail)
    return _PsRun(True, stdout, "")


def _pnp_action(script: str, instance_id: str) -> PnpResult:
    """Run a Disable/Enable script for one InstanceId, validating it first."""
    if not is_windows():
        return PnpResult(False, "USB reset is only supported on Windows")
    if not is_valid_instance_id(instance_id):
        return PnpResult(False, f"invalid PnP InstanceId format: {instance_id!r}")
    run = _run_powershell(script, {PNP_ID_ENV_VAR: instance_id}, USB_RESET_TIMEOUT_S)
    return PnpResult(run.ok, run.message)


def disable_device(instance_id: str) -> PnpResult:
    """Disable-PnpDevice for one InstanceId. ok=False (with PowerShell's error text) on any failure."""
    return _pnp_action(PS_DISABLE_PNP_SCRIPT, instance_id)


def enable_device(instance_id: str) -> PnpResult:
    """Enable-PnpDevice for one InstanceId. ok=False (with PowerShell's error text) on any failure."""
    return _pnp_action(PS_ENABLE_PNP_SCRIPT, instance_id)


def power_cycle_device(instance_id: str) -> PnpResult:
    """
    Disable the device, wait USB_RESET_REENUM_WAIT_S, then Enable it — a software
    equivalent of unplugging and replugging the phone.

    Enable is ALWAYS attempted, even if Disable failed or timed out (harmless if the
    device is still enabled), and is retried USB_RESET_ENABLE_RETRIES times. If Enable
    never succeeds the message says the device may be left disabled and how to fix it.

    Does not verify that ADB sees the phone again — the caller polls for that.

    Returns:
        PnpResult(ok=True) only when both Disable and Enable succeeded.
    """
    # Checked up front so an unsupported platform or bad ID never sleeps or runs anything.
    if not is_windows():
        return PnpResult(False, "USB reset is only supported on Windows")
    if not is_valid_instance_id(instance_id):
        return PnpResult(False, f"invalid PnP InstanceId format: {instance_id!r}")

    disable = disable_device(instance_id)

    time.sleep(USB_RESET_REENUM_WAIT_S)

    enable = enable_device(instance_id)
    retries_left = USB_RESET_ENABLE_RETRIES
    while not enable.ok and retries_left > 0:
        retries_left -= 1
        time.sleep(USB_RESET_REENUM_WAIT_S)
        enable = enable_device(instance_id)

    if not enable.ok:
        return PnpResult(
            False,
            f"Enable-PnpDevice failed ({enable.message}) — the device may be left DISABLED. "
            f"Run in an elevated PowerShell: Enable-PnpDevice -InstanceId '{instance_id}'"
            + (f" (Disable also failed: {disable.message})" if not disable.ok else ""),
        )
    if not disable.ok:
        return PnpResult(False, f"Disable-PnpDevice failed ({disable.message}); device is enabled")
    return PnpResult(True)


def find_instance_id(adb_serial: str) -> LookupResult:
    """
    Look up the Windows PnP InstanceId of the phone with this ADB serial: the present
    top-level USB device whose InstanceId ends with the serial, e.g.
    USB\\VID_18D1&PID_4EE7\\19161FDEE005RY. Read-only; needs no elevation.

    Returns:
        LookupResult. FOUND carries the InstanceId; NOT_FOUND (phone unplugged, or its
        USB descriptor does not expose the serial), AMBIGUOUS, ERROR and UNSUPPORTED
        carry an explanatory message and no InstanceId.
    """
    if not is_windows():
        return LookupResult(LookupStatus.UNSUPPORTED, message="Only supported on Windows")
    serial = (adb_serial or "").strip()
    if not serial:
        return LookupResult(LookupStatus.ERROR, message="No ADB serial to look up")

    run = _run_powershell(PS_FIND_PNP_SCRIPT, {PNP_SERIAL_ENV_VAR: serial}, PNP_LOOKUP_TIMEOUT_S)
    if not run.ok:
        return LookupResult(LookupStatus.ERROR, message=run.message)

    ids = [line.strip() for line in run.stdout.splitlines() if line.strip()]
    if not ids:
        return LookupResult(
            LookupStatus.NOT_FOUND,
            message=f"No USB device found for serial {serial} — is the phone plugged in?")
    if len(ids) > 1:
        return LookupResult(
            LookupStatus.AMBIGUOUS,
            message=f"{len(ids)} USB devices match serial {serial}: {', '.join(ids)}")
    if not is_valid_instance_id(ids[0]):
        return LookupResult(
            LookupStatus.ERROR, message=f"Found an unexpected InstanceId format: {ids[0]!r}")
    return LookupResult(LookupStatus.FOUND, instance_id=ids[0])


# ---------------------------------------------------------------------------
# CLI — manual diagnostics. Output goes through the app logger (no raw print).
# ---------------------------------------------------------------------------

def _adb_lists_device(serial: str) -> bool:
    """True if the bundled `adb devices` currently lists this serial in the "device" state."""
    from config.paths import adb_exe
    try:
        out = subprocess.run([adb_exe(), "devices"], capture_output=True, timeout=10.0)
        for line in out.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[0] == serial and parts[1] == "device":
                return True
    except Exception:
        pass
    return False


def _cli(argv: list[str]) -> int:
    """
    Minimal command line: `detect <serial>` or `reset <serial> [--instance-id <id>]`.
    Returns a process exit code (0 ok, 1 failure, 2 usage/not elevated).
    """
    from bot import app_logger
    log = app_logger.log

    usage = ("usage: python -m tools.usb_pnp detect <adb_serial>\n"
             "       python -m tools.usb_pnp reset <adb_serial> [--instance-id <id>]")
    if len(argv) < 2 or argv[0] not in ("detect", "reset"):
        log(usage, "INFO")
        return 2
    command, serial = argv[0], argv[1]

    instance_id = ""
    if "--instance-id" in argv:
        idx = argv.index("--instance-id")
        instance_id = argv[idx + 1] if idx + 1 < len(argv) else ""

    if command == "detect" or not instance_id:
        found = find_instance_id(serial)
        log(f"Lookup for {serial}: {found.status.value} {found.instance_id} {found.message}".strip(),
            "INFO" if found.status is LookupStatus.FOUND else "WARNING")
        if command == "detect":
            return 0 if found.status is LookupStatus.FOUND else 1
        if found.status is not LookupStatus.FOUND:
            return 1
        instance_id = found.instance_id

    if not is_elevated():
        log("reset needs an elevated (administrator) PowerShell — not elevated, aborting", "ERROR")
        return 2

    log(f"Power-cycling {instance_id} (Disable, wait, Enable) …", "WARNING")
    started = time.monotonic()
    result = power_cycle_device(instance_id)
    if not result.ok:
        log(f"Reset failed: {result.message}", "ERROR")
        return 1
    log("Disable + Enable dispatched — waiting for ADB to see the device again", "INFO")
    deadline = time.monotonic() + USB_RESET_ADB_REAPPEAR_TIMEOUT_S
    while time.monotonic() < deadline:
        if _adb_lists_device(serial):
            log(f"{serial} is back in `adb devices` {time.monotonic() - started:.1f}s after the reset began",
                "INFO")
            return 0
        time.sleep(USB_RESET_ADB_POLL_INTERVAL_S)
    log(f"{serial} did not return to `adb devices` within {USB_RESET_ADB_REAPPEAR_TIMEOUT_S:.0f}s", "ERROR")
    return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
