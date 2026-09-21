"""
tools/crop_tool.py

Crop tool — captures a live frame, lets the user draw a box crop selection,
optionally override the tap point, then saves the image.

Circle mode has been removed — box crops only. This avoids the masking
artifacts that caused poor template match scores with circle selections.

Fixes in this version:
  - Selection drawing: Tkinter canvas does not support 8-digit hex alpha.
    Fill uses stipple pattern for transparency instead.
  - Zoom: now anchors to mouse cursor position (zoom toward/away from cursor).
  - Scrollbars added so zoomed image can be panned.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from datetime import datetime, timezone
from tkinter import messagebox, ttk
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from bot import app_logger
from config.constants import ADB_DEFAULT_TIMEOUT_S
from config.devices import DetectorAssignment, DeviceConfig
from config.paths import adb_exe, project_root

WINDOW_WIDTH  = 1000
WINDOW_HEIGHT = 720
SIDEBAR_W     = 230
HANDLE_SIZE   = 9
EDGE_HANDLE_R = 5
MIN_SELECTION = 10
ZOOM_STEP     = 0.15
MIN_ZOOM      = 0.2
MAX_ZOOM      = 5.0


class CropTool(tk.Toplevel):

    def __init__(self, parent, serial: str, detector_name: str,
                 get_devices, save_devices_fn,
                 manager=None, detector_names: list = None):
        """
        get_devices / save_devices_fn are the app's device store: get_devices returns the
        LIVE in-memory dict every worker reads, save_devices_fn persists it. Save edits that
        dict and saves it through save_devices_fn, so the running workers see the new
        assignment immediately and a later save from elsewhere cannot overwrite it with a
        stale copy. This tool never reads or writes devices.json itself.
        """
        super().__init__(parent)
        self._serial = serial
        self._detector_name = detector_name
        self._get_devices = get_devices
        self._save_devices = save_devices_fn
        self._manager = manager
        self._detector_names = detector_names or [
            "disconnected", "crashed", "roblox_home", "lobby",
            "auto_farm_on", "auto_farm_off", "death_screen",
            "net_reveal", "in_tank", "end_run_button",
        ]

        self._frame: Optional[np.ndarray] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0

        # Box selection state: x1,y1,x2,y2 in frame coords
        self._sel: Optional[dict] = None
        self._drag_mode: Optional[str] = None
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_sel_snapshot: Optional[dict] = None

        self._tap_mode = tk.StringVar(value="center")
        self._tap_offset: Optional[Tuple[int, int]] = None

        self.title(f"Crop tool — {serial[:12]} · {detector_name}")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(700, 500)
        self.grab_set()
        self._build()
        self._center_on_parent(parent)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

    def _build_toolbar(self) -> None:
        tb = ttk.Frame(self, padding=(8, 6))
        tb.grid(row=0, column=0, sticky="ew")

        ttk.Button(tb, text="Capture frame",
                   command=self._capture).pack(side="left", padx=(0, 8))
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Label(tb, text="Zoom").pack(side="left")
        ttk.Button(tb, text="−", width=2,
                   command=lambda: self._adj_zoom(-ZOOM_STEP)).pack(side="left", padx=2)
        self._zoom_label = ttk.Label(tb, text="100%", width=5, anchor="center")
        self._zoom_label.pack(side="left")
        ttk.Button(tb, text="+", width=2,
                   command=lambda: self._adj_zoom(ZOOM_STEP)).pack(side="left", padx=2)
        ttk.Button(tb, text="Fit",
                   command=self._zoom_fit).pack(side="left", padx=(2, 0))

        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Label(tb, text="Detector:").pack(side="left")
        self._detector_var = tk.StringVar(value=self._detector_name)
        self._detector_combo = ttk.Combobox(
            tb, textvariable=self._detector_var,
            values=self._detector_names, state="readonly", width=22,
        )
        self._detector_combo.pack(side="left", padx=(2, 0))
        self._detector_combo.bind("<<ComboboxSelected>>", self._on_detector_change)

        self._status_label = ttk.Label(tb, text="Capture a frame to begin.",
                                        foreground="#888")
        self._status_label.pack(side="right")

    def _build_body(self) -> None:
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(
            body, bg="#111827", cursor="crosshair",
            highlightthickness=0, xscrollincrement=1, yscrollincrement=1)
        h_scroll = ttk.Scrollbar(body, orient="horizontal",
                                  command=self._canvas.xview)
        v_scroll = ttk.Scrollbar(body, orient="vertical",
                                  command=self._canvas.yview)
        self._canvas.configure(xscrollcommand=h_scroll.set,
                                yscrollcommand=v_scroll.set)

        self._canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self._canvas.bind("<ButtonPress-1>",   self._on_mouse_down)
        self._canvas.bind("<B1-Motion>",       self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self._canvas.bind("<Motion>",          self._on_mouse_move)
        self._canvas.bind("<MouseWheel>",      self._on_scroll)
        self._canvas.bind("<Button-4>",        self._on_scroll)
        self._canvas.bind("<Button-5>",        self._on_scroll)

        sidebar = ttk.Frame(body, width=SIDEBAR_W, padding=(10, 10))
        sidebar.grid(row=0, column=2, sticky="ns")
        sidebar.columnconfigure(0, weight=1)
        sidebar.grid_propagate(False)
        self._build_sidebar(sidebar)

    def _build_sidebar(self, f: ttk.Frame) -> None:
        ttk.Label(f, text="DETECTOR", font=("", 9),
                  foreground="#888").grid(row=0, column=0, sticky="w")
        self._det_name_label = ttk.Label(f, text=self._detector_name,
                                          font=("", 12, "bold"))
        self._det_name_label.grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(f, text=self._serial[:16], foreground="#888",
                  font=("", 9)).grid(row=2, column=0, sticky="w", pady=(0, 10))

        ttk.Separator(f, orient="horizontal").grid(
            row=3, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(f, text="PREVIEW", font=("", 9),
                  foreground="#888").grid(row=4, column=0, sticky="w")
        self._preview_canvas = tk.Canvas(
            f, width=SIDEBAR_W - 20, height=80, bg="#111827",
            highlightthickness=1, highlightbackground="#374151")
        self._preview_canvas.grid(row=5, column=0, sticky="ew", pady=(4, 0))

        self._crop_info = ttk.Label(f, text="No selection",
                                     foreground="#888", font=("", 9))
        self._crop_info.grid(row=6, column=0, sticky="w", pady=(4, 0))

        ttk.Separator(f, orient="horizontal").grid(
            row=7, column=0, sticky="ew", pady=8)

        ttk.Label(f, text="TAP COORDINATE", font=("", 9),
                  foreground="#888").grid(row=8, column=0, sticky="w")
        ttk.Radiobutton(f, text="Use center (default)",
                        variable=self._tap_mode, value="center",
                        command=self._on_tap_mode_change).grid(
            row=9, column=0, sticky="w", pady=1)
        ttk.Radiobutton(f, text="Override tap point",
                        variable=self._tap_mode, value="override",
                        command=self._on_tap_mode_change).grid(
            row=10, column=0, sticky="w", pady=1)

        self._tap_info_frame = ttk.Frame(f)
        self._tap_info_frame.grid(row=11, column=0, sticky="ew", pady=(6, 0))
        self._tap_info_label = ttk.Label(
            self._tap_info_frame, text="Tap: center of crop",
            foreground="#888", font=("", 9), wraplength=SIDEBAR_W - 20)
        self._tap_info_label.pack(anchor="w")

        self._clear_override_btn = ttk.Button(
            f, text="Clear override", command=self._clear_tap_override)

        ttk.Separator(f, orient="horizontal").grid(
            row=12, column=0, sticky="ew", pady=8)

        self._save_btn = ttk.Button(f, text="Save crop",
                                     command=self._save, state="disabled")
        self._save_btn.grid(row=13, column=0, sticky="ew")
        ttk.Button(f, text="Discard", command=self.destroy).grid(
            row=14, column=0, sticky="ew", pady=(4, 0))

    def _build_statusbar(self) -> None:
        sb = ttk.Frame(self, padding=(8, 4))
        sb.grid(row=2, column=0, sticky="ew")
        self._sb_left  = ttk.Label(sb, text="", foreground="#888", font=("", 9))
        self._sb_left.pack(side="left")
        self._sb_right = ttk.Label(sb, text="", foreground="#888", font=("", 9))
        self._sb_right.pack(side="right")

    def _center_on_parent(self, parent) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width()  // 2 - self.winfo_width()  // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

    def _on_detector_change(self, event=None) -> None:
        self._detector_name = self._detector_var.get()
        self._sel = None
        self._tap_offset = None
        self._tap_mode.set("center")
        self._save_btn.config(state="disabled")
        self._redraw()
        self._update_sidebar()
        self.title(f"Crop tool — {self._serial[:12]} · {self._detector_name}")
        try:
            self._det_name_label.config(text=self._detector_name)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _capture(self) -> None:
        self._set_status("Capturing frame...")
        def do_capture():
            try:
                result = subprocess.run(
                    [adb_exe(), "-s", self._serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=ADB_DEFAULT_TIMEOUT_S,
                )
                if result.returncode != 0 or not result.stdout:
                    self.after(0, lambda: self._set_status(
                        "Capture failed.", error=True))
                    return
                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.after(0, lambda: self._set_status(
                        "Could not decode screenshot.", error=True))
                    return
                self.after(0, lambda f=frame: self._show_frame(f))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"Error: {e}", error=True))
        threading.Thread(target=do_capture, daemon=True).start()

    def _show_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        self._sel = None
        self._tap_offset = None
        self._zoom_fit()
        h, w = frame.shape[:2]
        self._sb_left.config(
            text=f"Frame: {w}×{h}  ·  Drag to draw  ·  Scroll to zoom")
        self._set_status(f"Frame captured · {w}×{h}")
        self._update_sidebar()

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------

    def _adj_zoom(self, delta: float, mouse_cx: int = None,
                  mouse_cy: int = None) -> None:
        old_zoom = self._zoom
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom + delta))
        if new_zoom == old_zoom:
            return
        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        ax = mouse_cx if mouse_cx is not None else cw // 2
        ay = mouse_cy if mouse_cy is not None else ch // 2
        frame_x = (ax - self._pan_x) / old_zoom
        frame_y = (ay - self._pan_y) / old_zoom
        self._pan_x = int(ax - frame_x * new_zoom)
        self._pan_y = int(ay - frame_y * new_zoom)
        self._zoom = new_zoom
        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

    def _zoom_fit(self) -> None:
        if self._frame is None:
            return
        cw = self._canvas.winfo_width()  or WINDOW_WIDTH - SIDEBAR_W
        ch = self._canvas.winfo_height() or WINDOW_HEIGHT - 80
        h, w = self._frame.shape[:2]
        self._zoom = min(cw / w, ch / h, 1.0)
        self._pan_x = (cw - int(w * self._zoom)) // 2
        self._pan_y = (ch - int(h * self._zoom)) // 2
        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

    def _on_scroll(self, event) -> None:
        if self._frame is None:
            return
        delta = ZOOM_STEP if (event.num == 4 or event.delta > 0) else -ZOOM_STEP
        self._adj_zoom(delta,
                       mouse_cx=int(self._canvas.canvasx(event.x)),
                       mouse_cy=int(self._canvas.canvasy(event.y)))

    def _update_scroll_region(self) -> None:
        if self._frame is None:
            return
        h, w = self._frame.shape[:2]
        nw = int(w * self._zoom)
        nh = int(h * self._zoom)
        x0 = min(0, self._pan_x)
        y0 = min(0, self._pan_y)
        x1 = max(self._canvas.winfo_width(),  self._pan_x + nw)
        y1 = max(self._canvas.winfo_height(), self._pan_y + nh)
        self._canvas.configure(scrollregion=(x0, y0, x1, y1))

    # ------------------------------------------------------------------
    # Coordinate conversions
    # ------------------------------------------------------------------

    def _canvas_to_frame(self, cx: int, cy: int) -> Tuple[int, int]:
        fx = int((cx - self._pan_x) / self._zoom)
        fy = int((cy - self._pan_y) / self._zoom)
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            fx = max(0, min(fx, w - 1))
            fy = max(0, min(fy, h - 1))
        return fx, fy

    def _frame_to_canvas(self, fx: int, fy: int) -> Tuple[int, int]:
        return (int(fx * self._zoom + self._pan_x),
                int(fy * self._zoom + self._pan_y))

    # ------------------------------------------------------------------
    # Selection (box only)
    # ------------------------------------------------------------------

    def _empty_sel(self) -> dict:
        return {"x1": 0, "y1": 0, "x2": 0, "y2": 0}

    def _sel_contains(self, cx: int, cy: int) -> bool:
        if self._sel is None:
            return False
        x1c, y1c = self._frame_to_canvas(self._sel["x1"], self._sel["y1"])
        x2c, y2c = self._frame_to_canvas(self._sel["x2"], self._sel["y2"])
        return x1c <= cx <= x2c and y1c <= cy <= y2c

    def _hit_handle(self, cx: int, cy: int) -> Optional[str]:
        if self._sel is None:
            return None
        tol = HANDLE_SIZE + 3
        x1c, y1c = self._frame_to_canvas(self._sel["x1"], self._sel["y1"])
        x2c, y2c = self._frame_to_canvas(self._sel["x2"], self._sel["y2"])
        mxc = (x1c + x2c) // 2
        myc = (y1c + y2c) // 2
        handles = {
            "corner:nw": (x1c, y1c), "corner:ne": (x2c, y1c),
            "corner:sw": (x1c, y2c), "corner:se": (x2c, y2c),
            "edge:n":    (mxc, y1c), "edge:s":    (mxc, y2c),
            "edge:w":    (x1c, myc), "edge:e":    (x2c, myc),
        }
        for name, (hx, hy) in handles.items():
            if abs(cx - hx) <= tol and abs(cy - hy) <= tol:
                return name
        return None

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def _on_mouse_down(self, event) -> None:
        if self._frame is None:
            return
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        handle = self._hit_handle(cx, cy)

        if (self._tap_mode.get() == "override"
                and self._sel is not None
                and handle is None
                and self._sel_contains(cx, cy)):
            self._place_tap_override(cx, cy)
            return

        if handle:
            self._drag_mode = handle
            self._drag_start = (cx, cy)
            self._drag_sel_snapshot = dict(self._sel)
        elif self._sel_contains(cx, cy):
            self._drag_mode = "move"
            self._drag_start = (cx, cy)
            self._drag_sel_snapshot = dict(self._sel)
        else:
            self._sel = self._empty_sel()
            self._tap_offset = None
            self._tap_mode.set("center")
            fx, fy = self._canvas_to_frame(cx, cy)
            self._sel.update(x1=fx, y1=fy, x2=fx, y2=fy)
            self._drag_mode = "draw"
            self._drag_start = (cx, cy)
            self._drag_sel_snapshot = dict(self._sel)

    def _on_mouse_drag(self, event) -> None:
        if self._drag_mode is None or self._frame is None:
            return
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        dx_f = int((cx - self._drag_start[0]) / self._zoom)
        dy_f = int((cy - self._drag_start[1]) / self._zoom)
        snap = self._drag_sel_snapshot
        h, w = self._frame.shape[:2]

        def clamp(v, lo, hi):
            return max(lo, min(v, hi))

        if self._drag_mode == "draw":
            fx, fy = self._canvas_to_frame(cx, cy)
            ox, oy = snap["x1"], snap["y1"]
            self._sel.update(
                x1=min(ox, fx), y1=min(oy, fy),
                x2=max(ox, fx), y2=max(oy, fy))

        elif self._drag_mode == "move":
            bw = snap["x2"] - snap["x1"]
            bh = snap["y2"] - snap["y1"]
            nx1 = clamp(snap["x1"] + dx_f, 0, w - 1)
            ny1 = clamp(snap["y1"] + dy_f, 0, h - 1)
            self._sel.update(
                x1=nx1, y1=ny1,
                x2=clamp(nx1 + bw, 0, w - 1),
                y2=clamp(ny1 + bh, 0, h - 1))

        elif self._drag_mode.startswith("corner:"):
            c = self._drag_mode.split(":")[1]
            if c == "nw":
                self._sel.update(
                    x1=clamp(snap["x1"]+dx_f, 0, snap["x2"]-1),
                    y1=clamp(snap["y1"]+dy_f, 0, snap["y2"]-1))
            elif c == "ne":
                self._sel.update(
                    x2=clamp(snap["x2"]+dx_f, snap["x1"]+1, w-1),
                    y1=clamp(snap["y1"]+dy_f, 0, snap["y2"]-1))
            elif c == "sw":
                self._sel.update(
                    x1=clamp(snap["x1"]+dx_f, 0, snap["x2"]-1),
                    y2=clamp(snap["y2"]+dy_f, snap["y1"]+1, h-1))
            elif c == "se":
                self._sel.update(
                    x2=clamp(snap["x2"]+dx_f, snap["x1"]+1, w-1),
                    y2=clamp(snap["y2"]+dy_f, snap["y1"]+1, h-1))

        elif self._drag_mode.startswith("edge:"):
            e = self._drag_mode.split(":")[1]
            if e == "n":
                self._sel.update(y1=clamp(snap["y1"]+dy_f, 0, snap["y2"]-1))
            elif e == "s":
                self._sel.update(y2=clamp(snap["y2"]+dy_f, snap["y1"]+1, h-1))
            elif e == "w":
                self._sel.update(x1=clamp(snap["x1"]+dx_f, 0, snap["x2"]-1))
            elif e == "e":
                self._sel.update(x2=clamp(snap["x2"]+dx_f, snap["x1"]+1, w-1))

        self._redraw()
        self._update_sidebar()

    def _on_mouse_up(self, event) -> None:
        self._drag_mode = None
        self._drag_start = None
        self._drag_sel_snapshot = None
        if self._sel is not None:
            valid = self._sel_is_valid()
            self._save_btn.config(state="normal" if valid else "disabled")
            if not valid:
                self._sel = None
                self._redraw()
                self._update_sidebar()

    def _on_mouse_move(self, event) -> None:
        if self._frame is None:
            return
        cx = int(self._canvas.canvasx(event.x))
        cy = int(self._canvas.canvasy(event.y))
        fx, fy = self._canvas_to_frame(cx, cy)
        self._sb_right.config(text=f"Screen: ({fx}, {fy})")
        handle = self._hit_handle(cx, cy)
        if handle:
            cursors = {
                "corner:nw": "top_left_corner",  "corner:ne": "top_right_corner",
                "corner:sw": "bottom_left_corner","corner:se": "bottom_right_corner",
                "edge:n": "top_side",  "edge:s": "bottom_side",
                "edge:w": "left_side", "edge:e": "right_side",
            }
            self._canvas.config(cursor=cursors.get(handle, "crosshair"))
        elif self._sel_contains(cx, cy):
            self._canvas.config(cursor="fleur")
        else:
            self._canvas.config(cursor="crosshair")

    # ------------------------------------------------------------------
    # Tap override
    # ------------------------------------------------------------------

    def _on_tap_mode_change(self) -> None:
        if self._tap_mode.get() == "center":
            self._tap_offset = None
        self._redraw()
        self._update_sidebar()

    def _place_tap_override(self, cx: int, cy: int) -> None:
        if self._sel is None:
            return
        fx, fy = self._canvas_to_frame(cx, cy)
        ox = fx - self._sel["x1"]
        oy = fy - self._sel["y1"]
        self._tap_offset = (max(0, ox), max(0, oy))
        self._redraw()
        self._update_sidebar()

    def _clear_tap_override(self) -> None:
        self._tap_offset = None
        self._tap_mode.set("center")
        self._redraw()
        self._update_sidebar()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        if self._frame is None:
            return
        self._canvas.delete("all")

        h, w = self._frame.shape[:2]
        nw, nh = int(w * self._zoom), int(h * self._zoom)
        rgb = cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)
        self._canvas.create_image(self._pan_x, self._pan_y,
                                   anchor="nw", image=self._photo)
        self._update_scroll_region()

        if self._sel is not None and self._sel_is_valid():
            self._draw_box_selection()

            if self._tap_offset is not None:
                tdx = self._sel["x1"] + self._tap_offset[0]
                tdy = self._sel["y1"] + self._tap_offset[1]
                tcx, tcy = self._frame_to_canvas(tdx, tdy)
                self._canvas.create_oval(
                    tcx-5, tcy-5, tcx+5, tcy+5,
                    fill="#f59e0b", outline="white", width=2)

    def _draw_box_selection(self) -> None:
        s = self._sel
        x1c, y1c = self._frame_to_canvas(s["x1"], s["y1"])
        x2c, y2c = self._frame_to_canvas(s["x2"], s["y2"])
        mxc = (x1c + x2c) // 2
        myc = (y1c + y2c) // 2

        self._canvas.create_rectangle(
            x1c, y1c, x2c, y2c,
            outline="#60a5fa", width=2,
            fill="#4488ff", stipple="gray25")

        hs = HANDLE_SIZE
        for hx, hy in [(x1c,y1c),(x2c,y1c),(x1c,y2c),(x2c,y2c)]:
            self._canvas.create_rectangle(
                hx-hs, hy-hs, hx+hs, hy+hs,
                fill="#60a5fa", outline="white", width=1)

        er = EDGE_HANDLE_R
        for hx, hy in [(mxc,y1c),(mxc,y2c),(x1c,myc),(x2c,myc)]:
            self._canvas.create_oval(
                hx-er, hy-er, hx+er, hy+er,
                fill="#93c5fd", outline="white", width=1)

        cw = self._canvas.winfo_width()
        ch = self._canvas.winfo_height()
        self._canvas.create_line(0, y1c, cw, y1c, fill="#4488ff", dash=(4, 4))
        self._canvas.create_line(0, y2c, cw, y2c, fill="#4488ff", dash=(4, 4))
        self._canvas.create_line(x1c, 0, x1c, ch, fill="#4488ff", dash=(4, 4))
        self._canvas.create_line(x2c, 0, x2c, ch, fill="#4488ff", dash=(4, 4))

    # ------------------------------------------------------------------
    # Sidebar
    # ------------------------------------------------------------------

    def _update_sidebar(self) -> None:
        self._update_preview()
        if self._sel is None or not self._sel_is_valid():
            self._crop_info.config(text="No selection")
            self._tap_info_label.config(text="Tap: center of crop")
            self._clear_override_btn.grid_forget()
            return

        s = self._sel
        self._crop_info.config(
            text=f"{s['x2']-s['x1']}×{s['y2']-s['y1']} px  ({s['x1']},{s['y1']})")

        if self._tap_offset is not None:
            self._tap_info_label.config(
                text=f"Override: ({self._tap_offset[0]}, {self._tap_offset[1]}) within crop")
            self._clear_override_btn.grid(row=12, column=0, sticky="w", pady=(4, 0))
        else:
            self._tap_info_label.config(text="Tap: center of crop")
            self._clear_override_btn.grid_forget()

    def _update_preview(self) -> None:
        self._preview_canvas.delete("all")
        if self._frame is None or self._sel is None or not self._sel_is_valid():
            self._preview_canvas.create_text(
                (SIDEBAR_W-20)//2, 40, text="No selection",
                fill="#6b7280", font=("", 9))
            return

        crop = self._get_crop_image()
        if crop is None:
            return

        pw, ph = SIDEBAR_W - 20, 80
        ch2, cw2 = crop.shape[:2]
        scale = min(pw / cw2, ph / ch2, 1.0)
        nw2, nh2 = max(1, int(cw2*scale)), max(1, int(ch2*scale))
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw2, nh2), Image.LANCZOS)
        self._prev_photo = ImageTk.PhotoImage(pil)
        ox, oy = (pw - nw2) // 2, (ph - nh2) // 2
        self._preview_canvas.create_image(ox, oy, anchor="nw",
                                           image=self._prev_photo)

        if self._tap_offset is not None:
            tx = ox + int(self._tap_offset[0] * scale)
            ty = oy + int(self._tap_offset[1] * scale)
            self._preview_canvas.create_oval(
                tx-4, ty-4, tx+4, ty+4,
                fill="#f59e0b", outline="white", width=1)

    # ------------------------------------------------------------------
    # Crop
    # ------------------------------------------------------------------

    def _sel_is_valid(self) -> bool:
        if self._sel is None:
            return False
        return (self._sel["x2"] - self._sel["x1"] >= MIN_SELECTION and
                self._sel["y2"] - self._sel["y1"] >= MIN_SELECTION)

    def _get_crop_image(self) -> Optional[np.ndarray]:
        if self._frame is None or self._sel is None:
            return None
        fh, fw = self._frame.shape[:2]
        x1 = max(0, self._sel["x1"])
        y1 = max(0, self._sel["y1"])
        x2 = min(fw, self._sel["x2"])
        y2 = min(fh, self._sel["y2"])
        return self._frame[y1:y2, x1:x2].copy()

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not self._sel_is_valid():
            messagebox.showwarning("No selection",
                                   "Draw a crop region first.", parent=self)
            return
        crop = self._get_crop_image()
        if crop is None:
            messagebox.showerror("Error",
                                 "Could not extract crop image.", parent=self)
            return

        root = project_root()
        detector_dir = root / "assets" / "detectors" / self._detector_name
        detector_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._detector_name}_{self._serial}.png"
        save_path = detector_dir / filename

        if not cv2.imwrite(str(save_path), crop):
            messagebox.showerror("Save failed",
                                 f"Could not write to:\n{save_path}", parent=self)
            return

        devices = self._get_devices()          # the LIVE dict — never a disk snapshot
        cfg = devices.get(self._serial)
        if cfg is None:
            cfg = DeviceConfig(serial=self._serial)
            devices[self._serial] = cfg

        existing = cfg.detector_assignments.get(self._detector_name)
        cfg.detector_assignments[self._detector_name] = DetectorAssignment(
            image_filename=filename,
            last_tested=datetime.now(timezone.utc).isoformat(),
            last_score=None,
            tap_offset_x=self._tap_offset[0] if self._tap_offset else None,
            tap_offset_y=self._tap_offset[1] if self._tap_offset else None,
            cached_tap_x=None,   # cleared on new image assign
            cached_tap_y=None,
            # A property of the detector (floating position), not of the image — keep it.
            always_detect=existing.always_detect if existing else False,
        )
        self._save_devices(devices)

        if self._manager is not None:
            self._manager.invalidate_template(self._detector_name, self._serial)

        app_logger.log(
            f"[crop_tool] Saved {self._detector_name} for "
            f"{self._serial[:8]} → {filename}", "INFO")
        self._set_status(f"Saved → {save_path.name}", color="#16a34a")
        self.after(1200, self.destroy)

    def _set_status(self, msg: str, error: bool = False,
                    color: Optional[str] = None) -> None:
        c = color if color else ("#dc2626" if error else "#888")
        self._status_label.config(text=msg, foreground=c)
