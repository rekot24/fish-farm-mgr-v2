"""
ui/device_tab.py

Device tab — device selector dropdown at the top, then shows the full
config for the selected device: identity, tap coordinates, and timer intervals.

This tab is for viewing/editing config between sessions. Toggles live on
the device card (Main tab) not here.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import replace
from typing import Callable

from config.devices import DeviceConfig


class DeviceTab(ttk.Frame):

    def __init__(
        self,
        parent,
        get_devices: Callable[[], dict[str, DeviceConfig]],
        save_devices_fn: Callable,
    ):
        super().__init__(parent)
        self._get_devices = get_devices
        self._save_devices = save_devices_fn
        self._selected_serial = tk.StringVar()
        self._build()

    def _build(self) -> None:
        # ---- Device selector ----
        selector_frame = ttk.Frame(self, padding=(12, 10, 12, 4))
        selector_frame.pack(fill="x")

        ttk.Label(selector_frame, text="Device:").pack(side="left", padx=(0, 8))
        self._device_combo = ttk.Combobox(
            selector_frame, textvariable=self._selected_serial,
            state="readonly", width=36
        )
        self._device_combo.pack(side="left")
        self._device_combo.bind("<<ComboboxSelected>>", lambda e: self._load_selected())

        ttk.Button(selector_frame, text="Refresh", command=self._refresh_list).pack(
            side="left", padx=(8, 0)
        )

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # ---- Scrollable detail area ----
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._detail_frame = ttk.Frame(canvas, padding=(12, 8))
        self._canvas_win = canvas.create_window((0, 0), window=self._detail_frame, anchor="nw")
        self._detail_frame.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        ))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._canvas_win, width=e.width))

        self._empty_label = ttk.Label(
            self._detail_frame, text="Select a device above.", foreground="#6b7280"
        )
        self._empty_label.pack(pady=20)

        self._refresh_list()

    def _refresh_list(self) -> None:
        devices = self._get_devices()
        options = [
            f"{cfg.nickname or serial[:8]} — {cfg.model or serial}"
            for serial, cfg in devices.items()
        ]
        self._serial_list = list(devices.keys())
        self._device_combo["values"] = options
        if options and not self._selected_serial.get():
            self._device_combo.current(0)
            self._load_selected()

    def _load_selected(self) -> None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            return
        serial = self._serial_list[idx]
        devices = self._get_devices()
        cfg = devices.get(serial)
        if cfg:
            self._show_detail(serial, cfg)

    def _show_detail(self, serial: str, cfg: DeviceConfig) -> None:
        for w in self._detail_frame.winfo_children():
            w.destroy()

        f = self._detail_frame

        def section(label):
            ttk.Label(f, text=label, font=("", 10, "bold")).pack(anchor="w", pady=(10, 4))

        def field_row(label, value, readonly=False):
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(value) if value is not None else "")
            entry = ttk.Entry(row, textvariable=var, width=30,
                              state="readonly" if readonly else "normal")
            entry.pack(side="left")
            return var

        # Identity
        section("Identity")
        nickname_var = field_row("Nickname",   cfg.nickname)
        model_var    = field_row("Model",      cfg.model)
        account_var  = field_row("Account",    cfg.account)
        field_row("ADB serial", cfg.serial, readonly=True)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        # Tap coordinates
        section("Tap coordinates")
        ttk.Label(f, text="Use the coordinate finder tool to set these.",
                  foreground="#6b7280", font=("", 9)).pack(anchor="w", pady=(0, 6))

        coord_vars = {}
        for name, xval, yval in [
            ("Auto-farm button",  cfg.auto_farm_tap_x,  cfg.auto_farm_tap_y),
            ("End-run button",    cfg.end_run_tap_x,    cfg.end_run_tap_y),
            ("Reconnect button",  cfg.reconnect_tap_x,  cfg.reconnect_tap_y),
            ("Leave button",      cfg.leave_tap_x,      cfg.leave_tap_y),
        ]:
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=name, width=22, anchor="w").pack(side="left")
            xv = tk.StringVar(value="" if xval is None else str(xval))
            yv = tk.StringVar(value="" if yval is None else str(yval))
            ttk.Entry(row, textvariable=xv, width=8).pack(side="left", padx=(0, 4))
            ttk.Label(row, text=",").pack(side="left", padx=(0, 4))
            ttk.Entry(row, textvariable=yv, width=8).pack(side="left")
            coord_vars[name] = (xv, yv)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        # Timer intervals
        section("Timer intervals (seconds)")
        af_interval_var = field_row("Auto-farm interval",   cfg.auto_farm_interval_s)
        er_interval_var = field_row("End-run interval",     cfg.end_run_interval_s)
        sa_interval_var = field_row("Stay-awake interval",  cfg.stay_awake_interval_s)

        # Save button
        def _save():
            def _int(v):
                s = v.get().strip()
                try: return int(s) if s else None
                except ValueError: return None
            def _float(v, default):
                s = v.get().strip()
                try: return float(s) if s else default
                except ValueError: return default

            af_x, af_y = coord_vars["Auto-farm button"]
            er_x, er_y = coord_vars["End-run button"]
            rc_x, rc_y = coord_vars["Reconnect button"]
            lv_x, lv_y = coord_vars["Leave button"]

            updated = replace(
                cfg,
                nickname=nickname_var.get().strip(),
                model=model_var.get().strip(),
                account=account_var.get().strip(),
                auto_farm_interval_s=_float(af_interval_var, cfg.auto_farm_interval_s),
                end_run_interval_s=_float(er_interval_var, cfg.end_run_interval_s),
                stay_awake_interval_s=_float(sa_interval_var, cfg.stay_awake_interval_s),
                auto_farm_tap_x=_int(af_x), auto_farm_tap_y=_int(af_y),
                end_run_tap_x=_int(er_x),   end_run_tap_y=_int(er_y),
                reconnect_tap_x=_int(rc_x), reconnect_tap_y=_int(rc_y),
                leave_tap_x=_int(lv_x),     leave_tap_y=_int(lv_y),
            )
            devices = self._get_devices()
            devices[serial] = updated
            self._save_devices(devices)
            self._refresh_list()

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)
        ttk.Button(f, text="Save changes", command=_save).pack(anchor="e")
