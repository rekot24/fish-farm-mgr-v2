"""
ui/device_settings_dialog.py

Per-device settings dialog. Opened from the Settings button on each device card.
Nickname and Account are merged into one "Nickname / Acct" field.
ADB serial is displayed read-only using direct widget insert.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import replace

from config.devices import DeviceConfig


class DeviceSettingsDialog(tk.Toplevel):

    def __init__(self, parent, cfg: DeviceConfig):
        super().__init__(parent)
        self._cfg = cfg
        self.result: DeviceConfig | None = None

        self.title(f"Device settings — {cfg.nickname or cfg.serial[:8]}")
        self.resizable(False, False)
        self.grab_set()

        self._build()
        self._load(cfg)

        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{px}+{py}")

    def _build(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        # Identity
        ttk.Label(frame, text="Identity", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self._nickname_var = self._row(frame, 1, "Nickname / Acct")
        self._model_var    = self._row(frame, 2, "Model")

        # ADB serial — read-only, populated via direct insert
        ttk.Label(frame, text="ADB serial").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=2)
        self._serial_entry = ttk.Entry(frame, width=28, state="normal")
        self._serial_entry.grid(row=3, column=1, sticky="ew", pady=2)

        ttk.Separator(frame, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=10)

        # Timer intervals
        ttk.Label(frame, text="Timer intervals (seconds)", font=("", 10, "bold")).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(0, 6))
        self._auto_farm_var  = self._row(frame, 6, "Auto-farm interval")
        self._end_run_var    = self._row(frame, 7, "End-run interval")
        self._stay_awake_var = self._row(frame, 8, "Stay-awake interval")

        ttk.Label(
            frame,
            text="Tap coordinates are set automatically via template matching.\n"
                 "Use the Capture tab to assign detector images.",
            foreground="#6b7280", font=("", 9), justify="left"
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=10, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="right")

        frame.columnconfigure(1, weight=1)

    def _row(self, parent, row: int, label: str) -> tk.StringVar:
        var = tk.StringVar()
        ttk.Label(parent, text=label).grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=2)
        ttk.Entry(parent, textvariable=var, width=28).grid(
            row=row, column=1, sticky="ew", pady=2)
        return var

    def _load(self, cfg: DeviceConfig) -> None:
        self._nickname_var.set(cfg.nickname or "")
        self._model_var.set(cfg.model or "")
        self._auto_farm_var.set(str(cfg.auto_farm_interval_s))
        self._end_run_var.set(str(cfg.end_run_interval_s))
        self._stay_awake_var.set(str(cfg.stay_awake_interval_s))
        # Insert serial directly then lock — bypasses readonly StringVar issue
        self._serial_entry.insert(0, cfg.serial)
        self._serial_entry.config(state="readonly")

    def _save(self) -> None:
        def _float(v: tk.StringVar, default: float) -> float:
            try: return float(v.get()) if v.get().strip() else default
            except ValueError: return default

        nickname = self._nickname_var.get().strip()
        self.result = replace(
            self._cfg,
            nickname=nickname,
            model=self._model_var.get().strip(),
            account=nickname,   # keep account in sync with nickname
            auto_farm_interval_s=_float(self._auto_farm_var, self._cfg.auto_farm_interval_s),
            end_run_interval_s=_float(self._end_run_var, self._cfg.end_run_interval_s),
            stay_awake_interval_s=_float(self._stay_awake_var, self._cfg.stay_awake_interval_s),
        )
        self.destroy()
