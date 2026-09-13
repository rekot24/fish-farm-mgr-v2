"""
bot/device_manager.py

Manages all connected device workers. Single point of contact between
the UI and the workers.
"""

from __future__ import annotations

import subprocess
from typing import Callable

from bot import app_logger
from bot.device_worker import DeviceWorker
from capture.scrcpy_socket import ScrcpySocketBackend
from config.devices import DeviceConfig, load_devices
from config.paths import project_root, adb_exe
from config.settings import Settings
from detection.template_bank import TemplateBank


class DeviceManager:

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        get_devices: Callable[[], dict[str, DeviceConfig]],
    ):
        self._get_settings = get_settings
        self._get_devices = get_devices
        self._bank = TemplateBank(project_root=project_root())
        self._workers: dict[str, DeviceWorker] = {}

    def discover_devices(self) -> list[str]:
        """Run bundled adb devices and return connected serials."""
        try:
            result = subprocess.run(
                [adb_exe(), "devices"],
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

    def start_device(self, serial: str) -> bool:
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
        if serial in self._workers:
            self._workers[serial].stop()

    def start_all(self) -> None:
        serials = self.discover_devices()
        for serial in serials:
            self.start_device(serial)

    def stop_all(self) -> None:
        for worker in self._workers.values():
            if worker.is_running:
                worker.stop()

    def get_all_status(self) -> list[dict]:
        return [w.get_status() for w in self._workers.values()]

    def get_status(self, serial: str) -> dict | None:
        worker = self._workers.get(serial)
        return worker.get_status() if worker else None

    def force_end_run(self, serial: str) -> None:
        worker = self._workers.get(serial)
        if worker and worker.is_running:
            worker.force_end_run()
        else:
            app_logger.log(
                f"[manager] force_end_run called for {serial[:8]} but worker not running",
                "WARNING",
            )

    def invalidate_template(self, detector_name: str, serial: str | None = None) -> None:
        self._bank.invalidate(detector_name, serial)
