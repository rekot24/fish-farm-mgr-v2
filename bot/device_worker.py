"""
bot/device_worker.py

The main loop for a single device. One DeviceWorker per connected phone.

Loop:
  1. Capture a frame from the device
  2. Run all detectors against the frame
  3. Resolve the current state (simple priority-ordered if/elif)
  4. Take the appropriate action for that state
  5. Sleep for loop_interval_s
  6. Repeat

State resolution priority (highest to lowest):
  DISCONNECTED > CRASHED > ROBLOX_HOME > LOBBY > AUTO_FARM_OFF >
  DEATH_SCREEN > NET_REVEAL > IN_TANK > UNKNOWN

Timers:
  - auto_farm: fires a double-tap at the auto-farm button on interval
  - end_run: fires a tap at the end-run button on interval
  - stay_awake: fires a tap at (1,1) on interval
  - lobby_timer: tracks time spent in LOBBY; triggers leave+rejoin if stuck
  - disconnect_timer: tracks time on DISCONNECTED screen; triggers Leave if exceeded
"""

from __future__ import annotations

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


# ---------------------------------------------------------------------------
# Detector names — all states the worker checks each cycle
# ---------------------------------------------------------------------------

# Ordered from most-specific / highest-priority to least.
# The first detector that fires wins the state resolution.
_DETECTOR_PRIORITY = [
    states.DISCONNECTED,
    states.CRASHED,
    states.ROBLOX_HOME,
    states.LOBBY,
    states.AUTO_FARM_OFF,
    states.DEATH_SCREEN,
    states.NET_REVEAL,
    states.IN_TANK,
]


class DeviceWorker:
    """
    Manages the capture-detect-act loop for one Android device.

    Created and owned by DeviceManager. The UI interacts with this
    worker only through DeviceManager.get_status() — never directly.
    """

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

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # State
        self._current_state: str = states.UNKNOWN
        self._last_action: str = "None"
        self._running: bool = False
        self._start_time: Optional[float] = None

        # Timers — all tracked as "time of last fire" (monotonic seconds)
        self._last_auto_farm_tap: float = 0.0
        self._last_end_run_tap: float = 0.0
        self._last_stay_awake_tap: float = 0.0

        # Lobby stuck timer — set when LOBBY is first detected
        self._lobby_entered_at: Optional[float] = None

        # Disconnect timer — set when DISCONNECTED is first detected
        self._disconnect_detected_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public interface (called by DeviceManager only)
    # ------------------------------------------------------------------

    @property
    def serial(self) -> str:
        return self._serial

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        if self._running:
            self._log("start() called but worker is already running", "WARNING")
            return
        self._stop_event.clear()
        self._start_time = time.monotonic()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"worker-{self._serial[:8]}",
        )
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
        elapsed_end = now - self._last_end_run_tap
        return {
            "serial": self._serial,
            "nickname": cfg.nickname,
            "model": cfg.model,
            "account": cfg.account,
            "running": self._running,
            "state": self._current_state,
            "last_action": self._last_action,
            "runtime_s": (now - self._start_time) if self._start_time else 0.0,
            "auto_farm_countdown_s": max(0.0, cfg.auto_farm_interval_s - elapsed_auto),
            "end_run_countdown_s": max(0.0, cfg.end_run_interval_s - elapsed_end),
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
                    self._log("Frame capture returned None — skipping cycle", "WARNING")
                    time.sleep(settings.loop_interval_s)
                    continue

                detected_state = self._resolve_state(frame, cfg, settings)
                self._act(detected_state, cfg, settings)
                time.sleep(settings.loop_interval_s)

            except Exception as e:
                self._log(
                    f"Unhandled error in worker loop: {type(e).__name__}: {e}", "ERROR"
                )
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
                detector_name=detector_name,
                frame_bgr=frame,
                device_serial=self._serial,
                device_overrides=device_overrides,
                bank=self._bank,
                threshold=DETECTION_THRESHOLD,
            )
            if result.found:
                app_logger.debug(
                    settings.debug,
                    "detections",
                    f"{self._serial[:8]} detected {detector_name} (score={result.score:.3f})",
                    self._log,
                )
                if detector_name != self._current_state:
                    self._log(
                        f"State: {self._current_state} → {detector_name} "
                        f"(score={result.score:.3f})",
                        "INFO",
                    )
                    self._current_state = detector_name
                return detector_name

        if self._current_state != states.UNKNOWN:
            self._log(f"State: {self._current_state} → {states.UNKNOWN}", "INFO")
            self._current_state = states.UNKNOWN
        return states.UNKNOWN

    # ------------------------------------------------------------------
    # Action dispatch
    # ------------------------------------------------------------------

    def _act(self, state: str, cfg: DeviceConfig, settings: Settings) -> None:
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
        elif state == states.DEATH_SCREEN:
            self._reset_lobby_timer()
            self._reset_disconnect_timer()
        elif state == states.NET_REVEAL:
            self._reset_lobby_timer()
            self._reset_disconnect_timer()
        elif state == states.IN_TANK:
            self._handle_in_tank(cfg, settings)
        else:
            self._reset_lobby_timer()
            self._reset_disconnect_timer()

    # ------------------------------------------------------------------
    # State handlers
    # ------------------------------------------------------------------

    def _handle_in_tank(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        self._reset_disconnect_timer()
        now = time.monotonic()

        if cfg.stay_awake_enabled:
            if now - self._last_stay_awake_tap >= cfg.stay_awake_interval_s:
                stay_awake_tap(self._serial)
                self._last_stay_awake_tap = now
                self._set_last_action("Stay-awake tap")

        if cfg.auto_farm_enabled:
            if now - self._last_auto_farm_tap >= cfg.auto_farm_interval_s:
                self._do_auto_farm_double_click(cfg, settings)

        if cfg.end_run_enabled:
            if now - self._last_end_run_tap >= cfg.end_run_interval_s:
                self._do_end_run(cfg, settings)

    def _handle_lobby(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_disconnect_timer()
        now = time.monotonic()

        if self._lobby_entered_at is None:
            self._lobby_entered_at = now
            self._log("Entered lobby — starting stuck timer", "INFO")

        if cfg.stay_awake_enabled:
            if now - self._last_stay_awake_tap >= cfg.stay_awake_interval_s:
                stay_awake_tap(self._serial)
                self._last_stay_awake_tap = now
                self._set_last_action("Stay-awake tap (lobby)")

        if cfg.stuck_lobby_detection_enabled:
            time_in_lobby = now - self._lobby_entered_at
            if time_in_lobby >= settings.lobby_stuck_threshold_s:
                self._log(
                    f"Stuck in lobby for {time_in_lobby:.0f}s — leaving and rejoining",
                    "WARNING",
                )
                self._leave_and_rejoin(cfg, settings)

    def _handle_auto_farm_off(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_disconnect_timer()
        auto_farm_x = getattr(cfg, "auto_farm_tap_x", None)
        auto_farm_y = getattr(cfg, "auto_farm_tap_y", None)
        if auto_farm_x is None or auto_farm_y is None:
            self._log(
                "AUTO_FARM_OFF detected but auto_farm_tap_x/y not set in device config.",
                "WARNING",
            )
            return
        self._log("Auto-farm is OFF — tapping to re-enable", "INFO")
        tap(self._serial, auto_farm_x, auto_farm_y)
        self._set_last_action("Re-enabled auto-farm")

    def _handle_disconnected(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        now = time.monotonic()

        if self._disconnect_detected_at is None:
            self._disconnect_detected_at = now
            self._log("Disconnected dialog detected — tapping Reconnect", "INFO")
            reconnect_x = getattr(cfg, "reconnect_tap_x", None)
            reconnect_y = getattr(cfg, "reconnect_tap_y", None)
            if reconnect_x is None or reconnect_y is None:
                self._log("reconnect_tap_x/y not set in device config.", "WARNING")
                return
            tap(self._serial, reconnect_x, reconnect_y)
            self._set_last_action("Tapped Reconnect")
            return

        time_disconnected = now - self._disconnect_detected_at
        if time_disconnected >= settings.disconnect_timeout_s:
            self._log(
                f"Reconnect failed after {time_disconnected:.0f}s — tapping Leave",
                "WARNING",
            )
            leave_x = getattr(cfg, "leave_tap_x", None)
            leave_y = getattr(cfg, "leave_tap_y", None)
            if leave_x is None or leave_y is None:
                self._log("leave_tap_x/y not set in device config.", "WARNING")
                return
            tap(self._serial, leave_x, leave_y)
            self._set_last_action("Tapped Leave (reconnect timeout)")
            self._reset_disconnect_timer()

    def _handle_crashed(self, cfg: DeviceConfig, settings: Settings) -> None:
        self._reset_lobby_timer()
        self._reset_disconnect_timer()
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
        self._log("At Roblox home screen — joining private server", "INFO")
        join_private_server(self._serial, settings.private_server_link)
        self._set_last_action("Joined private server from home screen")

    # ------------------------------------------------------------------
    # Shared action helpers
    # ------------------------------------------------------------------

    def _do_auto_farm_double_click(self, cfg: DeviceConfig, settings: Settings) -> None:
        auto_farm_x = getattr(cfg, "auto_farm_tap_x", None)
        auto_farm_y = getattr(cfg, "auto_farm_tap_y", None)
        if auto_farm_x is None or auto_farm_y is None:
            self._log(
                "Auto-farm interval elapsed but auto_farm_tap_x/y not set.", "WARNING"
            )
            return
        self._log("Auto-farm interval elapsed — double-clicking", "INFO")
        double_tap(
            self._serial, auto_farm_x, auto_farm_y,
            delay_s=settings.double_click_delay_s,
        )
        self._last_auto_farm_tap = time.monotonic()
        self._set_last_action("Auto-farm double-click")

    def _do_end_run(self, cfg: DeviceConfig, settings: Settings) -> None:
        end_run_x = getattr(cfg, "end_run_tap_x", None)
        end_run_y = getattr(cfg, "end_run_tap_y", None)
        if end_run_x is None or end_run_y is None:
            self._log(
                "End-run interval elapsed but end_run_tap_x/y not set.", "WARNING"
            )
            return
        self._log("End-run tap firing", "INFO")
        tap(self._serial, end_run_x, end_run_y)
        self._last_end_run_tap = time.monotonic()
        self._set_last_action("End-run tap")

    def _leave_and_rejoin(self, cfg: DeviceConfig, settings: Settings) -> None:
        leave_x = getattr(cfg, "leave_tap_x", None)
        leave_y = getattr(cfg, "leave_tap_y", None)
        if leave_x is None or leave_y is None:
            self._log(
                "Stuck-in-lobby recovery: leave_tap_x/y not set.", "WARNING"
            )
            return
        tap(self._serial, leave_x, leave_y)
        time.sleep(3.0)
        join_private_server(self._serial, settings.private_server_link)
        self._reset_lobby_timer()
        self._set_last_action("Left + rejoined private server (stuck in lobby)")

    # ------------------------------------------------------------------
    # Timer helpers
    # ------------------------------------------------------------------

    def _reset_lobby_timer(self) -> None:
        if self._lobby_entered_at is not None:
            self._lobby_entered_at = None

    def _reset_disconnect_timer(self) -> None:
        if self._disconnect_detected_at is not None:
            self._disconnect_detected_at = None

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------

    def _set_last_action(self, action: str) -> None:
        self._last_action = action
        app_logger.debug(
            self._get_settings().debug,
            "actions",
            f"{self._serial[:8]}: {action}",
            self._log,
        )

    def _log(self, msg: str, level: str = "INFO") -> None:
        app_logger.log(f"[{self._serial[:8]}] {msg}", level)
