"""
ui/app.py

Main application window. Four tabs: Main / Device / Capture / Settings.
Wires the debug panel callback into app_logger after UI is built.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from bot import app_logger
from bot.device_manager import DeviceManager
from config.settings import Settings
from config.devices import DeviceConfig

WINDOW_WIDTH  = 900
WINDOW_HEIGHT = 700
POLL_INTERVAL_MS = 2000
CARD_COLUMNS = 2


class App(tk.Tk):

    def __init__(
        self,
        manager: DeviceManager,
        get_settings: Callable[[], Settings],
        get_devices: Callable[[], dict[str, DeviceConfig]],
        reload_settings: Callable[[], None],
        reload_devices: Callable[[], None],
        save_settings_fn: Callable[[Settings], None],
        save_devices_fn: Callable[[dict], None],
    ):
        super().__init__()
        self._manager = manager
        self._get_settings = get_settings
        self._get_devices = get_devices
        self._reload_settings = reload_settings
        self._reload_devices = reload_devices
        self._save_settings = save_settings_fn
        self._save_devices = save_devices_fn

        self.title("Be Fish Farm Manager v2")
        self.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.minsize(800, 500)

        self._build_ui()

        # Register the debug panel as the log callback AFTER UI is built
        app_logger.register_panel_callback(self._main_tab.append_log)

        self._start_poll()

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        from ui.main_tab import MainTab
        from ui.device_tab import DeviceTab
        from ui.capture_tab import CaptureTab
        from ui.settings_tab import SettingsTab

        self._main_tab = MainTab(
            notebook,
            manager=self._manager,
            get_settings=self._get_settings,
            get_devices=self._get_devices,
            save_devices_fn=self._save_devices,
            card_columns=CARD_COLUMNS,
        )
        self._device_tab = DeviceTab(
            notebook,
            get_devices=self._get_devices,
            save_devices_fn=self._save_devices,
        )
        self._capture_tab = CaptureTab(
            notebook,
            manager=self._manager,
            get_devices=self._get_devices,
            save_devices_fn=self._save_devices,
        )
        self._settings_tab = SettingsTab(
            notebook,
            get_settings=self._get_settings,
            save_settings_fn=self._save_settings,
            reload_settings=self._reload_settings,
        )

        notebook.add(self._main_tab,    text="Main")
        notebook.add(self._device_tab,  text="Device")
        notebook.add(self._capture_tab, text="Capture")
        notebook.add(self._settings_tab, text="Settings")

    def _start_poll(self) -> None:
        self._poll()

    def _poll(self) -> None:
        try:
            self._main_tab.refresh()
        except Exception:
            pass
        self.after(POLL_INTERVAL_MS, self._poll)

    def on_close(self) -> None:
        self._manager.stop_all()
        self.destroy()
