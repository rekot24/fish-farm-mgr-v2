"""
bot/device_manager.py

Manages all connected device workers. Single point of contact between
the UI and the workers.

Lifecycle rules:
  - A registered device card does not create a capture backend by itself.
  - start_device() creates exactly one worker/backend pair for that device.
  - stop_device() stops the worker, disconnects scrcpy, removes the backend,
    and removes the stopped worker object.
  - start_device() defensively tears down any stale backend left from an older
    session before creating a fresh one.
  - stop_all() uses the same per-device teardown path so app exit is clean.

get_all_status() returns an entry for every registered device, not just devices
with active workers. Devices without workers show running=False and
state=UNKNOWN so they appear as stopped cards on the Main tab immediately after
being registered.
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
        existing_worker = self._workers.get(serial)
        if existing_worker and existing_worker.is_running:
            app_logger.log(f"[manager] {serial[:8]} already running", "WARNING")
            return True

        # A stopped card must not retain a live capture backend. This also
        # cleans up stale state created by older builds where stop_device()
        # stopped only the worker thread and left scrcpy running.
        stale_backend = self._backends.pop(serial, None)
        if stale_backend:
            app_logger.log(
                f"[manager] Cleaning stale capture backend before starting {serial[:8]}",
                "WARNING",
            )
            try:
                stale_backend.disconnect()
            except Exception as e:
                app_logger.log(
                    f"[manager] Error cleaning stale backend for {serial[:8]}: {e}",
                    "WARNING",
                )

        # Any non-running worker object is stale; a successful start gets a
        # fresh worker paired with the fresh backend below.
        self._workers.pop(serial, None)

        settings = self._get_settings()
        devices = self._get_devices()

        backend = ScrcpySocketBackend(
            serial=serial,
            development_mode=settings.development_mode,
        )
        connected = backend.connect()
        if not connected:
            # connect() normally tears down partial state itself, but keep this
            # defensive cleanup here so a failed start can never own a backend.
            try:
                backend.disconnect()
            except Exception:
                pass
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
        """Fully stop one device: worker first, then its scrcpy backend."""
        worker = self._workers.get(serial)
        if worker:
            try:
                worker.stop()
            except Exception as e:
                app_logger.log(
                    f"[manager] Error stopping worker for {serial[:8]}: {e}",
                    "WARNING",
                )

        backend = self._backends.pop(serial, None)
        if backend:
            try:
                backend.disconnect()
            except Exception as e:
                app_logger.log(
                    f"[manager] Error disconnecting backend for {serial[:8]}: {e}",
                    "WARNING",
                )

        # Remove the stopped worker object only after teardown so status for a
        # stopped card cannot retain references to an old capture session.
        self._workers.pop(serial, None)
        app_logger.log(f"[manager] Fully stopped {serial[:8]}", "INFO")

    def _rebuild_backend(self, serial: str) -> bool:
        """
        Tear down the existing scrcpy backend for a device and build a fresh
        one in its place. Called by the worker as Level 3 tap-failure recovery.

        Only touches the one device — all other workers are unaffected.
        Returns True if the new backend connected successfully.
        """
        app_logger.log(
            f"[manager] Rebuilding scrcpy backend for {serial[:8]}", "WARNING")

        # Tear down the old backend cleanly and remove it from the manager
        # before constructing a replacement.
        old = self._backends.pop(serial, None)
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
            try:
                new_backend.disconnect()
            except Exception:
                pass
            app_logger.log(
                f"[manager] Backend rebuild failed for {serial[:8]}", "ERROR")
            return False

        # The worker may have been stopped while a rebuild was in flight. Do
        # not leave a newly connected backend alive for a stopped card.
        worker = self._workers.get(serial)
        if not worker or not worker.is_running:
            new_backend.disconnect()
            app_logger.log(
                f"[manager] Discarded rebuilt backend for stopped device {serial[:8]}",
                "WARNING",
            )
            return False

        self._backends[serial] = new_backend
        worker.replace_capture_backend(new_backend)

        app_logger.log(
            f"[manager] Backend rebuilt successfully for {serial[:8]}", "INFO")
        return True

    def start_all(self) -> None:
        """Explicitly start workers for all registered devices."""
        devices = self._get_devices()
        for serial in devices:
            self.start_device(serial)

    def stop_all(self) -> None:
        """Fully tear down every worker/backend pair, including stale backends."""
        serials = set(self._workers) | set(self._backends)
        for serial in list(serials):
            self.stop_device(serial)

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
