"""
ui/capture_tab.py

Capture tab — combined capture and detector management.
Device dropdown + detector dropdown at the top.
Below: a preview of the saved crop image for that detector/device combo,
and a full list of all detectors showing their image status and last score.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable
from pathlib import Path

from bot.device_manager import DeviceManager
from config.devices import DeviceConfig
from config.paths import project_root

DETECTOR_NAMES = [
    "disconnected",
    "crashed",
    "roblox_home",
    "lobby",
    "auto_farm_off",
    "death_screen",
    "net_reveal",
    "in_tank",
    "end_run_button",
]

_DOT_DEVICE = "#16a34a"   # green — image exists for this device
_DOT_OTHER  = "#2563eb"   # blue  — image exists but from another device
_DOT_UNSET  = "#9ca3af"   # gray  — no image at all
_LEGEND_DOT_BG = "#1e1e1e"


class CaptureTab(ttk.Frame):

    def __init__(
        self,
        parent,
        manager: DeviceManager,
        get_devices: Callable[[], dict[str, DeviceConfig]],
    ):
        super().__init__(parent)
        self._manager = manager
        self._get_devices = get_devices
        self._selected_serial = tk.StringVar()
        self._selected_detector = tk.StringVar(value=DETECTOR_NAMES[0])
        self._serial_list: list[str] = []
        self._build()

    def _build(self) -> None:
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(fill="x")

        ttk.Label(top, text="Device:").pack(side="left", padx=(0, 6))
        self._device_combo = ttk.Combobox(
            top, textvariable=self._selected_serial, state="readonly", width=28
        )
        self._device_combo.pack(side="left", padx=(0, 12))
        self._device_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change())

        ttk.Label(top, text="Detector:").pack(side="left", padx=(0, 6))
        detector_combo = ttk.Combobox(
            top, textvariable=self._selected_detector,
            values=DETECTOR_NAMES, state="readonly", width=20
        )
        detector_combo.pack(side="left", padx=(0, 12))
        detector_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change())

        ttk.Button(top, text="Open crop tool", command=self._launch_crop_tool).pack(side="left")
        ttk.Button(top, text="Refresh", command=self._refresh_device_list).pack(side="left", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # Preview box
        preview_outer = ttk.Frame(self, padding=(12, 4))
        preview_outer.pack(fill="x")
        self._preview_canvas = tk.Canvas(
            preview_outer, height=120, bg="#111827",
            highlightthickness=1, highlightbackground="#374151"
        )
        self._preview_canvas.pack(fill="x")
        self._preview_canvas.create_text(
            300, 60, text="Select a device and detector, then open the crop tool.",
            fill="#6b7280", font=("", 10), width=400, justify="center"
        )

        # Legend
        legend_frame = ttk.Frame(self, padding=(12, 4))
        legend_frame.pack(fill="x")
        for color, label in [
            (_DOT_DEVICE, "This device"),
            (_DOT_OTHER,  "Another device's image"),
            (_DOT_UNSET,  "Not configured"),
        ]:
            dot = tk.Canvas(legend_frame, width=10, height=10,
                            highlightthickness=0, bg=_LEGEND_DOT_BG)
            dot.pack(side="left")
            dot.create_oval(1, 1, 9, 9, fill=color, outline="")
            ttk.Label(legend_frame, text=label, font=("", 9),
                      foreground="#6b7280").pack(side="left", padx=(2, 14))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # Detector list
        list_frame = ttk.Frame(self, padding=(12, 4))
        list_frame.pack(fill="both", expand=True)

        self._detector_rows: dict[str, dict] = {}
        for name in DETECTOR_NAMES:
            row = ttk.Frame(list_frame)
            row.pack(fill="x", pady=2)
            dot_canvas = tk.Canvas(row, width=12, height=12,
                                   highlightthickness=0, bg=_LEGEND_DOT_BG)
            dot_canvas.pack(side="left", padx=(0, 8))
            dot_id = dot_canvas.create_oval(2, 2, 10, 10, fill=_DOT_UNSET, outline="")
            ttk.Label(row, text=name, width=20, anchor="w").pack(side="left")
            score_lbl = ttk.Label(row, text="—", width=8, foreground="#9ca3af", font=("", 9))
            score_lbl.pack(side="left")
            tap_lbl = ttk.Label(row, text="", font=("", 9), foreground="#6b7280")
            tap_lbl.pack(side="left", padx=(4, 0))
            self._detector_rows[name] = {
                "dot_canvas": dot_canvas, "dot_id": dot_id,
                "score_lbl": score_lbl, "tap_lbl": tap_lbl,
            }

        self._refresh_device_list()

    def _refresh_device_list(self) -> None:
        devices = self._get_devices()
        options = [
            f"{cfg.nickname or s[:8]} — {cfg.model or s}"
            for s, cfg in devices.items()
        ]
        self._serial_list = list(devices.keys())
        self._device_combo["values"] = options
        if options and self._device_combo.current() < 0:
            self._device_combo.current(0)
        self._on_selection_change()

    def _on_selection_change(self) -> None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            return
        serial = self._serial_list[idx]
        detector = self._selected_detector.get()
        devices = self._get_devices()
        cfg = devices.get(serial)
        self._update_preview(serial, detector, cfg)
        self._update_detector_list(serial, cfg)

    def _update_preview(self, serial: str, detector: str, cfg: DeviceConfig | None) -> None:
        self._preview_canvas.delete("all")
        root = project_root()
        # Check for this device's image first, then any other image for this detector
        device_path = root / "assets" / "detectors" / detector / f"{detector}_{serial}.png"
        assigned_path = None
        if cfg and detector in cfg.detector_assignments:
            fname = cfg.detector_assignments[detector].image_filename
            if fname:
                assigned_path = root / "assets" / "detectors" / detector / fname

        for p in [device_path, assigned_path]:
            if p and p.exists():
                try:
                    img = tk.PhotoImage(file=str(p))
                    self._preview_canvas._img = img
                    self._preview_canvas.create_image(0, 0, anchor="nw", image=img)
                    return
                except Exception:
                    pass

        self._preview_canvas.create_text(
            300, 60,
            text=f"No image saved for '{detector}' — open the crop tool to capture one.",
            fill="#6b7280", font=("", 10), width=400, justify="center"
        )

    def _update_detector_list(self, serial: str, cfg: DeviceConfig | None) -> None:
        root = project_root()
        for name, widgets in self._detector_rows.items():
            dc   = widgets["dot_canvas"]
            did  = widgets["dot_id"]
            slbl = widgets["score_lbl"]
            tlbl = widgets["tap_lbl"]

            device_path = root / "assets" / "detectors" / name / f"{name}_{serial}.png"
            detector_dir = root / "assets" / "detectors" / name
            any_exists = detector_dir.exists() and any(detector_dir.glob("*.png"))

            assignment = cfg.detector_assignments.get(name) if cfg else None

            if device_path.exists():
                dc.itemconfig(did, fill=_DOT_DEVICE)
            elif any_exists:
                dc.itemconfig(did, fill=_DOT_OTHER)
            else:
                dc.itemconfig(did, fill=_DOT_UNSET)

            score = assignment.last_score if assignment else None
            if score is not None:
                slbl.config(
                    text=f"{score:.2f}",
                    foreground="#16a34a" if score >= 0.80 else "#d97706"
                )
            else:
                slbl.config(text="—", foreground="#9ca3af")

            # Show tap override indicator
            if assignment and assignment.tap_offset_x is not None:
                tlbl.config(text=f"tap override ({assignment.tap_offset_x},{assignment.tap_offset_y})")
            else:
                tlbl.config(text="")

    def _launch_crop_tool(self) -> None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            messagebox.showinfo("No device", "Select a device first.", parent=self)
            return
        serial = self._serial_list[idx]
        detector = self._selected_detector.get()
        try:
            from tools.crop_tool import CropTool
            tool = CropTool(self, serial=serial, detector_name=detector, manager=self._manager)
            self.wait_window(tool)
            self._on_selection_change()
        except Exception as e:
            messagebox.showerror("Crop tool error", str(e), parent=self)
