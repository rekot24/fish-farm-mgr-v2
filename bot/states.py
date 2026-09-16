"""
bot/states.py

State name constants. Every state the bot can detect is defined here.
No logic lives in this file — only the names.

Constants use UPPER_CASE as is standard for Python constants.

Detector name resolution: state constants are UPPER_CASE but detector
assignment keys in devices.json use the detector name (lowercase).
The worker normalizes via states.to_detector_name() when doing lookups.
"""

IN_TANK                  = "IN_TANK"
AUTO_FARM_ON             = "AUTO_FARM_ON"
AUTO_FARM_OFF            = "AUTO_FARM_OFF"
DEATH_SCREEN             = "DEATH_SCREEN"
NET_REVEAL               = "NET_REVEAL"
LOBBY                    = "LOBBY"
DISCONNECTED             = "DISCONNECTED"
CRASHED                  = "CRASHED"
ROBLOX_HOME              = "ROBLOX_HOME"
END_RUN_BUTTON           = "END_RUN_BUTTON"
UNKNOWN                  = "UNKNOWN"

# --- Rejoin navigation states ---
JOIN_BUTTON              = "JOIN_BUTTON"
HAMBURGER_MENU_OPEN      = "HAMBURGER_MENU_OPEN"
CONTINUE_PLAYING_SCREEN  = "CONTINUE_PLAYING_SCREEN"
GAME_PAGE                = "GAME_PAGE"
GAME_PAGE_SCROLLED       = "GAME_PAGE_SCROLLED"
SERVER_LIST              = "SERVER_LIST"


def to_detector_name(state: str) -> str:
    """
    Convert a state constant to its corresponding detector name
    (the lowercase key used in detector_assignments and asset folders).

    e.g. "AUTO_FARM_OFF" → "auto_farm_off"
         "END_RUN_BUTTON" → "end_run_button"
    """
    return state.lower()


def from_detector_name(detector_name: str) -> str:
    """
    Convert a detector name back to its state constant value.
    e.g. "auto_farm_off" → "AUTO_FARM_OFF"
    """
    return detector_name.upper()
