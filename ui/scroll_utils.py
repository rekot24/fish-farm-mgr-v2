"""
ui/scroll_utils.py

Utility to bind mouse-wheel scrolling to a Canvas widget scoped to
when the mouse is hovering over it. Works on Windows (MouseWheel),
Linux (Button-4/5), and macOS (MouseWheel with delta).

Usage:
    bind_mousewheel(canvas)

Call this once after creating the canvas. It handles binding and
unbinding automatically on Enter/Leave so only the canvas under
the cursor scrolls — no global bind_all needed.
"""

from __future__ import annotations

import tkinter as tk


def bind_mousewheel(canvas: tk.Canvas) -> None:
    """
    Bind mouse-wheel scrolling to a canvas, active only when hovered.
    Safe to call on multiple canvases — they don't interfere.
    """

    def _on_mousewheel(event):
        # Windows/macOS: event.delta is ±120 per notch
        # Linux: event.num is 4 (up) or 5 (down)
        if event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        else:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind(event=None):
        canvas.bind("<MouseWheel>", _on_mousewheel)
        canvas.bind("<Button-4>",   _on_mousewheel)
        canvas.bind("<Button-5>",   _on_mousewheel)

    def _unbind(event=None):
        canvas.unbind("<MouseWheel>")
        canvas.unbind("<Button-4>")
        canvas.unbind("<Button-5>")

    canvas.bind("<Enter>", _bind)
    canvas.bind("<Leave>", _unbind)
