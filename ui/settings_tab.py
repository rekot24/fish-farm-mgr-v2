"""
ui/settings_tab.py

Settings tab — global app settings with full logging and debug controls.

Logic rules enforced in the UI:
  - Development mode OFF → all debug sub-options greyed
  - Show in panel OFF + log to file OFF → development mode auto-disabled
  - Log to file OFF → sub-category toggles greyed + note shown
  - Debug logging OFF → four sub-category toggles greyed
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import replace
from typing import Callable

from config.settings import Settings, DebugConfig, LoggingConfig


class SettingsTab(ttk.Frame):

    def __init__(
        self,
        parent,
        get_settings: Callable[[], Settings],
        save_settings_fn: Callable[[Settings], None],
        reload_settings: Callable[[], None],
    ):
        super().__init__(parent)
        self._get_settings = get_settings
        self._save_settings = save_settings_fn
        self._reload_settings = reload_settings
        self._build()
        self._load()

    def _build(self) -> None:
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=(16, 12))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        from ui.scroll_utils import bind_mousewheel
        bind_mousewheel(canvas)

        f = inner

        def section(label, row):
            ttk.Label(f, text=label, font=("", 10, "bold")).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(12, 2))
            ttk.Separator(f, orient="horizontal").grid(
                row=row+1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            return row + 2

        def field(label, desc=None, row=0, indent=0):
            pad = (indent, 0)
            lf = ttk.Frame(f)
            lf.grid(row=row, column=0, sticky="w", padx=pad, pady=3)
            ttk.Label(lf, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(lf, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.StringVar()
            entry = ttk.Entry(f, textvariable=var, width=20)
            entry.grid(row=row, column=1, sticky="w", pady=3)
            return var, entry

        def bool_field(label, desc=None, row=0, indent=0):
            pad = (indent, 0)
            lf = ttk.Frame(f)
            lf.grid(row=row, column=0, sticky="w", padx=pad, pady=3)
            ttk.Label(lf, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(lf, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(f, variable=var)
            cb.grid(row=row, column=1, sticky="w", pady=3)
            return var, cb

        r = 0

        # ---- Connection ----
        r = section("Connection", r)
        self._server_link_var, _ = field("Private server link",
            "Used for all rejoin and recovery actions", row=r)
        r += 1

        # ---- Timing ----
        r = section("Timing", r)
        self._dbl_click_var, _ = field("Double-click delay (s)",
            "Pause between the two taps", row=r)
        r += 1
        self._lobby_stuck_var, _ = field("Lobby stuck threshold (s)",
            "Time in lobby before leaving and rejoining", row=r)
        r += 1
        self._disconnect_var, _ = field("Disconnect timeout (s)",
            "Time before tapping Leave", row=r)
        r += 1
        self._loop_var, _ = field("Loop interval (s)",
            "How often each device captures and checks state", row=r)
        r += 1

        # ---- Logging ----
        r = section("Logging", r)
        self._log_to_file_var, self._log_to_file_cb = bool_field(
            "Log to file", "Write session log to logs/app.log", row=r)
        r += 1
        # Log file path display
        lf = ttk.Frame(f)
        lf.grid(row=r, column=0, sticky="w", padx=(16, 0), pady=2)
        ttk.Label(lf, text="Log file", font=("", 10)).pack(anchor="w")
        self._log_path_var = tk.StringVar()
        self._log_path_entry = ttk.Entry(f, textvariable=self._log_path_var,
                                          width=36, state="readonly")
        self._log_path_entry.grid(row=r, column=1, sticky="w", pady=2)
        r += 1
        self._log_level_var, self._log_level_cb = field("Log level",
            "Minimum level to write to file (DEBUG / INFO / WARNING)", row=r, indent=16)
        r += 1

        # Note when log to file is off
        self._log_off_note = ttk.Label(f, text="⚠ Only critical errors will be logged to file.",
                                        foreground="#b45309", font=("", 9))
        self._log_off_note.grid(row=r, column=0, columnspan=2, sticky="w", padx=(16, 0), pady=2)
        r += 1

        # ---- Debug ----
        r = section("Debug", r)

        self._dev_mode_var, self._dev_mode_cb = bool_field(
            "Development mode",
            "Shows debug panel on Main tab; fail loudly on errors", row=r)
        r += 1

        self._show_panel_var, self._show_panel_cb = bool_field(
            "Show logs in debug panel",
            "Route log output to the in-app debug panel", row=r, indent=16)
        r += 1

        self._debug_log_var, self._debug_log_cb = bool_field(
            "Debug logging",
            "Enable DEBUG-level messages (suppressed if off)", row=r, indent=16)
        r += 1

        # Sub-category toggles
        self._log_state_var,  self._log_state_cb  = bool_field("Log state changes",  row=r, indent=32)
        r += 1
        self._log_detect_var, self._log_detect_cb = bool_field("Log detections",
            "Print detector scores every cycle", row=r, indent=32)
        r += 1
        self._log_actions_var, self._log_actions_cb = bool_field("Log actions",
            "Print every tap and action taken", row=r, indent=32)
        r += 1
        self._log_config_var, self._log_config_cb  = bool_field("Log config reads", row=r, indent=32)
        r += 1

        # Auto-disable note
        self._auto_disable_note = ttk.Label(
            f,
            text="Development mode disabled — no output destination selected.\n"
                 "Enable 'Show logs in debug panel' or 'Log to file' to use development mode.",
            foreground="#b45309", font=("", 9), wraplength=400, justify="left"
        )
        self._auto_disable_note.grid(row=r, column=0, columnspan=2, sticky="w", padx=(16, 0), pady=4)
        r += 1

        # ---- Save ----
        ttk.Separator(f, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(14, 8))
        r += 1
        ttk.Button(f, text="Save settings", command=self._save).grid(
            row=r, column=1, sticky="e")

        f.columnconfigure(0, weight=1)

        # Wire traces for live UI state updates
        self._dev_mode_var.trace_add("write",     lambda *_: self._update_state())
        self._show_panel_var.trace_add("write",   lambda *_: self._update_state())
        self._debug_log_var.trace_add("write",    lambda *_: self._update_state())
        self._log_to_file_var.trace_add("write",  lambda *_: self._update_state())

        # Store sub-option widgets for greying
        self._debug_children = [
            self._show_panel_cb, self._debug_log_cb,
            self._log_state_cb, self._log_detect_cb,
            self._log_actions_cb, self._log_config_cb,
        ]
        self._debug_sub_children = [
            self._log_state_cb, self._log_detect_cb,
            self._log_actions_cb, self._log_config_cb,
        ]
        self._log_sub_children = [self._log_level_cb]

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        s = self._get_settings()
        self._server_link_var.set(s.private_server_link)
        self._dbl_click_var.set(str(s.double_click_delay_s))
        self._lobby_stuck_var.set(str(s.lobby_stuck_threshold_s))
        self._disconnect_var.set(str(s.disconnect_timeout_s))
        self._loop_var.set(str(s.loop_interval_s))

        self._log_to_file_var.set(s.logging.log_to_file)
        self._log_path_var.set(str(s.log_file_path()))
        self._log_level_var.set(s.logging.level)

        self._dev_mode_var.set(s.development_mode)
        self._show_panel_var.set(s.debug.show_in_panel)
        self._debug_log_var.set(s.debug.log_debug_messages)
        self._log_state_var.set(s.debug.log_state_changes)
        self._log_detect_var.set(s.debug.log_detections)
        self._log_actions_var.set(s.debug.log_actions)
        self._log_config_var.set(s.debug.log_config_reads)

        self._update_state()

    def _save(self) -> None:
        def _float(var, default):
            try: return float(var.get())
            except ValueError: return default

        s = self._get_settings()

        # Auto-disable dev mode if no output destination
        dev_mode = self._dev_mode_var.get()
        if dev_mode and not self._show_panel_var.get() and not self._log_to_file_var.get():
            dev_mode = False
            self._dev_mode_var.set(False)

        updated = replace(
            s,
            private_server_link=self._server_link_var.get().strip(),
            double_click_delay_s=_float(self._dbl_click_var, s.double_click_delay_s),
            lobby_stuck_threshold_s=_float(self._lobby_stuck_var, s.lobby_stuck_threshold_s),
            disconnect_timeout_s=_float(self._disconnect_var, s.disconnect_timeout_s),
            loop_interval_s=_float(self._loop_var, s.loop_interval_s),
            development_mode=dev_mode,
            logging=replace(
                s.logging,
                log_to_file=self._log_to_file_var.get(),
                level=self._log_level_var.get().strip() or "INFO",
            ),
            debug=replace(
                s.debug,
                show_in_panel=self._show_panel_var.get(),
                log_debug_messages=self._debug_log_var.get(),
                log_state_changes=self._log_state_var.get(),
                log_detections=self._log_detect_var.get(),
                log_actions=self._log_actions_var.get(),
                log_config_reads=self._log_config_var.get(),
            ),
        )
        self._save_settings(updated)
        self._reload_settings()
        self._update_state()

    # ------------------------------------------------------------------
    # Live UI state enforcement
    # ------------------------------------------------------------------

    def _update_state(self) -> None:
        """Grey/enable widgets based on current checkbox states."""
        dev_on      = self._dev_mode_var.get()
        panel_on    = self._show_panel_var.get()
        debug_on    = self._debug_log_var.get()
        file_on     = self._log_to_file_var.get()

        # Dev mode children
        for w in self._debug_children:
            w.config(state="normal" if dev_on else "disabled")

        # Debug sub-categories — need both dev mode and debug logging
        for w in self._debug_sub_children:
            w.config(state="normal" if (dev_on and debug_on) else "disabled")

        # Log to file sub-options
        for w in self._log_sub_children:
            w.config(state="normal" if file_on else "disabled")

        # Log-off note
        if file_on:
            self._log_off_note.grid_remove()
        else:
            self._log_off_note.grid()

        # Auto-disable note — show when dev mode on but both outputs off
        no_output = dev_on and not panel_on and not file_on
        if no_output:
            self._auto_disable_note.grid()
        else:
            self._auto_disable_note.grid_remove()
