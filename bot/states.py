"""
bot/states.py

State name constants. Every state the bot can detect is defined here.
No logic lives in this file — only the names.

Constants use UPPER_CASE as is standard for Python constants.

Detector name resolution: state constants are UPPER_CASE but detector
assignment keys in devices.json use the detector name (lowercase).
The worker normalizes via states.to_detector_name() when doing lookups.

Rule: every state constant's value must exactly match the detector name
used in the capture tab (which is also the key in detector_assignments
and the asset folder name). to_detector_name() lowercases the value —
so "SERVERS_BUTTON" → "servers_button", which must match the capture tab.

Tap-target-only detectors (24rolla_avatar, hamburger_menu,
continue_playing_button, befish_game_icon, private_server_entry,
end_run_button, auto_farm_on) are referenced as plain strings in
handler code only — no state constant needed.

CRASHED is determined by ADB process check, not image detection —
no detector image exists or is needed for it.

Rejoin fallback chain (hamburger route):
  ROBLOX_HOME → tap hamburger_menu (tap target)
  → CONTINUE_PLAYING_BUTTON detected → tap continue_playing_button (tap target)
  → BEFISH_GAME_ICON detected → tap befish_game_icon (tap target)
  → GAME_PAGE detected → swipe up (no tap)
  → SERVERS_BUTTON detected → tap servers_button (tap target)
  → SERVER_LIST detected → tap private_server_entry (tap target)
  → IN_TANK
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
CONTINUE_PLAYING_BUTTON  = "CONTINUE_PLAYING_BUTTON"
BEFISH_GAME_ICON         = "BEFISH_GAME_ICON"
GAME_PAGE                = "GAME_PAGE"
SERVERS_BUTTON           = "SERVERS_BUTTON"
SERVER_LIST              = "SERVER_LIST"


def to_detector_name(state: str) -> str:
    """
    Convert a state constant to its corresponding detector name
    (the lowercase key used in detector_assignments and asset folders).

    e.g. "AUTO_FARM_OFF"     → "auto_farm_off"
         "BEFISH_GAME_ICON"  → "befish_game_icon"
         "SERVERS_BUTTON"    → "servers_button"
    """
    return state.lower()


def from_detector_name(detector_name: str) -> str:
    """
    Convert a detector name back to its state constant value.
    e.g. "auto_farm_off" → "AUTO_FARM_OFF"
    """
    return detector_name.upper()
