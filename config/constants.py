"""
config/constants.py

All named constants used across the app. No magic numbers or magic strings
anywhere in the codebase — every meaningful value is named and explained here.

Every constant is tagged:
  [TUNABLE]  — a user-adjustable value; exposed in the Settings UI.
               The value here is the default.
  [INTERNAL] — an implementation fact. Never surfaces in the UI.

UI layout constants (pixel sizes, row heights, widget counts) are NOT here.
Those live as named module-level constants at the top of the UI file that uses them.
"""

# ---------------------------------------------------------------------------
# Loop timing
# ---------------------------------------------------------------------------

# [TUNABLE] How often the worker loop captures and checks game state (seconds).
# Relaxed cadence is fine for private tank — no timing pressure.
LOOP_INTERVAL_S = 5.0

# ---------------------------------------------------------------------------
# Double-click
# ---------------------------------------------------------------------------

# [TUNABLE] Delay between the two taps of a double-click (seconds).
# Too fast and the game may not register both; too slow and it acts as two singles.
DOUBLE_CLICK_DELAY_S = 0.15

# ---------------------------------------------------------------------------
# Auto-farm
# ---------------------------------------------------------------------------

# [TUNABLE] Default interval between auto-farm double-clicks (seconds).
AUTO_FARM_INTERVAL_S = 300.0  # 5 minutes

# ---------------------------------------------------------------------------
# End-run
# ---------------------------------------------------------------------------

# [TUNABLE] Default interval between end-run taps (seconds).
END_RUN_INTERVAL_S = 1800.0  # 30 minutes

# ---------------------------------------------------------------------------
# Lobby
# ---------------------------------------------------------------------------

# [TUNABLE] How long a device can be in the lobby before it is considered stuck
# and an end-run tap is fired (seconds).
LOBBY_STUCK_THRESHOLD_S = 60.0

# ---------------------------------------------------------------------------
# Stay-awake
# ---------------------------------------------------------------------------

# [TUNABLE] Default interval between stay-awake taps (seconds).
# Some Samsung (Knox) devices require this to prevent screen sleep.
STAY_AWAKE_INTERVAL_S = 30.0

# [INTERNAL] Screen coordinate tapped by the stay-awake feature.
# (1, 1) is a safe corner that does not interact with game UI.
STAY_AWAKE_TAP_X = 1
STAY_AWAKE_TAP_Y = 1

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# [TUNABLE] Minimum template match confidence score to consider a detector a hit.
# Lower = more permissive; higher = more strict.
DETECTION_THRESHOLD = 0.80

# ---------------------------------------------------------------------------
# ADB
# ---------------------------------------------------------------------------

# [TUNABLE] Timeout for standard ADB shell commands (seconds).
# Increase for slow or high-latency devices.
ADB_TIMEOUT_S = 10.0

# [INTERNAL] Timeout for quick ADB state checks (e.g. get-state, devices).
ADB_QUICK_TIMEOUT_S = 5.0

# [INTERNAL] Default timeout for ADB commands in the capture backends.
ADB_DEFAULT_TIMEOUT_S = 10.0

# [INTERNAL] Timeout for the ADB screencap command specifically.
# Screencap can take 300-500ms on slower devices; 15s is a generous ceiling.
ADB_SCREENCAP_TIMEOUT_S = 15.0

# [TUNABLE] How long to reuse the last 'adb devices' result before re-querying (seconds).
# Trades freshness for reduced subprocess spawning during the UI poll loop
# (the Main tab polls every ~2s; uncached that is ~43,000 spawns per day).
# Only the status-poll path uses this; start/rebuild always query live.
ADB_STATUS_CACHE_TTL_S: float = 10.0

# [TUNABLE] Timeout for the lightweight foreground-app check (seconds).
# Lower than the old 8s because the command output is ~200 bytes; measured
# ~0.1s on Android 12-17 devices. A timeout is treated as "not foreground".
ADB_FOREGROUND_CHECK_TIMEOUT_S: float = 3.0

# [INTERNAL] Device-side shell command for the foreground-app check. Grep runs
# on the phone so only the matching focus lines cross USB (~200 B) instead of the
# full activity stack (26-75 KB from `dumpsys activity activities`).
# Two things learned by probing real devices (Android 12-17) — do not "simplify":
#   - Use `dumpsys window displays`, NOT `dumpsys window windows`: the
#     mCurrentFocus / mFocusedApp lines are absent from the `windows` subset.
#   - No `grep -m1`: on Android 16/17 the first match is `mCurrentFocus=null` from
#     another display, ahead of the real Roblox line. Take all lines, match any.
ADB_FOREGROUND_CHECK_SHELL_CMD = (
    "dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'"
)

# [INTERNAL] Max 32-bit integer — used as "never timeout" for ADB screen_off_timeout.
MAX_INT32 = 2_147_483_647

# ---------------------------------------------------------------------------
# Scrcpy socket backend
# ---------------------------------------------------------------------------

# [INTERNAL] Number of ports in the pool for per-device port assignment.
# Base port is 27183; each device gets base + (hash(serial) % pool_size).
SCRCPY_PORT_RANGE_SIZE = 100

# [INTERNAL] Seconds to wait after starting the scrcpy server before
# attempting the socket connection. Gives the server time to bind.
SCRCPY_SERVER_BIND_SETTLE_S = 3.0

# [TUNABLE] Minimum time between BGR conversions of decoded frames (seconds).
# The decode thread still decodes EVERY H.264 packet (P-frames depend on earlier
# frames, and pausing the socket read would build a backlog of stale video); it
# only skips the expensive YUV->BGR conversion for frames arriving inside this
# window. The worker reads one frame every 5-10s, so 1s is more than enough.
# Reduce if faster detection is needed. Offline benchmark at native phone
# resolution: conversion ~6-7 ms/frame vs decode ~1.3-1.9 ms/frame.
SCRCPY_DECODE_FRAME_INTERVAL_S: float = 1.0

# [INTERNAL] Timeout when joining the decode thread on disconnect (seconds).
SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S = 5.0

# [INTERNAL] Timeout for ADB teardown commands (port remove, pkill) (seconds).
SCRCPY_TEARDOWN_TIMEOUT_S = 5.0

# [INTERNAL] Timeout for a single socket connection attempt (seconds).
# If the server isn't ready yet, we retry until connect_timeout_s is exceeded.
SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S = 1.0

# [INTERNAL] Sleep between socket connection retry attempts (seconds).
SCRCPY_SOCKET_RETRY_SLEEP_S = 0.5

# ---------------------------------------------------------------------------
# Windows admin elevation (main.py)
# ---------------------------------------------------------------------------
# USB port reset (Level 4 recovery, Disable/Enable-PnpDevice) needs an elevated
# process on Windows. main.py self-elevates once at startup via UAC.

# [INTERNAL] Value returned by platform.system() on Windows. Elevation is
# Windows-only; ctypes.windll does not exist elsewhere.
PLATFORM_WINDOWS = "Windows"

# [INTERNAL] Command-line flag that skips self-elevation (e.g. when running under
# an IDE debugger, where the elevated relaunch would be a new, unattached process).
# The app then runs unelevated and USB reset is unavailable.
NO_ELEVATE_FLAG = "--no-elevate"

# [INTERNAL] ShellExecuteW verb that triggers the UAC elevation prompt.
SHELLEXECUTE_VERB_RUNAS = "runas"

# [INTERNAL] Win32 nShowCmd values passed to ShellExecuteW for the elevated relaunch
# (Settings.suppress_launcher_console picks between them). Source: Win32 ShowWindow.
#   WIN_SW_HIDE       (0) - hides the console window the elevated process opens.
#                           Verified not to hide the app's own Tk window.
#   WIN_SW_SHOWNORMAL (1) - shows the console window normally.
WIN_SW_HIDE = 0
WIN_SW_SHOWNORMAL = 1

# [INTERNAL] ShellExecuteW returns an HINSTANCE; values > 32 mean success and
# values <= 32 are error codes (e.g. 5 = access denied, which is what a declined
# UAC prompt produces). Source: Win32 ShellExecute documentation.
SHELLEXECUTE_MAX_ERROR_CODE = 32

# [INTERNAL] Outcomes reported by main._ensure_admin() and logged once the logger
# is configured (nothing can be logged at the very top of main.py).
ELEVATION_STATUS_ADMIN = "admin"                # already running elevated
ELEVATION_STATUS_NOT_WINDOWS = "not_windows"    # elevation not applicable
ELEVATION_STATUS_OPTED_OUT = "opted_out"        # NO_ELEVATE_FLAG was passed
ELEVATION_STATUS_UNKNOWN = "unknown"            # could not determine admin state
ELEVATION_STATUS_LAUNCH_FAILED = "launch_failed"  # UAC declined or ShellExecuteW error

# ---------------------------------------------------------------------------
# USB port reset - Level 4 recovery (Windows; bot/device_manager.py, tools/usb_pnp.py)
# ---------------------------------------------------------------------------
# When a device is confirmed unresponsive (its worker hits adb_failure_threshold) the
# manager power-cycles the phone's USB device with PowerShell Disable-/Enable-PnpDevice,
# polls `adb devices` for it to return, then rebuilds the scrcpy backend. Needs an
# elevated process and a per-device pnp_instance_id in devices.json (blank = skip).

# [TUNABLE] Seconds to wait between Disable-PnpDevice and Enable-PnpDevice (and before
# an Enable retry). Lets Windows fully tear the device down before it re-enumerates.
USB_RESET_REENUM_WAIT_S: float = 3.0

# [TUNABLE] Subprocess timeout for each PowerShell PnP cmdlet call (seconds). PowerShell
# startup adds ~1-2s overhead even for fast commands - 10s is safe.
USB_RESET_TIMEOUT_S: float = 10.0

# [TUNABLE] After Enable-PnpDevice, how long to poll `adb devices` for the phone to come
# back (seconds). Phones vary: re-enumeration plus ADB re-authorization takes ~5-15s.
USB_RESET_ADB_REAPPEAR_TIMEOUT_S: float = 20.0

# [TUNABLE] Minimum time between USB resets of the same device (seconds). Stops a flapping
# phone being power-cycled in a loop overnight; a second failure inside this window falls
# through to the normal "stop the worker" behaviour.
USB_RESET_MIN_INTERVAL_S: float = 600.0

# [INTERNAL] Poll interval while waiting for ADB to see the device again (seconds).
USB_RESET_ADB_POLL_INTERVAL_S = 1.0

# [INTERNAL] Extra Enable-PnpDevice attempts if the first one fails. A phone left disabled
# is worse than one left offline, so Enable is retried before giving up.
USB_RESET_ENABLE_RETRIES = 1

# [INTERNAL] Timeout for the read-only Get-PnpDevice lookup behind the Detect button
# (seconds). It enumerates every PnP device, so it is slower than Disable/Enable.
PNP_LOOKUP_TIMEOUT_S = 20.0

# [INTERNAL] Allowed shape of a PnP InstanceId, e.g. USB\VID_18D1&PID_4EE7\19161FDEE005RY:
# letters, digits and _ & . \ { } - only. The InstanceId is free-text config used by an
# elevated process, so anything else is rejected before it reaches PowerShell.
PNP_INSTANCE_ID_PATTERN = r"^[A-Za-z0-9_&.\\{}\-]{1,200}$"

# [INTERNAL] Windows PowerShell 5.1 (ships the PnpDevice module). Launched with
# -NoProfile -NonInteractive and no console window.
POWERSHELL_EXE = "powershell"

# [INTERNAL] Environment variables that carry values into the PowerShell scripts, so
# nothing user-supplied is ever interpolated into script source (injection-proof).
PNP_ID_ENV_VAR = "FISHFARM_PNP_INSTANCE_ID"
PNP_SERIAL_ENV_VAR = "FISHFARM_ADB_SERIAL"

# [INTERNAL] Scripts run via `powershell -Command`. -ErrorAction Stop / try-catch make every
# failure a non-zero exit code: Disable/Enable-PnpDevice raise NON-terminating errors by
# default, so without this a failed reset would look like success.
_PS_FAIL_HANDLER = "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
PS_DISABLE_PNP_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "try { Disable-PnpDevice -InstanceId $env:" + PNP_ID_ENV_VAR + " -Confirm:$false } "
    + _PS_FAIL_HANDLER
)
PS_ENABLE_PNP_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "try { Enable-PnpDevice -InstanceId $env:" + PNP_ID_ENV_VAR + " -Confirm:$false } "
    + _PS_FAIL_HANDLER
)
# Find the phone's top-level USB device: present, USB\VID_*, and its InstanceId ENDS WITH the
# ADB serial (verified on Pixel and Samsung phones, Android 12-17). Child interface nodes
# (...&ADB\..., ...&MI_00\...) do not end with the serial, so they are never matched.
PS_FIND_PNP_SCRIPT = (
    "$ErrorActionPreference = 'Stop'; "
    "try { $serial = $env:" + PNP_SERIAL_ENV_VAR + "; "
    "Get-PnpDevice -PresentOnly | Where-Object { "
    "$_.InstanceId -like 'USB\\VID_*' -and "
    "$_.InstanceId.EndsWith('\\' + $serial, [System.StringComparison]::OrdinalIgnoreCase) } | "
    "ForEach-Object { $_.InstanceId } } "
    + _PS_FAIL_HANDLER
)
