"""
capture/

Screen capture backends for Android devices via ADB/scrcpy.

  capture/base.py          — abstract capture interface (ABC) (copied from fish-farm-manager)
  capture/scrcpy_socket.py — primary backend: frame from live scrcpy stream (copied from fish-farm-manager)
  capture/adb_screencap.py — fallback backend: on-demand ADB screenshot (copied from fish-farm-manager)
"""
