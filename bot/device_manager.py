"""
bot/device_manager.py

Manages all connected device workers. Single point of contact between
the UI and the workers — the UI never talks to a DeviceWorker directly.

Responsibilities:
  - Owns the shared TemplateBank
  - Creates and starts/stops DeviceWorkers
  - Provides status snapshots to the UI via get_all_status()
  - Routes force_end_run() from the UI to the correct worker
"""

from __future__ import annotations

import subprocess
from typing import Callable

from bot import app_logger
from bot.device_worker import DeviceWorker
from capture.scrcpy_socket import ScrcpySocketBackend
from config.devices import DeviceConfig, load_devices
from config.paths import project_root
from config.settings import Settings
from detection.template_bank import TemplateBank


class DeviceManager:
    """
    Creates, owns, and manages all DeviceWorker instances.

    One DeviceManager per app session. Created in main.py and passed
    to the UI for status polling and control calls.
    """

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        get_devices: Callable[[], dict[str, DeviceConfig]],
    ):
        self._get_settings = get_settings
        self._get_devices = get_devices
        self._bank = TemplateBank(project_root=project_root())
        self._workers: dict[str, DeviceWorker] = {}

    # ------------------------------------------------------------------
    # Device discovery
    # ------------------------------------------------------------------

    def discover_devices(self) -> list[str]:
        """
        Run 'adb devices' and return a list of connected device serials.
        Only returns devices in 'device' state (not offline, unauthorized, etc).
        """
        try:
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                timeout=10.0,
            )
            lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
            serials = []
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.append(parts[0])
            app_logger.log(f"[manager] Discovered {len(serials)} device(s): {serials}", "INFO")
            return serials
        except Exception as e:
            app_logger.log(f"[manager] discover_devices error: {e}", "ERROR")
            return []

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    def start_device(self, serial: str) -> bool:
        """
        Create (if needed) and start the worker for a device.
        Returns True if the worker started successfully.
        """
        if serial in self._workers and self._workers[serial].is_running:
            app_logger.log(f"[manager] {serial[:8]} already running", "WARNING")
            return True

        settings = self._get_settings()
        devices = self._get_devices()

        if serial not in devices:
            app_logger.log(
                f"[manager] No config found for {serial[:8]} — using defaults", "INFO"
            )

        backend = ScrcpySocketBackend(
            serial=serial,
            development_mode=settings.development_mode,
        )
        connected = backend.connect()
        if not connected:
            app_logger.log(
                f"[manager] Failed to connect capture backend for {serial[:8]}", "ERROR"
            )
            return False

        worker = DeviceWorker(
            device_cfg=devices.get(serial, DeviceConfig(serial=serial)),
            settings=settings,
            capture_backend=backend,
            template_bank=self._bank,
            get_settings=self._get_settings,
            get_device_cfg=lambda s=serial: self._get_devices().get(
                s, DeviceConfig(serial=s)
            ),
        )
        self._workers[serial] = worker
        worker.start()
        return True

    def stop_device(self, serial: str) -> None:
        """Stop the worker for a device. No-op if not running."""
        if serial in self._workers:
            self._workers[serial].stop()

    def start_all(self) -> None:
        """Discover all connected devices and start a worker for each."""
        serials = self.discover_devices()
        for serial in serials:
            self.start_device(serial)

    def stop_all(self) -> None:
        """Stop all running workers."""
        for worker in self._workers.values():
            if worker.is_running:
                worker.stop()

    # ------------------------------------------------------------------
    # UI interface
    # ------------------------------------------------------------------

    def get_all_status(self) -> list[dict]:
        """Return a status snapshot for every known worker."""
        return [w.get_status() for w in self._workers.values()]

    def get_status(self, serial: str) -> dict | None:
        """Return the status snapshot for a single device, or None if unknown."""
        worker = self._workers.get(serial)
        return worker.get_status() if worker else None

    def force_end_run(self, serial: str) -> None:
        """Immediately fire the end-run tap for a device and reset its timer."""
        worker = self._workers.get(serial)
        if worker and worker.is_running:
            worker.force_end_run()
        else:
            app_logger.log(
                f"[manager] force_end_run called for {serial[:8]} but worker not running",
                "WARNING",
            )

    def invalidate_template(self, detector_name: str, serial: str | None = None) -> None:
        """Invalidate a cached template image after the crop tool saves a new one."""
        self._bank.invalidate(detector_name, serial)
