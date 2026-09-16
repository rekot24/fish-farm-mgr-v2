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

- [x] bot/actions.py — ADB tap/double-tap/launch/swipe actions; no state logic
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
- [x] ui/settings_tab.py — global settings: timing, debug toggles
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
      - Box shape only: click+drag to draw; corner handles resize; edge midpoint handles
        resize one axis; drag inside to move whole selection
      - Tap override: radio button to override center; click inside selection to place
        amber dot; offset saved as tap_offset_x/y in DetectorAssignment
      - Save writes to assets/detectors/{detector_name}/{detector_name}_{serial}.png
      - Updates detector_assignments in devices.json with filename, timestamp
      - Clears cached_tap_x/y on save so worker rediscovers position from new image
      - Invalidates TemplateBank cache on save
      - Circle mode removed — masked corners caused poor template match scores
- [x] detection/template_bank.py — updated to v2 path structure (assets/detectors/{name}/)
- [x] config/devices.py — DetectorAssignment gains tap_offset_x/y and cached_tap_x/y;
      shape field removed; manual tap coord fields removed; legacy field stripping on load
- [x] ui/device_settings_dialog.py — manual coord fields removed; note points to Capture tab
- [x] ui/device_tab.py — manual coord fields removed
- [x] ui/capture_tab.py — wired to CropTool; updated legend; tap override shown in list;
      _assign_detector clears cached_tap_x/y when a new image is assigned

---

## Phase 5 — Validation & first run ✅ Done

- [x] Devices added and appearing on Main tab (7 devices)
- [x] Crop tool working — scrcpy and ADB screencap both functional
- [x] Core detector images cropped for all active devices:
      in_tank, auto_farm_off, auto_farm_on, lobby, end_run_button, disconnected,
      roblox_home, death_screen, net_reveal
- [x] Workers starting and detecting state correctly (IN_TANK, NET_REVEAL confirmed live)
- [x] Auto-farm double-tap firing on interval
- [x] scrcpy capture running without contention
- [x] Loop cadence stable across devices

---

## Phase 6 — Rejoin navigation & hardening ✅ Done

Completed in session — all items shipped.

### Chrome URL rejoin removed
- [x] join_private_server, _tap_continue_dialog removed from actions.py
- [x] private_server_link removed from settings, settings UI, settings.example.json
- [x] Chrome URL approach abandoned — unreliable across devices due to special character
      handling in ADB input text; & in URLs gets dropped or truncated

### State-driven rejoin navigation (design locked & implemented)
- [x] 6 new navigation states added to bot/states.py:
      FRIEND_CARD, HAMBURGER_MENU_OPEN, CONTINUE_PLAYING_SCREEN,
      GAME_PAGE, GAME_PAGE_SCROLLED, SERVER_LIST
- [x] Fast path: ROBLOX_HOME → tap 24rolla_avatar → FRIEND_CARD → tap join_button → IN_TANK
- [x] Fallback path: ROBLOX_HOME → tap hamburger_menu → HAMBURGER_MENU_OPEN
      → tap continue_playing_button → CONTINUE_PLAYING_SCREEN
      → tap befish_game_icon → GAME_PAGE → swipe_down_full → GAME_PAGE_SCROLLED
      → tap servers_button → SERVER_LIST → tap private_server_entry → IN_TANK
- [x] CRASHED state simplified to launch-only; state machine takes over from ROBLOX_HOME
- [x] DISCONNECTED fires immediately on detection — taps Leave via tap offset; no timer
- [x] 7 new detector images needed and added to capture tab:
      24rolla_avatar, join_button, hamburger_menu, continue_playing_button,
      befish_game_icon, servers_button, private_server_entry
- [x] swipe_down_full action added to bot/actions.py

### Coordinate cache (persistent)
- [x] DetectorAssignment gains cached_tap_x/y fields in config/devices.py
- [x] _resolve_tap_coords in device_worker.py implements 3-step priority:
      (1) tap_offset_x/y (manual override) → (2) cached_tap_x/y (persisted) →
      (3) template match → store result → use
- [x] Cache persisted to devices.json on first match via load_devices()/save_devices()
- [x] Cache cleared automatically in capture_tab._assign_detector and crop_tool._save
      whenever a new image is assigned

### Dead code removal
- [x] disconnect_timeout_s removed from constants, settings, settings UI, settings.example.json
- [x] _disconnect_detected_at and _reset_disconnect_timer removed from device_worker.py
- [x] All 5 call sites of _reset_disconnect_timer removed
- [x] DetectorAssignment.shape field removed (circle mode gone)

### Stuck-in-lobby fix
- [x] Lobby stuck threshold now fires end-run tap instead of pressing Back to home screen

---

## Phase 7 — UI redesign & reliability ✅ Done

### Device card redesign
- [x] Timer values moved inline with checkbox rows — 4-column grid per card
- [x] State badge + alert message share one fixed-height row above checkboxes
- [x] Running/Stopped displayed as colored badge (green/red) instead of plain dot
- [x] Start/Stop button moved into 3-button row alongside End run and Settings
- [x] Cards are fixed height — no jumping when alert content changes
- [x] Alert area shows: "In lobby for Xs" (amber), "Recovering — launching Roblox" (red),
      "Disconnected — attempting reconnect" (red), empty otherwise
- [x] Timers use local per-second countdown via Tkinter after() — resynced on each
      worker poll to correct drift; no flashing or full card rebuilds

### Non-blocking start/stop
- [x] Start/Stop buttons dispatch to background thread — app never freezes
- [x] Alert label shows "Starting…" / "Stopping…" (blue) while pending
- [x] Button disabled while pending; re-enabled when worker state confirms change
- [x] Start All / Stop All also non-blocking via background thread

### Settings additions
- [x] Recovery section added to Settings tab
- [x] adb_failure_threshold setting — consecutive "device not found" failures before
      worker stops itself (default 3); any successful contact resets counter
- [x] disconnect_timeout_s removed from settings (was never used)
- [x] private_server_link removed from settings

### Consecutive ADB failure auto-stop
- [x] DeviceWorker tracks consecutive "device not found" via _DEVICE_NOT_FOUND sentinel
- [x] ADB checks return sentinel (not False) on device not found — distinct from other errors
- [x] Counter increments only on consecutive failures; any successful frame resets to 0
- [x] At threshold: worker logs clearly and stops itself on a background thread
- [x] Card shows as Stopped; must be restarted manually once device is back and unlocked

### Crop tool
- [x] Circle mode removed — box crops only
- [x] Shape radiobuttons, _on_shape_change, _draw_circle_selection removed
- [x] _get_crop_image simplified to clean rectangular crop only

---

## Known issues / open questions

- scrcpy-server.jar must be placed at assets/scrcpy-server.jar manually (not in repo)
- assets/detectors/ folder created automatically on first crop save
- Rejoin navigation (fast path and fallback) not yet tested end-to-end on a live crash
- Detector images for rejoin states (24rolla_avatar etc.) added to capture tab but not
  yet cropped for all devices — must be done per-device before rejoin will work
- scrcpy startup race condition on Pixel 6 Pro — occasional "Failed to read device header"
  on launch; recovers on Stop All + Start; may need SCRCPY_SERVER_BIND_SETTLE_S increase

---

## Pending fixes

- [ ] DeviceCard pending state stuck on failed start — if worker fails to start (e.g.
      scrcpy backend error), "Starting…" label never clears because running never becomes
      True. Fix: add timeout in resync() — if pending == "Starting…" and not running and
      time since pending > ~10s, clear pending and re-enable button.

---

## Future / maybe

- Automated tests (natural candidates: _resolve_tap_coords priority chain, rejoin state dispatch)
- scrcpy live view window per device
- Pixel 6 Pro scrcpy settle time investigation (intermittent startup failure)
