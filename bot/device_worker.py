"""
bot/device_worker.py

The main loop for a single device. One DeviceWorker per connected phone.

Consecutive ADB failure detection:
  The worker tracks how many times in a row ADB reports the device gone
  ("device 'X' not found" or "device offline" — see tools/adb_errors.py)
  (checked via _check_roblox_foreground / _check_roblox_running each cycle).
  Any successful ADB contact resets the counter to zero. If the counter
  reaches settings.adb_failure_threshold consecutive failures, the worker
  stops itself cleanly. The card shows as stopped on the main tab and must
  be restarted manually once the device is back and unlocked.

  "Consecutive" is the key constraint — isolated blips during normal
  operation will not accumulate toward the threshold across cycles that
  otherwise succeed.

  Capture backend disconnect (scrcpy connection reset) is also funneled
  through this counter. If the backend's auto-reconnect fails, _connected
  becomes False and the worker treats each None-frame cycle as a failure.
  At threshold the worker stops itself — same behavior as device-not-found.

Tap failure recovery (_handle_tap_failure):
  The worker tracks how many tap/double_tap calls in a row have returned
  False (timeout or ADB error). Any successful tap resets the counter to 0.

  Level 1 (tap_failure_threshold, default 5):
    Call adb_reconnect() — restarts the ADB transport layer without touching
    USB or any running apps. Non-disruptive to the game session. The counter
    is NOT reset by this attempt: it keeps counting so a persistent failure
    escalates to Level 3. (Resetting it here made Level 3 unreachable with the
    default thresholds, 5 < 10 — a phone with dead taps looped adb_reconnect
    forever.)

  Level 3 (tap_failure_hard_threshold, default 10):
    Call reconnect_capture() — tears down and rebuilds the scrcpy backend
    for this device only. Slightly more disruptive (video stream drops and
    reconnects) but still leaves the game running. Counter resets after
    the attempt, so the whole ladder (Level 1 at 5, Level 3 at 10) repeats
    while failures persist. If hard <= soft, Level 3 wins and Level 1 never fires.

  Stop (hard threshold + rebuild failed):
    If the backend rebuild also fails, try USB reset recovery (Level 4, below)
    before giving up. Only if that is unavailable or fails is the worker stopped
    (card shows as Stopped).

  force_stop_roblox / launch_roblox are never called as part of tap failure
  recovery — those remain reserved for CRASHED / UNKNOWN state handlers only.

USB reset recovery (Level 4, Windows — _try_usb_reset_recovery):
  Reached from two places, both just before the worker would stop itself: consecutive
  ADB failures reaching settings.adb_failure_threshold (_handle_adb_failure), and a
  failed Level 3 scrcpy rebuild after repeated tap failures (_handle_tap_failure). The
  device is confirmed unresponsive, so the worker calls recover_via_usb_reset()
  (a DeviceManager callback): USB power cycle, wait for ADB, rebuild the scrcpy
  backend. If that succeeds the failure counter resets and the worker carries on;
  if it is skipped (no pnp_instance_id, not elevated, rate-limited) or fails, the
  worker stops itself exactly as before.

Tap coordinate resolution (_resolve_tap_coords):
  1. tap_offset_x/y set on the DetectorAssignment (manual override via
     crop tool amber dot) → use it always, runs detection for bbox origin.
  2. cached_tap_x/y set AND always_detect is False → use cached coord,
     no detection needed.
  3. Neither condition met (cache empty, or always_detect is True) → run
     template match live. Persist result only when always_detect is False.
     Detectors with always_detect=True never write to the cache.
  The disk write goes through the persist_tap_cache_fn callback owned by
  DeviceManager (thread-safe); the worker never touches devices.json itself.

Rejoin navigation is fully state-driven — no Chrome URL, no hardcoded sleeps.
Each detected state triggers one action that advances to the next state.
Each handler taps its OWN element — the next cycle detects the resulting screen.

Fast-path rejoin (when 24rolla is visible on home screen):
  ROBLOX_HOME → tap 24rolla_avatar (tap target) → JOIN_BUTTON → tap Join → IN_TANK

Fallback rejoin (hamburger menu route):
  ROBLOX_HOME → tap hamburger_menu (tap target)
  → CONTINUE_PLAYING_BUTTON → tap continue_playing_button (tap target)
  → BEFISH_GAME_ICON → tap befish_game_icon (tap target)
  → GAME_PAGE → tap game_page (active players icon — goes directly to server list)
  → PRIVATE_SERVER_ENTRY → tap private_server_entry (its own element)
  → IN_TANK

CRASHED state: determined by ADB process check, not image detection.
  Launches Roblox if not running, then falls into ROBLOX_HOME.
DISCONNECTED state: fires immediately — taps Leave via tap offset. No timer.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Optional

from bot import app_logger, states
from bot.actions import (
    adb_reconnect,
    double_tap,
    force_stop_roblox,
    launch_roblox,
    stay_awake_tap,
    tap,
)
from capture.base import CaptureBackend
from config.constants import (
    ADB_FOREGROUND_CHECK_SHELL_CMD,
    ADB_FOREGROUND_CHECK_TIMEOUT_S,
    DETECTION_THRESHOLD,
)
from config.devices import DeviceConfig
from config.settings import Settings
from detection.detector import run_detector_by_name
from detection.template_bank import TemplateBank
from tools.adb_errors import adb_output_means_device_gone

_DEVICE_NOT_FOUND = "device_not_found"

_DETECTOR_PRIORITY = [
    states.DISCONNECTED,
    states.JOIN_BUTTON,
    states.ROBLOX_HOME,
    states.CONTINUE_PLAYING_BUTTON,
    states.GAME_PAGE,
    states.BEFISH_GAME_ICON,
    states.PRIVATE_SERVER_ENTRY,
    states.LOBBY,
    states.AUTO_FARM_OFF,
    states.DEATH_SCREEN,
    states.NET_REVEAL,
    states.IN_TANK,
]


class DeviceWorker:

    def __init__(
        self,
        device_cfg: DeviceConfig,
        settings: Settings,
        capture_backend: CaptureBackend,
        template_bank: TemplateBank,
        get_settings: Callable[[], Settings],
        get_device_cfg: Callable[[], DeviceConfig],
        reconnect_capture: Callable[[], bool],
        persist_tap_cache_fn: Callable[[str, str, int, int], None],
        recover_via_usb_reset_fn: Callable[[], bool],
    ):
        self._serial = device_cfg.serial
        self._capture = capture_backend
        self._bank = template_bank
        self._get_settings = get_settings
        self._get_device_cfg = get_device_cfg
        self._reconnect_capture = reconnect_capture
        self._persist_tap_cache = persist_tap_cache_fn
        self._recover_via_usb_reset = recover_via_usb_reset_fn

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._current_state: str = states.UNKNOWN
        self._last_action: str = "None"
        self._running: bool = False
        self._start_time: Optional[float] = None

        _t = time.monotonic()
        self._last_auto_farm_tap: float = _t
        self._last_end_run_tap: float = _t
        self._last_stay_awake_tap: float = _t

        self._lobby_entered_at: Optional[float] = None
        self._unknown_entered_at: Optional[float] = None
        self._consecutive_adb_failures: int = 0
        self._consecutive_tap_failures: int = 0

        self._last_frame = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._consecutive_adb_failures = 0
        self._consecutive_tap_failures = 0
        self._start_time = time.monotonic()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"worker-{self._serial[:8]}")
        self._thread.start()
        self._running = True
        self._log("Worker started", "INFO")

    def stop(self) -> None:
        if not self._running:
            return
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=15.0)
        self._running = False
        self._start_time = None
        self._current_state = states.UNKNOWN
        self._last_action = "—"
        self._lobby_entered_at = None
        self._unknown_entered_at = None
        self._consecutive_adb_failures = 0
        self._consecutive_tap_failures = 0
        self._log("Worker stopped", "INFO")

    def replace_capture_backend(self, backend: CaptureBackend) -> None:
        """
        Swap in a freshly connected capture backend. Called by DeviceManager
        after a successful _rebuild_backend(). The old backend is already
        disconnected by the time this is called.
        """
        self._capture = backend
        self._latest_frame = None
        self._log("Capture backend replaced — resuming on new stream", "INFO")

    def get_status(self) -> dict:
        cfg = self._get_device_cfg()
        now = time.monotonic()
        elapsed_auto = now - self._last_auto_farm_tap
        elapsed_end  = now - self._last_end_run_tap
        time_in_lobby = (now - self._lobby_entered_at) if self._lobby_entered_at else 0.0
        return {
            "serial":                 self._serial,
            "nickname":               cfg.nickname,
            "model":                  cfg.model,
            "account":                cfg.account,
            "running":                self._running,
            "state":                  self._current_state,
            "last_action":            self._last_action,
            "runtime_s":              (now - self._start_time) if self._start_time else 0.0,
            "auto_farm_countdown_s":  max(0.0, cfg.auto_farm_interval_s - elapsed_auto),
            "end_run_countdown_s":    max(0.0, cfg.end_run_interval_s - elapsed_end),
            "stay_awake_countdown_s": max(0.0, cfg.stay_awake_interval_s - (now - self._last_stay_awake_tap)),
            "time_in_lobby_s":        time_in_lobby,
            "time_in_unknown_s":      (now - self._unknown_entered_at) if self._unknown_entered_at else 0.0,
        }

    def force_end_run(self) -> None:
        cfg = self._get_device_cfg()
        settings = self._get_settings()
        self._do_end_run(cfg, settings)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                settings = self._get_settings()
                cfg = self._get_device_cfg()

                frame = self._capture.get_frame()
                if frame is None:
                    if self._capture.is_reconnecting:
                        # The capture backend is intentionally waiting for a
                        # transient transport (typically USB/ADB) to recover.
                        # Do not count this known recovery window as an ADB
                        # failure or stop the worker prematurely.
                        time.sleep(settings.loop_interval_s)
                        continue

                    if not self._capture.is_connected:
                        self._log(
                            "Capture backend disconnected — "
                            "scrcpy reconnect failed", "WARNING")
                        if self._handle_adb_failure(settings):
                            return
                        time.sleep(settings.loop_interval_s)
                        continue

                    self._log(
                        "Frame capture returned None — checking if Roblox is running",
                        "WARNING")
                    foreground_result = self._check_roblox_foreground()

                    if foreground_result == _DEVICE_NOT_FOUND:
                        if self._handle_adb_failure(settings):
                            return
                    else:
                        self._consecutive_adb_failures = 0
                        if not foreground_result:
                            running_result = self._check_roblox_running()
                            if running_result == _DEVICE_NOT_FOUND:
                                if self._handle_adb_failure(settings):
                                    return
                            else:
                                self._consecutive_adb_failures = 0
                                if not running_result:
                                    if self._current_state != states.CRASHED:
                                        self._log(
                                            "Roblox not running — marking as CRASHED",
                                            "WARNING")
                                        self._current_state = states.CRASHED
                                    self._act(states.CRASHED, None, cfg, settings)
                                else:
                                    self._log(
                                        "Roblox is backgrounded — bringing to foreground",
                                        "WARNING")
                                    launch_roblox(self._serial)
                                    self._current_state = states.UNKNOWN

                    time.sleep(settings.loop_interval_s)
                    continue

                self._consecutive_adb_failures = 0
                self._last_frame = frame
                detected_state, detect_result = self._resolve_state(frame, cfg, settings)
                self._act(detected_state, detect_result, cfg, settings)
                time.sleep(settings.loop_interval_s)

            except Exception as e:
                self._log(
                    f"Unhandled error in worker loop: {type(e).__name__}: {e}", "ERROR")
                settings = self._get_settings()
                if settings.development_mode:
                    raise
                time.sleep(settings.loop_interval_s)

    # ------------------------------------------------------------------
    # Consecutive failure handling
    # ------------------------------------------------------------------

    def _try_usb_reset_recovery(self, settings: Settings) -> bool:
        """
        Last automated recovery step before the worker gives up: ask the manager (via
        the recover_via_usb_reset_fn callback) to USB power-cycle this phone, wait for
        ADB, and rebuild the scrcpy backend. Shared by the ADB-failure and tap-failure
        paths so both behave identically.

        Returns:
            True  — the device is back and capture was rebuilt; BOTH failure counters
                    are reset and the worker should carry on.
            False — recovery was skipped (no pnp_instance_id, not elevated, rate
                    limited, ...) or failed; the caller stops the worker.

        Two-mode error handling: an exception from the callback is logged and treated
        as "failed" in production, and re-raised in development mode.
        """
        try:
            recovered = bool(self._recover_via_usb_reset())
        except Exception as e:
            self._log(f"USB reset recovery raised {type(e).__name__}: {e}", "ERROR")
            if settings.development_mode:
                raise
            return False
        if recovered:
            self._consecutive_adb_failures = 0
            self._consecutive_tap_failures = 0
            self._log("USB reset recovery succeeded — resuming", "INFO")
        return recovered

    def _handle_adb_failure(self, settings: Settings) -> bool:
        """
        Increment the device-gone counter (ADB reports the device not found or
        offline). At the threshold, try USB reset recovery before giving up.

        Returns:
            True  — the worker should stop (threshold reached and recovery skipped
                    or failed).
            False — keep running: below the threshold, or recovery brought the
                    device back (the counter is reset).
        """
        self._consecutive_adb_failures += 1
        threshold = settings.adb_failure_threshold
        self._log(
            f"Device gone (not found / offline) — consecutive failures: "
            f"{self._consecutive_adb_failures}/{threshold}",
            "WARNING",
        )
        if self._consecutive_adb_failures >= threshold:
            self._log(
                f"Device gone (not found / offline) {threshold} times in a row — "
                f"trying USB reset recovery before stopping",
                "ERROR",
            )
            if self._try_usb_reset_recovery(settings):
                return False
            self._log(
                "USB reset recovery unavailable or failed — stopping worker. "
                "Restart manually when device is back.",
                "ERROR",
            )
            threading.Thread(target=self.stop, daemon=True).start()
            return True
        return False

    def _handle_tap_failure(self, settings: Settings) -> None:
        """
        Increment the consecutive tap failure counter and trigger recovery
        at the configured thresholds.

        Level 1 (tap_failure_threshold): adb reconnect — restarts ADB
          transport only. Non-disruptive to the game. Does NOT reset the
          counter, so failures keep escalating toward Level 3.
        Level 3 (tap_failure_hard_threshold): rebuild scrcpy backend — tears
          down and reconnects the video stream for this device only.
        Level 4 (rebuild failed): USB reset recovery via _try_usb_reset_recovery.
        Stop: only if that is skipped or fails too.

        force_stop_roblox / launch_roblox are never called here — those
        remain reserved for CRASHED / UNKNOWN state recovery only.
        """
        self._consecutive_tap_failures += 1
        soft = settings.tap_failure_threshold
        hard = settings.tap_failure_hard_threshold

        self._log(
            f"Tap failure — consecutive: {self._consecutive_tap_failures} "
            f"(soft={soft}, hard={hard})",
            "WARNING",
        )

        # Level 3 is checked first so that hard <= soft (a misconfiguration) cannot
        # fire both actions on the same failure.
        if self._consecutive_tap_failures >= hard:
            self._log(
                f"Tap failures reached {hard} — rebuilding scrcpy backend",
                "ERROR",
            )
            self._consecutive_tap_failures = 0
            ok = self._reconnect_capture()
            if not ok:
                self._log(
                    "Backend rebuild failed — trying USB reset recovery before stopping",
                    "ERROR",
                )
                if self._try_usb_reset_recovery(settings):
                    return
                self._log(
                    "Backend rebuild failed and USB reset recovery unavailable or "
                    "failed — stopping worker. Restart manually once device is "
                    "responding.",
                    "ERROR",
                )
                threading.Thread(target=self.stop, daemon=True).start()

        elif self._consecutive_tap_failures == soft:
            self._log(
                f"Tap failures reached {soft} — attempting ADB reconnect",
                "WARNING",
            )
            ok = adb_reconnect(self._serial)
            self._log(
                f"ADB reconnect {'succeeded' if ok else 'failed'} for {self._serial[:8]}",
                "INFO" if ok else "WARNING",
            )
            # Deliberately NOT reset: the counter must keep growing so that a
            # failure that survives the reconnect reaches the hard threshold.
            # Only a successful tap (_record_tap_success) or the Level 3 rebuild
            # resets it.

    def _record_tap_success(self) -> None:
        """Reset the tap failure counter on any successful tap."""
        if self._consecutive_tap_failures > 0:
            self._consecutive_tap_failures = 0

    # ------------------------------------------------------------------
    # State resolution
    # ------------------------------------------------------------------

    def _resolve_state(self, frame, cfg: DeviceConfig, settings: Settings):
        """
        Returns (state_str, detect_result) where detect_result is the
        DetectResult that matched, or None for CRASHED/UNKNOWN.
        """
        detector_assignments = cfg.detector_assignments

        for detector_name in _DETECTOR_PRIORITY:
            result = run_detector_by_name(
                detector_name=states.to_detector_name(detector_name),
                frame_bgr=frame,
                device_serial=self._serial,
                detector_assignments=detector_assignments,
                bank=self._bank,
                threshold=DETECTION_THRESHOLD,
            )
            if result.found:
                app_logger.debug(
                    settings.debug, "detections",
                    f"{self._serial[:8]} detected {detector_name} "
                    f"(score={result.score:.3f})",
                    self._log,
                )
                if detector_name != self._current_state:
                    self._log(
                        f"State: {self._current_state} → {detector_name} "
                        f"(score={result.score:.3f})", "INFO")
                    self._current_state = detector_name
                return detector_name, result

        foreground_result = self._check_roblox_foreground()
        if foreground_result == _DEVICE_NOT_FOUND:
            pass
        elif not foreground_result:
            running_result = self._check_roblox_running()
            if running_result != _DEVICE_NOT_FOUND and not running_result:
                if self._current_state != states.CRASHED:
                    self._log("Roblox not running — marking as CRASHED", "WARNING")
                    self._current_state = states.CRASHED
                return states.CRASHED, None
            elif running_result != _DEVICE_NOT_FOUND:
                self._log("Roblox is backgrounded — bringing to foreground", "WARNING")
                launch_roblox(self._serial)
                return states.UNKNOWN, None

        if self._current_state != states.UNKNOWN:
            self._log(f"State: {self._current_state} → {states.UNKNOWN}", "INFO")
            self._current_state = states.UNKNOWN
        return states.UNKNOWN, None

    def _check_secondary(self, detector_name: str, cfg: DeviceConfig,
                          settings: Settings) -> bool:
        if self._last_frame is None:
            return False
        detector_key = states.to_detector_name(detector_name)
        result = run_detector_by_name(
            detector_name=detector_key,
            frame_bgr=self._last_frame,
            device_serial=self._serial,
            detector_assignments=cfg.detector_assignments,
            bank=self._bank,
            threshold=DETECTION_THRESHOLD,
        )
        if result.found:
            app_logger.debug(
                settings.debug, "detections",
                f"{self._serial[:8]} secondary: {detector_key} "
                f"(score={result.score:.3f})",
                self._log,
            )
        return result.found

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _act(self, state: str, detect_result, cfg: DeviceConfig, settings: Settings) -> None:
        if cfg.stay_awake_enabled:
            now = time.monotonic()
            if now - self._last_stay_awake_tap >= cfg.stay_awake_interval_s:
                stay_awake_tap(self._serial)
                self._last_stay_awake_tap = now
                self._set_last_action("Stay-awake tap")

        if state == states.DISCONNECTED:
            self._handle_disconnected(cfg, settings)
        elif state == states.CRASHED:
            self._handle_crashed(cfg, settings)
        elif state == states.JOIN_BUTTON:
            self._handle_join_button(cfg, settings)
        elif state == states.ROBLOX_HOME:
            self._handle_roblox_home(cfg, settings)
        elif state == states.CONTINUE_PLAYING_BUTTON:
            self._handle_continue_playing_button(cfg, settings)
        elif state == states.BEFISH_GAME_ICON:
            self._handle_befish_game_icon(cfg, settings)
        elif state == states.GAME_PAGE:
            self._handle_game_page(detect_result, cfg, settings)
        elif state == states.PRIVATE_SERVER_ENTRY:
            self._handle_private_server_entry(cfg, settings)
        elif state == states.LOBBY:
            self._handle_lobby(cfg, settings)
        elif state == states.AUTO_FARM_OFF:
            self._handle_auto_farm_off(cfg, settings)
        elif state in (states.DEATH_SCREEN, states.NET_REVEAL):
            self._reset_lobby_timer()
            self._pause_auto_farm_timer()
            self._reset_end_run_timer()
        elif state == states.IN_TANK:
            self._handle_in_tank(cfg, settings)
        else:
            self._reset_lobby_timer()
            self._pause_auto_farm_timer()
            self._handle_unknown(cfg, settings)

    # ------------------------------------------------------------------
    # State handlers
    # Each handler taps its OWN element. The next cycle detects the
    # resulting screen and dispatches to the appropriate next handler.
    # ------------------------------------------------------------------

    def _handle_in_tank(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        self._reset_lobby_timer()
        now = time.monotonic()
        if cfg.auto_farm_enabled:
            if now - self._last_auto_farm_tap >= cfg.auto_farm_interval_s:
                self._do_auto_farm_double_click(cfg, settings)
        if cfg.end_run_enabled:
            if now - self._last_end_run_tap >= cfg.end_run_interval_s:
                self._do_end_run(cfg, settings)

    def _handle_lobby(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._pause_auto_farm_timer()
        self._reset_end_run_timer()
        now = time.monotonic()
        if self._lobby_entered_at is None:
            self._lobby_entered_at = now
            self._log("Entered lobby — starting lobby timer", "INFO")
        if cfg.auto_farm_enabled:
            if self._check_secondary(states.AUTO_FARM_OFF, cfg, settings):
                self._log("Auto-farm is OFF in lobby — tapping to re-enable", "INFO")
                self._do_auto_farm_tap(cfg, settings)
        if cfg.stuck_lobby_detection_enabled:
            time_in_lobby = now - self._lobby_entered_at
            if time_in_lobby >= settings.lobby_stuck_threshold_s:
                self._log(
                    f"Stuck in lobby for {time_in_lobby:.0f}s — firing end-run tap",
                    "WARNING")
                self._do_end_run(cfg, settings)
                self._reset_lobby_timer()
                self._set_last_action("End-run tap (stuck in lobby)")

    def _handle_unknown(self, cfg: DeviceConfig, settings: Settings) -> None:
        now = time.monotonic()
        if self._unknown_entered_at is None:
            self._unknown_entered_at = now
            return
        time_unknown = now - self._unknown_entered_at
        if time_unknown >= settings.unknown_stuck_threshold_s:
            self._log(
                f"Stuck in UNKNOWN for {time_unknown:.0f}s — force-stopping and relaunching",
                "WARNING")
            self._unknown_entered_at = None
            force_stop_roblox(self._serial)
            launch_roblox(self._serial)
            self._set_last_action("Force relaunched (stuck in UNKNOWN)")

    def _handle_auto_farm_off(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        self._log("Auto-farm is OFF — tapping to re-enable", "INFO")
        self._do_auto_farm_tap(cfg, settings)

    def _handle_disconnected(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        self._reset_lobby_timer()
        self._log("Disconnected dialog — tapping Leave", "INFO")
        self._do_leave_tap(cfg, settings)
        self._set_last_action("Tapped Leave (disconnected)")

    def _handle_crashed(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        self._reset_lobby_timer()
        self._pause_auto_farm_timer()
        self._reset_end_run_timer()
        self._log("App not running — launching Roblox", "INFO")
        launch_roblox(self._serial)
        self._set_last_action("Launched Roblox (crash recovery)")

    def _handle_roblox_home(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        self._reset_lobby_timer()
        self._pause_auto_farm_timer()
        self._reset_end_run_timer()
        coords = self._resolve_tap_coords(cfg, ["24rolla_avatar"])
        if coords:
            self._log("24rolla visible on home screen — tapping avatar (fast path)", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped 24rolla avatar (fast path)")
            return
        coords = self._resolve_tap_coords(cfg, ["hamburger_menu"])
        if coords:
            self._log("24rolla not visible — tapping hamburger menu (fallback path)", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped hamburger menu (fallback path)")
        else:
            self._log("Neither 24rolla_avatar nor hamburger_menu found on home screen",
                      "WARNING")

    def _handle_join_button(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        coords = self._resolve_tap_coords(cfg, ["join_button"])
        if coords:
            self._log("Join button visible — tapping Join", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped Join button")
        else:
            self._log("join_button coords not resolved", "WARNING")

    def _handle_continue_playing_button(self, cfg: DeviceConfig,
                                         settings: Settings) -> None:
        self._unknown_entered_at = None
        coords = self._resolve_tap_coords(cfg, ["continue_playing_button"])
        if coords:
            self._log("Continue Playing button visible — tapping it", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped Continue Playing button")
        else:
            self._log("continue_playing_button coords not resolved", "WARNING")

    def _handle_befish_game_icon(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        coords = self._resolve_tap_coords(cfg, ["befish_game_icon"])
        if coords:
            self._log("Be Fish game icon visible — tapping it", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped Be Fish game icon")
        else:
            self._log("befish_game_icon coords not resolved", "WARNING")

    def _handle_game_page(self, detect_result, cfg: DeviceConfig,
                           settings: Settings) -> None:
        """
        Tap the active players icon on the game page bottom-sheet.
        This icon (showing X active players) goes directly to the server list,
        bypassing the need to expand the sheet and scroll to the Servers button.
        The detector image should be cropped to this icon.
        """
        self._unknown_entered_at = None
        coords = self._resolve_tap_coords(cfg, [states.GAME_PAGE])
        if coords:
            self._log("Game page detected — tapping active players icon", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped active players icon (game page)")
        else:
            self._log("game_page coords not resolved", "WARNING")

    def _handle_private_server_entry(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._unknown_entered_at = None
        coords = self._resolve_tap_coords(cfg, [states.PRIVATE_SERVER_ENTRY])
        if coords:
            self._log("Private server entry visible — tapping it", "INFO")
            ok = tap(self._serial, coords[0], coords[1])
            if ok:
                self._record_tap_success()
            else:
                self._handle_tap_failure(settings)
            self._set_last_action("Tapped private server entry")
        else:
            self._log("private_server_entry coords not resolved", "WARNING")

    # ------------------------------------------------------------------
    # Action helpers
    # ------------------------------------------------------------------

    def _do_auto_farm_double_click(self, cfg: DeviceConfig,
                                    settings: Settings) -> None:
        coords = self._resolve_tap_coords(
            cfg, [states.AUTO_FARM_ON, states.AUTO_FARM_OFF])
        if coords is None:
            self._log(
                "Auto-farm: no assignment found for auto_farm_on or auto_farm_off",
                "WARNING")
            return
        self._log("Auto-farm interval elapsed — double-clicking", "INFO")
        ok = double_tap(self._serial, coords[0], coords[1],
                        delay_s=settings.double_click_delay_s)
        self._last_auto_farm_tap = time.monotonic()
        self._set_last_action("Auto-farm double-click")
        if ok:
            self._record_tap_success()
        else:
            self._handle_tap_failure(settings)

    def _do_auto_farm_tap(self, cfg: DeviceConfig, settings: Settings) -> None:
        coords = self._resolve_tap_coords(cfg, [states.AUTO_FARM_OFF])
        if coords is None:
            self._log("Auto-farm OFF: no assignment found for auto_farm_off", "WARNING")
            return
        ok = tap(self._serial, coords[0], coords[1])
        self._set_last_action("Re-enabled auto-farm (single tap)")
        if ok:
            self._record_tap_success()
        else:
            self._handle_tap_failure(settings)

    def _do_end_run(self, cfg: DeviceConfig, settings: Settings) -> None:
        coords = self._resolve_tap_coords(cfg, [states.END_RUN_BUTTON])
        if coords is None:
            self._log("End-run: no assignment found for end_run_button", "WARNING")
            return
        self._log("End-run tap firing", "INFO")
        ok = tap(self._serial, coords[0], coords[1])
        self._last_end_run_tap = time.monotonic()
        self._set_last_action("End-run tap")
        if ok:
            self._record_tap_success()
        else:
            self._handle_tap_failure(settings)

    def _do_leave_tap(self, cfg: DeviceConfig, settings: Settings) -> None:
        coords = self._resolve_tap_coords(cfg, [states.DISCONNECTED])
        if coords is None:
            self._log("Leave: no tap offset assigned for disconnected detector", "WARNING")
            return
        ok = tap(self._serial, coords[0], coords[1])
        self._set_last_action("Tapped Leave")
        if ok:
            self._record_tap_success()
        else:
            self._handle_tap_failure(settings)

    def _resolve_tap_coords(
        self,
        cfg: DeviceConfig,
        detector_names: list[str],
    ) -> Optional[tuple[int, int]]:
        """
        Resolve tap coordinates for the first matching detector in detector_names.

        Priority:
          1. tap_offset_x/y — manual override, always wins. Needs detection for bbox.
          2. cached_tap_x/y — persisted screen coord, used only when always_detect
             is False. No detection needed.
          3. Neither condition met (or always_detect is True) — run template match
             live. Persist result only when always_detect is False.
        """
        detector_assignments = cfg.detector_assignments

        for name in detector_names:
            detector_key = states.to_detector_name(name)
            assignment = detector_assignments.get(detector_key)
            if assignment is None:
                continue

            # Priority 1: manual tap override
            if assignment.tap_offset_x is not None:
                if self._last_frame is None:
                    continue
                result = run_detector_by_name(
                    detector_name=detector_key,
                    frame_bgr=self._last_frame,
                    device_serial=self._serial,
                    detector_assignments=detector_assignments,
                    bank=self._bank,
                    threshold=DETECTION_THRESHOLD,
                )
                if result.found and result.bbox:
                    return (result.bbox[0] + assignment.tap_offset_x,
                            result.bbox[1] + assignment.tap_offset_y)
                continue

            # Priority 2: persistent cache (skipped for always_detect detectors)
            if not assignment.always_detect and assignment.cached_tap_x is not None:
                self._log(
                    f"[tap_cache] HIT {detector_key} → "
                    f"({assignment.cached_tap_x}, {assignment.cached_tap_y})",
                    "DEBUG")
                return (assignment.cached_tap_x, assignment.cached_tap_y)

            # Priority 3: run detection live
            if self._last_frame is None:
                continue
            result = run_detector_by_name(
                detector_name=detector_key,
                frame_bgr=self._last_frame,
                device_serial=self._serial,
                detector_assignments=detector_assignments,
                bank=self._bank,
                threshold=DETECTION_THRESHOLD,
            )
            if result.found and result.center:
                x, y = result.center
                if not assignment.always_detect:
                    # Cache for detectors with stable positions. In-memory update
                    # is immediate (only this worker owns this device's cfg);
                    # the manager serializes the disk write across all workers.
                    assignment.cached_tap_x = x
                    assignment.cached_tap_y = y
                    self._persist_tap_cache(self._serial, detector_key, x, y)
                else:
                    # always_detect: use live result, never cache
                    self._log(
                        f"[tap_cache] LIVE {detector_key} → ({x}, {y})", "DEBUG")
                return (x, y)

        return None

    # ------------------------------------------------------------------
    # Timer helpers
    # ------------------------------------------------------------------

    def _reset_lobby_timer(self) -> None:
        if self._lobby_entered_at is not None:
            self._lobby_entered_at = None

    def _pause_auto_farm_timer(self) -> None:
        self._last_auto_farm_tap = time.monotonic()

    def _reset_end_run_timer(self) -> None:
        self._last_end_run_tap = time.monotonic()

    # ------------------------------------------------------------------
    # ADB checks
    # ------------------------------------------------------------------

    def _check_roblox_foreground(self):
        """
        Check whether Roblox is the foreground app via the device's window focus.

        Returns:
            True / False           — Roblox is / is not in the foreground. False
                                     also covers "could not determine" and any
                                     error or timeout (logged at WARNING).
            _DEVICE_NOT_FOUND      — ADB reports the device is gone; the caller
                                     feeds this to the consecutive-failure counter.
        """
        try:
            from config.paths import adb_exe
            # Lightweight foreground check — a couple of grep'd focus lines instead
            # of the full activity stack. 'dumpsys activity activities' was the
            # previous command; too much output to pull on every None-frame or
            # no-detector-match cycle. Same answer from ~200 bytes.
            result = subprocess.run(
                [adb_exe(), "-s", self._serial, "shell",
                 ADB_FOREGROUND_CHECK_SHELL_CMD],
                capture_output=True, timeout=ADB_FOREGROUND_CHECK_TIMEOUT_S,
            )
            if adb_output_means_device_gone(result.returncode, result.stderr):
                return _DEVICE_NOT_FOUND
            output = result.stdout.decode("utf-8", errors="replace")
            # grep already filtered to mCurrentFocus / mFocusedApp lines on-device.
            # Multi-display devices emit several (some `=null`), so match any line.
            focus_lines = [line for line in output.splitlines() if line.strip()]
            if focus_lines:
                is_fg = any("com.roblox.client" in line for line in focus_lines)
                self._log(
                    f"Roblox {'is' if is_fg else 'is NOT'} foreground app",
                    "DEBUG" if is_fg else "WARNING",
                )
                return is_fg
            self._log("Could not determine foreground app", "WARNING")
            return False
        except Exception as e:
            self._log(f"Foreground check failed: {e}", "WARNING")
            return False

    def _check_roblox_running(self):
        """
        Check whether a Roblox process exists on the device (used to tell CRASHED from
        "backgrounded").

        Returns:
            True / False       — a com.roblox.client process is / is not running. False
                               also covers any error or timeout (logged at WARNING).
            _DEVICE_NOT_FOUND  — ADB reports the device gone (not found / offline); the
                               caller feeds this to the consecutive-failure counter.
        """
        try:
            from config.paths import adb_exe
            result = subprocess.run(
                [adb_exe(), "-s", self._serial, "shell",
                 "ps", "-A", "-o", "NAME"],
                capture_output=True, timeout=5.0,
            )
            if adb_output_means_device_gone(result.returncode, result.stderr):
                return _DEVICE_NOT_FOUND
            stdout = result.stdout.decode("utf-8", errors="replace")
            return "com.roblox.client" in stdout
        except Exception as e:
            self._log(f"Process check failed: {e}", "WARNING")
            return False

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _set_last_action(self, action: str) -> None:
        self._last_action = action
        app_logger.debug(
            self._get_settings().debug, "actions",
            f"{self._serial[:8]}: {action}", self._log)

    def _log(self, msg: str, level: str = "INFO") -> None:
        app_logger.log(f"[{self._serial[:8]}] {msg}", level)
