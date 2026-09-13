"""
ui/device_tab.py

Device tab — device selector dropdown at the top, then shows the full
config for the selected device: identity and timer intervals.

Tap coordinates are resolved at runtime from template matching — they
are not stored or edited here. Use the Capture tab to assign detector
images and set optional tap overrides.
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
        self._serial_list: list[str] = []
        self._build()

    def _build(self) -> None:
        selector_frame = ttk.Frame(self, padding=(12, 10, 12, 4))
        selector_frame.pack(fill="x")

        ttk.Label(selector_frame, text="Device:").pack(side="left", padx=(0, 8))
        self._device_combo = ttk.Combobox(
            selector_frame, textvariable=self._selected_serial,
            state="readonly", width=36
        )
        self._device_combo.pack(side="left")
        self._device_combo.bind("<<ComboboxSelected>>", lambda e: self._load_selected())
        ttk.Button(selector_frame, text="Refresh", command=self._refresh_list).pack(side="left", padx=(8, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._detail_frame = ttk.Frame(canvas, padding=(12, 8))
        self._canvas_win = canvas.create_window((0, 0), window=self._detail_frame, anchor="nw")
        self._detail_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._canvas_win, width=e.width))
        from ui.scroll_utils import bind_mousewheel
        bind_mousewheel(canvas)

        ttk.Label(self._detail_frame, text="Select a device above.", foreground="#6b7280").pack(pady=20)
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
        cfg = self._get_devices().get(serial)
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
            ttk.Entry(row, textvariable=var, width=30,
                      state="readonly" if readonly else "normal").pack(side="left")
            return var

        section("Identity")
        nickname_var = field_row("Nickname",  cfg.nickname)
        model_var    = field_row("Model",     cfg.model)
        account_var  = field_row("Account",   cfg.account)
        field_row("ADB serial", cfg.serial, readonly=True)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        section("Timer intervals (seconds)")
        af_var = field_row("Auto-farm interval",  cfg.auto_farm_interval_s)
        er_var = field_row("End-run interval",    cfg.end_run_interval_s)
        sa_var = field_row("Stay-awake interval", cfg.stay_awake_interval_s)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(
            f,
            text="Tap coordinates are resolved automatically at runtime from template\n"
                 "match results. Use the Capture tab to assign detector images.",
            foreground="#6b7280", font=("", 9)
        ).pack(anchor="w")

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        def _save():
            def _float(v, default):
                try: return float(v.get()) if v.get().strip() else default
                except ValueError: return default
            updated = replace(
                cfg,
                nickname=nickname_var.get().strip(),
                model=model_var.get().strip(),
                account=account_var.get().strip(),
                auto_farm_interval_s=_float(af_var, cfg.auto_farm_interval_s),
                end_run_interval_s=_float(er_var, cfg.end_run_interval_s),
                stay_awake_interval_s=_float(sa_var, cfg.stay_awake_interval_s),
            )
            devices = self._get_devices()
            devices[serial] = updated
            self._save_devices(devices)
            self._refresh_list()

        ttk.Button(f, text="Save changes", command=_save).pack(anchor="e")
