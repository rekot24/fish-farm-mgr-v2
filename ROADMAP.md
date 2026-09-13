# ROADMAP — Fish Farm Manager v2

Living document. Completed items are checked off, not deleted — history matters.

---

## Phase 0 — Foundation ✅ Done

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

## Phase 1 — Copy from fish-farm-manager ✅ Done

- [x] capture/base.py
- [x] capture/scrcpy_socket.py
- [x] capture/adb_screencap.py
- [x] capture/__init__.py
- [x] detection/detector.py
- [x] detection/template_bank.py
- [x] bot/app_logger.py
- [x] tools/coordinate_finder.py

---

## Phase 2 — Core worker loop

Push these five files to complete Phase 2.
Commit message: `feat: Phase 2 — actions, device worker loop, device manager, updated result shape`

- [ ] **bot/actions.py** *(new)* — ADB tap/double-tap/launch/join actions; no state logic
- [ ] **bot/device_worker.py** *(new)* — per-device capture→detect→act loop; if/elif state dispatch
- [ ] **bot/device_manager.py** *(new)* — owns TemplateBank, creates/stops workers, UI status interface
- [ ] **main.py** *(replace stub)* — wires settings, logger, DeviceManager; UI stub (Phase 3 TODO)
- [ ] **detection/result.py** *(replace)* — updated DetectResult shape to match detector.py: name, found, score, bbox, center, matched_path, not_found() classmethod
- [ ] **config/devices.py** *(replace)* — adds tap coordinate fields: auto_farm_tap_x/y, end_run_tap_x/y, reconnect_tap_x/y, leave_tap_x/y (all Optional[int], default None)

### Known follow-ups before Phase 3
- template_bank.py still uses old v1 path structure (assets/shared/ and assets/devices/{serial}/)
  rather than new v2 structure (assets/detectors/{detector_name}/). Fix is scoped to Phase 4
  (crop tool redesign). Workers will log warnings until crop images are placed correctly.

---

## Phase 3 — UI

- [ ] ui/app.py — main window, three tabs: Main / Device / Settings
- [ ] ui/device_card.py — per-device card widget with all controls
- [ ] ui/device_settings_dialog.py — nickname, model, account, ADB ID, tap coordinates
- [ ] ui/settings_dialog.py — global settings dialog
- [ ] ui/capture_manager.py — combined capture + detector management tab (device dropdown + detector dropdown)

---

## Phase 4 — Crop tool redesign

- [ ] tools/crop_tool.py — zoom before crop, square/circle crop, preview after capture, replace existing
- [ ] Update detection/template_bank.py path structure from v1 (assets/shared/, assets/devices/{serial}/)
      to v2 (assets/detectors/{detector_name}/) with files named {detector_name}_{device_id}.png
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

## Phase 6 — Coordinate cache & LOBBY recovery (design locked 2026-09-12)

Design decisions locked this session — build after Phase 5 validates the core loop.

### Coordinate cache
- All click coordinates are found via template match **once per session per device** and
  cached in memory. Subsequent taps use the cached coordinate directly — no re-detection.
- State detection (does the button exist on screen?) still runs every cycle, unchanged.
- Cache is per-device, in-memory only — never written to disk.
- Cache is **invalidated on any Roblox relaunch** on that device (crash recovery, forced
  update, any relaunch), because UI element positions may shift after a Roblox update.
  Program close clears everything naturally since the cache lives in memory.
- End-run button follows the standard detector/template system (shared or device-specific
  crop image, same as every other detector) — the only thing unique about it is the
  find-once caching behavior.

### LOBBY recovery via End Run
- LOBBY state is now a handled recovery path, not just a stuck-timer scenario.
- Detected state LOBBY → fire end-run tap → immediate return to start position
  (no load screen, no delay) → player walks through portal back into tank →
  transition to IN_TANK.
- No guard state or wait needed between the tap and resuming IN_TANK monitoring.

### Tasks
- [ ] Add CoordinateCache (per-device dict: action_name → (x, y) | None) to DeviceWorker
- [ ] On session start / Roblox relaunch: all cache entries reset to None for that device
- [ ] Wire cache clear into existing crash/relaunch recovery path
- [ ] Migrate all click actions to cache-lookup → (miss) detect → store → tap flow
- [ ] Register end_run_button as a standard detector (crop image, DetectorConfig entry)
- [ ] Implement _execute_end_run() as a real cached tap (resolves v1 bug F-02)
- [ ] Add LOBBY → end-run tap → IN_TANK to the state dispatch
- [ ] Add log_coordinate_cache debug category to DebugConfig (cache hits/misses/clears)

---

## Known issues / open questions

- Private server link rejoin not yet tested — if it fails, additional navigation states needed
- Disconnected screen reconnect button sometimes does not reconnect — timer + leave fallback
  is designed in and will be validated in Phase 5

---

## Future / maybe

- Automated tests (deferred per dev-standards own guidance)
- scrcpy live view window per device
