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

ADB behavior:
  - A device must be present in `adb devices` before scrcpy startup begins.
  - Status snapshots include adb_connected so the UI can distinguish a normal
    stopped card from a phone whose USB/ADB transport has dropped.
  - The status-poll path (get_all_status / get_status) reuses the last
    `adb devices` result for ADB_STATUS_CACHE_TTL_S so the 2s UI poll does not
    spawn a subprocess every time. start_device / _rebuild_backend /
    discover_devices always query live — they need a current answer.

Tap-coordinate cache persistence:
  - Workers never touch devices.json directly. When a worker discovers a new
    tap coordinate it calls persist_tap_cache(), which serializes all workers'
    writes behind one lock so concurrent discoveries cannot overwrite each other.

get_all_status() returns an entry for every registered device, not just devices
with active workers. Devices without workers show running=False and
state=UNKNOWN so they appear as stopped cards on the Main tab immediately after
being registered.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable

from bot import app_logger
from bot.device_worker import DeviceWorker
from capture.scrcpy_socket import ScrcpySocketBackend
from config.constants import ADB_STATUS_CACHE_TTL_S
from config.devices import DeviceConfig, load_devices, save_devices
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
        # One lock guards every worker's read-modify-write of devices.json
        # (see persist_tap_cache). Without it two workers saving at once
        # would silently overwrite each other's cached coordinate.
        self._tap_cache_lock = threading.Lock()
        # Last successful `adb devices` result for the status-poll path. Written
        # and read only from the UI thread (get_all_status / get_status), so no
        # lock. -inf (not 0.0) so the first poll always queries live — monotonic()
        # counts from boot on Windows and could otherwise look "fresh" right after boot.
        self._adb_connected_cache: set[str] = set()
        self._adb_cache_updated_at: float = float("-inf")

    def persist_tap_cache(self, serial: str, detector_key: str, x: int, y: int) -> None:
        """
        Thread-safe write of a single cached tap coordinate to devices.json.
        Acquires _tap_cache_lock, loads current devices, updates only the one
        field for this serial + detector, and saves. Logs INFO on success,
        WARNING on failure. Called by DeviceWorker via callback; workers never
        call load_devices/save_devices directly.
        """
        with self._tap_cache_lock:
            try:
                all_devices = load_devices()
                persisted = all_devices.get(serial)
                if persisted is None:
                    # Device removed while its worker was running — nothing to update.
                    app_logger.log(
                        f"[tap_cache] Cannot persist {detector_key} for {serial[:8]} — "
                        f"device not found in devices.json",
                        "WARNING",
                    )
                    return
                assignment = persisted.detector_assignments.get(detector_key)
                if assignment is None:
                    app_logger.log(
                        f"[tap_cache] Cannot persist {detector_key} for {serial[:8]} — "
                        f"no such detector assignment in devices.json",
                        "WARNING",
                    )
                    return
                assignment.cached_tap_x = x
                assignment.cached_tap_y = y
                save_devices(all_devices)
                app_logger.log(
                    f"[tap_cache] STORED {detector_key} for {serial[:8]} → ({x}, {y})",
                    "INFO",
                )
            except Exception as e:
                app_logger.log(
                    f"[tap_cache] Failed to persist {detector_key} for {serial[:8]}: "
                    f"{type(e).__name__}: {e}",
                    "WARNING",
                )

    def _connected_serials(
        self, log_result: bool = False, use_cache: bool = False
    ) -> set[str]:
        """
        Return serials currently reported by bundled `adb devices`.

        Args:
            log_result : log the discovered serials at INFO (live queries only)
            use_cache  : status-poll path only. Return the last successful result
                         if it is younger than ADB_STATUS_CACHE_TTL_S; otherwise
                         query live and refresh the cache. Default False = always
                         query live and leave the cache untouched, which is what
                         start_device / _rebuild_backend / discover_devices need.

        Returns:
            Set of serials in the "device" state. Empty set if the query fails;
            a failed query is never cached, so the next poll retries.
        """
        if use_cache and (
            time.monotonic() - self._adb_cache_updated_at < ADB_STATUS_CACHE_TTL_S
        ):
            return self._adb_connected_cache
        try:
            result = subprocess.run(
                [adb_exe(), "devices"],
                capture_output=True,
                timeout=10.0,
            )
            lines = result.stdout.decode("utf-8", errors="replace").strip().splitlines()
            serials: set[str] = set()
            for line in lines[1:]:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "device":
                    serials.add(parts[0])
            if log_result:
                app_logger.log(
                    f"[manager] Discovered {len(serials)} device(s): {sorted(serials)}",
                    "INFO",
                )
            if use_cache:
                self._adb_connected_cache = serials
                self._adb_cache_updated_at = time.monotonic()
            return serials
        except Exception as e:
            app_logger.log(f"[manager] discover_devices error: {e}", "ERROR")
            return set()

    def discover_devices(self) -> list[str]:
        """Run bundled adb devices and return connected serials."""
        return sorted(self._connected_serials(log_result=True))

    def start_device(self, serial: str) -> bool:
        existing_worker = self._workers.get(serial)
        if existing_worker and existing_worker.is_running:
            app_logger.log(f"[manager] {serial[:8]} already running", "WARNING")
            return True

        # Fail early with an accurate error instead of letting scrcpy report a
        # misleading jar-push failure when the USB/ADB transport has dropped.
        if serial not in self._connected_serials():
            app_logger.log(
                f"[manager] Cannot start {serial[:8]} — device is not connected via ADB",
                "ERROR",
            )
            return False

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

        self._workers.pop(serial, None)

        settings = self._get_settings()
        devices = self._get_devices()

        backend = ScrcpySocketBackend(
            serial=serial,
            development_mode=settings.development_mode,
        )
        connected = backend.connect()
        if not connected:
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
            persist_tap_cache_fn=self.persist_tap_cache,
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

        self._workers.pop(serial, None)
        app_logger.log(f"[manager] Fully stopped {serial[:8]}", "INFO")

    def _rebuild_backend(self, serial: str) -> bool:
        """
        Tear down the existing scrcpy backend for a device and build a fresh
        one in its place. Called by the worker as Level 3 tap-failure recovery.
        """
        app_logger.log(
            f"[manager] Rebuilding scrcpy backend for {serial[:8]}", "WARNING")

        old = self._backends.pop(serial, None)
        if old:
            try:
                old.disconnect()
            except Exception as e:
                app_logger.log(
                    f"[manager] Error disconnecting old backend for "
                    f"{serial[:8]}: {e}", "WARNING")

        if serial not in self._connected_serials():
            app_logger.log(
                f"[manager] Backend rebuild aborted for {serial[:8]} — "
                f"device is not connected via ADB",
                "ERROR",
            )
            return False

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
        """Return a status snapshot for every registered device."""
        devices = self._get_devices()
        connected_serials = self._connected_serials(use_cache=True)
        result = []
        for serial, cfg in devices.items():
            worker = self._workers.get(serial)
            adb_connected = serial in connected_serials
            if worker:
                status = worker.get_status()
                status["adb_connected"] = adb_connected
                result.append(status)
            else:
                result.append({
                    "serial": serial,
                    "nickname": cfg.nickname,
                    "model": cfg.model,
                    "account": cfg.account,
                    "running": False,
                    "state": "UNKNOWN",
                    "adb_connected": adb_connected,
                    "last_action": "—",
                    "runtime_s": 0.0,
                    "auto_farm_countdown_s": 0.0,
                    "end_run_countdown_s": 0.0,
                })
        return result

    def get_status(self, serial: str) -> dict | None:
        adb_connected = serial in self._connected_serials(use_cache=True)
        worker = self._workers.get(serial)
        if worker:
            status = worker.get_status()
            status["adb_connected"] = adb_connected
            return status

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
                "adb_connected": adb_connected,
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
