"""
ui/settings_tab.py

Settings tab — global app settings.
All fields map directly to the Settings dataclass in config/settings.py.
Changes take effect immediately on Save (no restart required).
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
        # Scrollable container
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

        f = inner

        def section(label):
            ttk.Label(f, text=label, font=("", 10, "bold")).pack(anchor="w", pady=(12, 4))
            ttk.Separator(f, orient="horizontal").pack(fill="x", pady=(0, 6))

        def field(label, desc=None):
            row = ttk.Frame(f)
            row.pack(fill="x", pady=3)
            left = ttk.Frame(row)
            left.pack(side="left", fill="x", expand=True)
            ttk.Label(left, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(left, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=14).pack(side="right")
            return var

        def bool_field(label, desc=None):
            row = ttk.Frame(f)
            row.pack(fill="x", pady=3)
            left = ttk.Frame(row)
            left.pack(side="left", fill="x", expand=True)
            ttk.Label(left, text=label, font=("", 10)).pack(anchor="w")
            if desc:
                ttk.Label(left, text=desc, foreground="#6b7280", font=("", 9)).pack(anchor="w")
            var = tk.BooleanVar()
            ttk.Checkbutton(row, variable=var).pack(side="right")
            return var

        # Connection
        section("Connection")
        self._server_link_var = field(
            "Private server link",
            "Used for all rejoin and recovery actions"
        )

        # Timing
        section("Timing")
        self._double_click_delay_var = field(
            "Double-click delay (s)",
            "Pause between the two taps of a double-click"
        )
        self._lobby_stuck_var = field(
            "Lobby stuck threshold (s)",
            "Time in lobby before leaving and rejoining"
        )
        self._disconnect_timeout_var = field(
            "Disconnect timeout (s)",
            "Time on disconnect screen before tapping Leave"
        )
        self._loop_interval_var = field(
            "Loop interval (s)",
            "How often each device captures and checks state"
        )

        # Debug
        section("Debug")
        self._dev_mode_var = bool_field(
            "Development mode",
            "Fail loudly on errors instead of logging and continuing"
        )
        self._debug_enabled_var = bool_field("Debug logging")
        self._log_detections_var = bool_field(
            "Log detections",
            "Print detector scores every cycle"
        )
        self._log_actions_var = bool_field(
            "Log actions",
            "Print every tap and action taken"
        )
        self._log_state_changes_var = bool_field("Log state changes")
        self._log_config_reads_var  = bool_field("Log config reads")

        # Save button
        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=(14, 8))
        ttk.Button(f, text="Save settings", command=self._save).pack(anchor="e")

    def _load(self) -> None:
        s = self._get_settings()
        self._server_link_var.set(s.private_server_link)
        self._double_click_delay_var.set(str(s.double_click_delay_s))
        self._lobby_stuck_var.set(str(s.lobby_stuck_threshold_s))
        self._disconnect_timeout_var.set(str(s.disconnect_timeout_s))
        self._loop_interval_var.set(str(s.loop_interval_s))
        self._dev_mode_var.set(s.development_mode)
        self._debug_enabled_var.set(s.debug.enabled)
        self._log_detections_var.set(s.debug.log_detections)
        self._log_actions_var.set(s.debug.log_actions)
        self._log_state_changes_var.set(s.debug.log_state_changes)
        self._log_config_reads_var.set(s.debug.log_config_reads)

    def _save(self) -> None:
        def _float(var, default):
            try: return float(var.get())
            except ValueError: return default

        s = self._get_settings()
        updated = replace(
            s,
            private_server_link=self._server_link_var.get().strip(),
            double_click_delay_s=_float(self._double_click_delay_var, s.double_click_delay_s),
            lobby_stuck_threshold_s=_float(self._lobby_stuck_var, s.lobby_stuck_threshold_s),
            disconnect_timeout_s=_float(self._disconnect_timeout_var, s.disconnect_timeout_s),
            loop_interval_s=_float(self._loop_interval_var, s.loop_interval_s),
            development_mode=self._dev_mode_var.get(),
            debug=replace(
                s.debug,
                enabled=self._debug_enabled_var.get(),
                log_detections=self._log_detections_var.get(),
                log_actions=self._log_actions_var.get(),
                log_state_changes=self._log_state_changes_var.get(),
                log_config_reads=self._log_config_reads_var.get(),
            ),
        )
        self._save_settings(updated)
        self._reload_settings()
