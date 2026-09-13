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
- [x] tools/coordinate_finder.py (replaced in Phase 4)

---

## Phase 2 — Core worker loop ✅ Done

- [x] bot/actions.py — ADB tap/double-tap/launch/join actions; no state logic
- [x] bot/device_worker.py — per-device capture→detect→act loop; if/elif state dispatch
- [x] bot/device_manager.py — owns TemplateBank, creates/stops workers, UI status interface
- [x] main.py — wires settings, logger, DeviceManager, launches UI
- [x] detection/result.py — updated DetectResult shape: name, found, score, bbox, center, matched_path, not_found()
- [x] config/devices.py — tap coordinate fields (later removed in Phase 4 in favor of runtime resolution)

### Hotfixes applied post-Phase 2
- [x] detection/detector.py — renamed DEFAULT_TEMPLATE_CONFIDENCE → DETECTION_THRESHOLD
- [x] config/constants.py — added missing v1 constants: ADB_DEFAULT_TIMEOUT_S, ADB_QUICK_TIMEOUT_S,
      ADB_SCREENCAP_TIMEOUT_S, SCRCPY_PORT_RANGE_SIZE, SCRCPY_SERVER_BIND_SETTLE_S,
      SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S, SCRCPY_TEARDOWN_TIMEOUT_S,
      SCRCPY_SOCKET_CONNECT_ATTEMPT_TIMEOUT_S, SCRCPY_SOCKET_RETRY_SLEEP_S

---

## Phase 3 — UI ✅ Done

- [x] ui/app.py — main window, four tabs: Main / Device / Capture / Settings
- [x] ui/main_tab.py — scrollable 2-column device card grid, Start All / Stop All toolbar
- [x] ui/device_settings_dialog.py — per-device nickname, model, account, timer intervals
- [x] ui/settings_tab.py — global settings: private server link, timing, debug toggles
- [x] ui/capture_tab.py — device + detector dropdowns, crop preview, detector status list
- [x] ui/device_tab.py — device selector, identity fields, timer intervals
- [x] ui/__init__.py

### Hotfix applied post-Phase 3
- [x] ui/capture_tab.py — fixed tk.Canvas legend dot bg (ttk.Frame has no cget("bg"))

### Design decisions locked during Phase 3 UI design
- 2-column card grid (wider window)
- Per-card checkboxes for Auto-farm / End run / Stay awake / Lobby guard toggles
- Toggles on card only — not duplicated in Device tab
- Per-card Start/Stop buttons + running indicator (green/red dot + runtime)
- Context-aware timer area: IN_TANK shows countdowns, LOBBY shows stuck timer, CRASHED shows alert bar
- "End run" button (not "Force end run") + Settings button, split 50/50 at card bottom
- Last action removed from card

---

## Phase 4 — Crop tool redesign ✅ Done

- [x] tools/crop_tool.py — full replacement for coordinate_finder.py
      - Zoom in/out (scroll or buttons), Fit button
      - Box shape: click+drag to draw; corner handles resize (locked to 90°, no trapezoid);
        edge midpoint handles resize one axis; drag inside to move whole selection
      - Circle shape: click+drag to draw; 2 edge handles adjust radius (stays perfect circle);
        drag inside to move
      - Tap override: radio button to override center; click inside selection to place amber dot;
        offset saved as tap_offset_x/y in DetectorAssignment
      - Save writes to assets/detectors/{detector_name}/{detector_name}_{serial}.png
      - Updates detector_assignments in devices.json with filename, shape, timestamp
      - Invalidates TemplateBank cache on save
- [x] detection/template_bank.py — updated to v2 path structure (assets/detectors/{name}/)
- [x] config/devices.py — DetectorAssignment gains shape, tap_offset_x, tap_offset_y;
      manual tap coord fields (auto_farm_tap_x/y etc.) removed — runtime resolution via
      template match replaces them; legacy field stripping on load for backward compat
- [x] ui/device_settings_dialog.py — manual coord fields removed; note points to Capture tab
- [x] ui/device_tab.py — manual coord fields removed
- [x] ui/capture_tab.py — wired to CropTool; updated legend (this device / another device / unset);
      tap override shown in detector list

---

## Phase 5 — Validation & first run 🔄 Next

Connect a real device and smoke-test the full loop end-to-end.

- [ ] Add device to devices.json (or via Device tab) and verify it appears on Main tab
- [ ] Use Capture tab → Open crop tool → capture frame → verify scrcpy or ADB screencap works
- [ ] Save crop images for at least: in_tank, auto_farm_off, lobby, end_run_button
- [ ] Start worker — verify state detection fires correctly (watch log output)
- [ ] Verify auto-farm double-tap fires on interval and lands correctly
- [ ] Test private server link rejoin — confirm device re-enters game after leave
- [ ] If link rejoin fails: design and add intermediate navigation states
- [ ] Verify scrcpy capture not contending with action taps
- [ ] Verify loop cadence stable at 5–10s across all devices
- [ ] Verify stay-awake tap does not interfere with game state

---

## Phase 6 — Coordinate cache & LOBBY recovery (design locked 2026-09-13)

Build after Phase 5 validates the core loop.

### Coordinate cache (design locked)
- All click coordinates found via template match **once per session per device**, cached
  in memory. Subsequent taps use the cached coordinate — no re-detection on every tap.
- State detection still runs every cycle, unchanged.
- Cache is per-device, in-memory only — never written to disk.
- Invalidated on any Roblox relaunch (crash recovery, forced update) — positions may
  shift after an update. Program close clears everything naturally.
- Optional tap_offset_x/y from DetectorAssignment shifts the tap point from bbox center.

### LOBBY recovery via End Run (design locked)
- LOBBY detected → fire end-run tap → immediate return to start position (no load screen,
  no delay) → player walks through portal back into tank → transition to IN_TANK.
- No guard state or wait needed.

### Tasks
- [ ] Add CoordinateCache (per-device dict: detector_name → (x, y) | None) to DeviceWorker
- [ ] Cache populated on first tap per detector per session; cleared on Roblox relaunch
- [ ] Wire cache clear into crash/relaunch recovery path
- [ ] Migrate all click actions to: cache lookup → (miss) template match → store → tap
- [ ] Apply tap_offset_x/y from DetectorAssignment when set (overrides bbox center)
- [ ] Add LOBBY → end-run tap → IN_TANK to state dispatch
- [ ] Add log_coordinate_cache debug category (hits / misses / clears, DEBUG level only)

---

## Known issues / open questions

- Private server link rejoin not yet tested end-to-end — Phase 5 priority
- Disconnected screen reconnect fallback (Leave after timeout) designed in, not yet validated
- scrcpy-server.jar must be placed at assets/scrcpy-server.jar manually (not in repo)
- assets/detectors/ folder created automatically on first crop save

---

## Future / maybe

- Automated tests (deferred — natural candidates: CoordinateCache, LOBBY dispatch branch)
- scrcpy live view window per device
