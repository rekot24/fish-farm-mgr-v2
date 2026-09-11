# ROADMAP — Fish Farm Manager v2

Living document. Completed items are checked off, not deleted — history matters.

---

## Phase 0 — Foundation (Session 1)

- [x] Repo initialized
- [x] README.md
- [x] CLAUDE.md with standing instructions
- [x] ROADMAP.md
- [x] .gitignore
- [x] requirements.txt
- [x] config/constants.py
- [x] config/paths.py
- [x] config/settings.py
- [x] config/devices.py
- [x] config/settings.example.json
- [x] config/devices.example.json
- [x] bot/states.py
- [x] detection/result.py
- [x] All __init__.py files

---

## Phase 1 — Copy from fish-farm-manager

Files copied over as-is from v1 repo:
- [ ] capture/base.py
- [ ] capture/scrcpy_socket.py
- [ ] capture/adb_screencap.py
- [ ] capture/__init__.py
- [ ] detection/detector.py
- [ ] detection/template_bank.py
- [ ] bot/app_logger.py
- [ ] tools/coordinate_finder.py

---

## Phase 2 — Core worker loop

- [ ] bot/actions.py — private tank only: tap, double-tap, launch app, join via link
- [ ] bot/device_worker.py — simple if/elif state loop, timers, no state rules engine
- [ ] bot/device_manager.py — manages workers, exposes status to UI
- [ ] main.py — entry point, wires everything

---

## Phase 3 — UI

- [ ] ui/app.py — main window, three tabs: Main / Device / Settings
- [ ] ui/device_card.py — per-device card widget with all controls
- [ ] ui/device_settings_dialog.py — nickname, model, account, ADB ID
- [ ] ui/settings_dialog.py — global settings dialog
- [ ] ui/capture_manager.py — combined capture + detector management tab (device dropdown + detector dropdown)

---

## Phase 4 — Crop tool redesign

- [ ] tools/crop_tool.py — zoom before crop, square/circle crop, preview after capture, replace existing
- [ ] Shared image pool organized by detector folder
- [ ] Per-device image assignment with shared pool fallback
- [ ] Last tested timestamp + confidence score per detector per device
- [ ] View assigned image inline on the Device tab

---

## Phase 5 — Validation & first run

- [ ] Test private server link rejoin — confirm it works before building full recovery flow
- [ ] If link rejoin fails: design and add intermediate navigation states
- [ ] Verify scrcpy capture not contending with action taps
- [ ] Verify loop cadence stable at 5–10s across all devices
- [ ] Verify stay-awake tap does not interfere with game state

---

## Known issues / open questions

- Private server link rejoin not yet tested — if it fails, additional navigation states needed
- Disconnected screen reconnect button sometimes does not reconnect — timer + leave fallback is designed in

---

## Future / maybe

- Automated tests (Layer 10 of dev-standards — deferred per the standard's own guidance)
- scrcpy live view window per device
