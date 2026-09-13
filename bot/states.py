"""
bot/states.py

State name constants. Every state the bot can detect is defined here.
No logic lives in this file — only the names.
"""

# Device is inside the tank and the game is active.
IN_TANK = "IN_TANK"

# Auto-farm button is green (active/on).
# Used for coordinate resolution — finding the button when it's already on.
# Not a state-change trigger; the bot does not change behavior based on this.
AUTO_FARM_ON = "AUTO_FARM_ON"

# Auto-farm button is red (turned off).
# Action: single tap to re-enable.
AUTO_FARM_OFF = "AUTO_FARM_OFF"

# Death screen — device was eaten by another fish.
DEATH_SCREEN = "DEATH_SCREEN"

# Net reveal animation — plays immediately after death screen.
NET_REVEAL = "NET_REVEAL"

# Device is in the lobby, not yet inside the tank.
LOBBY = "LOBBY"

# Disconnected dialog is on screen.
DISCONNECTED = "DISCONNECTED"

# Roblox app is not open.
CRASHED = "CRASHED"

# Roblox is open but showing the home/games screen.
ROBLOX_HOME = "ROBLOX_HOME"

# No detector matched on this cycle.
UNKNOWN = "UNKNOWN"
