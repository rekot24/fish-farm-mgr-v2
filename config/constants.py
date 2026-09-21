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
# USB port reset (Level 3 recovery, Disable/Enable-PnpDevice) needs an elevated
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

# [INTERNAL] ShellExecuteW nShowCmd: SW_SHOWNORMAL - show the window normally.
SHELLEXECUTE_SW_SHOWNORMAL = 1

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
