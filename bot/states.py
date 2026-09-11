"""
bot/states.py

State name constants. Every state the bot can detect is defined here.
No logic lives in this file — only the names.

All state comparisons throughout the codebase use these constants,
never raw strings.
"""

# Device is inside the tank and the game is active.
# Auto-farm double-click and end-run timers are active in this state only.
IN_TANK = "IN_TANK"

# Auto-farm button is red (turned off).
# Visible in both IN_TANK and LOBBY contexts.
# Action: single tap to re-enable.
AUTO_FARM_OFF = "AUTO_FARM_OFF"

# Death screen — device was eaten by another fish.
# No action taken; wait for state to clear naturally.
DEATH_SCREEN = "DEATH_SCREEN"

# Net reveal animation — plays immediately after death screen.
# No action taken; wait for state to clear naturally.
NET_REVEAL = "NET_REVEAL"

# Device is in the lobby, not yet inside the tank.
# Auto-farm on/off is checked here. Lobby timer runs.
# If lobby timer exceeds threshold: leave server and rejoin.
LOBBY = "LOBBY"

# Disconnected dialog is on screen (Leave / Reconnect buttons visible).
# Action: tap Reconnect immediately. If timeout passes, tap Leave.
DISCONNECTED = "DISCONNECTED"

# Roblox app is not open (black screen or device home screen).
# Action: launch Roblox, then join via private server link.
CRASHED = "CRASHED"

# Roblox is open but showing the home/games screen, not the game.
# Action: join via private server link.
ROBLOX_HOME = "ROBLOX_HOME"

# No detector matched on this cycle.
# Action: wait one cycle and try again.
UNKNOWN = "UNKNOWN"
