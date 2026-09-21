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

## Phase 8 — Long-run stability fixes (next)

Root cause audit identified issues causing overnight degradation — app needs a reboot
after ~12–18 hours of continuous operation. All items below address confirmed findings.
Fix in order listed; each is independent but together they eliminate the overnight bleed.

All fixes must follow dev-standards app-framework.md. Specific compliance requirements
are called out per item below.

---

### 8-A  Coordinate cache — thread-safe write, no disk I/O in worker loop

**Problem:** `_resolve_tap_coords` in `device_worker.py` calls `load_devices()` and
`save_devices()` directly from inside the worker loop every time a new tap coordinate
is discovered. Two workers writing simultaneously silently overwrite each other's
result (not thread-safe). File I/O also does not belong on a hot path.

**Fix:**

- [ ] Add `_tap_cache_lock: threading.Lock` to `DeviceManager.__init__`. This is a
      module-level concern — one lock guards all workers' writes to devices.json.
- [ ] Add a `persist_tap_cache` method to `DeviceManager` with this exact signature:
      ```python
      def persist_tap_cache(self, serial: str, detector_key: str, x: int, y: int) -> None:
          """
          Thread-safe write of a single cached tap coordinate to devices.json.
          Acquires _tap_cache_lock, loads current devices, updates only the one
          field for this serial + detector, and saves. Logs INFO on success,
          WARNING on failure. Called by DeviceWorker via callback; workers never
          call load_devices/save_devices directly.
          """
      ```
      Define the interface (signature + docstring) before implementing.
- [ ] Pass `persist_tap_cache` into `DeviceWorker.__init__` as a `Callable` callback,
      named `persist_tap_cache_fn`. Store as `self._persist_tap_cache`. Same pattern
      as the existing `get_settings` and `get_device_cfg` callbacks.
- [ ] In `_resolve_tap_coords`, mutate `assignment.cached_tap_x/y` immediately on the
      in-memory cfg object (no lock needed — only this worker owns this cfg). Then call
      `self._persist_tap_cache(self._serial, detector_key, x, y)` for the disk write.
      Remove the inline `load_devices` / `save_devices` block entirely.
- [ ] Inside `persist_tap_cache`: defensively handle `all_devices.get(serial)` returning
      None (device removed while running) — log WARNING and return without writing.
      Handle save failure with try/except — log WARNING, do not raise.
- [ ] Log INFO when a coordinate is successfully persisted; WARNING on any failure.
      No silent swallowing. Follows Layer 6 (error handling) and Layer 7 (logging).

**Files:** `bot/device_worker.py`, `bot/device_manager.py`

---

### 8-B  ADB devices subprocess — cache the poll result, don't spawn per-poll

**Problem:** `DeviceManager.get_all_status()` calls `_connected_serials()` on every
invocation, which spawns `subprocess.run([adb, "devices"])`. The UI polls every
2 000 ms, producing ~43 200 subprocess spawns over 24 hours — a steady handle and
CPU bleed.

**Fix:**

- [ ] Add the following named constant to `config/constants.py`, tagged `[TUNABLE]`
      with a comment explaining it:
      ```python
      ADB_STATUS_CACHE_TTL_S: float = 10.0  # [TUNABLE] How long to reuse the last
                                              # 'adb devices' result before re-querying.
                                              # Trades freshness for reduced subprocess
                                              # spawning during the UI poll loop.
      ```
- [ ] Add `_adb_connected_cache: set[str]` and `_adb_cache_updated_at: float = 0.0`
      to `DeviceManager.__init__`.
- [ ] In `_connected_serials()`, return the cached set when
      `time.monotonic() - self._adb_cache_updated_at < ADB_STATUS_CACHE_TTL_S`.
      Refresh and update `_adb_cache_updated_at` only when the TTL has elapsed.
- [ ] `start_device()` and `_rebuild_backend()` bypass the cache and always call
      `subprocess.run` directly — those paths need a live answer.
      Only the status-poll path in `get_all_status()` / `get_status()` uses the cache.
- [ ] Import `ADB_STATUS_CACHE_TTL_S` from `config/constants.py` — not hardcoded
      on the class. No magic numbers (Layer 13, CLAUDE.md instruction 5).

**Files:** `bot/device_manager.py`, `config/constants.py`

---

### 8-C  Foreground check — replace heavy dumpsys command with lightweight equivalent

**Problem:** `_check_roblox_foreground()` in `device_worker.py` runs
`dumpsys activity activities`, which dumps the entire Android activity stack. This is
one of the heaviest ADB shell commands available. It runs every time `get_frame()`
returns None — exactly when the system is already under stress.

**Fix:**

- [ ] Add the following named constant to `config/constants.py`, tagged `[TUNABLE]`:
      ```python
      ADB_FOREGROUND_CHECK_TIMEOUT_S: float = 3.0  # [TUNABLE] Timeout for the
                                                     # lightweight foreground check.
                                                     # Lower than the old 8s because
                                                     # the new command output is ~1 line.
      ```
- [ ] Replace the `dumpsys activity activities` call with:
      ```
      adb shell "dumpsys window windows | grep -m1 -E 'mCurrentFocus|mFocusedApp'"
      ```
      This returns a single matching line — ~10× less output, significantly faster.
- [ ] Add a comment at the call site explaining the choice:
      ```python
      # Lightweight foreground check — single grep line instead of full activity stack.
      # 'dumpsys activity activities' was the previous command; it is too heavy to run
      # on every None-frame cycle. This produces the same result from one output line.
      ```
- [ ] Update the subprocess timeout from 8.0 s to `ADB_FOREGROUND_CHECK_TIMEOUT_S`.
- [ ] Parse the result the same way — check for `com.roblox.client` in the output line.

**Files:** `bot/device_worker.py`, `config/constants.py`

---

### 8-D  Decode thread frame-rate governor — stop pegging CPU 24/7

**Problem:** `_decode_loop` in `scrcpy_socket.py` runs as a tight loop consuming H.264
frames at the encoder's full output rate (~30–60 fps). The worker reads `_latest_frame`
only every `loop_interval_s` (~5–10 s). The decode thread discards ~99 % of what it
produces. With 5 devices this keeps multiple CPU cores at high utilization continuously.

**Fix:**

- [ ] Add the following named constant to `config/constants.py`, tagged `[TUNABLE]`:
      ```python
      SCRCPY_DECODE_FRAME_INTERVAL_S: float = 1.0  # [TUNABLE] Minimum time between
                                                     # BGR conversions of decoded
                                                     # frames. H.264 decode still runs
                                                     # on every packet; only the
                                                     # YUV->BGR conversion is skipped.
                                                     # One per second is more than
                                                     # sufficient for a 5–10s
                                                     # detection loop. Reduce if
                                                     # faster detection is needed.
      ```
- **Implemented differently from the original plan (2026-09-20).** The original
      design slept for the interval at the end of `_store_frames`. That runs on the
      same thread that drains the scrcpy socket, so it would have consumed ~1 packet/s
      against an encoder producing 10–60/s, letting the backlog grow and
      `_latest_frame` go stale. Offline benchmark (native phone resolution): BGR
      conversion ≈ 6–7 ms/frame vs H.264 decode ≈ 1.3–1.9 ms/frame, so the conversion is
      what is throttled. `_store_frames` skips conversion for any frame arriving within
      the interval of the last stored one, and never sleeps. `_last_store_at` is
      initialized to `-inf` and reset in `_reset_decoder_state`, so the first frame after
      any (re)connect is stored immediately; it advances only after a successful
      conversion. No `_stop_event.wait` is needed because nothing blocks.
- [ ] Import `SCRCPY_DECODE_FRAME_INTERVAL_S` from `config/constants.py` in
      `capture/scrcpy_socket.py`. No magic numbers (Layer 13, CLAUDE.md instruction 5).

**Files:** `capture/scrcpy_socket.py`, `config/constants.py`

---

### 8-E  Latest-frame lock — protect numpy array swap during YUV conversion

**Problem:** `_latest_frame` is written by the decode thread and read by the worker
thread without synchronization. CPython's GIL makes the pointer assignment atomic, but
`_frame_to_bgr` on the OpenCV YUV path (`_opencv_yuv_to_bgr`) calls `frame.to_ndarray()`
which can release the GIL. If the worker reads `_latest_frame` while the decode thread
is mid-conversion on the same underlying buffer, the worker may receive a partially
constructed array.

**Fix:**

- [ ] Add `self._frame_lock: threading.Lock = threading.Lock()` to
      `ScrcpySocketBackend.__init__`. Use `threading.Lock()` (not `RLock`) — these two
      code paths (`_store_frames` and `get_frame`) are always called from different
      threads, never re-entrantly from the same thread. RLock here would mask a future
      deadlock bug.
- [ ] In `_store_frames`, wrap only the assignment:
      ```python
      with self._frame_lock:
          self._latest_frame = bgr_frame
      ```
      Do not hold the lock during `_frame_to_bgr` conversion — conversion is the slow
      part and holding the lock there would block the worker from reading the last
      good frame during it.
- [ ] In `get_frame()`:
      ```python
      with self._frame_lock:
          return self._latest_frame
      ```
- [ ] The lock is held only for the assignment and read, never during conversion.
      Contention is microseconds. Add a brief comment at the lock declaration:
      ```python
      # Guards _latest_frame swap between decode thread (_store_frames) and
      # worker thread (get_frame). Held only for assignment/read, not conversion.
      ```

**Files:** `capture/scrcpy_socket.py`

---

### 8-F  Reconnect decode thread — join old thread before starting new one

**Problem:** `_attempt_reconnect` in `scrcpy_socket.py` starts a new `_decode_loop`
thread without waiting for the old one to finish. If the old thread is still winding
down, both threads read from the same socket simultaneously, corrupting the H.264
stream. Over multiple reconnect cycles this accumulates orphaned threads and leaked
socket handles.

**Fix:**

- [ ] At the top of `_attempt_reconnect`, after `_reset_transport_for_retry()` and
      before any reconnect loop logic, add an explicit join on the old decode thread:
      ```python
      if self._decode_thread and self._decode_thread.is_alive():
          app_logger.log(
              f"[scrcpy] Waiting for previous decode thread to exit for {self.serial}",
              "WARNING",
          )
          self._decode_thread.join(timeout=SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S)
          if self._decode_thread.is_alive():
              app_logger.log(
                  f"[scrcpy] Decode thread did not exit within timeout for "
                  f"{self.serial} — proceeding anyway",
                  "WARNING",
              )
      self._decode_thread = None
      ```
      Log at WARNING when the thread is still alive (unexpected); proceed regardless
      after the timeout rather than blocking indefinitely (Layer 11 — defensive).
- [ ] Verify `disconnect()` also joins before clearing `_decode_thread`. The join must
      execute before `_reset_decoder_state()` is called. If it already does, note it
      confirmed; if not, add the same join pattern there too.
- [ ] Reuse the existing `SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S` constant from
      `config/constants.py` for the join timeout — already defined, do not create a
      duplicate.
- **Resolved without a code change (2026-09-20) — the join was NOT added.**
      - `_attempt_reconnect` has exactly one caller: the end of `_decode_loop`
        (scrcpy_socket.py), so it runs ON the decode thread itself — `self._decode_thread`
        is the current thread. The snippet above would call `join()` on the running thread
        and raise `RuntimeError: cannot join current thread` (reproduced against the real
        `_decode_loop` exit path). That exception escapes `_attempt_reconnect` (its `finally`
        only clears `_reconnecting`) and kills the decode thread, leaving `_connected` True
        and `_latest_frame` None — the worker would see None frames forever and never
        reconnect. Adding the roadmap's code as written would have broken auto-reconnect.
      - The stated hazard does not occur on the normal path: by the time
        `_attempt_reconnect` runs, the old read loop has already exited and
        `_reset_transport_for_retry()` has closed the old socket; the new thread opens a
        fresh one, and the old thread ends as soon as `_attempt_reconnect` returns. Threads
        form a chain (T1 → T2 → T3), they do not accumulate, and two threads never read
        the same socket. (Established by tracing the code, not observed on a device.)
      - `disconnect()` already handles the join correctly: it joins the decode thread with
        a `threading.current_thread() is not self._decode_thread` guard and
        `SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S`, before `_reset_decoder_state()` runs. Confirmed
        — nothing to add there.
      - A guarded join (only when the old thread is a different, live thread) was considered
        and declined: it would be inert, since the only caller is the decode thread itself.
        Revisit only if `_attempt_reconnect` is ever called from another thread.

**Files:** `capture/scrcpy_socket.py`

---

### 8-G  `_reconnecting` attribute — initialize in `__init__`

**Problem:** `_reconnecting` is assigned only inside `_attempt_reconnect`
(`self._reconnecting = True`). The `is_reconnecting` property on `capture/base.py`
reads this attribute. If checked before `_attempt_reconnect` has ever been called,
Python raises `AttributeError` because the attribute does not yet exist.

**Fix:**

- [ ] Add `self._reconnecting: bool = False` to `ScrcpySocketBackend.__init__`,
      alongside the other state flags (`_connected`, `_stop_event`, etc.).
- [ ] Add a one-line docstring comment at the declaration:
      ```python
      self._reconnecting: bool = False  # True while _attempt_reconnect is active
      ```
      Follows Layer 8 (commenting standard) — state flags that aren't obvious from
      the name get a short explanation.
- [ ] No other changes needed — the `finally: self._reconnecting = False` in
      `_attempt_reconnect` already handles the reset correctly.
- **Resolved without a code change (2026-09-20) — the attribute was NOT re-declared.**
      `_reconnecting` is already initialized: `CaptureBackend.__init__` (capture/base.py:42)
      sets `self._reconnecting = False` alongside `self._connected = False`, and
      `ScrcpySocketBackend.__init__` calls `super().__init__(serial)` as its first line.
      The `AttributeError` described above cannot occur — a freshly constructed
      `ScrcpySocketBackend` that has never attempted a reconnect reports
      `is_reconnecting == False` (verified). The item also assumed `_connected` was declared
      in `ScrcpySocketBackend.__init__`; it is in the base class too. Re-declaring the flag in
      the subclass would only duplicate the base initialization.

**Files:** `capture/scrcpy_socket.py`

---

### 8-H  USB port reset — Windows (PowerShell PnP) + admin elevation, Linux (uhubctl) roadmap

**What was already ruled out and why:**
- `pyusb dev.reset()` — tested and rejected. Sends a USB reset signal but Windows does
  not fully re-enumerate the device afterward. Does not replicate a physical replug.
- `uhubctl` — does not work on Windows due to the winusb.sys driver limitation (libusb
  cannot power-cycle ports through it). Confirmed viable on Linux — the MINISFORUM
  deployment with the Sabrent HB-BU10 hub (Realtek 0bda chipset) is uhubctl-compatible.
  That path is documented here but not implemented until Linux migration.
- `devcon.exe` (Windows Driver Kit) — operates at the same PnP layer as PowerShell
  `Disable-PnpDevice`/`Enable-PnpDevice` and requires the same admin elevation.
  PowerShell cmdlets are built into Windows with no extra binary to ship — devcon should
  not be implemented unless PowerShell testing fails.
- The scrcpy-layer recovery (pkill scrcpy-server + adb forward --remove-all + retry)
  is already Level 2. USB reset is Level 3 — only attempted after Level 2 also fails.

**Problem:** When a device goes ADB Offline and scrcpy-layer recovery fails, the only
remaining automated option is a USB port power cycle. PowerShell `Disable-PnpDevice` /
`Enable-PnpDevice` operates at the Windows PnP driver level and produces a full device
re-enumeration — equivalent to a physical replug. These cmdlets require administrator
elevation. The app does not currently run elevated. Recovery is a core requirement, not
optional — without it the farm stops and requires manual intervention. Admin elevation
is an accepted hard requirement for this app.

**Part 1 — Admin self-elevation in `main.py`**

- [ ] Add `_ensure_admin()` to `main.py`, called at the very top of the file before
      any other initialization. Gate it behind `platform.system() == "Windows"` so the
      Linux deployment is unaffected:
      ```python
      import ctypes
      import sys
      import platform

      def _ensure_admin() -> None:
          """
          Relaunch the process with UAC elevation if not already running as admin.
          Windows only. On Linux this function is never called.
          No-ops silently if elevation cannot be determined — app continues and
          USB reset will fail gracefully at runtime if elevation is missing.
          """
          try:
              is_admin = ctypes.windll.shell32.IsUserAnAdmin()
          except Exception:
              return  # cannot determine — proceed and fail gracefully later

          if not is_admin:
              # Relaunch with UAC prompt (runas verb). Original process exits cleanly.
              ctypes.windll.shell32.ShellExecuteW(
                  None,
                  "runas",
                  sys.executable,
                  " ".join(f'"{a}"' for a in sys.argv),
                  None,
                  1,  # SW_SHOWNORMAL
              )
              sys.exit(0)

      if platform.system() == "Windows":
          _ensure_admin()
      ```
- [ ] This triggers a single UAC prompt at launch. Once elevated, the whole session
      runs as admin — the user is not prompted again mid-run.
- [ ] Add a docstring comment above the call explaining why:
      ```python
      # USB port reset (Level 3 recovery) requires admin elevation on Windows.
      # Self-elevate now so UAC fires once at startup rather than mid-recovery.
      # On Linux this is skipped — uhubctl does not require elevation.
      ```
- [ ] This is Windows-only code. The `platform.system()` guard is non-negotiable —
      `ctypes.windll` does not exist on Linux and will crash without it.

**Files:** `main.py`

---

**Part 2 — PowerShell PnP USB reset in `bot/device_manager.py`**

- [ ] Add `pnp_instance_id: str = ""` to `DeviceConfig` in `config/devices.py`.
      This is the Windows PnP InstanceId for the device's USB entry, retrieved by
      running `Get-PnpDevice` in PowerShell. Default empty string = "not configured,
      skip USB reset for this device." Per-device because each phone is its own PnP
      entry. Follows config placement rule: per-device options → devices.json.
- [ ] Add the field to the Device Settings dialog — label "PnP Instance ID (USB reset)",
      text entry, note:
      "Run in PowerShell: Get-PnpDevice | Where-Object { $_.FriendlyName -like '*Android*' }
      | Select-Object FriendlyName, InstanceId — paste the InstanceId here.
      Leave blank to skip USB reset for this device."
      Follows Layer 2 — feature is visible in UI with explicit on/off state per device.
- [ ] Add `reset_usb_port(serial: str) -> bool` to `DeviceManager`:
      ```python
      def reset_usb_port(self, serial: str) -> bool:
          """
          Attempt a USB port power cycle via PowerShell PnP cmdlets (Windows only).
          Requires pnp_instance_id in device config and admin elevation in the process.
          Returns True if disable+enable dispatched without error; False on any failure.
          Does not verify ADB re-enumeration — caller must wait and retry ADB afterward.
          Only called after scrcpy-layer recovery (Level 2) has already failed.

          Windows: Disable-PnpDevice / Enable-PnpDevice (same PnP layer as devcon.exe,
                   no extra binary required).
          Linux:   Not implemented here — uhubctl handles this at the MINISFORUM host.
                   See Future/maybe section.
          """
      ```
      Define interface and docstring before implementing (Layer 10).
- [ ] Add these constants to `config/constants.py`:
      ```python
      USB_RESET_REENUM_WAIT_S: float = 3.0  # [TUNABLE] Seconds to wait after
                                              # Enable-PnpDevice before retrying ADB.
                                              # Allows Windows time to re-enumerate
                                              # the device on the bus.

      USB_RESET_TIMEOUT_S: float = 10.0     # [TUNABLE] Subprocess timeout for each
                                              # PowerShell PnP cmdlet call. PowerShell
                                              # startup adds ~1–2s overhead even for
                                              # fast commands — 10s is safe.
      ```
- [ ] The PowerShell commands to execute:
      ```powershell
      Disable-PnpDevice -InstanceId "<pnp_instance_id>" -Confirm:$false
      Enable-PnpDevice  -InstanceId "<pnp_instance_id>" -Confirm:$false
      ```
      Called via `subprocess.run(["powershell", "-Command", "..."])`.
      Sleep `USB_RESET_REENUM_WAIT_S` between disable and enable, and again after
      enable, before returning. Use `time.sleep` — this runs in a recovery context on
      a background thread, blocking is acceptable.
- [ ] Skip immediately (log WARNING, return False) if any of these are true:
      - `platform.system() != "Windows"`
      - `cfg.pnp_instance_id` is empty
      - Process is not elevated (check `ctypes.windll.shell32.IsUserAnAdmin()`)
      Follows Layer 11 (defensive programming) and Layer 6 (graceful failure).
- [ ] Wire into `_rebuild_backend()` between ADB-check failure and giving up:
      ```
      disconnect old backend
            ↓
      check adb devices
            ↓ (device present) → rebuild scrcpy normally
            ↓ (device missing)
      attempt scrcpy-layer recovery (pkill + forward --remove-all + retry connect)
            ↓ (device now present) → rebuild scrcpy
            ↓ (still missing)
      attempt USB reset via reset_usb_port() — Windows only, if pnp_instance_id set
            ↓ wait USB_RESET_REENUM_WAIT_S
      check adb devices again
            ↓ (now present) → rebuild scrcpy, log INFO "USB reset recovered {serial}"
            ↓ (still missing) → log ERROR, return False — end of automated recovery
      ```
- [ ] Log at WARNING when USB reset is attempted. Log at INFO if device comes back.
      Log at ERROR if device is still missing — this is the final automated step.
- [ ] Add this comment block at the top of `reset_usb_port`:
      ```python
      # Windows USB reset via PowerShell Disable-PnpDevice / Enable-PnpDevice.
      # These cmdlets operate at the same Windows PnP driver level as devcon.exe
      # but require no extra binary — PowerShell is built into Windows.
      # Both require administrator elevation (handled at startup in main.py).
      #
      # pyusb dev.reset() was tested and rejected — it does not trigger full
      # Windows re-enumeration, so the device does not reappear in adb devices.
      # uhubctl does not work on Windows (winusb.sys driver limitation).
      #
      # Linux migration path: replace this method with uhubctl port power cycling.
      # uhubctl -l <hub_location> -p <port> -a cycle
      # Sabrent HB-BU10 (Realtek 0bda) on MINISFORUM is confirmed uhubctl-compatible.
      ```
      Follows Layer 8 — comment the why, the rejected alternatives, and the future path.

**Files:** `bot/device_manager.py`, `config/devices.py`, `config/constants.py`,
`ui/device_settings_dialog.py`

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

- [ ] `_DEVICE_NOT_FOUND` never fires — text mismatch. `_check_roblox_foreground` and
      `_check_roblox_running` (device_worker.py) detect a dropped device by looking for the
      literal string "device not found" in adb's output. With `-s <serial>` adb actually
      prints `adb.exe: device 'SERIAL' not found` (verified with an unknown serial on
      2026-09-20), which does not contain that substring. Result: a device that has left ADB
      is treated as "Roblox not running" → CRASHED → `launch_roblox` instead of counting
      toward `adb_failure_threshold`, so the Phase 7 consecutive-failure auto-stop very likely
      never triggers through these two paths. Pre-existing; found during Phase 8-C.
      Fix: match adb's real wording (e.g. a regex like `device '.*' not found|device not
      found`), put the pattern(s) in config/constants.py, and share one helper between both
      checks. Also decide whether `error: device offline` (ADB Offline) should count as a
      failure — it is not matched today either. Check the same assumption in
      `bot/actions.py` and the capture backends.

---

## Future / maybe

- Automated tests (natural candidates: _resolve_tap_coords priority chain, rejoin state dispatch)
- scrcpy live view window per device
- Pixel 6 Pro scrcpy settle time investigation (intermittent startup failure)
