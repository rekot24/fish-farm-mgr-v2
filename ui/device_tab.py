"""
ui/device_tab.py

Device tab — device selector, identity/timer editing, add/remove devices.
"""

from __future__ import annotations

import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import replace
from typing import Callable

from config.devices import DeviceConfig
from config.paths import adb_exe


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
            state="readonly", width=34
        )
        self._device_combo.pack(side="left")
        self._device_combo.bind("<<ComboboxSelected>>", lambda e: self._load_selected())

        ttk.Button(selector_frame, text="Refresh",
                   command=self._refresh_list).pack(side="left", padx=(6, 0))
        ttk.Button(selector_frame, text="Add device",
                   command=self._add_device).pack(side="left", padx=(6, 0))
        self._remove_btn = ttk.Button(selector_frame, text="Remove",
                                       command=self._remove_device)
        self._remove_btn.pack(side="left", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self._detail_frame = ttk.Frame(canvas, padding=(12, 8))
        self._canvas_win = canvas.create_window(
            (0, 0), window=self._detail_frame, anchor="nw")
        self._detail_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._canvas_win, width=e.width))
        from ui.scroll_utils import bind_mousewheel
        bind_mousewheel(canvas)

        ttk.Label(
            self._detail_frame,
            text="No devices registered. Click 'Add device' to get started.",
            foreground="#6b7280"
        ).pack(pady=20)
        self._refresh_list()

    # ------------------------------------------------------------------
    # Device list
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        devices = self._get_devices()
        options = [
            f"{cfg.nickname or serial[:12]} — {cfg.model or serial}"
            for serial, cfg in devices.items()
        ]
        self._serial_list = list(devices.keys())
        self._device_combo["values"] = options
        if options:
            cur = self._device_combo.current()
            if cur < 0 or cur >= len(options):
                self._device_combo.current(0)
            self._load_selected()
        else:
            self._device_combo.set("")
            self._show_empty()
        self._remove_btn.config(state="normal" if self._serial_list else "disabled")

    def _load_selected(self) -> None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            return
        serial = self._serial_list[idx]
        cfg = self._get_devices().get(serial)
        if cfg:
            self._show_detail(serial, cfg)

    def _show_empty(self) -> None:
        for w in self._detail_frame.winfo_children():
            w.destroy()
        ttk.Label(
            self._detail_frame,
            text="No devices registered. Click 'Add device' to get started.",
            foreground="#6b7280"
        ).pack(pady=20)

    # ------------------------------------------------------------------
    # Add / remove device
    # ------------------------------------------------------------------

    def _add_device(self) -> None:
        try:
            result = subprocess.run(
                [adb_exe(), "devices"], capture_output=True, timeout=10, text=True
            )
        except Exception as e:
            messagebox.showerror("ADB error",
                f"Could not run adb devices:\n{e}", parent=self)
            return

        connected = []
        for line in result.stdout.strip().splitlines()[1:]:
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1] == "device":
                connected.append(parts[0])

        if not connected:
            messagebox.showinfo("No devices found",
                "No ADB devices detected.\n\n"
                "Make sure your device is connected and USB debugging is enabled.",
                parent=self)
            return

        registered = set(self._get_devices().keys())
        available = [s for s in connected if s not in registered]

        if not available:
            messagebox.showinfo("All connected",
                f"All connected devices are already registered.\n\nConnected: {', '.join(connected)}",
                parent=self)
            return

        AddDeviceDialog(self, available=available, on_add=self._on_device_added)

    def _on_device_added(self, serial: str, nickname: str, model: str) -> None:
        devices = self._get_devices()
        if serial in devices:
            return
        devices[serial] = DeviceConfig(
            serial=serial,
            nickname=nickname.strip(),
            model=model.strip(),
        )
        self._save_devices(devices)
        self._refresh_list()
        if serial in self._serial_list:
            self._device_combo.current(self._serial_list.index(serial))
            self._load_selected()

    def _remove_device(self) -> None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            return
        serial = self._serial_list[idx]
        devices = self._get_devices()
        cfg = devices.get(serial)
        label = cfg.nickname or serial[:12] if cfg else serial[:12]

        if not messagebox.askyesno(
            "Remove device",
            f"Remove '{label}' from the device list?\n\n"
            "This only removes the configuration — it does not affect\n"
            "the physical device or any saved detector images.",
            parent=self
        ):
            return

        devices.pop(serial, None)
        self._save_devices(devices)
        self._refresh_list()

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    def _show_detail(self, serial: str, cfg: DeviceConfig) -> None:
        for w in self._detail_frame.winfo_children():
            w.destroy()

        f = self._detail_frame

        def section(label):
            ttk.Label(f, text=label, font=("", 10, "bold")).pack(anchor="w", pady=(10, 4))

        def editable_row(label, value):
            """Editable field — normal Entry with StringVar."""
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(value) if value else "")
            ttk.Entry(row, textvariable=var, width=30).pack(side="left")
            return var

        def readonly_row(label, value):
            """
            Read-only display field. Uses a disabled Entry with textvariable
            set before the widget is rendered to ensure the value displays.
            """
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22, anchor="w").pack(side="left")
            var = tk.StringVar(value=str(value) if value else "")
            e = ttk.Entry(row, width=30)
            e.pack(side="left")
            # Insert directly into the widget — bypasses readonly restriction
            e.insert(0, str(value) if value else "")
            e.config(state="readonly")

        section("Identity")
        nickname_var = editable_row("Nickname / Acct", cfg.nickname)
        model_var    = editable_row("Model",           cfg.model)
        readonly_row("ADB serial", serial)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        section("Timer intervals (seconds)")
        af_var = editable_row("Auto-farm interval",  cfg.auto_farm_interval_s)
        er_var = editable_row("End-run interval",    cfg.end_run_interval_s)
        sa_var = editable_row("Stay-awake interval", cfg.stay_awake_interval_s)

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=8)

        ttk.Label(
            f,
            text="Tap coordinates are resolved automatically at runtime.\n"
                 "Use the Capture tab to assign detector images.",
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
                # account is now merged into nickname — keep account in sync
                account=nickname_var.get().strip(),
                auto_farm_interval_s=_float(af_var, cfg.auto_farm_interval_s),
                end_run_interval_s=_float(er_var, cfg.end_run_interval_s),
                stay_awake_interval_s=_float(sa_var, cfg.stay_awake_interval_s),
            )
            devices = self._get_devices()
            devices[serial] = updated
            self._save_devices(devices)
            self._refresh_list()

        ttk.Button(f, text="Save changes", command=_save).pack(anchor="e")


# ---------------------------------------------------------------------------
# Add Device Dialog
# ---------------------------------------------------------------------------

class AddDeviceDialog(tk.Toplevel):

    def __init__(self, parent, available: list[str], on_add):
        super().__init__(parent)
        self._available = available
        self._on_add = on_add
        self.title("Add device")
        self.resizable(False, False)
        self.grab_set()
        self._build()
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _build(self) -> None:
        f = ttk.Frame(self, padding=16)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="Connected ADB devices", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(f, text="Select device:").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=4)
        self._serial_var = tk.StringVar(value=self._available[0])
        ttk.Combobox(f, textvariable=self._serial_var, values=self._available,
                     state="readonly", width=28).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Separator(f, orient="horizontal").grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=8)

        ttk.Label(f, text="Nickname / Acct:").grid(
            row=3, column=0, sticky="w", padx=(0, 12), pady=4)
        self._nickname_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._nickname_var, width=28).grid(
            row=3, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="Model (optional):").grid(
            row=4, column=0, sticky="w", padx=(0, 12), pady=4)
        self._model_var = tk.StringVar()
        ttk.Entry(f, textvariable=self._model_var, width=28).grid(
            row=4, column=1, sticky="ew", pady=4)

        ttk.Label(f, text="You can fill in these details later on the Device tab.",
                  foreground="#6b7280", font=("", 9)).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=6, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(
            side="right", padx=(6, 0))
        ttk.Button(btn_frame, text="Add device", command=self._confirm).pack(side="right")
        f.columnconfigure(1, weight=1)

    def _confirm(self) -> None:
        serial = self._serial_var.get().strip()
        if not serial:
            return
        self._on_add(serial, self._nickname_var.get(), self._model_var.get())
        self.destroy()
