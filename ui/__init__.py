"""
ui/

Display layer only. The UI never writes to workers directly.
All control flows through the settings store.

  ui/app.py                    — main window, three tabs: Main / Device / Settings
  ui/device_card.py            — per-device card widget
  ui/device_settings_dialog.py — per-device settings popup
  ui/settings_dialog.py        — global settings dialog
  ui/capture_manager.py        — combined capture + detector management tab
"""
