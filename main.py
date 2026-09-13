"""
main.py

Entry point only. Wires settings, logger, DeviceManager, and UI.
"""

from __future__ import annotations

from config.devices import load_devices, save_devices
from config.paths import project_root
from config.settings import load_settings, save_settings
from bot import app_logger
from bot.device_manager import DeviceManager


def main() -> None:
    settings = load_settings()
    devices = load_devices()

    _settings_box = [settings]
    _devices_box  = [devices]

    def get_settings(): return _settings_box[0]
    def get_devices():  return _devices_box[0]

    def reload_settings():
        _settings_box[0] = load_settings()
        app_logger.configure(_settings_box[0], project_root())
        app_logger.log("Settings reloaded", "INFO")

    def reload_devices():
        _devices_box[0] = load_devices()
        app_logger.log("Device configs reloaded", "INFO")

    def save_settings_fn(s):
        _settings_box[0] = s
        save_settings(s)
        app_logger.configure(s, project_root())

    def save_devices_fn(d):
        _devices_box[0] = d
        save_devices(d)

    # Pass full Settings object (app_logger.configure now takes Settings, not LoggingConfig)
    app_logger.configure(settings, project_root())
    app_logger.log("Fish Farm Manager v2 starting", "INFO")

    manager = DeviceManager(get_settings=get_settings, get_devices=get_devices)

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
