"""
ui/settings_tab.py

Settings tab — Timing, Recovery, Logging, Debug sections.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from dataclasses import replace
from typing import Callable

from config.settings import Settings, DebugConfig, LoggingConfig

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


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
        self._suppress_traces = False
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
        r = 0

        def section(label):
            nonlocal r
            ttk.Label(f, text=label, font=("", 10, "bold")).grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(12, 2))
            r += 1
            ttk.Separator(f, orient="horizontal").grid(
                row=r, column=0, columnspan=2, sticky="ew", pady=(0, 6))
            r += 1

        def str_field(label, desc=None, indent=0):
            nonlocal r
            lf = ttk.Frame(f)
            lf.grid(row=r, column=0, sticky="w", padx=(indent, 0), pady=3)
            ttk.Label(lf, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(lf, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.StringVar()
            entry = ttk.Entry(f, textvariable=var, width=20)
            entry.grid(row=r, column=1, sticky="w", pady=3)
            r += 1
            return var, entry

        def bool_field(label, desc=None, indent=0):
            nonlocal r
            lf = ttk.Frame(f)
            lf.grid(row=r, column=0, sticky="w", padx=(indent, 0), pady=3)
            ttk.Label(lf, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(lf, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.BooleanVar()
            cb = ttk.Checkbutton(f, variable=var)
            cb.grid(row=r, column=1, sticky="w", pady=3)
            r += 1
            return var, cb

        def dropdown_field(label, desc=None, values=None, indent=0):
            nonlocal r
            lf = ttk.Frame(f)
            lf.grid(row=r, column=0, sticky="w", padx=(indent, 0), pady=3)
            ttk.Label(lf, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(lf, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.StringVar()
            cb = ttk.Combobox(f, textvariable=var, values=values or [],
                              state="readonly", width=12)
            cb.grid(row=r, column=1, sticky="w", pady=3)
            r += 1
            return var, cb

        def note(text, color="#b45309", indent=16):
            nonlocal r
            lbl = ttk.Label(f, text=text, foreground=color,
                            font=("", 9), wraplength=380, justify="left")
            lbl.grid(row=r, column=0, columnspan=2, sticky="w",
                     padx=(indent, 0), pady=(0, 4))
            r += 1
            return lbl

        # ---- Timing ----
        section("Timing")
        self._dbl_click_var,     _ = str_field("Double-click delay (s)",
            "Pause between the two taps")
        self._lobby_stuck_var,   _ = str_field("Lobby stuck threshold (s)",
            "Time in lobby before firing end-run tap")
        self._unknown_stuck_var, _ = str_field("Unknown stuck threshold (s)",
            "Time in UNKNOWN state before forcing a relaunch")
        self._loop_var,          _ = str_field("Loop interval (s)",
            "How often each device captures and checks state")

        # ---- Recovery ----
        section("Recovery")
        self._adb_fail_var, _ = str_field(
            "ADB failure threshold",
            "Consecutive 'device not found' failures before worker stops.\n"
            "Must be consecutive — any successful contact resets the count.",
        )

        # ---- Logging (Stream 1 — file) ----
        section("Logging")
        self._log_to_file_var, self._log_to_file_cb = bool_field(
            "Log to file", "Write session log to logs/app.log")

        lf = ttk.Frame(f)
        lf.grid(row=r, column=0, sticky="w", padx=(16, 0), pady=2)
        ttk.Label(lf, text="Log file", font=("", 10)).pack(anchor="w")
        self._log_path_var = tk.StringVar()
        self._log_path_entry = ttk.Entry(f, textvariable=self._log_path_var,
                                          width=36, state="readonly")
        self._log_path_entry.grid(row=r, column=1, sticky="w", pady=2)
        r += 1

        self._log_level_var, self._log_level_cb = dropdown_field(
            "Log level",
            "Minimum level to write to file",
            values=LOG_LEVELS, indent=16)

        self._log_off_note = note(
            "Log to file is off — only critical errors will be written to errors.log.")

        # ---- Debug (panel + streams) ----
        section("Debug")

        self._dev_mode_var, self._dev_mode_cb = bool_field(
            "Development mode",
            "Shows debug panel on Main tab")

        self._show_log_var, self._show_log_cb = bool_field(
            "Show logs in debug panel",
            "Stream 1 — routes INFO/WARNING/ERROR to the panel", indent=16)

        self._show_debug_var, self._show_debug_cb = bool_field(
            "Debug logging",
            "Stream 2 — routes verbose cycle-by-cycle detail to the panel", indent=16)

        self._log_state_var,   self._log_state_cb  = bool_field(
            "Log state changes",  indent=32)
        self._log_detect_var,  self._log_detect_cb = bool_field(
            "Log detections", "Print detector scores every cycle", indent=32)
        self._log_actions_var, self._log_actions_cb = bool_field(
            "Log actions", "Print every tap and action taken", indent=32)
        self._log_config_var,  self._log_config_cb  = bool_field(
            "Log config reads", indent=32)

        self._auto_off_note = note(
            "Development mode disabled — both log streams are off. "
            "Enable 'Show logs' or 'Debug logging' to use the debug panel.")

        # ---- Save ----
        ttk.Separator(f, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=(14, 8))
        r += 1
        ttk.Button(f, text="Save settings", command=self._save).grid(
            row=r, column=1, sticky="e")

        f.columnconfigure(0, weight=1)

        for var in (self._log_to_file_var, self._dev_mode_var,
                    self._show_log_var, self._show_debug_var):
            var.trace_add("write", lambda *_: self._update_state())

        self._debug_children = [
            self._show_log_cb, self._show_debug_cb,
            self._log_state_cb, self._log_detect_cb,
            self._log_actions_cb, self._log_config_cb,
        ]
        self._debug_sub_children = [
            self._log_state_cb, self._log_detect_cb,
            self._log_actions_cb, self._log_config_cb,
        ]
        self._log_file_children = [self._log_level_cb]

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _load(self) -> None:
        self._suppress_traces = True
        s = self._get_settings()

        self._dbl_click_var.set(str(s.double_click_delay_s))
        self._lobby_stuck_var.set(str(s.lobby_stuck_threshold_s))
        self._unknown_stuck_var.set(str(s.unknown_stuck_threshold_s))
        self._loop_var.set(str(s.loop_interval_s))
        self._adb_fail_var.set(str(s.adb_failure_threshold))

        self._log_to_file_var.set(s.logging.log_to_file)
        self._log_path_var.set(str(s.log_file_path()))
        self._log_level_var.set(s.logging.level if s.logging.level in LOG_LEVELS else "INFO")

        self._dev_mode_var.set(s.development_mode)
        self._show_log_var.set(s.debug.show_log_in_panel)
        self._show_debug_var.set(s.debug.show_debug_in_panel)
        self._log_state_var.set(s.debug.log_state_changes)
        self._log_detect_var.set(s.debug.log_detections)
        self._log_actions_var.set(s.debug.log_actions)
        self._log_config_var.set(s.debug.log_config_reads)

        self._suppress_traces = False
        self._update_state()

    def _save(self) -> None:
        def _float(var, default):
            try: return float(var.get())
            except ValueError: return default

        def _int(var, default):
            try: return max(1, int(var.get()))
            except ValueError: return default

        s = self._get_settings()

        dev_mode = self._dev_mode_var.get()
        if dev_mode and not self._show_log_var.get() and not self._show_debug_var.get():
            dev_mode = False
            self._suppress_traces = True
            self._dev_mode_var.set(False)
            self._suppress_traces = False

        updated = replace(
            s,
            double_click_delay_s=_float(self._dbl_click_var, s.double_click_delay_s),
            lobby_stuck_threshold_s=_float(self._lobby_stuck_var, s.lobby_stuck_threshold_s),
            unknown_stuck_threshold_s=_float(self._unknown_stuck_var, s.unknown_stuck_threshold_s),
            loop_interval_s=_float(self._loop_var, s.loop_interval_s),
            adb_failure_threshold=_int(self._adb_fail_var, s.adb_failure_threshold),
            development_mode=dev_mode,
            logging=replace(
                s.logging,
                log_to_file=self._log_to_file_var.get(),
                level=self._log_level_var.get() or "INFO",
            ),
            debug=replace(
                s.debug,
                show_log_in_panel=self._show_log_var.get(),
                show_debug_in_panel=self._show_debug_var.get(),
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
        if self._suppress_traces:
            return

        dev_on     = self._dev_mode_var.get()
        show_log   = self._show_log_var.get()
        show_debug = self._show_debug_var.get()
        file_on    = self._log_to_file_var.get()

        for w in self._log_file_children:
            w.config(state="normal" if file_on else "disabled")
        if file_on:
            self._log_off_note.grid_remove()
        else:
            self._log_off_note.grid()

        for w in self._debug_children:
            w.config(state="normal" if dev_on else "disabled")

        for w in self._debug_sub_children:
            w.config(state="normal" if (dev_on and show_debug) else "disabled")

        both_off = dev_on and not show_log and not show_debug
        if both_off:
            self._auto_off_note.grid()
        else:
            self._auto_off_note.grid_remove()
