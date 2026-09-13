"""
tools/crop_tool.py

Crop tool — captures a live frame from a device, lets the user draw a
crop selection (box or circle), optionally override the tap point within
the crop, then saves the image to the correct detector asset path.

Replaces the old coordinate_finder.py entirely.

Interaction model:
  - Drag on empty canvas  : draw a new selection
  - Drag inside selection : move the whole selection
  - Drag corner handle    : resize box (stays rectangular)
  - Drag edge handle      : resize one axis (box) or radius (circle)
  - Scroll                : zoom in/out
  - Zoom +/- buttons      : same as scroll
  - Fit button            : reset zoom to fit frame in window

Box handles:
  4 corner handles (square) — resize from that corner, maintain 90°
  4 edge midpoint handles (round) — resize one axis only

Circle handles:
  2 handles (top and right) — both adjust radius uniformly

Tap override:
  Radio: "Use center" (default) or "Override tap point"
  When override is active, click anywhere inside the selection to place
  the amber tap dot. Saved as tap_offset_x/y within the crop image.
"""

from __future__ import annotations

import math
import subprocess
import threading
import tkinter as tk
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from bot import app_logger
from config.constants import ADB_DEFAULT_TIMEOUT_S
from config.devices import DetectorAssignment, DeviceConfig, load_devices, save_devices
from config.paths import project_root

# ---------------------------------------------------------------------------
# Layout constants [INTERNAL]
# ---------------------------------------------------------------------------
WINDOW_WIDTH  = 1000
WINDOW_HEIGHT = 720
SIDEBAR_W     = 230
HANDLE_SIZE   = 9     # corner handle half-size in canvas pixels
EDGE_HANDLE_R = 5     # edge handle radius in canvas pixels
MIN_SELECTION = 10    # minimum selection size in canvas pixels
ZOOM_STEP     = 0.15
MIN_ZOOM      = 0.2
MAX_ZOOM      = 5.0


class CropTool(tk.Toplevel):
    """
    Modal crop tool window.

    Opens from the Capture tab. After the user saves, the result is
    written to disk and the TemplateBank cache is invalidated.

    Args:
        parent          : parent Tkinter widget
        serial          : ADB device serial
        detector_name   : which detector this crop is for
        manager         : DeviceManager (for TemplateBank.invalidate)
    """

    def __init__(
        self,
        parent,
        serial: str,
        detector_name: str,
        manager=None,
    ):
        super().__init__(parent)
        self._serial = serial
        self._detector_name = detector_name
        self._manager = manager

        # Frame state
        self._frame: Optional[np.ndarray] = None       # full-res BGR frame
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._zoom = 1.0
        self._pan_x = 0   # canvas offset for the image origin
        self._pan_y = 0

        # Selection state
        self._shape = tk.StringVar(value="box")
        self._sel: Optional[dict] = None   # see _empty_sel()
        self._drag_mode: Optional[str] = None  # "draw"|"move"|"corner:nw"|"edge:n" etc.
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_sel_snapshot: Optional[dict] = None

        # Tap override
        self._tap_mode = tk.StringVar(value="center")
        self._tap_offset: Optional[Tuple[int, int]] = None  # within crop image pixels

        self.title(f"Crop tool — {serial[:12]} · {detector_name}")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(700, 500)
        self.grab_set()

        self._build()
        self._center_on_parent(parent)

    # ------------------------------------------------------------------
    # UI construction
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

        ttk.Button(tb, text="Capture frame", command=self._capture).pack(side="left", padx=(0, 8))

        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Label(tb, text="Zoom").pack(side="left")
        ttk.Button(tb, text="−", width=2, command=lambda: self._adj_zoom(-ZOOM_STEP)).pack(side="left", padx=2)
        self._zoom_label = ttk.Label(tb, text="100%", width=5, anchor="center")
        self._zoom_label.pack(side="left")
        ttk.Button(tb, text="+", width=2, command=lambda: self._adj_zoom(ZOOM_STEP)).pack(side="left", padx=2)
        ttk.Button(tb, text="Fit", command=self._zoom_fit).pack(side="left", padx=(2, 0))

        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)

        ttk.Label(tb, text="Shape").pack(side="left")
        ttk.Radiobutton(tb, text="Box",    variable=self._shape, value="box",    command=self._on_shape_change).pack(side="left", padx=2)
        ttk.Radiobutton(tb, text="Circle", variable=self._shape, value="circle", command=self._on_shape_change).pack(side="left", padx=2)

        self._status_label = ttk.Label(tb, text="Capture a frame to begin.", foreground="#888")
        self._status_label.pack(side="right")

    def _build_body(self) -> None:
        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        # Canvas
        self._canvas = tk.Canvas(body, bg="#111827", cursor="crosshair", highlightthickness=0)
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<ButtonPress-1>",   self._on_mouse_down)
        self._canvas.bind("<B1-Motion>",       self._on_mouse_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self._canvas.bind("<Motion>",          self._on_mouse_move)
        self._canvas.bind("<MouseWheel>",      self._on_scroll)
        self._canvas.bind("<Button-4>",        self._on_scroll)
        self._canvas.bind("<Button-5>",        self._on_scroll)

        # Sidebar
        sidebar = ttk.Frame(body, width=SIDEBAR_W, padding=(10, 10))
        sidebar.grid(row=0, column=1, sticky="ns")
        sidebar.columnconfigure(0, weight=1)
        sidebar.grid_propagate(False)
        self._build_sidebar(sidebar)

    def _build_sidebar(self, f: ttk.Frame) -> None:
        # Detector info
        ttk.Label(f, text="DETECTOR", font=("", 9), foreground="#888").grid(row=0, column=0, sticky="w")
        ttk.Label(f, text=self._detector_name, font=("", 12, "bold")).grid(row=1, column=0, sticky="w", pady=(2, 0))
        ttk.Label(f, text=self._serial[:16], foreground="#888", font=("", 9)).grid(row=2, column=0, sticky="w", pady=(0, 10))

        ttk.Separator(f, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=(0, 8))

        # Crop preview
        ttk.Label(f, text="PREVIEW", font=("", 9), foreground="#888").grid(row=4, column=0, sticky="w")
        self._preview_canvas = tk.Canvas(f, width=SIDEBAR_W - 20, height=80, bg="#111827",
                                          highlightthickness=1, highlightbackground="#374151")
        self._preview_canvas.grid(row=5, column=0, sticky="ew", pady=(4, 0))

        self._crop_info = ttk.Label(f, text="No selection", foreground="#888", font=("", 9))
        self._crop_info.grid(row=6, column=0, sticky="w", pady=(4, 0))

        ttk.Separator(f, orient="horizontal").grid(row=7, column=0, sticky="ew", pady=8)

        # Tap coordinate
        ttk.Label(f, text="TAP COORDINATE", font=("", 9), foreground="#888").grid(row=8, column=0, sticky="w")
        ttk.Radiobutton(f, text="Use center (default)",
                        variable=self._tap_mode, value="center",
                        command=self._on_tap_mode_change).grid(row=9, column=0, sticky="w", pady=1)
        ttk.Radiobutton(f, text="Override tap point",
                        variable=self._tap_mode, value="override",
                        command=self._on_tap_mode_change).grid(row=10, column=0, sticky="w", pady=1)

        self._tap_info_frame = ttk.Frame(f)
        self._tap_info_frame.grid(row=11, column=0, sticky="ew", pady=(6, 0))
        self._tap_info_label = ttk.Label(self._tap_info_frame, text="Tap: center of crop",
                                          foreground="#888", font=("", 9), wraplength=SIDEBAR_W - 20)
        self._tap_info_label.pack(anchor="w")

        self._clear_override_btn = ttk.Button(f, text="Clear override", command=self._clear_tap_override)
        # shown only when override is set

        ttk.Separator(f, orient="horizontal").grid(row=12, column=0, sticky="ew", pady=8)

        # Action buttons
        self._save_btn = ttk.Button(f, text="Save crop", command=self._save, state="disabled")
        self._save_btn.grid(row=13, column=0, sticky="ew")
        ttk.Button(f, text="Discard", command=self.destroy).grid(row=14, column=0, sticky="ew", pady=(4, 0))

    def _build_statusbar(self) -> None:
        sb = ttk.Frame(self, padding=(8, 4))
        sb.grid(row=2, column=0, sticky="ew")
        self._sb_left  = ttk.Label(sb, text="", foreground="#888", font=("", 9))
        self._sb_left.pack(side="left")
        self._sb_right = ttk.Label(sb, text="", foreground="#888", font=("", 9))
        self._sb_right.pack(side="right")

    def _center_on_parent(self, parent) -> None:
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_width() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 2 - self.winfo_height() // 2
        self.geometry(f"+{max(0, px)}+{max(0, py)}")

    # ------------------------------------------------------------------
    # Frame capture
    # ------------------------------------------------------------------

    def _capture(self) -> None:
        self._set_status("Capturing frame...")
        def do_capture():
            try:
                result = subprocess.run(
                    ["adb", "-s", self._serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=ADB_DEFAULT_TIMEOUT_S,
                )
                if result.returncode != 0 or not result.stdout:
                    self.after(0, lambda: self._set_status("Capture failed — check ADB connection.", error=True))
                    return
                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.after(0, lambda: self._set_status("Could not decode screenshot.", error=True))
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
        self._sb_left.config(text=f"Frame: {w}×{h}  ·  Drag to draw selection  ·  Scroll to zoom")
        self._set_status(f"Frame captured · {w}×{h}")
        self._update_sidebar()

    # ------------------------------------------------------------------
    # Zoom & pan
    # ------------------------------------------------------------------

    def _adj_zoom(self, delta: float) -> None:
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom + delta))
        self._zoom_label.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

    def _zoom_fit(self) -> None:
        if self._frame is None:
            return
        cw = self._canvas.winfo_width() or WINDOW_WIDTH - SIDEBAR_W
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
        if event.num == 4 or event.delta > 0:
            self._adj_zoom(ZOOM_STEP)
        else:
            self._adj_zoom(-ZOOM_STEP)

    # ------------------------------------------------------------------
    # Coordinate conversions
    # ------------------------------------------------------------------

    def _canvas_to_frame(self, cx: int, cy: int) -> Tuple[int, int]:
        """Convert canvas pixel → frame pixel."""
        fx = int((cx - self._pan_x) / self._zoom)
        fy = int((cy - self._pan_y) / self._zoom)
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            fx = max(0, min(fx, w - 1))
            fy = max(0, min(fy, h - 1))
        return fx, fy

    def _frame_to_canvas(self, fx: int, fy: int) -> Tuple[int, int]:
        """Convert frame pixel → canvas pixel."""
        return int(fx * self._zoom + self._pan_x), int(fy * self._zoom + self._pan_y)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    def _empty_sel(self) -> dict:
        return {
            "shape": self._shape.get(),
            # box: x1,y1,x2,y2 in frame pixels (always x1<x2, y1<y2)
            "x1": 0, "y1": 0, "x2": 0, "y2": 0,
            # circle: cx,cy,r in frame pixels
            "cx": 0, "cy": 0, "r": 0,
        }

    def _sel_contains(self, cx: int, cy: int) -> bool:
        """Is canvas point (cx, cy) inside the current selection?"""
        if self._sel is None:
            return False
        if self._sel["shape"] == "box":
            x1c, y1c = self._frame_to_canvas(self._sel["x1"], self._sel["y1"])
            x2c, y2c = self._frame_to_canvas(self._sel["x2"], self._sel["y2"])
            return x1c <= cx <= x2c and y1c <= cy <= y2c
        else:
            ccx, ccy = self._frame_to_canvas(self._sel["cx"], self._sel["cy"])
            rc = self._sel["r"] * self._zoom
            return math.hypot(cx - ccx, cy - ccy) <= rc

    def _hit_handle(self, cx: int, cy: int) -> Optional[str]:
        """Return which handle (if any) is at canvas point (cx, cy)."""
        if self._sel is None:
            return None
        tol = HANDLE_SIZE + 3

        if self._sel["shape"] == "box":
            x1c, y1c = self._frame_to_canvas(self._sel["x1"], self._sel["y1"])
            x2c, y2c = self._frame_to_canvas(self._sel["x2"], self._sel["y2"])
            mxc, myc = (x1c + x2c) // 2, (y1c + y2c) // 2
            handles = {
                "corner:nw": (x1c, y1c), "corner:ne": (x2c, y1c),
                "corner:sw": (x1c, y2c), "corner:se": (x2c, y2c),
                "edge:n": (mxc, y1c),    "edge:s": (mxc, y2c),
                "edge:w": (x1c, myc),    "edge:e": (x2c, myc),
            }
        else:
            ccx, ccy = self._frame_to_canvas(self._sel["cx"], self._sel["cy"])
            rc = int(self._sel["r"] * self._zoom)
            handles = {
                "circle:top":   (ccx, ccy - rc),
                "circle:right": (ccx + rc, ccy),
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

        cx, cy = event.x, event.y
        handle = self._hit_handle(cx, cy)

        # Tap override mode — click inside selection to set tap point
        if self._tap_mode.get() == "override" and self._sel is not None and handle is None:
            if self._sel_contains(cx, cy):
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
            # Start a new selection
            self._sel = self._empty_sel()
            self._tap_offset = None
            self._tap_mode.set("center")
            fx, fy = self._canvas_to_frame(cx, cy)
            if self._sel["shape"] == "box":
                self._sel.update(x1=fx, y1=fy, x2=fx, y2=fy)
            else:
                self._sel.update(cx=fx, cy=fy, r=0)
            self._drag_mode = "draw"
            self._drag_start = (cx, cy)
            self._drag_sel_snapshot = dict(self._sel)

    def _on_mouse_drag(self, event) -> None:
        if self._drag_mode is None or self._frame is None:
            return
        cx, cy = event.x, event.y
        dx_c = cx - self._drag_start[0]
        dy_c = cy - self._drag_start[1]
        dx_f = int(dx_c / self._zoom)
        dy_f = int(dy_c / self._zoom)
        snap = self._drag_sel_snapshot
        h, w = self._frame.shape[:2]

        def clamp_f(v, lo, hi): return max(lo, min(v, hi))

        if self._drag_mode == "draw":
            fx, fy = self._canvas_to_frame(cx, cy)
            if self._sel["shape"] == "box":
                ox, oy = snap["x1"], snap["y1"]
                self._sel.update(
                    x1=min(ox, fx), y1=min(oy, fy),
                    x2=max(ox, fx), y2=max(oy, fy),
                )
            else:
                r = int(math.hypot(dx_c, dy_c) / self._zoom)
                self._sel.update(r=max(0, r))

        elif self._drag_mode == "move":
            if self._sel["shape"] == "box":
                new_x1 = clamp_f(snap["x1"] + dx_f, 0, w - 1)
                new_y1 = clamp_f(snap["y1"] + dy_f, 0, h - 1)
                bw = snap["x2"] - snap["x1"]
                bh = snap["y2"] - snap["y1"]
                self._sel.update(
                    x1=new_x1, y1=new_y1,
                    x2=clamp_f(new_x1 + bw, 0, w - 1),
                    y2=clamp_f(new_y1 + bh, 0, h - 1),
                )
            else:
                self._sel.update(
                    cx=clamp_f(snap["cx"] + dx_f, 0, w - 1),
                    cy=clamp_f(snap["cy"] + dy_f, 0, h - 1),
                )

        elif self._drag_mode.startswith("corner:"):
            corner = self._drag_mode.split(":")[1]
            if corner == "nw":
                self._sel.update(x1=clamp_f(snap["x1"] + dx_f, 0, snap["x2"] - 1),
                                  y1=clamp_f(snap["y1"] + dy_f, 0, snap["y2"] - 1))
            elif corner == "ne":
                self._sel.update(x2=clamp_f(snap["x2"] + dx_f, snap["x1"] + 1, w - 1),
                                  y1=clamp_f(snap["y1"] + dy_f, 0, snap["y2"] - 1))
            elif corner == "sw":
                self._sel.update(x1=clamp_f(snap["x1"] + dx_f, 0, snap["x2"] - 1),
                                  y2=clamp_f(snap["y2"] + dy_f, snap["y1"] + 1, h - 1))
            elif corner == "se":
                self._sel.update(x2=clamp_f(snap["x2"] + dx_f, snap["x1"] + 1, w - 1),
                                  y2=clamp_f(snap["y2"] + dy_f, snap["y1"] + 1, h - 1))

        elif self._drag_mode.startswith("edge:"):
            edge = self._drag_mode.split(":")[1]
            if edge == "n":
                self._sel.update(y1=clamp_f(snap["y1"] + dy_f, 0, snap["y2"] - 1))
            elif edge == "s":
                self._sel.update(y2=clamp_f(snap["y2"] + dy_f, snap["y1"] + 1, h - 1))
            elif edge == "w":
                self._sel.update(x1=clamp_f(snap["x1"] + dx_f, 0, snap["x2"] - 1))
            elif edge == "e":
                self._sel.update(x2=clamp_f(snap["x2"] + dx_f, snap["x1"] + 1, w - 1))

        elif self._drag_mode.startswith("circle:"):
            # Both handles adjust radius only
            r = int(math.hypot(
                cx - self._frame_to_canvas(snap["cx"], snap["cy"])[0],
                cy - self._frame_to_canvas(snap["cx"], snap["cy"])[1],
            ) / self._zoom)
            self._sel.update(r=max(1, r))

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
        fx, fy = self._canvas_to_frame(event.x, event.y)
        self._sb_right.config(text=f"Screen: ({fx}, {fy})")
        # Update cursor based on what's under the mouse
        handle = self._hit_handle(event.x, event.y)
        if handle:
            cursors = {
                "corner:nw": "top_left_corner", "corner:ne": "top_right_corner",
                "corner:sw": "bottom_left_corner", "corner:se": "bottom_right_corner",
                "edge:n": "top_side", "edge:s": "bottom_side",
                "edge:w": "left_side", "edge:e": "right_side",
                "circle:top": "top_side", "circle:right": "right_side",
            }
            self._canvas.config(cursor=cursors.get(handle, "crosshair"))
        elif self._sel_contains(event.x, event.y):
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
        """Set the tap override point from a canvas click inside the selection."""
        if self._sel is None:
            return
        fx, fy = self._canvas_to_frame(cx, cy)
        if self._sel["shape"] == "box":
            ox = fx - self._sel["x1"]
            oy = fy - self._sel["y1"]
        else:
            ox = fx - (self._sel["cx"] - self._sel["r"])
            oy = fy - (self._sel["cy"] - self._sel["r"])
        self._tap_offset = (max(0, ox), max(0, oy))
        self._redraw()
        self._update_sidebar()

    def _clear_tap_override(self) -> None:
        self._tap_offset = None
        self._tap_mode.set("center")
        self._redraw()
        self._update_sidebar()

    # ------------------------------------------------------------------
    # Shape change
    # ------------------------------------------------------------------

    def _on_shape_change(self) -> None:
        self._sel = None
        self._tap_offset = None
        self._redraw()
        self._update_sidebar()
        self._save_btn.config(state="disabled")

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _redraw(self) -> None:
        if self._frame is None:
            return
        self._canvas.delete("all")

        # Draw scaled frame
        h, w = self._frame.shape[:2]
        nw, nh = int(w * self._zoom), int(h * self._zoom)
        rgb = cv2.cvtColor(self._frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)
        self._canvas.create_image(self._pan_x, self._pan_y, anchor="nw", image=self._photo)

        if self._sel is None:
            return

        if self._sel["shape"] == "box":
            self._draw_box_selection()
        else:
            self._draw_circle_selection()

        # Tap override dot
        if self._tap_offset is not None and self._sel is not None:
            if self._sel["shape"] == "box":
                tdx = self._sel["x1"] + self._tap_offset[0]
                tdy = self._sel["y1"] + self._tap_offset[1]
            else:
                tdx = self._sel["cx"] - self._sel["r"] + self._tap_offset[0]
                tdy = self._sel["cy"] - self._sel["r"] + self._tap_offset[1]
            tcx, tcy = self._frame_to_canvas(tdx, tdy)
            self._canvas.create_oval(tcx - 5, tcy - 5, tcx + 5, tcy + 5,
                                      fill="#f59e0b", outline="white", width=2)

    def _draw_box_selection(self) -> None:
        s = self._sel
        x1c, y1c = self._frame_to_canvas(s["x1"], s["y1"])
        x2c, y2c = self._frame_to_canvas(s["x2"], s["y2"])
        mxc = (x1c + x2c) // 2
        myc = (y1c + y2c) // 2

        self._canvas.create_rectangle(x1c, y1c, x2c, y2c,
                                       outline="#60a5fa", width=2, dash=(6, 3),
                                       fill="#60a5fa22")

        # Corner handles (square)
        hs = HANDLE_SIZE
        for hx, hy in [(x1c, y1c), (x2c, y1c), (x1c, y2c), (x2c, y2c)]:
            self._canvas.create_rectangle(hx - hs, hy - hs, hx + hs, hy + hs,
                                           fill="#60a5fa", outline="white", width=1)

        # Edge midpoint handles (circle)
        er = EDGE_HANDLE_R
        for hx, hy in [(mxc, y1c), (mxc, y2c), (x1c, myc), (x2c, myc)]:
            self._canvas.create_oval(hx - er, hy - er, hx + er, hy + er,
                                      fill="#93c5fd", outline="white", width=1)

        # Crosshairs
        self._canvas.create_line(0, y1c, self._canvas.winfo_width(), y1c, fill="#60a5fa44")
        self._canvas.create_line(0, y2c, self._canvas.winfo_width(), y2c, fill="#60a5fa44")
        self._canvas.create_line(x1c, 0, x1c, self._canvas.winfo_height(), fill="#60a5fa44")
        self._canvas.create_line(x2c, 0, x2c, self._canvas.winfo_height(), fill="#60a5fa44")

    def _draw_circle_selection(self) -> None:
        s = self._sel
        ccx, ccy = self._frame_to_canvas(s["cx"], s["cy"])
        rc = int(s["r"] * self._zoom)

        self._canvas.create_oval(ccx - rc, ccy - rc, ccx + rc, ccy + rc,
                                   outline="#60a5fa", width=2, dash=(6, 3),
                                   fill="#60a5fa22")

        # 2 handles: top and right
        hs = HANDLE_SIZE
        for hx, hy in [(ccx, ccy - rc), (ccx + rc, ccy)]:
            self._canvas.create_oval(hx - hs, hy - hs, hx + hs, hy + hs,
                                      fill="#60a5fa", outline="white", width=1)

    # ------------------------------------------------------------------
    # Sidebar update
    # ------------------------------------------------------------------

    def _update_sidebar(self) -> None:
        self._update_preview()

        if self._sel is None or not self._sel_is_valid():
            self._crop_info.config(text="No selection")
            self._tap_info_label.config(text="Tap: center of crop")
            self._clear_override_btn.grid_forget()
            return

        s = self._sel
        if s["shape"] == "box":
            bw = s["x2"] - s["x1"]
            bh = s["y2"] - s["y1"]
            self._crop_info.config(text=f"Box  {bw}×{bh} px  origin ({s['x1']},{s['y1']})")
        else:
            self._crop_info.config(text=f"Circle  r={s['r']} px  center ({s['cx']},{s['cy']})")

        if self._tap_offset is not None:
            self._tap_info_label.config(
                text=f"Tap override: ({self._tap_offset[0]}, {self._tap_offset[1]}) within crop"
            )
            self._clear_override_btn.grid(row=12, column=0, sticky="w", pady=(4, 0))
        else:
            self._tap_info_label.config(text="Tap: center of crop")
            self._clear_override_btn.grid_forget()

    def _update_preview(self) -> None:
        self._preview_canvas.delete("all")
        if self._frame is None or self._sel is None or not self._sel_is_valid():
            self._preview_canvas.create_text(
                (SIDEBAR_W - 20) // 2, 40,
                text="No selection", fill="#6b7280", font=("", 9)
            )
            return

        crop = self._get_crop_image()
        if crop is None:
            return

        pw = SIDEBAR_W - 20
        ph = 80
        ch, cw = crop.shape[:2]
        scale = min(pw / cw, ph / ch, 1.0)
        nw2, nh2 = max(1, int(cw * scale)), max(1, int(ch * scale))
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw2, nh2), Image.LANCZOS)
        self._prev_photo = ImageTk.PhotoImage(pil)
        ox = (pw - nw2) // 2
        oy = (ph - nh2) // 2
        self._preview_canvas.create_image(ox, oy, anchor="nw", image=self._prev_photo)

        # Draw tap dot on preview if override is set
        if self._tap_offset is not None:
            tx = ox + int(self._tap_offset[0] * scale)
            ty = oy + int(self._tap_offset[1] * scale)
            self._preview_canvas.create_oval(tx - 4, ty - 4, tx + 4, ty + 4,
                                              fill="#f59e0b", outline="white", width=1)

    # ------------------------------------------------------------------
    # Crop extraction
    # ------------------------------------------------------------------

    def _sel_is_valid(self) -> bool:
        if self._sel is None:
            return False
        if self._sel["shape"] == "box":
            return (self._sel["x2"] - self._sel["x1"] >= MIN_SELECTION and
                    self._sel["y2"] - self._sel["y1"] >= MIN_SELECTION)
        else:
            return self._sel["r"] >= MIN_SELECTION // 2

    def _get_crop_image(self) -> Optional[np.ndarray]:
        if self._frame is None or self._sel is None:
            return None
        s = self._sel
        h, w = self._frame.shape[:2]

        if s["shape"] == "box":
            x1 = max(0, s["x1"]); y1 = max(0, s["y1"])
            x2 = min(w, s["x2"]); y2 = min(h, s["y2"])
            return self._frame[y1:y2, x1:x2].copy()
        else:
            r = s["r"]
            cx, cy = s["cx"], s["cy"]
            x1 = max(0, cx - r); y1 = max(0, cy - r)
            x2 = min(w, cx + r); y2 = min(h, cy + r)
            crop = self._frame[y1:y2, x1:x2].copy()
            # Mask outside circle to black
            ch2, cw2 = crop.shape[:2]
            mask = np.zeros((ch2, cw2), dtype=np.uint8)
            ccx2 = cx - x1; ccy2 = cy - y1
            cv2.circle(mask, (ccx2, ccy2), r, 255, -1)
            result = crop.copy()
            result[mask == 0] = 0
            return result

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if not self._sel_is_valid():
            messagebox.showwarning("No selection", "Draw a crop region first.", parent=self)
            return

        crop = self._get_crop_image()
        if crop is None:
            messagebox.showerror("Error", "Could not extract crop image.", parent=self)
            return

        # Determine save path
        root = project_root()
        detector_dir = root / "assets" / "detectors" / self._detector_name
        detector_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{self._detector_name}_{self._serial}.png"
        save_path = detector_dir / filename

        # Save image
        ok = cv2.imwrite(str(save_path), crop)
        if not ok:
            messagebox.showerror("Save failed", f"Could not write to:\n{save_path}", parent=self)
            return

        # Update devices.json
        devices = load_devices()
        cfg = devices.get(self._serial)
        if cfg is None:
            from config.devices import DeviceConfig
            cfg = DeviceConfig(serial=self._serial)
            devices[self._serial] = cfg

        assignment = DetectorAssignment(
            image_filename=filename,
            shape=self._sel["shape"],
            last_tested=datetime.now(timezone.utc).isoformat(),
            last_score=None,
            tap_offset_x=self._tap_offset[0] if self._tap_offset else None,
            tap_offset_y=self._tap_offset[1] if self._tap_offset else None,
        )
        cfg.detector_assignments[self._detector_name] = assignment
        save_devices(devices)

        # Invalidate TemplateBank cache
        if self._manager is not None:
            self._manager.invalidate_template(self._detector_name, self._serial)

        app_logger.log(
            f"[crop_tool] Saved {self._detector_name} for {self._serial[:8]} → {filename}", "INFO"
        )
        self._set_status(f"Saved → {save_path.name}", color="#16a34a")
        self.after(1200, self.destroy)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _set_status(self, msg: str, error: bool = False, color: Optional[str] = None) -> None:
        c = color if color else ("#dc2626" if error else "#888")
        self._status_label.config(text=msg, foreground=c)
