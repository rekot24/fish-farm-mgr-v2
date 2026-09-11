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
# and the leave-and-rejoin recovery is triggered (seconds).
LOBBY_STUCK_THRESHOLD_S = 60.0

# ---------------------------------------------------------------------------
# Disconnected screen
# ---------------------------------------------------------------------------

# [TUNABLE] How long to wait for a reconnect attempt before giving up and
# tapping Leave instead (seconds).
DISCONNECT_TIMEOUT_S = 60.0

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

# [TUNABLE] Timeout for ADB shell commands (seconds).
# Increase for slow or high-latency devices.
ADB_TIMEOUT_S = 10.0

# [INTERNAL] Max 32-bit integer — used as "never timeout" for ADB screen_off_timeout.
MAX_INT32 = 2_147_483_647
