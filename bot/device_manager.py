"""
bot/device_manager.py

Manages all connected device workers. Single point of contact between
the UI and the workers.

get_all_status() now returns an entry for every registered device,
not just devices with active workers. Devices without workers show
running=False and state=UNKNOWN so they appear as stopped cards
on the Main tab immediately after being registered.
"""

from __future__ import annotations

import subprocess
from typing import Callable

from bot import app_logger
from bot.device_worker import DeviceWorker
from capture.scrcpy_socket import ScrcpySocketBackend
from config.devices import DeviceConfig
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
        self._backends: dict[str, ScrcpySocketBackend] = {}

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

        self._backends[serial] = backend

        worker = DeviceWorker(
            device_cfg=devices.get(serial, DeviceConfig(serial=serial)),
            settings=settings,
            capture_backend=backend,
            template_bank=self._bank,
            get_settings=self._get_settings,
            get_device_cfg=lambda s=serial: self._get_devices().get(
                s, DeviceConfig(serial=s)
            ),
            reconnect_capture=lambda s=serial: self._rebuild_backend(s),
        )
        self._workers[serial] = worker
        worker.start()
        return True

    def stop_device(self, serial: str) -> None:
        if serial in self._workers:
            self._workers[serial].stop()

    def _rebuild_backend(self, serial: str) -> bool:
        """
        Tear down the existing scrcpy backend for a device and build a fresh
        one in its place. Called by the worker as Level 3 tap-failure recovery.

        Only touches the one device — all other workers are unaffected.
        Returns True if the new backend connected successfully.
        """
        app_logger.log(
            f"[manager] Rebuilding scrcpy backend for {serial[:8]}", "WARNING")

        # Tear down the old backend cleanly
        old = self._backends.get(serial)
        if old:
            try:
                old.disconnect()
            except Exception as e:
                app_logger.log(
                    f"[manager] Error disconnecting old backend for "
                    f"{serial[:8]}: {e}", "WARNING")

        settings = self._get_settings()
        new_backend = ScrcpySocketBackend(
            serial=serial,
            development_mode=settings.development_mode,
        )
        connected = new_backend.connect()
        if not connected:
            app_logger.log(
                f"[manager] Backend rebuild failed for {serial[:8]}", "ERROR")
            return False

        self._backends[serial] = new_backend

        # Hand the new backend to the worker so it starts reading frames from it
        worker = self._workers.get(serial)
        if worker:
            worker.replace_capture_backend(new_backend)

        app_logger.log(
            f"[manager] Backend rebuilt successfully for {serial[:8]}", "INFO")
        return True

    def start_all(self) -> None:
        """Start workers for all registered devices that are connected."""
        devices = self._get_devices()
        for serial in devices:
            self.start_device(serial)

    def stop_all(self) -> None:
        for worker in self._workers.values():
            if worker.is_running:
                worker.stop()

    def get_all_status(self) -> list[dict]:
        """
        Return a status snapshot for every registered device.
        Devices without an active worker show as stopped (running=False).
        This ensures all registered devices appear on the Main tab
        immediately, even before their worker is started.
        """
        devices = self._get_devices()
        result = []
        for serial, cfg in devices.items():
            worker = self._workers.get(serial)
            if worker:
                result.append(worker.get_status())
            else:
                # Stopped device — return a minimal status dict
                result.append({
                    "serial": serial,
                    "nickname": cfg.nickname,
                    "model": cfg.model,
                    "account": cfg.account,
                    "running": False,
                    "state": "UNKNOWN",
                    "last_action": "—",
                    "runtime_s": 0.0,
                    "auto_farm_countdown_s": 0.0,
                    "end_run_countdown_s": 0.0,
                })
        return result

    def get_status(self, serial: str) -> dict | None:
        worker = self._workers.get(serial)
        if worker:
            return worker.get_status()
        # Return stopped status for registered but not-started device
        devices = self._get_devices()
        cfg = devices.get(serial)
        if cfg:
            return {
                "serial": serial,
                "nickname": cfg.nickname,
                "model": cfg.model,
                "account": cfg.account,
                "running": False,
                "state": "UNKNOWN",
                "last_action": "—",
                "runtime_s": 0.0,
                "auto_farm_countdown_s": 0.0,
                "end_run_countdown_s": 0.0,
            }
        return None

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
