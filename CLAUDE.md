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
- `tools/usb_pnp.py` — Windows PnP lookup + USB power-cycle via PowerShell (USB reset recovery); also a CLI: `python -m tools.usb_pnp detect|reset <adb_serial>`
- `tools/adb_errors.py` — recognizes adb "device gone" errors (`not found` / `offline`) from exit code + stderr; wording in `ADB_DEVICE_GONE_PATTERN`

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
- Hide console window on launch (Windows) — `suppress_launcher_console`, default on; applies on next restart

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
- **2026-09-20** Roadmap items are hypotheses, not specs — verify every prescribed command and premise against the code and real devices before implementing. In Phase 8, 4 of 8 prescriptions were wrong or unnecessary (8-C, 8-D, 8-F, 8-G) and would have broken the app or done nothing.
- **2026-09-20** The app self-elevates on Windows at startup (one UAC prompt) because USB reset needs admin. `--no-elevate` opts out (IDE debugging); declining UAC keeps the app running unelevated with a WARNING. `_ensure_admin()` runs before settings/logging exist, so it returns a status that `main()` logs afterwards. Considered and rejected a settings-store flag: it would need settings loaded before elevation.
- **2026-09-20** `suppress_launcher_console` (global setting, default True) hides the elevated relaunch's console window via `SW_HIDE`; verified it hides only the console, not the Tk window. Read straight from settings.json at startup, so it applies on next restart. Trade-off: a startup crash before logging is invisible.
- **2026-09-20** USB port reset is recovery **Level 4** (worker ladder: 1 = adb reconnect, 3 = scrcpy rebuild). It is wired at the worker's ADB-failure threshold via `DeviceManager.recover_via_usb_reset()` — NOT in `_rebuild_backend`, which is only reached from tap failures and never from a phone dropping off ADB. Skipped when `pnp_instance_id` is blank, the app is not elevated, or the device was already reset in the last 10 minutes (`USB_RESET_MIN_INTERVAL_S`, stops a flapping phone being power-cycled forever).
- **2026-09-20** The PnP target is the present top-level USB device whose InstanceId ends with the phone's ADB serial (`USB\VID_xxxx&PID_xxxx\<serial>`), not the `&ADB` interface nodes. Per-device `pnp_instance_id` in devices.json (blank = skip); the Device Settings **Detect** button fills it from the ADB serial.
- **2026-09-20** PowerShell hardening for the elevated process: the InstanceId travels in an environment variable and is format-validated (never interpolated into script source); `-ErrorAction Stop` so failures are non-zero exits; Enable is always attempted (retried once) even if Disable failed; ADB return is polled, not a blind sleep.
- **2026-09-20** The scrcpy decode thread throttles only the BGR conversion (`SCRCPY_DECODE_FRAME_INTERVAL_S`); it decodes every packet and never sleeps, because it is also the thread that drains the socket.
- **2026-09-20** Foreground check is `dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'` and matches Roblox on ANY returned line (multi-display devices emit `=null` lines first).
- **2026-09-20** Workers never touch devices.json: tap-coordinate persistence goes through `DeviceManager.persist_tap_cache()`, which saves the live in-memory dict (this replaced the first design's disk read-modify-write — see the follow-up decisions below).
- **2026-09-20 (follow-up)** **Memory is the source of truth for devices; devices.json is its mirror.** `save_devices()` is the ONLY writer and is thread-safe and atomic (module lock, temp file + fsync + `os.replace`, retried on Windows `PermissionError`). Every UI/tool path edits the live dict and saves through the injected `get_devices` / `save_devices_fn` — nothing edits a private `load_devices()` snapshot (that left memory stale and the next save silently reverted the change). `persist_tap_cache` discards a coordinate whose assignment was replaced mid-discovery.
- **2026-09-20 (follow-up)** "Device gone" means adb says `device 'X' not found` or `device offline` (`tools/adb_errors.py`; non-zero exit, stderr only, `adb:`/`error:` prefix). NOT counted: `unauthorized` / `still connecting` (need a person; a USB reset cannot fix them) and timeouts (a slow phone is not a dead one). A received frame still resets the ADB-failure counter (a stale frame from a wedged stream is not counted) — decided, revisit if seen.
- **2026-09-20 (follow-up)** Tap-failure ladder: the soft (adb reconnect) attempt does NOT reset the counter; the hard threshold is checked first; a failed Level 3 rebuild tries USB reset (`_try_usb_reset_recovery`, shared with the ADB-failure path) before the worker stops. `recover_via_usb_reset` refuses to run for a stopped worker.
- **2026-09-20 (follow-up)** **ADB never runs on the Tk thread.** `get_all_status`/`get_status` read a snapshot and start one single-flight background refresh when it is older than `ADB_STATUS_CACHE_TTL_S` (`adb_connected` is omitted until the first result; the UI defaults it to True); `_connected_serials()` is live-only and only for worker/background threads. Every `subprocess` call in `ui/` must be inside a thread target (checked statically). `App._poll` logs failures (once per distinct message) instead of swallowing them.
- **2026-09-20 (follow-up)** Reading the code is not enough to claim a failure mode: my "tap failures reach the rebuild" analysis was wrong until a simulation showed the counter never got past 4. Reproduce the failure with the real loop / real adb output before proposing or writing a fix.

## Tried and rejected

- **2026-09-10** Full state rules engine (from v1) — more complexity than needed for 8 states with simple 1:1 actions.
- **2026-09-10** Health monitor — caused ADB contention and device instability in v1. Not needed for private tank.
- **2026-09-10** Profile system — single behavior set is sufficient; per-device config handles all variation.
- **2026-09-10** Multi-tab approach for capture + management — replaced with single Device tab + dropdowns.
- **2026-09-20** Sleeping in `_store_frames` to throttle the decoder (roadmap 8-D) — runs on the socket-draining thread, so it would consume ~1 packet/s against a 10–60/s encoder and turn `_latest_frame` into minutes-old video.
- **2026-09-20** `dumpsys window windows | grep -m1 -E 'mCurrentFocus|mFocusedApp'` (roadmap 8-C) — the `windows` subset has no focus lines (0 of 8 devices detected the foreground; it would have caused a Roblox relaunch loop) and `-m1` hits `mCurrentFocus=null` first on Android 16/17.
- **2026-09-20** Joining the old decode thread at the top of `_attempt_reconnect` (roadmap 8-F) — `_attempt_reconnect` runs on that very thread, so `join()` raises `RuntimeError: cannot join current thread` and would break auto-reconnect; the two-threads-one-socket hazard it targets does not occur. A guarded (inert) join was also declined.
- **2026-09-20** Re-declaring `_reconnecting` in `ScrcpySocketBackend.__init__` (roadmap 8-G) — already initialized in `CaptureBackend.__init__`; the described AttributeError cannot occur.
- **2026-09-20** The `Get-PnpDevice | Where FriendlyName -like '*Android*'` query for the PnP ID (roadmap 8-H) — returns opaque Samsung `&ADB` interface nodes and stale ghosts, and no Pixels.
- **2026-09-20** Wiring USB reset inside `_rebuild_backend` (roadmap 8-H) — not on the path a phone dropping off ADB takes (that ends in the worker's ADB-failure stop).
- **2026-09-20** Unconditional elevation with no opt-out, and a settings-store `require_admin` flag — the former blocks IDE debugging, the latter needs settings loaded before the UAC relaunch. `--no-elevate` was chosen.
- **2026-09-20 (follow-up)** Hooking USB reset into the tap-failure rebuild path BEFORE fixing the ladder — the hard threshold was unreachable (soft reset the counter), so it would have been dead code. Fixed the ladder first.
- **2026-09-20 (follow-up)** `persist_tap_cache` as a disk read-modify-write under a manager lock — cannot protect against UI writers that save memory, and could stamp an old-image coordinate onto a re-cropped assignment. Replaced by saving the live dict.
- **2026-09-20 (follow-up)** Counting adb timeouts or `unauthorized` as "device gone" — would power-cycle slow or merely unauthorized phones. Counting a stale frame toward the ADB-failure counter (restructuring the loop) — declined for now.
- **2026-09-20 (follow-up)** Matching adb's error text against stdout, or without the `adb:`/`error:` prefix — stdout is arbitrary command output (ps, dumpsys) and a shell command's own stderr could match.
- **2026-09-20 (follow-up)** 5 x 50 ms retries for the atomic `os.replace` — a stress test with a busy reader exhausted it on Windows; widened to 20 x 50 ms.

---

## Current state

- Working: Phases 0–8 and the Phase 8 follow-up are complete, merged to `main` and pushed (see ROADMAP.md). Per-device workers (capture → detect → if/elif state → act) on scrcpy capture; state-driven rejoin navigation; crop tool; redesigned UI. Phase 8: thread-safe persistence, throttled decode, lightweight foreground check, frame lock, Windows UAC self-elevation (`--no-elevate`, `suppress_launcher_console`), and USB port reset recovery (Level 4) with a per-device PnP Instance ID + Detect button. Follow-up: adb "device gone" wording fixed (`tools/adb_errors.py`), tap-failure ladder now reaches the scrcpy rebuild and then USB reset, memory-as-source-of-truth device persistence (atomic `save_devices`, crop tool/capture tab through the live store), and ADB never on the Tk thread (non-blocking status poll, End run and Add device on threads, poll errors logged).
- In progress: nothing. `main` and `origin/main` are in sync; the Phase 8 and follow-up branches are deleted.
- Known broken / unverified: (1) the Phase 8 goal itself — no reboot after 12–18 h — has NOT been confirmed by a soak; (2) verified with mocks, simulations of the real worker loop, real adb output and real PowerShell, but never on the farm for a long run: the tap-failure ladder now really rebuilds scrcpy after 10 failed taps (never ran on hardware before) and the automatic USB-reset path; (3) a stale frame still resets the ADB-failure counter (decided; see Key decisions); (4) rejoin navigation is still untested end-to-end on a live crash; (5) open Pending fixes in ROADMAP.md: `replace_capture_backend` clears `_latest_frame` instead of `_last_frame`, DeviceCard "Starting…" stuck on failed start, dead `reload_devices` wiring.
- Next: run the overnight soak and read `logs/app.log` for the new WARNING lines (`Device gone`, `Tap failures reached`, `USB reset`, `Main tab refresh failed`); then the small Pending fixes.


---

## Session log

### 2026-09-20 — Phase 8 follow-up (recovery-chain hardening), branch `phase-8-followup`
Pushed `main`, branched, read ROADMAP.md and CLAUDE.md in full, then worked three items one at a time (explain → confirm → implement → test → commit). Each premise was checked against the code and real adb output first; two of my own claims were corrected along the way.
- **Item 1 — `_DEVICE_NOT_FOUND`.** Confirmed the text mismatch (adb prints `device 'X' not found`) but the premise was only partly right: the scrcpy-disconnected path already counted. Measured with the real worker loop: a "connected" backend with no frame never counted and spammed `launch_roblox`. Fixed with `tools/adb_errors.py` (`not found` + `offline`). While tracing it found two more breaks: the tap-failure ladder reset its counter at the soft threshold so Level 3 was unreachable (100 failures → adb reconnect ×20, rebuild ×0), and no USB reset was tried when the rebuild failed. Fixed the ladder, then added the USB-reset attempt as a separate commit. My first claim about the tap path was wrong until a simulation disproved it.
- **Item 2 — UI saves bypassing the lock.** Inventory of every devices.json writer. Found a bigger bug: `CropTool._save` edited a disk snapshot and never the live dict, so workers kept the old assignment and the next unrelated UI save reverted the crop (reproduced with the real `_save`). Made memory the source of truth: atomic, lock-protected `save_devices()`, `persist_tap_cache` saves the live dict and discards stale coordinates, crop tool / capture tab go through the store. Also stopped re-crop / re-assign resetting `always_detect`.
- **Item 3 — ADB on the Tk thread.** Traced `App._poll` → `get_all_status` → `adb devices`; measured 2 s / 10 s freezes for slow / hung adb. Non-blocking status poll (snapshot + single-flight background refresh); End run and Add device moved to threads; static check that every `subprocess` call in `ui/` is a thread target; `App._poll` now logs failures.
- **Commits:** 3 (item 1), 2 (item 2), 4 (item 3), then ROADMAP. **Tests:** every change has a test, and the key fixes have a measured before/after (the mismatch, the tap ladder, the crop-tool overwrite, the UI-thread blocking); tests use real adb / PowerShell / phones where possible; the full suite (17 scripts) was green before merging.
- **Decisions:** all recorded above (memory source of truth, device-gone definition, ladder + shared USB-reset recovery, ADB never on Tk thread, reproduce before fixing).
- Next: see Current state.

### 2026-09-20 — Phase 8 (long-run stability), branch `phase-8-long-run-stability`
Phases 2–7 were built in earlier sessions and are recorded in ROADMAP.md, not here. Worked 8-A → 8-H one item at a time: read the listed files, explained the plan, waited for confirmation, implemented, tested, committed separately. Every roadmap prescription was checked against the code and real devices first.
- **8-A** `DeviceManager.persist_tap_cache()` + lock; workers no longer read/write devices.json. Tested with 8 concurrent writers.
- **8-B** `ADB_STATUS_CACHE_TTL_S` (10 s) on the status poll only; `_connected_serials(use_cache=False)` stays live for start/rebuild/discover; failed queries are not cached.
- **8-C** Built with a corrected command after probing 8 real devices (Android 12–17): the roadmap's `dumpsys window windows | grep -m1 …` matched nothing anywhere. Now `dumpsys window displays | grep -E …`, any-line match.
- **8-D** Built as a throttle on BGR conversion, not a sleep (the sleep would have starved the socket-draining thread). Offline, ~85 % less decode-thread busy time; not measured live.
- **8-E** `_frame_lock` around every `_latest_frame` access. Defensive hygiene — the torn read the roadmap described cannot occur.
- **8-F / 8-G** No code change, findings recorded in ROADMAP (the join would raise `RuntimeError`; `_reconnecting` is already initialized in the base class).
- **8-H Part 1** `_ensure_admin()` (UAC relaunch, `--no-elevate`, declined UAC keeps running), `suppress_launcher_console` setting + Settings-tab "Startup" section, README. UAC flow confirmed on hardware.
- **8-H Part 2** `tools/usb_pnp.py`, `pnp_instance_id`, Device Settings field + Detect button, `reset_usb_port` / `recover_via_usb_reset`, wired at the worker's ADB-failure threshold (not `_rebuild_backend`). CLI reset confirmed on hardware (Note 20 Ultra re-enumerated).
- **Findings logged** in ROADMAP: `_DEVICE_NOT_FOUND` text mismatch, `replace_capture_backend` wrong attribute, unserialized UI saves, adb on the Tk thread, uhubctl for Linux.
- **Decisions made** (all recorded above): self-elevate with `--no-elevate` opt-out; USB reset = Level 4 at the ADB-failure threshold with a 10-minute per-device rate limit; PnP ID = top-level USB device ending in the ADB serial, env-var-injected and validated; roadmap items are hypotheses to verify first.
- **Process note:** ROADMAP 8-C, 8-D, 8-F, 8-G and 8-H were rewritten in the check-off pass to describe what was built, not what was prescribed. The branch was merged to `main` with a merge commit and pushed at the start of the follow-up session.
- Next: see Current state.

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
