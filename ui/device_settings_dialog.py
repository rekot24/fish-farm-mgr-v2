"""
ui/device_settings_dialog.py

Per-device settings dialog. Opened from the Settings button on each device card.
Covers: identity (nickname, model, account, ADB serial) and tap coordinates.
Toggles are on the device card itself, not here.
Timer intervals are also here since they need numeric input.

Result is stored in self.result (a DeviceConfig) after the user clicks Save.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import replace

from config.devices import DeviceConfig


class DeviceSettingsDialog(tk.Toplevel):
    """
    Modal dialog for per-device settings.

    Usage:
        dialog = DeviceSettingsDialog(parent, cfg=cfg)
        parent.wait_window(dialog)
        if dialog.result:
            # use dialog.result (DeviceConfig)
    """

    def __init__(self, parent, cfg: DeviceConfig):
        super().__init__(parent)
        self._cfg = cfg
        self.result: DeviceConfig | None = None

        self.title(f"Device settings — {cfg.nickname or cfg.serial[:8]}")
        self.resizable(False, False)
        self.grab_set()

        self._build()
        self._load(cfg)

        # Center over parent
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        pad = dict(padx=12, pady=4)

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        # ---- Identity ----
        ttk.Label(frame, text="Identity", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        self._nickname_var = self._row(frame, 1, "Nickname")
        self._model_var    = self._row(frame, 2, "Model")
        self._account_var  = self._row(frame, 3, "Account")
        self._serial_var   = self._row(frame, 4, "ADB serial", readonly=True)

        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=10
        )

        # ---- Timer intervals ----
        ttk.Label(frame, text="Timer intervals (seconds)", font=("", 10, "bold")).grid(
            row=6, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        self._auto_farm_interval_var  = self._row(frame, 7,  "Auto-farm interval")
        self._end_run_interval_var    = self._row(frame, 8,  "End-run interval")
        self._stay_awake_interval_var = self._row(frame, 9,  "Stay-awake interval")

        ttk.Separator(frame, orient="horizontal").grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=10
        )

        # ---- Tap coordinates ----
        ttk.Label(frame, text="Tap coordinates", font=("", 10, "bold")).grid(
            row=11, column=0, columnspan=2, sticky="w", pady=(0, 6)
        )
        ttk.Label(frame, text="Use the coordinate finder tool to capture these.", foreground="#6b7280",
                  font=("", 9)).grid(row=12, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._af_x_var  = self._coord_row(frame, 13, "Auto-farm button", "x")
        self._af_y_var  = self._coord_row(frame, 14, "Auto-farm button", "y")
        self._er_x_var  = self._coord_row(frame, 15, "End-run button",   "x")
        self._er_y_var  = self._coord_row(frame, 16, "End-run button",   "y")
        self._rc_x_var  = self._coord_row(frame, 17, "Reconnect button", "x")
        self._rc_y_var  = self._coord_row(frame, 18, "Reconnect button", "y")
        self._lv_x_var  = self._coord_row(frame, 19, "Leave button",     "x")
        self._lv_y_var  = self._coord_row(frame, 20, "Leave button",     "y")

        # ---- Buttons ----
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=21, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

        frame.columnconfigure(1, weight=1)

    def _row(self, parent, row: int, label: str, readonly: bool = False) -> tk.StringVar:
        var = tk.StringVar()
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=2)
        state = "readonly" if readonly else "normal"
        ttk.Entry(parent, textvariable=var, width=28, state=state).grid(
            row=row, column=1, sticky="ew", pady=2
        )
        return var

    def _coord_row(self, parent, row: int, label: str, axis: str) -> tk.StringVar:
        var = tk.StringVar()
        ttk.Label(parent, text=f"{label} ({axis})").grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=2
        )
        ttk.Entry(parent, textvariable=var, width=10).grid(row=row, column=1, sticky="w", pady=2)
        return var

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self, cfg: DeviceConfig) -> None:
        self._nickname_var.set(cfg.nickname or "")
        self._model_var.set(cfg.model or "")
        self._account_var.set(cfg.account or "")
        self._serial_var.set(cfg.serial)

        self._auto_farm_interval_var.set(str(cfg.auto_farm_interval_s))
        self._end_run_interval_var.set(str(cfg.end_run_interval_s))
        self._stay_awake_interval_var.set(str(cfg.stay_awake_interval_s))

        self._af_x_var.set("" if cfg.auto_farm_tap_x is None else str(cfg.auto_farm_tap_x))
        self._af_y_var.set("" if cfg.auto_farm_tap_y is None else str(cfg.auto_farm_tap_y))
        self._er_x_var.set("" if cfg.end_run_tap_x   is None else str(cfg.end_run_tap_x))
        self._er_y_var.set("" if cfg.end_run_tap_y   is None else str(cfg.end_run_tap_y))
        self._rc_x_var.set("" if cfg.reconnect_tap_x is None else str(cfg.reconnect_tap_x))
        self._rc_y_var.set("" if cfg.reconnect_tap_y is None else str(cfg.reconnect_tap_y))
        self._lv_x_var.set("" if cfg.leave_tap_x     is None else str(cfg.leave_tap_x))
        self._lv_y_var.set("" if cfg.leave_tap_y     is None else str(cfg.leave_tap_y))

    def _save(self) -> None:
        def _int(v: tk.StringVar) -> int | None:
            s = v.get().strip()
            try:
                return int(s) if s else None
            except ValueError:
                return None

        def _float(v: tk.StringVar, default: float) -> float:
            s = v.get().strip()
            try:
                return float(s) if s else default
            except ValueError:
                return default

        self.result = replace(
            self._cfg,
            nickname=self._nickname_var.get().strip(),
            model=self._model_var.get().strip(),
            account=self._account_var.get().strip(),
            auto_farm_interval_s=_float(self._auto_farm_interval_var, self._cfg.auto_farm_interval_s),
            end_run_interval_s=_float(self._end_run_interval_var, self._cfg.end_run_interval_s),
            stay_awake_interval_s=_float(self._stay_awake_interval_var, self._cfg.stay_awake_interval_s),
            auto_farm_tap_x=_int(self._af_x_var),
            auto_farm_tap_y=_int(self._af_y_var),
            end_run_tap_x=_int(self._er_x_var),
            end_run_tap_y=_int(self._er_y_var),
            reconnect_tap_x=_int(self._rc_x_var),
            reconnect_tap_y=_int(self._rc_y_var),
            leave_tap_x=_int(self._lv_x_var),
            leave_tap_y=_int(self._lv_y_var),
        )
        self.destroy()
