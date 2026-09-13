"""
ui/app.py

Main application window. Four tabs: Main / Device / Capture / Settings.
Owns the DeviceManager reference and the polling loop that keeps
device cards up to date.

Layout constants are defined at the top of this file (never in config/constants.py).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from bot.device_manager import DeviceManager
from config.settings import Settings, save_settings
from config.devices import DeviceConfig, save_devices

# ---------------------------------------------------------------------------
# Layout constants [INTERNAL]
# ---------------------------------------------------------------------------
WINDOW_WIDTH  = 900
WINDOW_HEIGHT = 700
POLL_INTERVAL_MS = 2000   # how often the UI polls worker status (ms)
CARD_COLUMNS = 2          # device cards per row on the Main tab


class App(tk.Tk):
    """
    Root window. Creates the tab structure and owns the poll loop.

    Args:
        manager       : the DeviceManager that runs all workers
        get_settings  : callable returning the current Settings
        get_devices   : callable returning the current device config dict
        reload_settings : callable that re-reads settings.json into the box
        reload_devices  : callable that re-reads devices.json into the box
        save_settings_fn: callable(Settings) that persists settings
        save_devices_fn : callable(dict) that persists device configs
    """

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
        self.configure(bg="#1e1e1e")

        self._build_ui()
        self._start_poll()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the tab structure and all child panels."""
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=0, pady=0)

        # Import here to avoid circular deps at module level
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
        )
        self._settings_tab = SettingsTab(
            notebook,
            get_settings=self._get_settings,
            save_settings_fn=self._save_settings,
            reload_settings=self._reload_settings,
        )

        notebook.add(self._main_tab, text="Main")
        notebook.add(self._device_tab, text="Device")
        notebook.add(self._capture_tab, text="Capture")
        notebook.add(self._settings_tab, text="Settings")

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    def _start_poll(self) -> None:
        """Begin the recurring UI update cycle."""
        self._poll()

    def _poll(self) -> None:
        """Pull fresh status from all workers and refresh the Main tab cards."""
        try:
            self._main_tab.refresh()
        except Exception:
            pass  # never let a poll error crash the UI
        self.after(POLL_INTERVAL_MS, self._poll)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        """Stop all workers then destroy the window."""
        self._manager.stop_all()
        self.destroy()
