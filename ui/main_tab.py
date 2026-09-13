"""
ui/main_tab.py

Main tab — shows all device cards in a 2-column scrollable grid.
Also owns the global Start All / Stop All toolbar at the top.

Device cards are created once per known device and refreshed in place
on each poll cycle. New devices that appear (from discover_devices) get
a card added dynamically.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from bot.device_manager import DeviceManager
from config.devices import DeviceConfig


class MainTab(ttk.Frame):
    """
    Scrollable 2-column grid of DeviceCard widgets plus a toolbar.
    """

    def __init__(
        self,
        parent,
        manager: DeviceManager,
        get_settings,
        get_devices: Callable[[], dict[str, DeviceConfig]],
        save_devices_fn,
        card_columns: int = 2,
    ):
        super().__init__(parent)
        self._manager = manager
        self._get_settings = get_settings
        self._get_devices = get_devices
        self._save_devices = save_devices_fn
        self._card_columns = card_columns

        # serial → DeviceCard
        self._cards: dict[str, DeviceCard] = {}

        self._build()

    def _build(self) -> None:
        # ---- Toolbar ----
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", padx=12, pady=(10, 6))

        self._status_label = ttk.Label(toolbar, text="No devices running")
        self._status_label.pack(side="left")

        ttk.Button(toolbar, text="Stop all", command=self._stop_all).pack(side="right", padx=(4, 0))
        ttk.Button(toolbar, text="Start all", command=self._start_all).pack(side="right")

        # ---- Scrollable card area ----
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._card_frame = ttk.Frame(canvas)
        self._canvas_window = canvas.create_window((0, 0), window=self._card_frame, anchor="nw")

        self._card_frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        ))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(
            self._canvas_window, width=e.width
        ))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"
        ))

        self._canvas = canvas

    # ------------------------------------------------------------------
    # Toolbar actions
    # ------------------------------------------------------------------

    def _start_all(self) -> None:
        self._manager.start_all()

    def _stop_all(self) -> None:
        self._manager.stop_all()

    # ------------------------------------------------------------------
    # Refresh (called by App poll loop)
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Pull latest status from all workers and update / create cards."""
        all_status = self._manager.get_all_status()
        devices = self._get_devices()

        running_count = sum(1 for s in all_status if s.get("running"))
        total = len(all_status)
        self._status_label.config(
            text=f"{running_count} of {total} devices running" if total else "No devices"
        )

        # Update existing cards or create new ones
        for status in all_status:
            serial = status["serial"]
            if serial not in self._cards:
                self._add_card(serial, devices.get(serial))
            self._cards[serial].update(status)

        # Layout cards in 2-column grid
        for idx, card in enumerate(self._cards.values()):
            row, col = divmod(idx, self._card_columns)
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

        for col in range(self._card_columns):
            self._card_frame.columnconfigure(col, weight=1)

    def _add_card(self, serial: str, cfg: DeviceConfig | None) -> None:
        card = DeviceCard(
            self._card_frame,
            serial=serial,
            manager=self._manager,
            get_devices=self._get_devices,
            save_devices_fn=self._save_devices,
        )
        self._cards[serial] = card


# ---------------------------------------------------------------------------
# DeviceCard
# ---------------------------------------------------------------------------

class DeviceCard(ttk.Frame):
    """
    One card per device. Shows state, timers, toggles, and action buttons.
    Refreshed in place by MainTab.refresh() — no recreation needed.
    """

    # State → border highlight color
    _STATE_COLORS = {
        "IN_TANK":    "#2563eb",  # blue accent
        "LOBBY":      "#d97706",  # amber
        "CRASHED":    "#dc2626",  # red
        "DISCONNECTED": "#dc2626",
        "DEATH_SCREEN": "#6b7280",
        "NET_REVEAL":   "#6b7280",
        "ROBLOX_HOME":  "#6b7280",
        "AUTO_FARM_OFF":"#d97706",
        "UNKNOWN":    "#6b7280",
    }

    _STATE_BADGE_COLORS = {
        "IN_TANK":      ("#16a34a", "#dcfce7"),   # fg, bg
        "LOBBY":        ("#b45309", "#fef3c7"),
        "CRASHED":      ("#dc2626", "#fee2e2"),
        "DISCONNECTED": ("#dc2626", "#fee2e2"),
        "AUTO_FARM_OFF":("#b45309", "#fef3c7"),
        "DEATH_SCREEN": ("#6b7280", "#f3f4f6"),
        "NET_REVEAL":   ("#6b7280", "#f3f4f6"),
        "ROBLOX_HOME":  ("#6b7280", "#f3f4f6"),
        "UNKNOWN":      ("#6b7280", "#f3f4f6"),
    }

    def __init__(
        self,
        parent,
        serial: str,
        manager: DeviceManager,
        get_devices: Callable[[], dict[str, DeviceConfig]],
        save_devices_fn,
    ):
        super().__init__(parent, relief="solid", borderwidth=1, padding=10)
        self._serial = serial
        self._manager = manager
        self._get_devices = get_devices
        self._save_devices = save_devices_fn

        # Toggle vars — bound to checkboxes, saved on change
        self._auto_farm_var   = tk.BooleanVar()
        self._end_run_var     = tk.BooleanVar()
        self._stay_awake_var  = tk.BooleanVar()
        self._lobby_guard_var = tk.BooleanVar()

        for var, attr in [
            (self._auto_farm_var,   "auto_farm_enabled"),
            (self._end_run_var,     "end_run_enabled"),
            (self._stay_awake_var,  "stay_awake_enabled"),
            (self._lobby_guard_var, "stuck_lobby_detection_enabled"),
        ]:
            var.trace_add("write", lambda *_, a=attr, v=var: self._on_toggle(a, v))

        self._build()

    def _build(self) -> None:
        # ---- Header row ----
        header = ttk.Frame(self)
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left")
        self._name_label  = ttk.Label(left, font=("", 12, "bold"))
        self._name_label.pack(anchor="w")
        self._model_label = ttk.Label(left, foreground="#6b7280", font=("", 10))
        self._model_label.pack(anchor="w")

        right = ttk.Frame(header)
        right.pack(side="right")

        top_right = ttk.Frame(right)
        top_right.pack(anchor="e")
        self._state_badge = tk.Label(
            top_right, font=("", 9, "bold"), padx=6, pady=2,
            relief="flat", bd=0
        )
        self._state_badge.pack(side="left", padx=(0, 6))
        self._start_stop_btn = ttk.Button(top_right, width=6, command=self._toggle_worker)
        self._start_stop_btn.pack(side="left")

        self._run_indicator = ttk.Label(right, font=("", 9))
        self._run_indicator.pack(anchor="e", pady=(3, 0))

        # ---- Divider ----
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=6)

        # ---- Timer row (context-aware — rebuilt on each update) ----
        self._timer_frame = ttk.Frame(self)
        self._timer_frame.pack(fill="x")

        # ---- Alert bar (hidden by default) ----
        self._alert_bar = tk.Label(
            self, font=("", 10), padx=6, pady=4, anchor="w",
            relief="flat", bd=0
        )

        # ---- Divider ----
        self._lower_sep = ttk.Separator(self, orient="horizontal")
        self._lower_sep.pack(fill="x", pady=6)

        # ---- Toggles (2-column grid) ----
        toggle_frame = ttk.Frame(self)
        toggle_frame.pack(fill="x")
        toggle_frame.columnconfigure(0, weight=1)
        toggle_frame.columnconfigure(1, weight=1)

        toggles = [
            ("Auto-farm",   self._auto_farm_var),
            ("End run",     self._end_run_var),
            ("Stay awake",  self._stay_awake_var),
            ("Lobby guard", self._lobby_guard_var),
        ]
        for idx, (label, var) in enumerate(toggles):
            row, col = divmod(idx, 2)
            cb = ttk.Checkbutton(toggle_frame, text=label, variable=var)
            cb.grid(row=row, column=col, sticky="w", padx=2, pady=1)

        # ---- Action buttons ----
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=6)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        ttk.Button(btn_row, text="End run", command=self._fire_end_run).grid(
            row=0, column=0, sticky="ew", padx=(0, 3)
        )
        ttk.Button(btn_row, text="Settings", command=self._open_settings).grid(
            row=0, column=1, sticky="ew", padx=(3, 0)
        )

    # ------------------------------------------------------------------
    # Update (called every poll cycle)
    # ------------------------------------------------------------------

    def update(self, status: dict) -> None:
        """Refresh all card fields from the latest worker status dict."""
        cfg = self._get_devices().get(self._serial)

        # Header
        name  = (cfg.nickname if cfg and cfg.nickname else self._serial[:8])
        model = (cfg.model    if cfg and cfg.model    else "")
        self._name_label.config(text=name)
        self._model_label.config(text=model)

        # State badge
        state = status.get("state", "UNKNOWN")
        fg, bg = self._STATE_BADGE_COLORS.get(state, ("#6b7280", "#f3f4f6"))
        self._state_badge.config(text=state, fg=fg, bg=bg)

        # Start/stop button + run indicator
        running = status.get("running", False)
        runtime_s = status.get("runtime_s", 0.0)
        runtime_str = _fmt_runtime(runtime_s)

        if running:
            self._start_stop_btn.config(text="Stop")
            self._run_indicator.config(
                text=f"● Running · {runtime_str}", foreground="#16a34a"
            )
        else:
            self._start_stop_btn.config(text="Start")
            self._run_indicator.config(text="● Off", foreground="#dc2626")

        # Context-aware timer row
        self._rebuild_timers(state, status)

        # Toggles — set without triggering save (suppress trace temporarily)
        if cfg:
            self._auto_farm_var.set(cfg.auto_farm_enabled)
            self._end_run_var.set(cfg.end_run_enabled)
            self._stay_awake_var.set(cfg.stay_awake_enabled)
            self._lobby_guard_var.set(cfg.stuck_lobby_detection_enabled)

    def _rebuild_timers(self, state: str, status: dict) -> None:
        """Rebuild the timer row to match the current state context."""
        for w in self._timer_frame.winfo_children():
            w.destroy()
        self._alert_bar.pack_forget()

        if state == "IN_TANK" or state == "AUTO_FARM_OFF":
            af = status.get("auto_farm_countdown_s", 0.0)
            er = status.get("end_run_countdown_s", 0.0)
            _timer_col(self._timer_frame, "Auto-farm", _fmt_secs(af))
            _timer_col(self._timer_frame, "End run",   _fmt_secs(er), warn=er < 60)

        elif state == "LOBBY":
            stuck_cd = status.get("lobby_stuck_countdown_s", 0.0)
            time_in  = status.get("time_in_lobby_s", 0.0)
            _timer_col(self._timer_frame, "Stuck timer", _fmt_secs(stuck_cd), warn=True)
            _timer_col(self._timer_frame, "In lobby",    _fmt_secs(time_in),  warn=True)
            self._alert_bar.config(
                text=f"Leaving and rejoining in {_fmt_secs(stuck_cd)}",
                fg="#b45309", bg="#fef3c7"
            )
            self._alert_bar.pack(fill="x", pady=(4, 0))

        elif state in ("CRASHED", "DISCONNECTED"):
            self._alert_bar.config(
                text="Recovering — launching Roblox and rejoining"
                     if state == "CRASHED" else "Disconnected — attempting reconnect",
                fg="#dc2626", bg="#fee2e2"
            )
            self._alert_bar.pack(fill="x", pady=(4, 0))

        else:
            # DEATH_SCREEN, NET_REVEAL, ROBLOX_HOME, UNKNOWN — show nothing
            pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _toggle_worker(self) -> None:
        status = self._manager.get_status(self._serial)
        if status and status.get("running"):
            self._manager.stop_device(self._serial)
        else:
            self._manager.start_device(self._serial)

    def _fire_end_run(self) -> None:
        self._manager.force_end_run(self._serial)

    def _open_settings(self) -> None:
        from ui.device_settings_dialog import DeviceSettingsDialog
        devices = self._get_devices()
        cfg = devices.get(self._serial, None)
        if cfg is None:
            return
        dialog = DeviceSettingsDialog(self, cfg=cfg)
        self.wait_window(dialog)
        if dialog.result:
            devices[self._serial] = dialog.result
            self._save_devices(devices)

    def _on_toggle(self, attr: str, var: tk.BooleanVar) -> None:
        """Save a toggle change immediately to devices.json."""
        devices = self._get_devices()
        cfg = devices.get(self._serial)
        if cfg is None:
            return
        setattr(cfg, attr, var.get())
        self._save_devices(devices)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_secs(s: float) -> str:
    """Format a seconds value as '43s' or '1m 28s'."""
    s = max(0.0, s)
    m, sec = divmod(int(s), 60)
    return f"{m}m {sec}s" if m else f"{sec}s"


def _fmt_runtime(s: float) -> str:
    """Format runtime as '2h 14m' or '43m' or '12s'."""
    s = max(0.0, s)
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m"
    return f"{sec}s"


def _timer_col(parent, label: str, value: str, warn: bool = False) -> None:
    """Add a label+value column to the timer row."""
    col = ttk.Frame(parent)
    col.pack(side="left", padx=(0, 16))
    ttk.Label(col, text=label, font=("", 9), foreground="#6b7280").pack(anchor="w")
    fg = "#d97706" if warn else None
    lbl = ttk.Label(col, text=value, font=("", 12, "bold"))
    if fg:
        lbl.config(foreground=fg)
    lbl.pack(anchor="w")
