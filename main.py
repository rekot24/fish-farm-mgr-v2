"""
main.py

Entry point only. Wires the settings store, device manager, and UI together.
Contains no business logic.

Startup sequence:
  1. Load settings and device configs
  2. Configure the logger
  3. Create the DeviceManager
  4. Launch the UI (hands off control to Tkinter event loop)
"""

from __future__ import annotations

from config.devices import load_devices, save_devices
from config.paths import project_root
from config.settings import load_settings, save_settings
from bot import app_logger
from bot.device_manager import DeviceManager


def main() -> None:
    """Wire everything together and launch the UI."""

    # 1. Load settings and device configs
    settings = load_settings()
    devices = load_devices()

    # Mutable containers so workers always read the latest values
    _settings_box: list = [settings]
    _devices_box:  list = [devices]

    def get_settings():
        return _settings_box[0]

    def get_devices():
        return _devices_box[0]

    def reload_settings():
        _settings_box[0] = load_settings()
        app_logger.configure(_settings_box[0].logging, project_root())
        app_logger.log("Settings reloaded", "INFO")

    def reload_devices():
        _devices_box[0] = load_devices()
        app_logger.log("Device configs reloaded", "INFO")

    def save_settings_fn(s):
        _settings_box[0] = s
        save_settings(s)

    def save_devices_fn(d):
        _devices_box[0] = d
        save_devices(d)

    # 2. Configure logger
    app_logger.configure(settings.logging, project_root())
    app_logger.log("Fish Farm Manager v2 starting", "INFO")

    # 3. Create device manager
    manager = DeviceManager(
        get_settings=get_settings,
        get_devices=get_devices,
    )

    # 4. Launch UI
    from ui.app import App
    app = App(
        manager=manager,
        get_settings=get_settings,
        get_devices=get_devices,
        reload_settings=reload_settings,
        reload_devices=reload_devices,
        save_settings_fn=save_settings_fn,
        save_devices_fn=save_devices_fn,
    )
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
