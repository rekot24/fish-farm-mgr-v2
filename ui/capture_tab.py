"""
ui/capture_tab.py

Capture tab — device/detector selection, crop tool launcher, and
per-detector image management.

Detector list columns:
  dot · name · image dropdown · Test · Assign · score · tap override

Image dropdown: lists all available .png files for that detector across
all devices. Defaults to the currently assigned image.

Test: captures a fresh frame from the device, runs template match against
the assigned image (same image the live bot loop uses). If no image is
assigned yet, falls back to the dropdown selection. Does not save anything.

Assign: saves the currently selected image as the assignment for this
device+detector in devices.json. Clears cached_tap_x/y so the worker
rediscovers the tap coordinate from the new image on next use.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import ttk, messagebox
from typing import Callable

import cv2
import numpy as np

from bot.device_manager import DeviceManager
from config.devices import DeviceConfig, DetectorAssignment
from config.paths import project_root, adb_exe
from config.constants import ADB_SCREENCAP_TIMEOUT_S, DETECTION_THRESHOLD

DETECTOR_NAMES = [
    # Game states
    # Note: "crashed" is intentionally absent — CRASHED state is determined by
    # ADB process check (is Roblox running?), not by image detection. There is
    # no screen to crop for it.
    "disconnected",
    "roblox_home",
    "lobby",
    "auto_farm_on",
    "auto_farm_off",
    "death_screen",
    "net_reveal",
    "in_tank",
    "end_run_button",
    # Rejoin navigation — fast path
    "24rolla_avatar",
    "join_button",
    # Rejoin navigation — hamburger fallback
    "hamburger_menu",
    "continue_playing_button",
    "befish_game_icon",
    "game_page",
    "servers_button",
    "private_server_entry",
]

_DOT_DEVICE    = "#16a34a"
_DOT_OTHER     = "#2563eb"
_DOT_UNSET     = "#9ca3af"
_LEGEND_DOT_BG = "#1e1e1e"


class CaptureTab(ttk.Frame):

    def __init__(
        self,
        parent,
        manager: DeviceManager,
        get_devices: Callable[[], dict[str, DeviceConfig]],
        save_devices_fn: Callable[[dict[str, DeviceConfig]], None],
    ):
        """
        get_devices / save_devices_fn are the app's device store: get_devices returns the
        LIVE in-memory dict that every worker reads, save_devices_fn persists it. This tab
        edits that dict and saves it through save_devices_fn — it never writes
        devices.json itself.
        """
        super().__init__(parent)
        self._manager = manager
        self._get_devices = get_devices
        self._save_devices = save_devices_fn
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
        self._device_combo.bind("<<ComboboxSelected>>",
                                lambda e: self._on_selection_change())

        ttk.Label(top, text="Detector:").pack(side="left", padx=(0, 6))
        detector_combo = ttk.Combobox(
            top, textvariable=self._selected_detector,
            values=DETECTOR_NAMES, state="readonly", width=24)
        detector_combo.pack(side="left", padx=(0, 12))
        detector_combo.bind("<<ComboboxSelected>>",
                            lambda e: self._on_selection_change())

        ttk.Button(top, text="Open crop tool",
                   command=self._launch_crop_tool).pack(side="left")
        ttk.Button(top, text="Refresh",
                   command=self._refresh_device_list).pack(side="left", padx=(6, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12, pady=4)

        preview_outer = ttk.Frame(self, padding=(12, 4))
        preview_outer.pack(fill="x")
        self._preview_canvas = tk.Canvas(
            preview_outer, height=120, bg="#111827",
            highlightthickness=1, highlightbackground="#374151")
        self._preview_canvas.pack(fill="x")
        self._preview_canvas.create_text(
            300, 60,
            text="Select a device and detector, then open the crop tool.",
            fill="#6b7280", font=("", 10), width=400, justify="center")

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

        hdr = ttk.Frame(self, padding=(12, 0))
        hdr.pack(fill="x")
        ttk.Label(hdr, text=" ", width=2).pack(side="left")
        ttk.Label(hdr, text="Detector", width=22, foreground="#6b7280",
                  font=("", 9)).pack(side="left")
        ttk.Label(hdr, text="Image", width=24, foreground="#6b7280",
                  font=("", 9)).pack(side="left")
        ttk.Label(hdr, text="", width=8).pack(side="left")
        ttk.Label(hdr, text="", width=8).pack(side="left")
        ttk.Label(hdr, text="Score", width=7, foreground="#6b7280",
                  font=("", 9)).pack(side="left")
        ttk.Label(hdr, text="Assigned", width=22, foreground="#6b7280",
                  font=("", 9)).pack(side="left", padx=(6, 0))

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

            dot_canvas = tk.Canvas(row, width=12, height=12,
                                   highlightthickness=0, bg=_LEGEND_DOT_BG)
            dot_canvas.pack(side="left", padx=(0, 6))
            dot_id = dot_canvas.create_oval(2, 2, 10, 10, fill=_DOT_UNSET, outline="")

            ttk.Label(row, text=name, width=22, anchor="w").pack(side="left")

            img_var = tk.StringVar(value="—")
            img_combo = ttk.Combobox(row, textvariable=img_var,
                                     state="readonly", width=22)
            img_combo.pack(side="left", padx=(0, 4))

            test_btn = ttk.Button(row, text="Test", width=5,
                command=lambda n=name: self._test_detector(n))
            test_btn.pack(side="left", padx=(0, 2))

            assign_btn = ttk.Button(row, text="Assign", width=6,
                command=lambda n=name: self._assign_detector(n))
            assign_btn.pack(side="left", padx=(0, 6))

            score_lbl = ttk.Label(row, text="—", width=6,
                                   foreground="#9ca3af", font=("", 9))
            score_lbl.pack(side="left")

            tap_lbl = ttk.Label(row, text="", font=("", 9), foreground="#6b7280")
            tap_lbl.pack(side="left", padx=(4, 0))

            unassign_btn = ttk.Button(row, text="✕", width=2,
                command=lambda n=name: self._unassign_detector(n))
            unassign_btn.pack(side="left", padx=(6, 0))

            assigned_lbl = ttk.Label(row, text="not assigned",
                                     foreground="#9ca3af", font=("", 9), width=22)
            assigned_lbl.pack(side="left", padx=(6, 0))

            self._detector_rows[name] = {
                "dot_canvas": dot_canvas, "dot_id": dot_id,
                "img_var": img_var, "img_combo": img_combo,
                "test_btn": test_btn, "assign_btn": assign_btn,
                "score_lbl": score_lbl, "tap_lbl": tap_lbl,
                "unassign_btn": unassign_btn, "assigned_lbl": assigned_lbl,
            }
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
        device_path = (root / "assets" / "detectors" / detector
                       / f"{detector}_{serial}.png")
        assigned_path = None
        if cfg and detector in cfg.detector_assignments:
            fname = cfg.detector_assignments[detector].image_filename
            if fname:
                assigned_path = (root / "assets" / "detectors" / detector / fname)

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

            device_path  = (root / "assets" / "detectors" / name
                            / f"{name}_{serial}.png")
            detector_dir = root / "assets" / "detectors" / name
            any_exists   = detector_dir.exists() and any(detector_dir.glob("*.png"))
            assignment   = cfg.detector_assignments.get(name) if cfg else None

            if device_path.exists():
                dc.itemconfig(did, fill=_DOT_DEVICE)
            elif any_exists:
                dc.itemconfig(did, fill=_DOT_OTHER)
            else:
                dc.itemconfig(did, fill=_DOT_UNSET)

            available = self._list_available_images(name)
            img_combo["values"] = available if available else ["—"]

            current_selection = "—"
            if assignment and assignment.image_filename and \
               assignment.image_filename in available:
                current_selection = assignment.image_filename
            elif device_path.exists():
                current_selection = device_path.name
            elif available:
                current_selection = available[0]

            img_var.set(current_selection)

            score = None
            if assignment and assignment.image_filename == current_selection:
                score = assignment.last_score
            if score is not None:
                score_lbl.config(
                    text=f"{score:.2f}",
                    foreground="#16a34a" if score >= 0.80 else "#d97706")
            else:
                score_lbl.config(text="—", foreground="#9ca3af")

            if assignment and assignment.tap_offset_x is not None:
                tap_lbl.config(
                    text=f"tap ({assignment.tap_offset_x},{assignment.tap_offset_y})")
            else:
                tap_lbl.config(text="")

            assigned_lbl = widgets.get("assigned_lbl")
            if assigned_lbl:
                if assignment and assignment.image_filename:
                    assigned_lbl.config(
                        text=assignment.image_filename, foreground="#16a34a")
                else:
                    assigned_lbl.config(text="not assigned", foreground="#9ca3af")

    def _on_image_selection_change(self, detector_name: str) -> None:
        widgets = self._detector_rows.get(detector_name)
        if widgets:
            widgets["score_lbl"].config(text="—", foreground="#9ca3af")

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def _resolve_test_image_path(self, detector_name: str, serial: str) -> tuple[str | None, str]:
        """
        Resolve which image file the Test button should use.

        Mirrors the live bot loop's image resolution exactly:
          1. Use image_filename from devices.json detector_assignments (assigned via UI)
          2. Fall back to the dropdown selection

        Returns (path_str_or_None, source_label) where source_label is for
        the warning message if the path doesn't exist.
        """
        root = project_root()
        devices = self._get_devices()
        cfg = devices.get(serial)

        # Priority 1: assigned image from devices.json (same as live loop)
        if cfg:
            assignment = cfg.detector_assignments.get(detector_name)
            if assignment and assignment.image_filename:
                path = root / "assets" / "detectors" / detector_name / assignment.image_filename
                return str(path), f"assigned ({assignment.image_filename})"

        # Priority 2: dropdown selection (fallback for unassigned detectors)
        widgets = self._detector_rows[detector_name]
        selected_image = widgets["img_var"].get()
        if selected_image and selected_image != "—":
            path = root / "assets" / "detectors" / detector_name / selected_image
            return str(path), f"dropdown ({selected_image})"

        return None, "no image"

    def _test_detector(self, detector_name: str) -> None:
        serial = self._current_serial()
        if not serial:
            messagebox.showinfo("No device", "Select a device first.", parent=self)
            return

        image_path_str, source_label = self._resolve_test_image_path(
            detector_name, serial)

        if image_path_str is None:
            messagebox.showinfo(
                "No image",
                f"No image configured for '{detector_name}'.\n"
                "Use the crop tool to capture one first.", parent=self)
            return

        from pathlib import Path
        image_path = Path(image_path_str)
        if not image_path.exists():
            messagebox.showerror(
                "Image missing",
                f"Image file not found ({source_label}):\n{image_path}", parent=self)
            return

        widgets = self._detector_rows[detector_name]
        widgets["test_btn"].config(state="disabled", text="…")
        widgets["score_lbl"].config(text="…", foreground="#9ca3af")

        def do_test():
            try:
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
                match_result = cv2.matchTemplate(
                    frame, template, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(match_result)
                score = float(max_val)

                # Invalidate the bank cache for this detector so the live loop
                # picks up any changes on the next cycle.
                if self._manager and hasattr(self._manager, "template_bank"):
                    self._manager.template_bank.invalidate_detector(detector_name)

                self.after(0, lambda s=score: self._test_done(
                    detector_name, s, None))
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
            widgets["score_lbl"].config(text=f"{score:.2f}", foreground="#16a34a")
        else:
            widgets["score_lbl"].config(text=f"{score:.2f}", foreground="#d97706")

    # ------------------------------------------------------------------
    # Assign
    # ------------------------------------------------------------------

    def _assign_detector(self, detector_name: str) -> None:
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

        # Preserve tap_offset if the image hasn't changed; clear it if it has.
        # Always clear cached_tap_x/y — new image means new position to discover.
        same_image = (existing and existing.image_filename == selected_image)
        new_assignment = DetectorAssignment(
            image_filename=selected_image,
            last_tested=(datetime.now(timezone.utc).isoformat()
                         if score is not None
                         else (existing.last_tested if existing else None)),
            last_score=score,
            tap_offset_x=existing.tap_offset_x if (existing and same_image) else None,
            tap_offset_y=existing.tap_offset_y if (existing and same_image) else None,
            cached_tap_x=None,   # always cleared — worker rediscovers on next use
            cached_tap_y=None,
            # A property of the detector (floating position), not of the image — keep it.
            always_detect=existing.always_detect if existing else False,
        )
        cfg.detector_assignments[detector_name] = new_assignment
        self._save_devices(devices)

        if self._manager:
            self._manager.invalidate_template(detector_name, serial)

        own_image = f"{detector_name}_{serial}.png"
        if selected_image == own_image:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_DEVICE)
        else:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_OTHER)

        assigned_lbl = widgets.get("assigned_lbl")
        if assigned_lbl:
            assigned_lbl.config(text=selected_image, foreground="#16a34a")

        if self._selected_detector.get() == detector_name:
            cfg2 = self._get_devices().get(serial)
            self._update_preview(serial, detector_name, cfg2)

    # ------------------------------------------------------------------
    # Unassign
    # ------------------------------------------------------------------

    def _unassign_detector(self, detector_name: str) -> None:
        serial = self._current_serial()
        if not serial:
            return
        devices = self._get_devices()
        cfg = devices.get(serial)
        if cfg is None:
            return
        if detector_name not in cfg.detector_assignments:
            return

        del cfg.detector_assignments[detector_name]
        self._save_devices(devices)

        if self._manager:
            self._manager.invalidate_template(detector_name, serial)

        widgets = self._detector_rows[detector_name]
        widgets["score_lbl"].config(text="—", foreground="#9ca3af")
        widgets["tap_lbl"].config(text="")

        root = project_root()
        device_path = (root / "assets" / "detectors" / detector_name
                       / f"{detector_name}_{serial}.png")
        detector_dir = root / "assets" / "detectors" / detector_name
        any_exists = detector_dir.exists() and any(detector_dir.glob("*.png"))

        if device_path.exists():
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_DEVICE)
            widgets["img_var"].set(device_path.name)
        elif any_exists:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_OTHER)
            available = self._list_available_images(detector_name)
            widgets["img_var"].set(available[0] if available else "—")
        else:
            widgets["dot_canvas"].itemconfig(widgets["dot_id"], fill=_DOT_UNSET)
            widgets["img_var"].set("—")

        assigned_lbl = widgets.get("assigned_lbl")
        if assigned_lbl:
            assigned_lbl.config(text="not assigned", foreground="#9ca3af")

        cfg2 = self._get_devices().get(serial)
        if self._selected_detector.get() == detector_name:
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
                            get_devices=self._get_devices,
                            save_devices_fn=self._save_devices,
                            manager=self._manager,
                            detector_names=DETECTOR_NAMES)
            self.wait_window(tool)
            self._on_selection_change()
        except Exception as e:
            messagebox.showerror("Crop tool error", str(e), parent=self)
