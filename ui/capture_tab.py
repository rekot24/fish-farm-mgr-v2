"""
ui/capture_tab.py

Capture tab — device/detector selection, crop tool launcher, and
per-detector image management.

Detector list columns:
  dot · name · image dropdown · Test · Assign · score · tap override

Image dropdown: lists all available .png files for that detector across
all devices. Defaults to the currently assigned image.

Test: captures a fresh frame from the device, runs template match against
the selected image, shows the score. Does not save anything.

Assign: saves the currently selected image as the assignment for this
device+detector in devices.json.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timezone
from tkinter import ttk, messagebox
from typing import Callable

import cv2
import numpy as np

from bot.device_manager import DeviceManager
from config.devices import DeviceConfig, load_devices, save_devices, DetectorAssignment
from config.paths import project_root, adb_exe
from config.constants import ADB_SCREENCAP_TIMEOUT_S, DETECTION_THRESHOLD

DETECTOR_NAMES = [
    "disconnected",
    "crashed",
    "roblox_home",
    "lobby",
    "auto_farm_on",
    "auto_farm_off",
    "death_screen",
    "net_reveal",
    "in_tank",
    "end_run_button",
]

_DOT_DEVICE = "#16a34a"
_DOT_OTHER  = "#2563eb"
_DOT_UNSET  = "#9ca3af"
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

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(fill="x")

        ttk.Label(top, text="Device:").pack(side="left", padx=(0, 6))
        self._device_combo = ttk.Combobox(
            top, textvariable=self._selected_serial, state="readonly", width=28)
        self._device_combo.pack(side="left", padx=(0, 12))
        self._device_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change())

        ttk.Label(top, text="Detector:").pack(side="left", padx=(0, 6))
        detector_combo = ttk.Combobox(
            top, textvariable=self._selected_detector,
            values=DETECTOR_NAMES, state="readonly", width=20)
        detector_combo.pack(side="left", padx=(0, 12))
        detector_combo.bind("<<ComboboxSelected>>", lambda e: self._on_selection_change())

        ttk.Button(top, text="Open crop tool", command=self._launch_crop_tool).pack(side="left")
        ttk.Button(top, text="Refresh", command=self._refresh_device_list).pack(
            side="left", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # Preview
        preview_outer = ttk.Frame(self, padding=(12, 4))
        preview_outer.pack(fill="x")
        self._preview_canvas = tk.Canvas(
            preview_outer, height=120, bg="#111827",
            highlightthickness=1, highlightbackground="#374151")
        self._preview_canvas.pack(fill="x")
        self._preview_canvas.create_text(
            300, 60, text="Select a device and detector, then open the crop tool.",
            fill="#6b7280", font=("", 10), width=400, justify="center")

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

        # Column headers
        hdr = ttk.Frame(self, padding=(12, 0))
        hdr.pack(fill="x")
        ttk.Label(hdr, text=" ", width=2).pack(side="left")
        ttk.Label(hdr, text="Detector", width=18, foreground="#6b7280",
                  font=("", 9)).pack(side="left")
        ttk.Label(hdr, text="Image", width=24, foreground="#6b7280",
                  font=("", 9)).pack(side="left")
        ttk.Label(hdr, text="", width=8).pack(side="left")   # Test
        ttk.Label(hdr, text="", width=8).pack(side="left")   # Assign
        ttk.Label(hdr, text="Score", width=7, foreground="#6b7280",
                  font=("", 9)).pack(side="left")

        # Scrollable detector list
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        list_frame = ttk.Frame(canvas, padding=(12, 4))
        canvas.create_window((0, 0), window=list_frame, anchor="nw")
        list_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        from ui.scroll_utils import bind_mousewheel
        bind_mousewheel(canvas)

        self._detector_rows: dict[str, dict] = {}
        for name in DETECTOR_NAMES:
            row = ttk.Frame(list_frame)
            row.pack(fill="x", pady=3)

            # Status dot
            dot_canvas = tk.Canvas(row, width=12, height=12,
                                   highlightthickness=0, bg=_LEGEND_DOT_BG)
            dot_canvas.pack(side="left", padx=(0, 6))
            dot_id = dot_canvas.create_oval(2, 2, 10, 10, fill=_DOT_UNSET, outline="")

            # Name
            ttk.Label(row, text=name, width=18, anchor="w").pack(side="left")

            # Image dropdown — populated when device is selected
            img_var = tk.StringVar(value="—")
            img_combo = ttk.Combobox(row, textvariable=img_var,
                                     state="readonly", width=22)
            img_combo.pack(side="left", padx=(0, 4))

            # Test button
            test_btn = ttk.Button(row, text="Test", width=5,
                command=lambda n=name: self._test_detector(n))
            test_btn.pack(side="left", padx=(0, 2))

            # Assign button
            assign_btn = ttk.Button(row, text="Assign", width=6,
                command=lambda n=name: self._assign_detector(n))
            assign_btn.pack(side="left", padx=(0, 6))

            # Score label
            score_lbl = ttk.Label(row, text="—", width=6,
                                   foreground="#9ca3af", font=("", 9))
            score_lbl.pack(side="left")

            # Tap override note
            tap_lbl = ttk.Label(row, text="", font=("", 9), foreground="#6b7280")
            tap_lbl.pack(side="left", padx=(4, 0))

            self._detector_rows[name] = {
                "dot_canvas": dot_canvas, "dot_id": dot_id,
                "img_var": img_var, "img_combo": img_combo,
                "test_btn": test_btn, "assign_btn": assign_btn,
                "score_lbl": score_lbl, "tap_lbl": tap_lbl,
            }
            # Bind dropdown change to clear score (score is per-selection)
            img_var.trace_add("write",
                lambda *_, n=name: self._on_image_selection_change(n))

        self._refresh_device_list()

    # ------------------------------------------------------------------
    # Device list
    # ------------------------------------------------------------------

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

    def _current_serial(self) -> str | None:
        idx = self._device_combo.current()
        if idx < 0 or idx >= len(self._serial_list):
            return None
        return self._serial_list[idx]

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    def _update_preview(self, serial: str, detector: str,
                        cfg: DeviceConfig | None) -> None:
        self._preview_canvas.delete("all")
        root = project_root()
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
            fill="#6b7280", font=("", 10), width=400, justify="center")

    # ------------------------------------------------------------------
    # Detector list
    # ------------------------------------------------------------------

    def _list_available_images(self, detector_name: str) -> list[str]:
        """Return filenames of all available images for a detector."""
        detector_dir = project_root() / "assets" / "detectors" / detector_name
        if not detector_dir.exists():
            return []
        return sorted(p.name for p in detector_dir.glob("*.png"))

    def _update_detector_list(self, serial: str, cfg: DeviceConfig | None) -> None:
        root = project_root()
        for name, widgets in self._detector_rows.items():
            dc        = widgets["dot_canvas"]
            did       = widgets["dot_id"]
            img_var   = widgets["img_var"]
            img_combo = widgets["img_combo"]
            score_lbl = widgets["score_lbl"]
            tap_lbl   = widgets["tap_lbl"]

            device_path  = root / "assets" / "detectors" / name / f"{name}_{serial}.png"
            detector_dir = root / "assets" / "detectors" / name
            any_exists   = detector_dir.exists() and any(detector_dir.glob("*.png"))
            assignment   = cfg.detector_assignments.get(name) if cfg else None

            # Dot color
            if device_path.exists():
                dc.itemconfig(did, fill=_DOT_DEVICE)
            elif any_exists:
                dc.itemconfig(did, fill=_DOT_OTHER)
            else:
                dc.itemconfig(did, fill=_DOT_UNSET)

            # Image dropdown
            available = self._list_available_images(name)
            img_combo["values"] = available if available else ["—"]

            # Default to assigned image, then device image, then first available
            current_selection = "—"
            if assignment and assignment.image_filename and \
               assignment.image_filename in available:
                current_selection = assignment.image_filename
            elif device_path.exists():
                current_selection = device_path.name
            elif available:
                current_selection = available[0]

            # Set without triggering trace
            img_var.set(current_selection)

            # Score — from assignment if the assigned image matches current selection
            score = None
            if assignment and assignment.image_filename == current_selection:
                score = assignment.last_score
            if score is not None:
                score_lbl.config(
                    text=f"{score:.2f}",
                    foreground="#16a34a" if score >= 0.80 else "#d97706")
            else:
                score_lbl.config(text="—", foreground="#9ca3af")

            # Tap override
            if assignment and assignment.tap_offset_x is not None:
                tap_lbl.config(
                    text=f"tap ({assignment.tap_offset_x},{assignment.tap_offset_y})")
            else:
                tap_lbl.config(text="")

    def _on_image_selection_change(self, detector_name: str) -> None:
        """When dropdown changes, clear score — it's now unknown for this selection."""
        widgets = self._detector_rows.get(detector_name)
        if widgets:
            widgets["score_lbl"].config(text="—", foreground="#9ca3af")

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def _test_detector(self, detector_name: str) -> None:
        """Capture a fresh frame and run template match against selected image."""
        serial = self._current_serial()
        if not serial:
            messagebox.showinfo("No device", "Select a device first.", parent=self)
            return

        widgets = self._detector_rows[detector_name]
        selected_image = widgets["img_var"].get()
        if not selected_image or selected_image == "—":
            messagebox.showinfo("No image",
                f"No image selected for '{detector_name}'.\n"
                "Use the crop tool to capture one first.", parent=self)
            return

        image_path = (project_root() / "assets" / "detectors" /
                      detector_name / selected_image)
        if not image_path.exists():
            messagebox.showerror("Image missing",
                f"Image file not found:\n{image_path}", parent=self)
            return

        # Disable test button while running
        widgets["test_btn"].config(state="disabled", text="…")
        widgets["score_lbl"].config(text="…", foreground="#9ca3af")

        def do_test():
            try:
                # Fresh screencap
                result = subprocess.run(
                    [adb_exe(), "-s", serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=ADB_SCREENCAP_TIMEOUT_S,
                )
                if result.returncode != 0 or not result.stdout:
                    self.after(0, lambda: self._test_done(
                        detector_name, None, "Screencap failed"))
                    return

                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.after(0, lambda: self._test_done(
                        detector_name, None, "Could not decode frame"))
                    return

                # Load template and match
                template = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
                if template is None:
                    self.after(0, lambda: self._test_done(
                        detector_name, None, "Could not load template image"))
                    return

                fh, fw = frame.shape[:2]
                th, tw = template.shape[:2]
                if th > fh or tw > fw:
                    self.after(0, lambda: self._test_done(
                        detector_name, None, "Template larger than frame"))
                    return

                match_result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(match_result)
                score = float(max_val)
                self.after(0, lambda s=score: self._test_done(detector_name, s, None))

            except Exception as e:
                self.after(0, lambda: self._test_done(
                    detector_name, None, str(e)))

        threading.Thread(target=do_test, daemon=True).start()

    def _test_done(self, detector_name: str,
                   score: float | None, error: str | None) -> None:
        widgets = self._detector_rows[detector_name]
        widgets["test_btn"].config(state="normal", text="Test")

        if error:
            widgets["score_lbl"].config(text="err", foreground="#dc2626")
            messagebox.showerror("Test failed", error, parent=self)
            return

        if score >= DETECTION_THRESHOLD:
            widgets["score_lbl"].config(
                text=f"{score:.2f}", foreground="#16a34a")
        else:
            widgets["score_lbl"].config(
                text=f"{score:.2f}", foreground="#d97706")

    # ------------------------------------------------------------------
    # Assign
    # ------------------------------------------------------------------

    def _assign_detector(self, detector_name: str) -> None:
        """Save the currently selected image as the assignment for this device."""
        serial = self._current_serial()
        if not serial:
            messagebox.showinfo("No device", "Select a device first.", parent=self)
            return

        widgets = self._detector_rows[detector_name]
        selected_image = widgets["img_var"].get()
        if not selected_image or selected_image == "—":
            messagebox.showinfo("No image",
                f"No image selected for '{detector_name}'.", parent=self)
            return

        # Read current score from the score label
        score_text = widgets["score_lbl"].cget("text")
        try:
            score = float(score_text)
        except (ValueError, TypeError):
            score = None

        devices = self._get_devices()
        cfg = devices.get(serial)
        if cfg is None:
            messagebox.showerror("Device not found",
                f"Device {serial} not in config.", parent=self)
            return

        existing = cfg.detector_assignments.get(detector_name)
        new_assignment = DetectorAssignment(
            image_filename=selected_image,
            shape=existing.shape if existing else "box",
            last_tested=datetime.now(timezone.utc).isoformat() if score is not None else (
                existing.last_tested if existing else None),
            last_score=score,
            tap_offset_x=existing.tap_offset_x if existing else None,
            tap_offset_y=existing.tap_offset_y if existing else None,
        )
        cfg.detector_assignments[detector_name] = new_assignment
        save_devices(devices)

        # Invalidate template bank cache
        if self._manager:
            self._manager.invalidate_template(detector_name, serial)

        # Update dot color
        image_path = (project_root() / "assets" / "detectors" /
                      detector_name / selected_image)
        own_image = f"{detector_name}_{serial}.png"
        if selected_image == own_image:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_DEVICE)
        else:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_OTHER)

        # Update preview if this is the selected detector
        if self._selected_detector.get() == detector_name:
            cfg2 = self._get_devices().get(serial)
            self._update_preview(serial, detector_name, cfg2)

    # ------------------------------------------------------------------
    # Crop tool
    # ------------------------------------------------------------------

    def _launch_crop_tool(self) -> None:
        serial = self._current_serial()
        if not serial:
            messagebox.showinfo("No device", "Select a device first.", parent=self)
            return
        detector = self._selected_detector.get()
        try:
            from tools.crop_tool import CropTool
            tool = CropTool(self, serial=serial, detector_name=detector,
                            manager=self._manager,
                            detector_names=DETECTOR_NAMES)
            self.wait_window(tool)
            self._on_selection_change()
        except Exception as e:
            messagebox.showerror("Crop tool error", str(e), parent=self)
