"""
tools/coordinate_finder.py

ADB Coordinate Finder.

Captures a live frame from a device, displays it, and lets you click
to read back screen-absolute coordinates. Useful for setting click_offset
values when the tap target isn't the center of a detected image.

Usage:
    Run standalone: python tools/coordinate_finder.py
    Or launch from device settings dialog.
"""

from __future__ import annotations

import subprocess
import threading
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import Optional, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

from config.constants import ADB_DEFAULT_TIMEOUT_S


class CoordinateFinder:
    """
    Displays a device screenshot and reports click coordinates.
    Coordinates are in screen-absolute ADB space.
    """

    def __init__(self, parent=None, serial: str = "", adb_path: str = "adb"):
        self.serial = serial
        self.adb_path = adb_path

        self._frame: Optional[np.ndarray] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._scale = 1.0
        self._offset = (0, 0)
        self._captured_points: List[Tuple[str, int, int]] = []

        if parent:
            self.top = tk.Toplevel(parent)
        else:
            self.top = tk.Tk()

        self.top.title(f"Coordinate Finder — {serial or 'No device'}")
        self.top.geometry("900x680")
        self._build()

    def _build(self) -> None:
        self.top.columnconfigure(0, weight=1)
        self.top.rowconfigure(1, weight=1)

        # ---- Top controls ----
        top = ttk.Frame(self.top, padding=(8, 6))
        top.grid(row=0, column=0, sticky="ew")

        ttk.Label(top, text="Device serial:").pack(side="left")
        self._serial_var = tk.StringVar(value=self.serial)
        serial_entry = ttk.Entry(top, textvariable=self._serial_var, width=22)
        serial_entry.pack(side="left", padx=(4, 8))

        ttk.Button(top, text="Capture Frame",
                   command=self._capture).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Clear Points",
                   command=self._clear_points).pack(side="left", padx=(0, 8))
        ttk.Button(top, text="Copy to Clipboard",
                   command=self._copy_points).pack(side="left")

        self._lbl_status = ttk.Label(top, text="Click 'Capture Frame' to start.",
                                      foreground="#888888")
        self._lbl_status.pack(side="right")

        # ---- Canvas ----
        canvas_frame = ttk.Frame(self.top, relief="sunken", borderwidth=1)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(canvas_frame, bg="#1a1a1a", cursor="crosshair")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._canvas.bind("<Button-1>", self._on_click)
        self._canvas.bind("<Motion>", self._on_hover)

        # ---- Point log ----
        log_frame = ttk.LabelFrame(self.top, text="Captured Points", padding=(8, 4))
        log_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=(0, 8))
        log_frame.columnconfigure(0, weight=1)

        self._log_text = tk.Text(log_frame, height=5, wrap="word", state="disabled")
        self._log_text.grid(row=0, column=0, sticky="ew")

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _capture(self) -> None:
        serial = self._serial_var.get().strip()
        if not serial:
            self._lbl_status.config(text="Enter a device serial first.", foreground="red")
            return

        self.serial = serial
        self._lbl_status.config(text="Capturing...", foreground="#888888")
        self.top.update_idletasks()

        def do_capture():
            try:
                result = subprocess.run(
                    [self.adb_path, "-s", serial, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=ADB_DEFAULT_TIMEOUT_S,
                )
                if result.returncode != 0 or not result.stdout:
                    self.top.after(0, lambda: self._lbl_status.config(
                        text="Capture failed — check ADB connection.", foreground="red"))
                    return

                arr = np.frombuffer(result.stdout, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    self.top.after(0, lambda: self._lbl_status.config(
                        text="Could not decode screenshot.", foreground="red"))
                    return

                self.top.after(0, lambda f=frame: self._show_frame(f))

            except Exception as e:
                self.top.after(0, lambda: self._lbl_status.config(
                    text=f"Error: {e}", foreground="red"))

        threading.Thread(target=do_capture, daemon=True).start()

    def _show_frame(self, frame: np.ndarray) -> None:
        self._frame = frame
        h, w = frame.shape[:2]

        cw = self._canvas.winfo_width() or 800
        ch = self._canvas.winfo_height() or 500
        scale = min(cw / w, ch / h, 1.0)
        nw, nh = int(w * scale), int(h * scale)

        self._scale = scale
        self._offset = ((cw - nw) // 2, (ch - nh) // 2)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(pil)

        self._canvas.delete("all")
        ox, oy = self._offset
        self._canvas.create_image(ox, oy, anchor="nw", image=self._photo)
        self._lbl_status.config(text=f"Frame: {w}x{h}. Click anywhere to record coordinates.",
                                 foreground="#00aa55")

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _canvas_to_screen(self, cx: int, cy: int) -> Tuple[int, int]:
        """Convert canvas pixel to screen-absolute ADB coordinate."""
        ox, oy = self._offset
        sx = int((cx - ox) / self._scale)
        sy = int((cy - oy) / self._scale)
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            sx = max(0, min(sx, w - 1))
            sy = max(0, min(sy, h - 1))
        return sx, sy

    def _on_hover(self, event) -> None:
        if self._frame is None:
            return
        sx, sy = self._canvas_to_screen(event.x, event.y)
        self._lbl_status.config(text=f"Screen coords: ({sx}, {sy})", foreground="#888888")

    def _on_click(self, event) -> None:
        if self._frame is None:
            return
        sx, sy = self._canvas_to_screen(event.x, event.y)

        # Draw a small dot on the canvas
        self._canvas.create_oval(
            event.x - 5, event.y - 5, event.x + 5, event.y + 5,
            fill="#00ff88", outline="white", width=1
        )
        self._canvas.create_text(
            event.x + 10, event.y,
            text=f"({sx},{sy})", fill="#00ff88", anchor="w",
            font=("TkFixedFont", 9)
        )

        # Ask for an optional label
        label = f"point_{len(self._captured_points) + 1}"
        self._captured_points.append((label, sx, sy))
        self._log(f'"{label}": ({sx}, {sy})')

    def _log(self, msg: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", msg + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _clear_points(self) -> None:
        self._captured_points.clear()
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")
        if self._frame is not None:
            self._show_frame(self._frame)

    def _copy_points(self) -> None:
        if not self._captured_points:
            return
        lines = [f'"{name}": ({x}, {y}),' for name, x, y in self._captured_points]
        text = "\n".join(lines)
        self.top.clipboard_clear()
        self.top.clipboard_append(text)
        self._lbl_status.config(text="Copied to clipboard!", foreground="#00aa55")


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    serial = sys.argv[1] if len(sys.argv) > 1 else ""
    root = CoordinateFinder(serial=serial)
    root.top.mainloop()
