# CLAUDE.md — Fish Farm Manager v2

> This file is read automatically at the start of every Claude Code session.
> Follow all standing instructions below without being prompted.

---

## Project summary

A focused Android device farm manager for the Roblox game Be Fish — private tank only. Connects to Android phones via ADB/scrcpy, captures screenshots, reads game state via template matching, and takes automated actions. Each device runs its own independent worker loop. Rebuilt from fish-farm-manager (v1) with dramatically reduced scope: private tank only, simple if/elif state logic, no profiles, no health monitor, no public server logic.

---

## Standards

This project follows https://github.com/Rekot24/dev-standards
Read app-framework.md before making any architectural decisions.
If asked to do something that conflicts with those standards, flag it before proceeding.

---

## Architecture

- `main.py` — entry point only; wires everything together
- `bot/device_worker.py` — main loop per device: capture → detect → if/elif state → act
- `bot/device_manager.py` — manages all connected device workers
- `bot/states.py` — state name constants only
- `bot/actions.py` — all tap/click/launch actions the bot can take
- `bot/app_logger.py` — rotating logs/app.log + always-on logs/errors.log
- `detection/detector.py` — runs template matching against captured frames
- `detection/template_bank.py` — loads and manages reference images
- `detection/result.py` — DetectResult data shape
- `capture/base.py` — abstract capture interface
- `capture/scrcpy_socket.py` — primary capture backend
- `capture/adb_screencap.py` — fallback capture backend
- `config/settings.py` — global settings loader/saver
- `config/devices.py` — per-device config loader/saver
- `config/constants.py` — all named values, tagged [TUNABLE] or [INTERNAL]
- `config/paths.py` — all path resolution in one place
- `ui/app.py` — main window, three tabs: Main / Device / Settings
- `ui/device_card.py` — per-device card widget
- `ui/device_settings_dialog.py` — per-device settings popup
- `ui/settings_dialog.py` — global settings dialog
- `ui/capture_manager.py` — combined capture + detector management tab
- `tools/crop_tool.py` — image capture with zoom, square/circle crop, preview
- `tools/coordinate_finder.py` — ADB coordinate helper utility

---

## State list

| State | Meaning | Action |
|---|---|---|
| `IN_TANK` | Inside the tank, game active | Run timers; double-click auto-farm, tap end-run, stay-awake |
| `AUTO_FARM_OFF` | Auto-farm button is red | Single tap to re-enable; resume |
| `DEATH_SCREEN` | Just been eaten | Wait — no action |
| `NET_REVEAL` | Post-death net animation | Wait — no action |
| `LOBBY` | In lobby, not yet in tank | Check/enable auto-farm; start lobby timer; if stuck → leave + rejoin |
| `DISCONNECTED` | Reconnect/Leave dialog on screen | Tap reconnect immediately; if 60s passes → tap leave |
| `CRASHED` | App not open | Launch Roblox → join via private server link → lobby takes over |
| `ROBLOX_HOME` | Roblox open but at home screen | Join via private server link → lobby takes over |
| `UNKNOWN` | Nothing matched | Wait one cycle; retry |

---

## Device card controls

Each device card shows:
- Nickname + device model (ADB ID shown only if neither is set)
- Start / Stop buttons
- Auto-farm interval (editable) + live countdown to next click
- End-run interval (editable) + enabled checkbox + Force End Run button
- Stay-awake interval (editable) + enabled checkbox
- Stuck-in-lobby detection enabled checkbox
- Runtime timer (how long this device has been running)
- Current state indicator
- Last action taken

---

## Global settings

- Private server link (used for all rejoin actions)
- Double-click delay between the two taps
- Stuck-in-lobby timer threshold (default 60s)
- Disconnected screen timer threshold (default 60s)
- Loop interval (default 5s)

---

## Image / detector system

- One image per detector per device
- Images live in `assets/detectors/{detector_name}/`
- Named `{detector_name}_{device_id}` — e.g. `in_tank_pixel6a.png`
- Shared pool: any device can reference any image in the detector's folder
- Per-device assignment stored in devices.json (pointer to which image is active)
- If no device-specific image assigned, shared pool is used as fallback
- Crop tool supports: zoom before crop, square or circle crop, preview after capture, replace existing
- Device tab shows: detector dropdown, assigned image preview, last tested timestamp, last score

---

## Key decisions

- **2026-09-10** Private tank only — no public server logic. Scope reduced from v1.
- **2026-09-10** Simple if/elif state loop in device_worker — no rules engine, no state machine class, no event bus.
- **2026-09-10** No health monitor — ADB health polling caused device instability in v1. Dropped entirely.
- **2026-09-10** No profile system — single behavior set; per-device config in settings store covers all variation needed.
- **2026-09-10** Loop cadence relaxed to 5–10s — private tank has no timing pressure (no revenge deaths, no revive windows).
- **2026-09-10** Lobby is the convergence point — crashed, disconnected, and home screen all resolve to lobby; lobby handles getting into the tank.
- **2026-09-10** Auto-farm double-click active in IN_TANK only. Lobby only checks if auto-farm is on/off and enables it if red.
- **2026-09-10** Force End Run button on device card — manually fires end-run tap and resets the end-run countdown timer.
- **2026-09-10** Images organized by detector folder in shared pool; per-device assignment is a pointer into that pool.
- **2026-09-10** New repo (fish-farm-mgr-v2) — v1 repo (fish-farm-manager) kept intact as reference. Never import from v1; copy files over directly.

## Tried and rejected

- **2026-09-10** Full state rules engine (from v1) — more complexity than needed for 8 states with simple 1:1 actions.
- **2026-09-10** Health monitor — caused ADB contention and device instability in v1. Not needed for private tank.
- **2026-09-10** Profile system — single behavior set is sufficient; per-device config handles all variation.
- **2026-09-10** Multi-tab approach for capture + management — replaced with single Device tab + dropdowns.

---

## Current state

- Working: nothing yet — foundation files only
- In progress: Phase 1 (copy capture/detection files from v1)
- Known broken: n/a

---

## Session log

### 2026-09-10 — Session 1
- Full redesign discussion: scope reduced to private tank only
- Removed from scope: health monitor, profiles, state rules engine, event bus, public server logic
- Defined: 8 states, actions per state, device card controls, global settings, image pool model
- Created: all Phase 0 foundation files (see ROADMAP Phase 0)
- Next: confirm Phase 1 files are copied from fish-farm-manager, then build bot/actions.py and the worker loop

---

## Standing instructions

These apply every session without being included in the prompt:

1. Read this file fully before touching any code.
2. Read app-framework.md from https://github.com/Rekot24/dev-standards before any architectural work.
3. Before building anything, explain what you are going to do and why. Wait for confirmation before proceeding.
4. Flag anything that conflicts with dev-standards before proceeding — do not comply silently.
5. No magic numbers or magic strings — all named values go in `config/constants.py` with a comment explaining what they mean and where they came from. Tag every constant `[TUNABLE]` or `[INTERNAL]`. UI layout constants (pixel sizes, row heights, widget counts) are the exception — those live as named module-level constants at the top of the UI file that uses them.
6. No raw print statements — all output goes through the logger.
7. Every function gets a docstring before implementation is written.
8. All error handling follows the two-mode pattern: fail loudly in development, fail gracefully in production.
9. No feature runs unconditionally — every feature checks its enabled flag in the settings store before doing anything.
10. The UI never writes to workers directly. UI → settings store → worker reads → worker acts.
11. GitHub MCP is READ ONLY. Never attempt push_files, create_or_update_file, or any write operation via GitHub tools. Provide file contents for Joshua to push manually with a commit message.
12. At the end of every session, update this file: add a dated session log entry, update current state, add decisions, add anything tried and rejected. Commit the updated CLAUDE.md as the final commit of the session.
