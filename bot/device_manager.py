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

USB reset recovery (Level 4, Windows):
  - When a worker reaches adb_failure_threshold — or its Level 3 scrcpy rebuild
    fails after repeated tap failures — it calls recover_via_usb_reset()
    (callback) instead of stopping straight away: USB power cycle via PowerShell
    Disable-/Enable-PnpDevice, poll `adb devices` until the phone returns, then rebuild
    the scrcpy backend. Skipped when the device's pnp_instance_id is blank, when the
    process is not elevated, and at most once per USB_RESET_MIN_INTERVAL_S per device.

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

import platform
import subprocess
import threading
import time
from typing import Callable

from bot import app_logger
from bot.device_worker import DeviceWorker
from capture.scrcpy_socket import ScrcpySocketBackend
from config.constants import (
    ADB_STATUS_CACHE_TTL_S,
    PLATFORM_WINDOWS,
    USB_RESET_ADB_POLL_INTERVAL_S,
    USB_RESET_ADB_REAPPEAR_TIMEOUT_S,
    USB_RESET_MIN_INTERVAL_S,
)
from config.devices import DeviceConfig, load_devices, save_devices
from config.paths import project_root, adb_exe
from config.settings import Settings
from detection.template_bank import TemplateBank
from tools import usb_pnp


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
        # serial -> monotonic time of the last USB reset attempt (rate limit, see
        # recover_via_usb_reset). Each entry is written only by that device's own
        # worker thread, so no lock is needed.
        self._last_usb_reset_at: dict[str, float] = {}
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
            recover_via_usb_reset_fn=lambda s=serial: self.recover_via_usb_reset(s),
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

    def reset_usb_port(self, serial: str) -> bool:
        """
        Attempt a USB port power cycle via PowerShell PnP cmdlets (Windows only).
        Requires pnp_instance_id in device config and admin elevation in the process.
        Returns True if disable+enable dispatched without error; False on any failure
        or if the reset was skipped (the reason is logged at WARNING).
        Does not verify ADB re-enumeration — caller must wait and poll ADB afterward
        (see recover_via_usb_reset).
        Only reached from recover_via_usb_reset, i.e. after the worker has hit its ADB
        failure threshold and scrcpy-layer recovery has already failed.

        Windows: Disable-PnpDevice / Enable-PnpDevice (same PnP layer as devcon.exe,
                 no extra binary required). Implemented in tools/usb_pnp.py.
        Linux:   Not implemented here — uhubctl handles this at the MINISFORUM host.
                 See ROADMAP Future/maybe.
        """
        # Windows USB reset via PowerShell Disable-PnpDevice / Enable-PnpDevice.
        # These cmdlets operate at the same Windows PnP driver level as devcon.exe
        # but require no extra binary — PowerShell is built into Windows.
        # Both require administrator elevation (handled at startup in main.py).
        #
        # pyusb dev.reset() was tested and rejected — it does not trigger full
        # Windows re-enumeration, so the device does not reappear in adb devices.
        # uhubctl does not work on Windows (winusb.sys driver limitation).
        #
        # Linux migration path: replace this method with uhubctl port power cycling.
        # uhubctl -l <hub_location> -p <port> -a cycle
        # Sabrent HB-BU10 (Realtek 0bda) on MINISFORUM is confirmed uhubctl-compatible.
        tag = serial[:8]
        if platform.system() != PLATFORM_WINDOWS:
            app_logger.log(
                f"[manager] USB reset skipped for {tag} — only supported on Windows",
                "WARNING")
            return False

        cfg = self._get_devices().get(serial)
        instance_id = (cfg.pnp_instance_id if cfg else "").strip()
        if not instance_id:
            app_logger.log(
                f"[manager] USB reset skipped for {tag} — no PnP Instance ID configured "
                f"(Device Settings → Detect)", "WARNING")
            return False
        if not usb_pnp.is_valid_instance_id(instance_id):
            app_logger.log(
                f"[manager] USB reset skipped for {tag} — configured PnP Instance ID "
                f"has an invalid format: {instance_id!r}", "WARNING")
            return False
        if not usb_pnp.is_elevated():
            app_logger.log(
                f"[manager] USB reset skipped for {tag} — the app is not running as "
                f"administrator (declined UAC or --no-elevate)", "WARNING")
            return False

        app_logger.log(
            f"[manager] Attempting USB port reset for {tag} ({instance_id}) — "
            f"Disable/Enable-PnpDevice", "WARNING")
        self._last_usb_reset_at[serial] = time.monotonic()
        result = usb_pnp.power_cycle_device(instance_id)
        if not result.ok:
            app_logger.log(
                f"[manager] USB reset failed for {tag}: {result.message}", "ERROR")
            return False
        app_logger.log(
            f"[manager] USB reset dispatched for {tag} — Disable and Enable both succeeded",
            "INFO")
        return True

    def _wait_for_adb_device(self, serial: str) -> bool:
        """
        Poll a live `adb devices` (never the status cache) until this serial is back in
        the "device" state, for at most USB_RESET_ADB_REAPPEAR_TIMEOUT_S. Phones vary in
        how long they take to re-enumerate and re-authorize, so poll instead of one
        blind sleep. Abandons early if the worker was stopped meanwhile.
        """
        deadline = time.monotonic() + USB_RESET_ADB_REAPPEAR_TIMEOUT_S
        while time.monotonic() < deadline:
            worker = self._workers.get(serial)
            if worker is None or not worker.is_running:
                app_logger.log(
                    f"[manager] Worker for {serial[:8]} stopped during USB reset — "
                    f"no longer waiting for ADB", "WARNING")
                return False
            if serial in self._connected_serials():
                return True
            time.sleep(USB_RESET_ADB_POLL_INTERVAL_S)
        return False

    def recover_via_usb_reset(self, serial: str) -> bool:
        """
        Last automated recovery step for an unresponsive device: USB power cycle,
        wait for ADB to see the phone again, then rebuild the scrcpy backend.

        Called by the device's worker (via callback) just before it would stop
        itself: when it reaches adb_failure_threshold, or when its Level 3 scrcpy
        rebuild fails after repeated tap failures. Blocks the calling
        worker thread — acceptable, that device has nothing else to do.

        Skips (returns False) when the device's worker is not running (it was stopped
        meanwhile — never power-cycle a phone the user just stopped), the per-device
        pnp_instance_id is blank, the app is not elevated, the platform is not
        Windows, or this device was already reset within USB_RESET_MIN_INTERVAL_S (stops a flapping phone being power-cycled
        in a loop).

        Returns:
            True  — the device is back on ADB and capture was rebuilt; the worker
                    should reset its failure counter and carry on.
            False — recovery skipped or failed; the worker stops itself as before.
        """
        tag = serial[:8]
        worker = self._workers.get(serial)
        if worker is None or not worker.is_running:
            app_logger.log(
                f"[manager] USB reset for {tag} skipped — its worker is not running",
                "WARNING")
            return False

        last = self._last_usb_reset_at.get(serial)
        if last is not None and time.monotonic() - last < USB_RESET_MIN_INTERVAL_S:
            app_logger.log(
                f"[manager] USB reset for {tag} skipped — it was already reset "
                f"{time.monotonic() - last:.0f}s ago (minimum interval "
                f"{USB_RESET_MIN_INTERVAL_S:.0f}s)", "WARNING")
            return False

        if not self.reset_usb_port(serial):
            return False

        if not self._wait_for_adb_device(serial):
            app_logger.log(
                f"[manager] {tag} still missing from adb devices "
                f"{USB_RESET_ADB_REAPPEAR_TIMEOUT_S:.0f}s after USB reset — "
                f"end of automated recovery", "ERROR")
            return False

        app_logger.log(f"[manager] USB reset recovered {tag}", "INFO")
        return self._rebuild_backend(serial)

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
