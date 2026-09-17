"""
ui/main_tab.py

Main tab — 2-column device card grid + resizable debug panel at the bottom.

Card layout (top to bottom):
  - Header: device name/model left, run-badge + runtime right
  - Separator
  - Status+alert row: state badge (1/3) | alert message (2/3)
  - Toggle grid: 4 columns — [cb label] [timer] [cb label] [timer]
  - Button row: Start/Stop | End run | Settings

Non-blocking start/stop:
  DeviceCard._toggle_worker() dispatches start_device / stop_device to a
  background thread and immediately updates the alert label to "Starting…"
  or "Stopping…". The next poll cycle picks up the real state and clears it.
  The app never freezes waiting for scrcpy to connect or the worker to join.

  If the worker fails to start (e.g. scrcpy backend error), running never
  becomes True. resync() detects this via a timestamp set when pending was
  entered: if "Starting…" is still pending after settings.start_timeout_s
  seconds with running still False, the pending state is cleared, the button
  is re-enabled, and the alert label is set to "Start failed" in red so the
  problem is immediately visible on the card.

ADB state:
  Status snapshots include adb_connected. A stopped phone whose USB/ADB
  transport has dropped is shown as ADB DISCONNECTED rather than looking like
  a normal ready-to-start stopped card, and Start remains disabled until ADB
  sees the serial again.

Timer smoothness:
  Each card maintains local countdown variables that tick every second via
  Tkinter after(). The worker poll (every loop_interval_s) resyncs the
  local values. This gives smooth per-second display without flashing from
  full card rebuilds, and tolerates 1-2s drift between display and reality.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from tkinter import ttk
from typing import Callable
from datetime import datetime

from bot.device_manager import DeviceManager
from config.devices import DeviceConfig
from config.settings import Settings

CARD_COLUMNS    = 2
PANEL_DEFAULT_H = 150
PANEL_MIN_H     = 60

_STATE_COLORS: dict[str, tuple[str, str]] = {
    "IN_TANK":                 ("#166534", "#dcfce7"),
    "LOBBY":                   ("#92400e", "#fef3c7"),
    "CRASHED":                 ("#991b1b", "#fee2e2"),
    "DISCONNECTED":            ("#991b1b", "#fee2e2"),
    "ADB_DISCONNECTED":        ("#991b1b", "#fee2e2"),
    "AUTO_FARM_OFF":           ("#92400e", "#fef3c7"),
    "DEATH_SCREEN":            ("#374151", "#f3f4f6"),
    "NET_REVEAL":              ("#374151", "#f3f4f6"),
    "ROBLOX_HOME":             ("#374151", "#f3f4f6"),
    "FRIEND_CARD":             ("#374151", "#f3f4f6"),
    "HAMBURGER_MENU_OPEN":     ("#374151", "#f3f4f6"),
    "CONTINUE_PLAYING_BUTTON": ("#374151", "#f3f4f6"),
    "GAME_PAGE":               ("#374151", "#f3f4f6"),
    "GAME_PAGE_SCROLLED":      ("#374151", "#f3f4f6"),
    "SERVER_LIST":             ("#374151", "#f3f4f6"),
    "UNKNOWN":                 ("#374151", "#f3f4f6"),
    "OFF":                     ("#9ca3af", "#f3f4f6"),
}

_ALERT: dict[str, tuple[str, str, str]] = {
    "CRASHED":      ("Recovering — launching Roblox",      "#991b1b", "#fee2e2"),
    "DISCONNECTED": ("Disconnected — attempting reconnect", "#991b1b", "#fee2e2"),
}

_ALERT_EMPTY_FG   = "#9ca3af"
_ALERT_EMPTY_BG   = "#f3f4f6"
_ALERT_PENDING_FG = "#1d4ed8"
_ALERT_PENDING_BG = "#dbeafe"
_ALERT_FAILED_FG  = "#991b1b"
_ALERT_FAILED_BG  = "#fee2e2"


def _fmt_secs(s: float) -> str:
    s = max(0.0, s)
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec}s" if m else f"{sec}s"


def _fmt_runtime(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(int(s), 3600)
    m, _ = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{int(s)}s"


class MainTab(ttk.Frame):

    def __init__(
        self,
        parent,
        manager: DeviceManager,
        get_settings: Callable[[], Settings],
        get_devices: Callable[[], dict[str, DeviceConfig]],
        save_devices_fn: Callable,
        card_columns: int = CARD_COLUMNS,
    ):
        super().__init__(parent)
        self._manager = manager
        self._get_settings = get_settings
        self._get_devices = get_devices
        self._save_devices = save_devices_fn
        self._card_columns = card_columns
        self._cards: dict[str, "DeviceCard"] = {}
        self._panel_visible = False
        self._build()

    def _build(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self._paned = tk.PanedWindow(
            self, orient="vertical", sashwidth=5,
            sashrelief="flat", bg="#d1d5db",
        )
        self._paned.grid(row=0, column=0, sticky="nsew")

        card_outer = ttk.Frame(self._paned)
        self._paned.add(card_outer, stretch="always")

        toolbar = ttk.Frame(card_outer)
        toolbar.pack(fill="x", padx=12, pady=(10, 6))
        self._status_label = ttk.Label(toolbar, text="No devices")
        self._status_label.pack(side="left")
        ttk.Button(toolbar, text="Stop all",
                   command=self._stop_all).pack(side="right", padx=(4, 0))
        ttk.Button(toolbar, text="Start all",
                   command=self._start_all).pack(side="right")

        canvas_container = ttk.Frame(card_outer)
        canvas_container.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            canvas_container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._card_frame = ttk.Frame(canvas)
        self._canvas_window = canvas.create_window(
            (0, 0), window=self._card_frame, anchor="nw")
        self._card_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._canvas_window, width=e.width))
        from ui.scroll_utils import bind_mousewheel
        bind_mousewheel(canvas)
        self._canvas = canvas

        self._panel_frame = ttk.Frame(self._paned)

        panel_header = ttk.Frame(self._panel_frame)
        panel_header.pack(fill="x", padx=8, pady=(4, 2))
        ttk.Label(panel_header, text="Debug panel", font=("", 9, "bold"),
                  foreground="#888").pack(side="left")
        ttk.Button(panel_header, text="Clear", width=6,
                   command=self._clear_panel).pack(side="right")

        self._log_text = tk.Text(
            self._panel_frame, height=8, wrap="none",
            bg="#111827", fg="#d1d5db", font=("Courier", 9),
            state="disabled", relief="flat", highlightthickness=0,
        )
        self._log_text.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        h_scroll = ttk.Scrollbar(
            self._panel_frame, orient="horizontal",
            command=self._log_text.xview)
        h_scroll.pack(fill="x", padx=4)
        self._log_text.configure(xscrollcommand=h_scroll.set)

        self._log_text.tag_configure("DEBUG",    foreground="#6b7280")
        self._log_text.tag_configure("INFO",     foreground="#d1d5db")
        self._log_text.tag_configure("WARNING",  foreground="#f59e0b")
        self._log_text.tag_configure("ERROR",    foreground="#ef4444")
        self._log_text.tag_configure("CRITICAL", foreground="#dc2626",
                                     font=("Courier", 9, "bold"))

    def append_log(self, msg: str, level: str) -> None:
        self.after(0, lambda m=msg, l=level: self._do_append(m, l))

    def _do_append(self, msg: str, level: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        self._log_text.configure(state="normal")
        self._log_text.insert("end", line, level.upper())
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_panel(self) -> None:
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def set_panel_visible(self, visible: bool) -> None:
        if visible == self._panel_visible:
            return
        self._panel_visible = visible
        if visible:
            self._paned.add(self._panel_frame, minsize=PANEL_MIN_H,
                            height=PANEL_DEFAULT_H, stretch="never")
        else:
            try:
                self._paned.remove(self._panel_frame)
            except Exception:
                pass

    def _start_all(self) -> None:
        threading.Thread(
            target=self._manager.start_all, daemon=True).start()
        for card in self._cards.values():
            card.set_pending("Starting…")

    def _stop_all(self) -> None:
        threading.Thread(
            target=self._manager.stop_all, daemon=True).start()
        for card in self._cards.values():
            card.set_pending("Stopping…")

    def refresh(self) -> None:
        all_status = self._manager.get_all_status()
        devices = self._get_devices()
        settings = self._get_settings()

        running = sum(1 for s in all_status if s.get("running"))
        total = len(all_status)
        self._status_label.config(
            text=f"{running} of {total} devices running" if total
            else "No devices"
        )

        for status in all_status:
            serial = status["serial"]
            if serial not in self._cards:
                card = DeviceCard(
                    self._card_frame,
                    serial=serial,
                    manager=self._manager,
                    get_devices=self._get_devices,
                    save_devices_fn=self._save_devices,
                )
                self._cards[serial] = card
            self._cards[serial].resync(status, settings)

        for idx, card in enumerate(self._cards.values()):
            row, col = divmod(idx, self._card_columns)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        for col in range(self._card_columns):
            self._card_frame.columnconfigure(col, weight=1)

        self.set_panel_visible(settings.development_mode)


class DeviceCard(ttk.Frame):
    """One card per device."""

    def __init__(self, parent, serial, manager, get_devices, save_devices_fn):
        super().__init__(parent, relief="solid", borderwidth=1, padding=10)
        self._serial = serial
        self._manager = manager
        self._get_devices = get_devices
        self._save_devices = save_devices_fn

        self._af_secs: float    = 0.0
        self._er_secs: float    = 0.0
        self._sa_secs: float    = 0.0
        self._lobby_secs: float = 0.0
        self._is_running: bool  = False
        self._current_state: str = ""
        self._pending: str = ""
        self._pending_since: float = 0.0
        self._start_failed: bool = False
        self._tick_job = None

        self._auto_farm_var   = tk.BooleanVar()
        self._end_run_var     = tk.BooleanVar()
        self._stay_awake_var  = tk.BooleanVar()
        self._lobby_guard_var = tk.BooleanVar()
        self._suppress_toggle = False

        for var, attr in [
            (self._auto_farm_var,   "auto_farm_enabled"),
            (self._end_run_var,     "end_run_enabled"),
            (self._stay_awake_var,  "stay_awake_enabled"),
            (self._lobby_guard_var, "stuck_lobby_detection_enabled"),
        ]:
            var.trace_add("write",
                          lambda *_, a=attr, v=var: self._on_toggle(a, v))

        self._build()
        self._start_tick()

    def _build(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left")
        self._name_label  = ttk.Label(left, font=("", 12, "bold"))
        self._name_label.pack(anchor="w")
        self._model_label = ttk.Label(left, foreground="#6b7280", font=("", 9))
        self._model_label.pack(anchor="w")

        right = ttk.Frame(header)
        right.pack(side="right")
        self._run_badge = tk.Label(
            right, font=("", 9, "bold"), padx=6, pady=2, relief="flat")
        self._run_badge.pack(anchor="e")
        self._runtime_label = ttk.Label(right, font=("", 9), foreground="#6b7280")
        self._runtime_label.pack(anchor="e", pady=(2, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(8, 6))

        sa_row = tk.Frame(self)
        sa_row.pack(fill="x", pady=(0, 6))
        self._state_badge = tk.Label(
            sa_row, font=("", 9, "bold"), padx=6, pady=3,
            relief="flat", anchor="center", width=14,
        )
        self._state_badge.pack(side="left")
        self._alert_label = tk.Label(
            sa_row, font=("", 9), padx=6, pady=3, relief="flat",
            anchor="w", text="", fg=_ALERT_EMPTY_FG, bg=_ALERT_EMPTY_BG,
        )
        self._alert_label.pack(side="left", fill="x", expand=True)

        tg = ttk.Frame(self)
        tg.pack(fill="x", pady=(0, 4))
        tg.columnconfigure(0, weight=1)
        tg.columnconfigure(2, weight=1)

        ttk.Checkbutton(tg, text="Auto-farm",
                        variable=self._auto_farm_var).grid(
            row=0, column=0, sticky="w", pady=2)
        self._af_lbl = ttk.Label(tg, font=("", 9, "bold"), width=7, anchor="e")
        self._af_lbl.grid(row=0, column=1, sticky="e", padx=(0, 10), pady=2)

        ttk.Checkbutton(tg, text="End run",
                        variable=self._end_run_var).grid(
            row=0, column=2, sticky="w", pady=2)
        self._er_lbl = ttk.Label(tg, font=("", 9, "bold"), width=7, anchor="e")
        self._er_lbl.grid(row=0, column=3, sticky="e", pady=2)

        ttk.Checkbutton(tg, text="Stay awake",
                        variable=self._stay_awake_var).grid(
            row=1, column=0, sticky="w", pady=2)
        self._sa_lbl = ttk.Label(tg, font=("", 9, "bold"), width=7, anchor="e")
        self._sa_lbl.grid(row=1, column=1, sticky="e", padx=(0, 10), pady=2)

        ttk.Checkbutton(tg, text="Lobby guard",
                        variable=self._lobby_guard_var).grid(
            row=1, column=2, sticky="w", pady=2)
        self._lg_lbl = ttk.Label(tg, font=("", 9, "bold"), width=7, anchor="e")
        self._lg_lbl.grid(row=1, column=3, sticky="e", pady=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=6)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)
        btn_row.columnconfigure(2, weight=1)
        self._start_stop_btn = ttk.Button(
            btn_row, text="Start", command=self._toggle_worker)
        self._start_stop_btn.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        ttk.Button(btn_row, text="End run",
                   command=self._fire_end_run).grid(
            row=0, column=1, sticky="ew", padx=3)
        ttk.Button(btn_row, text="Settings",
                   command=self._open_settings).grid(
            row=0, column=2, sticky="ew", padx=(3, 0))

    def set_pending(self, msg: str) -> None:
        self._pending = msg
        self._pending_since = time.monotonic()
        self._start_failed = False
        self._alert_label.config(
            text=msg, fg=_ALERT_PENDING_FG, bg=_ALERT_PENDING_BG)
        self._start_stop_btn.config(state="disabled")

    def _clear_pending(self) -> None:
        self._pending = ""
        self._pending_since = 0.0
        self._start_stop_btn.config(state="normal")

    def _set_start_failed(self) -> None:
        self._start_failed = True
        self._clear_pending()
        self._alert_label.config(
            text="Start failed", fg=_ALERT_FAILED_FG, bg=_ALERT_FAILED_BG)

    def _start_tick(self) -> None:
        self._tick_job = self.after(1000, self._tick)

    def _tick(self) -> None:
        if self._is_running:
            state = self._current_state
            if state in ("IN_TANK", "AUTO_FARM_OFF"):
                self._af_secs = max(0.0, self._af_secs - 1)
                self._er_secs = max(0.0, self._er_secs - 1)
                self._sa_secs = max(0.0, self._sa_secs - 1)
            elif state == "LOBBY":
                self._lobby_secs += 1
                self._sa_secs = max(0.0, self._sa_secs - 1)
            self._refresh_timer_labels()
        self._tick_job = self.after(1000, self._tick)

    def _refresh_timer_labels(self) -> None:
        state   = self._current_state
        running = self._is_running

        cfg = self._get_devices().get(self._serial)
        sa_enabled = cfg.stay_awake_enabled if cfg else True
        lg_enabled = cfg.stuck_lobby_detection_enabled if cfg else True

        MUTED  = "#9ca3af"
        NORMAL = "#111827"
        WARN   = "#d97706"

        def _set(lbl, text, color):
            lbl.config(text=text, foreground=color)

        if not running or state not in ("IN_TANK", "AUTO_FARM_OFF", "LOBBY"):
            for lbl in (self._af_lbl, self._er_lbl,
                        self._sa_lbl, self._lg_lbl):
                _set(lbl, "—", MUTED)
            return

        if state in ("IN_TANK", "AUTO_FARM_OFF"):
            _set(self._af_lbl, _fmt_secs(self._af_secs), NORMAL)
            _set(self._er_lbl, _fmt_secs(self._er_secs),
                 WARN if self._er_secs < 60 else NORMAL)
            _set(self._sa_lbl,
                 _fmt_secs(self._sa_secs) if sa_enabled else "—",
                 NORMAL if sa_enabled else MUTED)
            _set(self._lg_lbl, "—", MUTED)

        elif state == "LOBBY":
            _set(self._af_lbl, "—", MUTED)
            _set(self._er_lbl, "—", MUTED)
            _set(self._sa_lbl,
                 _fmt_secs(self._sa_secs) if sa_enabled else "—",
                 NORMAL if sa_enabled else MUTED)
            if lg_enabled:
                _set(self._lg_lbl, _fmt_secs(self._lobby_secs),
                     WARN if self._lobby_secs > 30 else NORMAL)
                if not self._pending and not self._start_failed:
                    self._alert_label.config(
                        text=f"In lobby for {_fmt_secs(self._lobby_secs)}",
                        fg="#92400e", bg="#fef3c7")
            else:
                _set(self._lg_lbl, "—", MUTED)

    def resync(self, status: dict, settings: Settings) -> None:
        cfg = self._get_devices().get(self._serial)
        name  = cfg.nickname if cfg and cfg.nickname else self._serial[:8]
        model = cfg.model    if cfg and cfg.model    else self._serial
        self._name_label.config(text=name)
        self._model_label.config(text=model)

        running = status.get("running", False)
        state   = status.get("state", "UNKNOWN")
        runtime = status.get("runtime_s", 0.0)
        adb_connected = status.get("adb_connected", True)

        if self._pending == "Starting…" and running:
            self._start_failed = False
            self._clear_pending()
        elif self._pending == "Stopping…" and not running:
            self._clear_pending()

        if (
            self._pending == "Starting…"
            and not running
            and self._pending_since > 0
            and (time.monotonic() - self._pending_since) >= settings.start_timeout_s
        ):
            self._set_start_failed()

        if running:
            self._run_badge.config(text="● Running", fg="#166534", bg="#dcfce7")
            self._runtime_label.config(text=_fmt_runtime(runtime))
            self._start_stop_btn.config(
                text="Stop",
                state="normal" if not self._pending else "disabled")
        elif not adb_connected:
            self._run_badge.config(text="● ADB Offline", fg="#991b1b", bg="#fee2e2")
            self._runtime_label.config(text="")
            self._start_stop_btn.config(text="Start", state="disabled")
        else:
            self._run_badge.config(text="● Stopped", fg="#991b1b", bg="#fee2e2")
            self._runtime_label.config(text="")
            self._start_stop_btn.config(
                text="Start",
                state="normal" if not self._pending else "disabled")

        self._is_running = running

        display_state = state if running else ("ADB_DISCONNECTED" if not adb_connected else "OFF")
        fg, bg = _STATE_COLORS.get(display_state, ("#374151", "#f3f4f6"))
        self._state_badge.config(text=display_state, fg=fg, bg=bg)

        if not self._pending and not self._start_failed:
            alert = _ALERT.get(state) if running else None
            if not running and not adb_connected:
                self._alert_label.config(
                    text="USB/ADB disconnected", fg="#991b1b", bg="#fee2e2")
            elif state == "LOBBY" and running:
                self._alert_label.config(fg="#92400e", bg="#fef3c7")
            elif alert:
                self._alert_label.config(
                    text=alert[0], fg=alert[1], bg=alert[2])
            else:
                self._alert_label.config(
                    text="", fg=_ALERT_EMPTY_FG, bg=_ALERT_EMPTY_BG)

        if self._start_failed and running:
            self._start_failed = False
            self._alert_label.config(
                text="", fg=_ALERT_EMPTY_FG, bg=_ALERT_EMPTY_BG)

        if running:
            self._af_secs    = status.get("auto_farm_countdown_s",  self._af_secs)
            self._er_secs    = status.get("end_run_countdown_s",     self._er_secs)
            self._sa_secs    = status.get("stay_awake_countdown_s",  self._sa_secs)
            self._lobby_secs = status.get("time_in_lobby_s",         self._lobby_secs)
        else:
            self._af_secs = self._er_secs = self._sa_secs = self._lobby_secs = 0.0

        self._current_state = state
        self._refresh_timer_labels()

        if cfg:
            self._suppress_toggle = True
            self._auto_farm_var.set(cfg.auto_farm_enabled)
            self._end_run_var.set(cfg.end_run_enabled)
            self._stay_awake_var.set(cfg.stay_awake_enabled)
            self._lobby_guard_var.set(cfg.stuck_lobby_detection_enabled)
            self._suppress_toggle = False

    def _toggle_worker(self) -> None:
        if self._is_running:
            self.set_pending("Stopping…")
            threading.Thread(
                target=self._manager.stop_device,
                args=(self._serial,),
                daemon=True,
            ).start()
        else:
            self.set_pending("Starting…")
            threading.Thread(
                target=self._manager.start_device,
                args=(self._serial,),
                daemon=True,
            ).start()

    def _fire_end_run(self) -> None:
        self._manager.force_end_run(self._serial)

    def _open_settings(self) -> None:
        from ui.device_settings_dialog import DeviceSettingsDialog
        devices = self._get_devices()
        cfg = devices.get(self._serial)
        if not cfg:
            return
        dialog = DeviceSettingsDialog(self, cfg=cfg)
        self.wait_window(dialog)
        if dialog.result:
            devices[self._serial] = dialog.result
            self._save_devices(devices)

    def _on_toggle(self, attr: str, var: tk.BooleanVar) -> None:
        if self._suppress_toggle:
            return
        devices = self._get_devices()
        cfg = devices.get(self._serial)
        if not cfg:
            return
        setattr(cfg, attr, var.get())
        self._save_devices(devices)
