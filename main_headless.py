"""
main_headless.py

Headless entry point for the Linux server: runs the same per-device workers as the
Tkinter GUI (main.py) with no window, started by hand (e.g. over SSH). Thin wiring only:
settings, logging, DeviceManager, then wait for SIGINT / SIGTERM and stop everything.

Nothing starts unless asked:
    python main_headless.py --device <adb_serial>   start exactly that device
    python main_headless.py --start-all             start every device in devices.json
                                                    that `adb devices` lists as "device"
    python main_headless.py                         start nothing, say so, exit 0

No Tkinter, no UAC / elevation code, no ctypes. main.py is not involved.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading

from bot import app_logger
from bot.device_manager import DeviceManager
from config.constants import (
    HEADLESS_ADB_PREFLIGHT_TIMEOUT_S,
    HEADLESS_EXIT_FAILURE,
    HEADLESS_EXIT_OK,
    HEADLESS_SHUTDOWN_TIMEOUT_S,
)
from config.devices import load_devices
from config.paths import adb_exe, project_root
from config.settings import load_settings


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line. --device and --start-all are mutually exclusive."""
    parser = argparse.ArgumentParser(
        description="Fish Farm Manager v2 - headless server mode (no GUI).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--device", metavar="ADB_SERIAL",
        help="start exactly this device (it must be listed in config/devices.json)")
    group.add_argument(
        "--start-all", action="store_true",
        help="start every device in config/devices.json that adb lists as 'device'")
    return parser.parse_args(argv)


def _adb_available() -> bool:
    """
    Preflight: True if the adb client can be run. On Linux config.paths.adb_exe() is the
    bare "adb" on PATH, so a missing package would otherwise surface as a confusing
    FileNotFoundError deep inside a worker. Logs the reason at ERROR when it is not.
    """
    try:
        result = subprocess.run(
            [adb_exe(), "version"], capture_output=True,
            timeout=HEADLESS_ADB_PREFLIGHT_TIMEOUT_S)
    except FileNotFoundError:
        app_logger.log(
            f"adb not found ('{adb_exe()}' is not on PATH) - install it with: "
            f"sudo apt install adb", "ERROR")
        return False
    except Exception as e:
        app_logger.log(f"adb preflight failed: {e}", "ERROR")
        return False
    if result.returncode != 0:
        app_logger.log(
            f"adb preflight failed: `adb version` exited {result.returncode}", "ERROR")
        return False
    return True


def _select_serials(args: argparse.Namespace, manager: DeviceManager,
                    registered: set[str]) -> list[str] | None:
    """
    Decide which serials to start from the command line.

    --device S    -> [S] if S is in devices.json, else None (logged; nothing to run).
    --start-all   -> registered serials that `adb devices` lists as "device"; registered
                     serials that are not connected are logged at INFO and skipped (so a
                     one-phone server does not log an ERROR per absent phone).
    Returns None when the request cannot be satisfied; an empty list means nothing to start.
    """
    if args.device:
        if args.device not in registered:
            app_logger.log(
                f"Device {args.device} is not in config/devices.json - copy your "
                f"devices.json to this machine first", "ERROR")
            return None
        return [args.device]

    connected = set(manager.discover_devices())
    serials = sorted(registered & connected)
    for serial in sorted(registered - connected):
        app_logger.log(
            f"Skipping {serial[:8]} - registered but not listed as 'device' by adb", "INFO")
    return serials


def _stop_bounded(manager: DeviceManager) -> bool:
    """
    Run manager.stop_all() in a daemon thread and wait at most HEADLESS_SHUTDOWN_TIMEOUT_S.
    Returns True if every device stopped in time; otherwise logs a WARNING and returns
    False (the caller exits anyway - the workers are daemon threads).
    """
    stopper = threading.Thread(target=manager.stop_all, name="stop-all", daemon=True)
    stopper.start()
    stopper.join(timeout=HEADLESS_SHUTDOWN_TIMEOUT_S)
    if stopper.is_alive():
        app_logger.log(
            f"Shutdown did not finish within {HEADLESS_SHUTDOWN_TIMEOUT_S:.0f}s - "
            f"exiting anyway; leftover scrcpy/adb processes may remain", "WARNING")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Run headless mode as described in the module docstring; returns the exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Logging first (incl. stdout), so nothing below falls back to print.
    settings = load_settings()
    app_logger.configure(settings, project_root(), stdout=True)
    app_logger.log("Fish Farm Manager v2 headless starting", "INFO")

    if not args.device and not args.start_all:
        app_logger.log(
            "No devices started: pass --device <adb_serial> or --start-all", "INFO")
        return HEADLESS_EXIT_OK

    if not _adb_available():
        return HEADLESS_EXIT_FAILURE

    devices = load_devices()
    manager = DeviceManager(get_settings=lambda: settings, get_devices=lambda: devices)

    serials = _select_serials(args, manager, set(devices))
    if serials is None:
        return HEADLESS_EXIT_FAILURE
    if not serials:
        app_logger.log(
            "Nothing to start: no registered device is connected via adb", "ERROR")
        return HEADLESS_EXIT_FAILURE

    stop_requested = threading.Event()

    def _request_stop(signum: int, _frame) -> None:
        """Signal handler: note which signal arrived and wake the main thread."""
        app_logger.log(f"Received {signal.Signals(signum).name} - shutting down", "INFO")
        stop_requested.set()

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    started = [s for s in serials if manager.start_device(s)]
    if not started:
        app_logger.log("No device could be started - see errors above", "ERROR")
        manager.stop_all()
        return HEADLESS_EXIT_FAILURE
    app_logger.log(
        f"Running {len(started)} device(s): {[s[:8] for s in started]} - "
        f"Ctrl+C or SIGTERM to stop", "INFO")

    stop_requested.wait()

    clean = _stop_bounded(manager)
    app_logger.log("Headless stopped", "INFO")
    return HEADLESS_EXIT_OK if clean else HEADLESS_EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
