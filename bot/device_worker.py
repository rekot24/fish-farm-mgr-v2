"""
bot/device_worker.py

The main loop for a single device. One DeviceWorker per connected phone.

Key changes from previous version:
  - AUTO_FARM_OFF is now also checked inside _handle_lobby() so auto farm
    gets re-enabled even when the primary state is LOBBY.
  - get_status() now includes time_in_lobby_s for the UI card.
  - Lobby card shows a single "In lobby" timer; no redundant stuck countdown.
  - Tap coordinates resolved via template bank (Phase 6 cache prep):
    auto_farm and end_run no longer rely on manual x/y fields.
    For now, tap_x/y are resolved from the detector result center.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Callable, Optional

from bot import app_logger, states
from bot.actions import (
    double_tap,
    force_stop_roblox,
    join_private_server,
    launch_roblox,
    stay_awake_tap,
    tap,
)
from capture.base import CaptureBackend
from config.constants import DETECTION_THRESHOLD
from config.devices import DeviceConfig
from config.settings import Settings
from detection.detector import run_detector_by_name
from detection.template_bank import TemplateBank


_DETECTOR_PRIORITY = [
    states.DISCONNECTED,
    # CRASHED is detected via ADB process check, not screenshot — see _resolve_state()
    states.ROBLOX_HOME,
    states.LOBBY,
    states.AUTO_FARM_OFF,
    states.DEATH_SCREEN,
    states.NET_REVEAL,
    states.IN_TANK,
]

# Detectors checked inside lobby to catch auto-farm state
_LOBBY_SECONDARY_CHECKS = [
    states.AUTO_FARM_OFF,
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
    ):
        self._serial = device_cfg.serial
        self._capture = capture_backend
        self._bank = template_bank
        self._get_settings = get_settings
        self._get_device_cfg = get_device_cfg

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self._current_state: str = states.UNKNOWN
        self._last_action: str = "None"
        self._running: bool = False
        self._start_time: Optional[float] = None

        # Initialize to now so first fire happens after a full interval, not instantly
        _t = time.monotonic()
        self._last_auto_farm_tap: float = _t
        self._last_end_run_tap: float = _t
        self._last_stay_awake_tap: float = _t

        self._lobby_entered_at: Optional[float] = None
        self._disconnect_detected_at: Optional[float] = None

        # Last captured frame — kept so lobby secondary checks reuse same frame
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
        self._log("Worker stopped", "INFO")

    def get_status(self) -> dict:
        cfg = self._get_device_cfg()
        now = time.monotonic()
        elapsed_auto = now - self._last_auto_farm_tap
        elapsed_end  = now - self._last_end_run_tap
        time_in_lobby = (now - self._lobby_entered_at) if self._lobby_entered_at else 0.0
        return {
            "serial":               self._serial,
            "nickname":             cfg.nickname,
            "model":                cfg.model,
            "account":              cfg.account,
            "running":              self._running,
            "state":                self._current_state,
            "last_action":          self._last_action,
            "runtime_s":            (now - self._start_time) if self._start_time else 0.0,
            "auto_farm_countdown_s":  max(0.0, cfg.auto_farm_interval_s - elapsed_auto),
            "end_run_countdown_s":   max(0.0, cfg.end_run_interval_s - elapsed_end),
            "stay_awake_countdown_s": max(0.0, cfg.stay_awake_interval_s - (now - self._last_stay_awake_tap)),
            "time_in_lobby_s":       time_in_lobby,
        }

    def force_end_run(self) -> None:
        cfg = self._get_device_cfg()
        settings = self._get_settings()
        self._do_end_run(cfg, settings)

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        settings = self._get_settings()
        while not self._stop_event.is_set():
            try:
                settings = self._get_settings()
                cfg = self._get_device_cfg()

                frame = self._capture.get_frame()
                if frame is None:
                    self._log("Frame capture returned None — checking if Roblox is running", "WARNING")
                    # No frame usually means scrcpy has nothing to stream — check process
                    if not self._is_roblox_foreground():
                        if not self._is_roblox_running():
                            # Process not running at all — crash recovery
                            if self._current_state != states.CRASHED:
                                self._log("Roblox not running — marking as CRASHED", "WARNING")
                                self._current_state = states.CRASHED
                            self._act(states.CRASHED, cfg, settings)
                        else:
                            # Process running but backgrounded — bring to foreground
                            self._log("Roblox is backgrounded — bringing to foreground", "WARNING")
                            launch_roblox(self._serial)
                            self._current_state = states.UNKNOWN
                    time.sleep(settings.loop_interval_s)
                    continue

                self._last_frame = frame
                detected_state = self._resolve_state(frame, cfg, settings)
                self._act(detected_state, cfg, settings)
                time.sleep(settings.loop_interval_s)

            except Exception as e:
                self._log(
                    f"Unhandled error in worker loop: {type(e).__name__}: {e}", "ERROR")
                if settings.development_mode:
                    raise
                time.sleep(settings.loop_interval_s)

    # ------------------------------------------------------------------
    # State resolution
    # ------------------------------------------------------------------

    def _resolve_state(self, frame, cfg: DeviceConfig, settings: Settings) -> str:
        device_overrides = list(cfg.detector_assignments.keys())

        for detector_name in _DETECTOR_PRIORITY:
            result = run_detector_by_name(
                detector_name=states.to_detector_name(detector_name),
                frame_bgr=frame,
                device_serial=self._serial,
                device_overrides=device_overrides,
                bank=self._bank,
                threshold=DETECTION_THRESHOLD,
            )
            if result.found:
                app_logger.debug(
                    settings.debug, "detections",
                    f"{self._serial[:8]} detected {detector_name} (score={result.score:.3f})",
                    self._log,
                )
                if detector_name != self._current_state:
                    self._log(
                        f"State: {self._current_state} → {detector_name} "
                        f"(score={result.score:.3f})", "INFO")
                    self._current_state = detector_name
                return detector_name

        # Nothing matched — check if Roblox is foreground before declaring UNKNOWN.
        # Only runs when no other detector fired, avoiding unnecessary ADB calls.
        if not self._is_roblox_foreground():
            if not self._is_roblox_running():
                # Process gone entirely — crash
                if self._current_state != states.CRASHED:
                    self._log("Roblox not running — marking as CRASHED", "WARNING")
                    self._current_state = states.CRASHED
                return states.CRASHED
            else:
                # Process exists but backgrounded — bring to foreground
                self._log("Roblox is backgrounded — bringing to foreground", "WARNING")
                launch_roblox(self._serial)
                return states.UNKNOWN

        if self._current_state != states.UNKNOWN:
            self._log(f"State: {self._current_state} → {states.UNKNOWN}", "INFO")
            self._current_state = states.UNKNOWN
        return states.UNKNOWN

    def _check_secondary(self, detector_name: str, cfg: DeviceConfig,
                          settings: Settings) -> bool:
        """
        Run a secondary detector check on the current frame without changing
        the primary state. Used to detect AUTO_FARM_OFF while in LOBBY.
        Returns True if the detector matched.
        """
        if self._last_frame is None:
            return False
        device_overrides = list(cfg.detector_assignments.keys())
        detector_key = states.to_detector_name(detector_name)
        result = run_detector_by_name(
            detector_name=detector_key,
            frame_bgr=self._last_frame,
            device_serial=self._serial,
            device_overrides=device_overrides,
            bank=self._bank,
            threshold=DETECTION_THRESHOLD,
        )
        if result.found:
            app_logger.debug(
                settings.debug, "detections",
                f"{self._serial[:8]} secondary: {detector_key} (score={result.score:.3f})",
                self._log,
            )
        return result.found

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _act(self, state: str, cfg: DeviceConfig, settings: Settings) -> None:
        # Stay-awake fires on its own interval regardless of game state
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
        elif state == states.ROBLOX_HOME:
            self._handle_roblox_home(cfg, settings)
        elif state == states.LOBBY:
            self._handle_lobby(cfg, settings)
        elif state == states.AUTO_FARM_OFF:
            self._handle_auto_farm_off(cfg, settings)
        elif state in (states.DEATH_SCREEN, states.NET_REVEAL):
            self._reset_lobby_timer()
            self._reset_disconnect_timer()
            self._pause_auto_farm_timer()   # pause: don't count time outside IN_TANK
            self._reset_end_run_timer()     # reset: run ended naturally
        elif state == states.IN_TANK:
            self._handle_in_tank(cfg, settings)
        else:
            self._reset_lobby_timer()
            self._reset_disconnect_timer()
            self._pause_auto_farm_timer()   # pause: unknown state, not in tank

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_in_tank(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        self._reset_disconnect_timer()
        now = time.monotonic()

        if cfg.auto_farm_enabled:
            if now - self._last_auto_farm_tap >= cfg.auto_farm_interval_s:
                self._do_auto_farm_double_click(cfg, settings)

        if cfg.end_run_enabled:
            if now - self._last_end_run_tap >= cfg.end_run_interval_s:
                self._do_end_run(cfg, settings)

    def _handle_lobby(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_disconnect_timer()
        self._pause_auto_farm_timer()   # pause auto-farm — not in tank
        self._reset_end_run_timer()     # reset end-run — lobby means run ended
        now = time.monotonic()

        if self._lobby_entered_at is None:
            self._lobby_entered_at = now
            self._log("Entered lobby — starting lobby timer", "INFO")

        # Secondary check: auto farm may be off while in lobby — re-enable it
        if cfg.auto_farm_enabled:
            if self._check_secondary(states.AUTO_FARM_OFF, cfg, settings):
                self._log("Auto-farm is OFF in lobby — tapping to re-enable", "INFO")
                self._do_auto_farm_tap(cfg, settings)

        if cfg.stuck_lobby_detection_enabled:
            time_in_lobby = now - self._lobby_entered_at
            if time_in_lobby >= settings.lobby_stuck_threshold_s:
                self._log(
                    f"Stuck in lobby for {time_in_lobby:.0f}s — leaving and rejoining",
                    "WARNING")
                self._leave_and_rejoin(cfg, settings)

    def _handle_auto_farm_off(self, cfg: DeviceConfig, settings: Settings) -> None:
        """Auto farm is off and we're not in the lobby — single tap to re-enable."""
        self._reset_disconnect_timer()
        self._log("Auto-farm is OFF — tapping to re-enable", "INFO")
        self._do_auto_farm_tap(cfg, settings)

    def _handle_disconnected(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        now = time.monotonic()

        if self._disconnect_detected_at is None:
            self._disconnect_detected_at = now
            self._log("Disconnected dialog detected — tapping Reconnect", "INFO")
            self._do_reconnect_tap(cfg)
            return

        time_disconnected = now - self._disconnect_detected_at
        if time_disconnected >= settings.disconnect_timeout_s:
            self._log(
                f"Reconnect failed after {time_disconnected:.0f}s — tapping Leave",
                "WARNING")
            self._do_leave_tap(cfg)
            self._reset_disconnect_timer()

    def _handle_crashed(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        self._reset_disconnect_timer()
        self._pause_auto_farm_timer()
        self._reset_end_run_timer()
        self._log("App crashed — launching Roblox", "INFO")
        force_stop_roblox(self._serial)
        time.sleep(2.0)
        launch_roblox(self._serial)
        time.sleep(5.0)
        join_private_server(self._serial, settings.private_server_link)
        self._set_last_action("Launched Roblox + joined private server")

    def _handle_roblox_home(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        self._reset_disconnect_timer()
        self._pause_auto_farm_timer()
        self._reset_end_run_timer()
        self._log("At Roblox home screen — joining private server", "INFO")
        join_private_server(self._serial, settings.private_server_link)
        self._set_last_action("Joined private server from home screen")

    # ------------------------------------------------------------------
    # Action helpers
    # ------------------------------------------------------------------

    def _do_auto_farm_double_click(self, cfg: DeviceConfig, settings: Settings) -> None:
        coords = self._resolve_tap_coords(cfg, [states.AUTO_FARM_ON, states.AUTO_FARM_OFF])
        if coords is None:
            self._log("Auto-farm: no assignment found for auto_farm_on or auto_farm_off", "WARNING")
            return
        self._log("Auto-farm interval elapsed — double-clicking", "INFO")
        double_tap(self._serial, coords[0], coords[1], delay_s=settings.double_click_delay_s)
        self._last_auto_farm_tap = time.monotonic()
        self._set_last_action("Auto-farm double-click")

    def _do_auto_farm_tap(self, cfg: DeviceConfig, settings: Settings) -> None:
        """Single tap to re-enable auto farm when it's detected as OFF."""
        coords = self._resolve_tap_coords(cfg, [states.AUTO_FARM_OFF])
        if coords is None:
            self._log("Auto-farm OFF: no assignment found for auto_farm_off", "WARNING")
            return
        tap(self._serial, coords[0], coords[1])
        self._set_last_action("Re-enabled auto-farm (single tap)")

    def _do_end_run(self, cfg: DeviceConfig, settings: Settings) -> None:
        coords = self._resolve_tap_coords(cfg, [states.END_RUN_BUTTON])
        if coords is None:
            self._log("End-run: no assignment found for end_run_button", "WARNING")
            return
        self._log("End-run tap firing", "INFO")
        tap(self._serial, coords[0], coords[1])
        self._last_end_run_tap = time.monotonic()
        self._set_last_action("End-run tap")

    def _do_reconnect_tap(self, cfg: DeviceConfig) -> None:
        coords = self._resolve_tap_coords(cfg, [states.DISCONNECTED])
        if coords is None:
            self._log("Reconnect: no image assigned for disconnected", "WARNING")
            return
        tap(self._serial, coords[0], coords[1])
        self._set_last_action("Tapped Reconnect")

    def _do_leave_tap(self, cfg: DeviceConfig) -> None:
        # Leave button is a separate region on the disconnected screen
        # For now reuse disconnected detector center — Phase 6 will add
        # a dedicated leave_button detector if needed
        coords = self._resolve_tap_coords(cfg, [states.DISCONNECTED])
        if coords is None:
            self._log("Leave: no image assigned for disconnected", "WARNING")
            return
        tap(self._serial, coords[0], coords[1])
        self._set_last_action("Tapped Leave")

    def _resolve_tap_coords(
        self,
        cfg: DeviceConfig,
        detector_names: list[str],
    ) -> Optional[tuple[int, int]]:
        """
        Find tap coordinates by running template match for the first assigned
        detector in detector_names that has a match on the current frame.
        Returns (x, y) center of the match, or None if nothing matched.
        Phase 6 will add caching on top of this.
        """
        if self._last_frame is None:
            return None
        device_overrides = list(cfg.detector_assignments.keys())
        for name in detector_names:
            detector_key = states.to_detector_name(name)
            if detector_key not in device_overrides:
                continue
            result = run_detector_by_name(
                detector_name=detector_key,
                frame_bgr=self._last_frame,
                device_serial=self._serial,
                device_overrides=device_overrides,
                bank=self._bank,
                threshold=DETECTION_THRESHOLD,
            )
            if result.found and result.center:
                assignment = cfg.detector_assignments.get(detector_key)
                if assignment and assignment.tap_offset_x is not None:
                    # Apply tap offset from crop tool
                    bbox_x = result.bbox[0] if result.bbox else result.center[0]
                    bbox_y = result.bbox[1] if result.bbox else result.center[1]
                    return (bbox_x + assignment.tap_offset_x,
                            bbox_y + assignment.tap_offset_y)
                return result.center
        return None

    def _leave_and_rejoin(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._do_leave_tap(cfg)
        time.sleep(3.0)
        join_private_server(self._serial, settings.private_server_link)
        self._reset_lobby_timer()
        self._set_last_action("Left + rejoined (stuck in lobby)")

    # ------------------------------------------------------------------
    # Timer helpers
    # ------------------------------------------------------------------

    def _reset_lobby_timer(self) -> None:
        if self._lobby_entered_at is not None:
            self._lobby_entered_at = None

    def _reset_disconnect_timer(self) -> None:
        if self._disconnect_detected_at is not None:
            self._disconnect_detected_at = None

    def _pause_auto_farm_timer(self) -> None:
        """
        Pause the auto-farm countdown by advancing the last-tap timestamp to now.
        Effect: the countdown restarts from the full interval when back in IN_TANK.
        Only the time spent in IN_TANK counts toward the interval.
        """
        self._last_auto_farm_tap = time.monotonic()

    def _reset_end_run_timer(self) -> None:
        """
        Reset the end-run countdown to zero.
        Called when DEATH_SCREEN, NET_REVEAL, LOBBY, CRASHED, or ROBLOX_HOME
        is detected — the run has already ended naturally so firing end-run
        would be redundant. Fresh countdown starts on return to IN_TANK.
        """
        self._last_end_run_tap = time.monotonic()

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _is_roblox_foreground(self) -> bool:
        """
        Check if Roblox is the active foreground app via ADB.
        Uses dumpsys activity to find the resumed activity.
        Returns True only if com.roblox.client is the foreground app.
        Defaults to True on error to avoid false recovery loops.
        """
        try:
            from config.paths import adb_exe
            result = subprocess.run(
                [adb_exe(), "-s", self._serial, "shell",
                 "dumpsys", "activity", "activities"],
                capture_output=True, timeout=8.0,
            )
            output = result.stdout.decode("utf-8", errors="replace")
            # Look for the resumed activity line
            for line in output.splitlines():
                if "mResumedActivity" in line or "ResumedActivity" in line:
                    is_foreground = "com.roblox.client" in line
                    self._log(
                        f"Roblox {'is' if is_foreground else 'is NOT'} foreground app",
                        "DEBUG" if is_foreground else "WARNING",
                    )
                    return is_foreground
            # No resumed activity line found — assume not foreground
            self._log("Could not determine foreground app", "WARNING")
            return False
        except Exception as e:
            self._log(f"Foreground check failed: {e}", "WARNING")
            return True  # assume foreground on error to avoid false recovery

    def _is_roblox_running(self) -> bool:
        """
        Check if Roblox process exists at all (running or backgrounded).
        Uses ps -A — universally supported on Android.
        """
        try:
            from config.paths import adb_exe
            result = subprocess.run(
                [adb_exe(), "-s", self._serial, "shell",
                 "ps", "-A", "-o", "NAME"],
                capture_output=True, timeout=5.0,
            )
            output = result.stdout.decode("utf-8", errors="replace")
            return "com.roblox.client" in output
        except Exception as e:
            self._log(f"Process check failed: {e}", "WARNING")
            return True

    def _set_last_action(self, action: str) -> None:
        self._last_action = action
        app_logger.debug(
            self._get_settings().debug, "actions",
            f"{self._serial[:8]}: {action}", self._log)

    def _log(self, msg: str, level: str = "INFO") -> None:
        app_logger.log(f"[{self._serial[:8]}] {msg}", level)
