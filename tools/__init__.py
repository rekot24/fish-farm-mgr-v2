"""
tools/

Reusable utilities — general enough to copy to another project.

  tools/crop_tool.py         — image capture with zoom, square/circle crop, preview
  tools/coordinate_finder.py — ADB coordinate helper (copied from fish-farm-manager)
  tools/usb_pnp.py           — Windows PnP lookup + USB power-cycle via PowerShell
  tools/usb_recovery.py      — platform-chosen USB recovery interface (Windows wraps usb_pnp; Linux stub)
  tools/adb_errors.py        — recognize adb device-gone errors from exit code + stderr
"""
