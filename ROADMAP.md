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

## Phase 8 — Long-run stability fixes ✅ Done (2026-09-20)

Root cause audit identified issues causing overnight degradation — app needs a reboot
after ~12–18 hours of continuous operation. All items below address confirmed findings.
Fix in order listed; each is independent but together they eliminate the overnight bleed.

All fixes must follow dev-standards app-framework.md. Specific compliance requirements
are called out per item below.

**Outcome (2026-09-20, branch `phase-8-long-run-stability`).** Each item was checked against
the code — and where a command or behaviour was involved, against real devices — before
implementing. Four of the eight roadmap prescriptions were wrong or unnecessary and were
changed; the per-item notes below record what was actually built and why.

| Item | Outcome |
|---|---|
| 8-A | ✅ As specified (persistence later reworked — see Phase 8 follow-up, F-2) |
| 8-B | ✅ As specified (later replaced by a non-blocking background refresh — see F-3) |
| 8-C | ✅ Built with a **different command** — the prescribed one returned nothing on every device |
| 8-D | ✅ Built with a **different mechanism** — throttle BGR conversion, never sleep the drain thread |
| 8-E | ✅ As specified — defensive hygiene, the described torn-read cannot occur |
| 8-F | ⛔ **No code change** — the prescribed join would raise `RuntimeError` and break reconnect |
| 8-G | ⛔ **No code change** — attribute already initialized in the base class |
| 8-H | ✅ Both parts built; USB reset **wired at the worker's ADB-failure threshold**, not `_rebuild_backend` |

---

### 8-A  Coordinate cache — thread-safe write, no disk I/O in worker loop

**Status:** ✅ Done 2026-09-20.

**Problem:** `_resolve_tap_coords` in `device_worker.py` calls `load_devices()` and
`save_devices()` directly from inside the worker loop every time a new tap coordinate
is discovered. Two workers writing simultaneously silently overwrite each other's
result (not thread-safe). File I/O also does not belong on a hot path.

**Fix:**

- [x] Add `_tap_cache_lock: threading.Lock` to `DeviceManager.__init__`. This is a
      module-level concern — one lock guards all workers' writes to devices.json.
- [x] Add a `persist_tap_cache` method to `DeviceManager` with this exact signature:
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
- [x] Pass `persist_tap_cache` into `DeviceWorker.__init__` as a `Callable` callback,
      named `persist_tap_cache_fn`. Store as `self._persist_tap_cache`. Same pattern
      as the existing `get_settings` and `get_device_cfg` callbacks.
- [x] In `_resolve_tap_coords`, mutate `assignment.cached_tap_x/y` immediately on the
      in-memory cfg object (no lock needed — only this worker owns this cfg). Then call
      `self._persist_tap_cache(self._serial, detector_key, x, y)` for the disk write.
      Remove the inline `load_devices` / `save_devices` block entirely.
- [x] Inside `persist_tap_cache`: defensively handle `all_devices.get(serial)` returning
      None (device removed while running) — log WARNING and return without writing.
      Handle save failure with try/except — log WARNING, do not raise.
- [x] Log INFO when a coordinate is successfully persisted; WARNING on any failure.
      No silent swallowing. Follows Layer 6 (error handling) and Layer 7 (logging).

**Notes (as first built):** The lock serialized worker-vs-worker writes only; UI saves
still bypassed it and `persist_tap_cache` did a disk read-modify-write from a snapshot that
could be older than memory. **Superseded in the Phase 8 follow-up (F-2):** `_tap_cache_lock`
and the disk read are gone. `save_devices()` itself is now the single, lock-protected,
atomic writer; `persist_tap_cache` saves the live in-memory dict (memory is the source of
truth) and discards a coordinate whose assignment was replaced mid-discovery. The disk write
still happens on the worker thread, only the first time a coordinate is discovered.

**Files:** `bot/device_worker.py`, `bot/device_manager.py`

---

### 8-B  ADB devices subprocess — cache the poll result, don't spawn per-poll

**Status:** ✅ Done 2026-09-20.

**Problem:** `DeviceManager.get_all_status()` calls `_connected_serials()` on every
invocation, which spawns `subprocess.run([adb, "devices"])`. The UI polls every
2 000 ms, producing ~43 200 subprocess spawns over 24 hours — a steady handle and
CPU bleed.

**Fix:**

- [x] Add the following named constant to `config/constants.py`, tagged `[TUNABLE]`
      with a comment explaining it:
      ```python
      ADB_STATUS_CACHE_TTL_S: float = 10.0  # [TUNABLE] How long to reuse the last
                                              # 'adb devices' result before re-querying.
                                              # Trades freshness for reduced subprocess
                                              # spawning during the UI poll loop.
      ```
- [x] Add `_adb_connected_cache: set[str]` and `_adb_cache_updated_at: float = 0.0`
      to `DeviceManager.__init__`.
- [x] In `_connected_serials()`, return the cached set when
      `time.monotonic() - self._adb_cache_updated_at < ADB_STATUS_CACHE_TTL_S`.
      Refresh and update `_adb_cache_updated_at` only when the TTL has elapsed.
- [x] `start_device()` and `_rebuild_backend()` bypass the cache and always call
      `subprocess.run` directly — those paths need a live answer.
      Only the status-poll path in `get_all_status()` / `get_status()` uses the cache.
- [x] Import `ADB_STATUS_CACHE_TTL_S` from `config/constants.py` — not hardcoded
      on the class. No magic numbers (Layer 13, CLAUDE.md instruction 5).

**As built:** `_connected_serials(log_result=False, use_cache=False)` — `use_cache=True` is
passed only by `get_all_status()` / `get_status()`; every other caller (`start_device`,
`_rebuild_backend`, `discover_devices`, the USB-reset ADB poll) stays live by default.
`_adb_cache_updated_at` starts at `float("-inf")`, not `0.0` (`time.monotonic()` counts from
boot on Windows, so `0.0` could look "fresh" right after boot). A failed `adb devices` is
never cached, so the next poll retries. Only the status-poll path writes the cache; live
calls do not refresh it, so a card's `adb_connected` badge can lag a real plug/unplug by up
to 10 s. **Superseded in the Phase 8 follow-up (F-3):** `get_all_status()` ran the
subprocess on the Tk thread whenever the TTL expired, freezing the window for up to 10 s when
adb was hung. It now never runs adb: it reads a snapshot and starts one single-flight
background refresh when the snapshot is stale; `use_cache` is gone and `_connected_serials()`
is live-only again.

**Files:** `bot/device_manager.py`, `config/constants.py`

---

### 8-C  Foreground check — replace heavy dumpsys command with lightweight equivalent

**Status:** ✅ Done 2026-09-20 — built with a corrected command (the originally prescribed one does not work; see below).

**Problem:** `_check_roblox_foreground()` in `device_worker.py` runs
`dumpsys activity activities`, which dumps the entire Android activity stack. This is
one of the heaviest ADB shell commands available. It runs every time `get_frame()`
returns None — exactly when the system is already under stress.

**Fix (as built):**

- [x] `ADB_FOREGROUND_CHECK_TIMEOUT_S: float = 3.0` in `config/constants.py`, `[TUNABLE]`
      (was 8.0 s inline).
- [x] `ADB_FOREGROUND_CHECK_SHELL_CMD` in `config/constants.py`, `[INTERNAL]`:
      ```
      dumpsys window displays | grep -E 'mCurrentFocus|mFocusedApp'
      ```
      Run as `adb -s <serial> shell "<cmd>"`. The grep runs on the phone, so only the ~2–4
      matching focus lines (~200 B) cross USB instead of 26–75 KB of activity stack. The
      constant's comment records why it is `displays` and has no `-m1`.
- [x] Call-site comment in `_check_roblox_foreground` explaining the choice, plus a
      docstring.
- [x] Subprocess timeout is `ADB_FOREGROUND_CHECK_TIMEOUT_S`.
- [x] Parsing: Roblox counts as foreground if **any** returned line contains
      `com.roblox.client` (multi-display devices emit several lines, some `=null`). No
      lines → "Could not determine foreground app" → False. The device-not-found check is
      unchanged (see the `_DEVICE_NOT_FOUND` item in Pending fixes).

**Why not the originally prescribed command.** The roadmap said
`dumpsys window windows | grep -m1 -E 'mCurrentFocus|mFocusedApp'`. Probed on 8 real
devices (Pixel 6 Pro, Pixel 8a, six Samsungs; Android 12–17):
- `dumpsys window windows` does not contain the `mCurrentFocus`/`mFocusedApp` lines at all —
  0 of 8 devices detected the foreground. The worker would have concluded "Roblox not
  foreground" on every None-frame / no-detector-match cycle and relaunched it in a loop.
- `grep -m1` returns `mCurrentFocus=null` first on Android 16/17 (a second display), ahead of
  the real Roblox line.
- Wall time is unchanged (~0.1 s either way; the old command was already fast). The gain is
  ~99 % fewer bytes over USB, not speed.
- The check also runs from `_resolve_state` whenever no detector matches, not only when
  `get_frame()` returns None, so it fires more often than the problem statement says.

Verified: the real method returned True on all online devices, and the parser handled
Roblox-only, null-first, other-app-focused, only-null, empty, timeout and device-not-found
output (stubbed). A genuine "Roblox in the background" case was not reproduced on hardware.

**Files:** `bot/device_worker.py`, `config/constants.py`

---

### 8-D  Decode thread frame-rate governor — stop pegging CPU 24/7

**Status:** ✅ Done 2026-09-20 — built with a different mechanism than originally planned (see the note below).

**Problem:** `_decode_loop` in `scrcpy_socket.py` runs as a tight loop consuming H.264
frames at the encoder's full output rate (~30–60 fps). The worker reads `_latest_frame`
only every `loop_interval_s` (~5–10 s). The decode thread discards ~99 % of what it
produces. With 5 devices this keeps multiple CPU cores at high utilization continuously.

**Fix:**

- [x] Add the following named constant to `config/constants.py`, tagged `[TUNABLE]`:
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
- [x] **Implemented differently from the original plan (2026-09-20).** The original
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
      (`_attempt_reconnect` re-initializes its decoder fields itself rather than calling
      `_reset_decoder_state`, so `_last_store_at` is not reset there — harmless, a reconnect
      always takes longer than the interval.)
- **Measured (offline, synthetic mostly-static H.264 at native phone resolution):** decode-
      thread busy time per packet fell from ~8.2 → 1.1 ms (1080×2340) and 9.1 → 1.4 ms
      (1440×3120), roughly 85 % less, with every packet still decoded. Not measured on a live
      scrcpy session. Assumes scrcpy re-sends an unchanged screen about every 100 ms, so a
      skipped frame is replaced almost immediately (believed, not confirmed on-device).
- [x] Import `SCRCPY_DECODE_FRAME_INTERVAL_S` from `config/constants.py` in
      `capture/scrcpy_socket.py`. No magic numbers (Layer 13, CLAUDE.md instruction 5).

**Files:** `capture/scrcpy_socket.py`, `config/constants.py`

---

### 8-E  Latest-frame lock — protect numpy array swap during YUV conversion

**Status:** ✅ Done 2026-09-20 — as specified, but as defensive hygiene: the described torn read cannot occur.

**Problem:** `_latest_frame` is written by the decode thread and read by the worker
thread without synchronization. CPython's GIL makes the pointer assignment atomic, but
`_frame_to_bgr` on the OpenCV YUV path (`_opencv_yuv_to_bgr`) calls `frame.to_ndarray()`
which can release the GIL. If the worker reads `_latest_frame` while the decode thread
is mid-conversion on the same underlying buffer, the worker may receive a partially
constructed array.

**Fix:**

- [x] Add `self._frame_lock: threading.Lock = threading.Lock()` to
      `ScrcpySocketBackend.__init__`. Use `threading.Lock()` (not `RLock`) — these two
      code paths (`_store_frames` and `get_frame`) are always called from different
      threads, never re-entrantly from the same thread. RLock here would mask a future
      deadlock bug.
- [x] In `_store_frames`, wrap only the assignment:
      ```python
      with self._frame_lock:
          self._latest_frame = bgr_frame
      ```
      Do not hold the lock during `_frame_to_bgr` conversion — conversion is the slow
      part and holding the lock there would block the worker from reading the last
      good frame during it.
- [x] In `get_frame()`:
      ```python
      with self._frame_lock:
          return self._latest_frame
      ```
- [x] The lock is held only for the assignment and read, never during conversion.
      Contention is microseconds. Add a brief comment at the lock declaration:
      ```python
      # Guards _latest_frame swap between decode thread (_store_frames) and
      # worker thread (get_frame). Held only for assignment/read, not conversion.
      ```

**Notes:** `self._latest_frame = self._frame_to_bgr(frame)` builds the complete BGR array
before the single reference rebind, and a published array is never mutated afterwards (verified
across both the FFmpeg `bgr24` and `_opencv_yuv_to_bgr` paths: 79 published arrays, all distinct
objects, none changed after publishing). So the "partially constructed array" in the problem
statement was not possible under the GIL; the lock makes the hand-off explicit. **Beyond the
spec:** the two reset-to-`None` writes (`_reset_decoder_state`, `_attempt_reconnect` on recovery
exhausted) also take the lock, so "guards `_latest_frame`" is true for every access. The lock is
never held during conversion.

**Files:** `capture/scrcpy_socket.py`

---

### 8-F  Reconnect decode thread — join old thread before starting new one

**Status:** ⛔ Resolved without a code change (2026-09-20) — the prescribed join was not added; see the resolution note at the end of this item.

**Problem:** `_attempt_reconnect` in `scrcpy_socket.py` starts a new `_decode_loop`
thread without waiting for the old one to finish. If the old thread is still winding
down, both threads read from the same socket simultaneously, corrupting the H.264
stream. Over multiple reconnect cycles this accumulates orphaned threads and leaked
socket handles.

**Fix:**

- ⛔ **Not implemented** (would raise `RuntimeError` — see resolution) — At the top of `_attempt_reconnect`, after `_reset_transport_for_retry()` and
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
- [x] Verify `disconnect()` also joins before clearing `_decode_thread`. The join must
      execute before `_reset_decoder_state()` is called. If it already does, note it
      confirmed; if not, add the same join pattern there too.
- ⛔ N/A (no join was added) — Reuse the existing `SCRCPY_DECODE_THREAD_JOIN_TIMEOUT_S` constant from
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

**Status:** ⛔ Resolved without a code change (2026-09-20) — the attribute is already initialized; see the resolution note below.

**Problem:** `_reconnecting` is assigned only inside `_attempt_reconnect`
(`self._reconnecting = True`). The `is_reconnecting` property on `capture/base.py`
reads this attribute. If checked before `_attempt_reconnect` has ever been called,
Python raises `AttributeError` because the attribute does not yet exist.

**Fix:**

- ⛔ **Not implemented** (already initialized in `CaptureBackend.__init__`) — Add `self._reconnecting: bool = False` to `ScrcpySocketBackend.__init__`,
      alongside the other state flags (`_connected`, `_stop_event`, etc.).
- ⛔ N/A (no declaration added) — Add a one-line docstring comment at the declaration:
      ```python
      self._reconnecting: bool = False  # True while _attempt_reconnect is active
      ```
      Follows Layer 8 (commenting standard) — state flags that aren't obvious from
      the name get a short explanation.
- [x] No other changes needed — the `finally: self._reconnecting = False` in
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

**Status:** ✅ Done 2026-09-20 — both parts built and manually verified on hardware (UAC relaunch; `tools.usb_pnp detect`/`reset` power-cycling a dropped phone). Several details differ from the original plan because they were tested against real devices; the sections below describe what was built.

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
  is already Level 2. USB reset is the last step (called "Level 4" in the code, since the
  worker's tap-failure ladder already uses Level 1 and Level 3) — only attempted after the
  scrcpy layer has failed and the worker has hit its ADB failure threshold.

**Problem:** When a device goes ADB Offline and scrcpy-layer recovery fails, the only
remaining automated option is a USB port power cycle. PowerShell `Disable-PnpDevice` /
`Enable-PnpDevice` operates at the Windows PnP driver level and produces a full device
re-enumeration — equivalent to a physical replug. These cmdlets require administrator
elevation. The app does not currently run elevated. Recovery is a core requirement, not
optional — without it the farm stops and requires manual intervention. Admin elevation
is an accepted hard requirement for this app.

**Part 1 — Admin self-elevation in `main.py` (as built)**

- [x] `_ensure_admin() -> str` in `main.py`, called before the remaining project imports so an
      unelevated process exits before doing any other initialization. Windows only (the
      `platform.system()` guard is inside the function); skipped with `--no-elevate`.
      Already admin → nothing. Otherwise relaunches with the `runas` verb via `ShellExecuteW`
      and `sys.exit(0)`. It **returns a status** (`ELEVATION_STATUS_*` in constants) that
      `main()` logs once the logger is configured, since nothing can be logged at the top of the
      file: INFO when elevated, WARNING whenever the app runs unelevated on Windows.
- [x] Differences from the original snippet: a **declined or failed UAC prompt keeps the app
      running** unelevated (`ShellExecuteW` returns ≤ 32 on failure) instead of exiting
      silently; the script path is absolute and the cwd is passed explicitly; arguments use
      `subprocess.list2cmdline` (the naive quote-join misparses trailing backslashes and embedded
      quotes); `restype` is `c_void_p` so the 64-bit return value is not truncated; all named
      values (`"runas"`, the show-window flags, the `> 32` threshold, statuses) are `[INTERNAL]`
      constants in `config/constants.py`.
- [x] **`--no-elevate` flag** — runs unelevated (e.g. under an IDE debugger, where the elevated
      copy is a new process the debugger is not attached to). The roadmap made elevation
      unconditional; CLAUDE.md instruction 9 / dev-standards Layer 2 say no feature runs
      unconditionally, so a command-line opt-out was added (a full settings flag was judged too
      heavy: it would need settings loaded before elevation).
- [x] **`suppress_launcher_console: bool = True`** global setting (settings.json, Settings tab →
      "Startup" → "Hide console window on launch (Windows)"; takes effect on next restart).
      Chooses the `nShowCmd` for the relaunch: `WIN_SW_HIDE` (0) or `WIN_SW_SHOWNORMAL` (1).
      `main.py` reads it straight from settings.json (it runs before the settings store exists)
      and falls back to hide if unreadable. Verified `SW_HIDE` hides only the console window,
      not the app's Tk window. Trade-off: with the console hidden, a crash before logging is
      configured is invisible — documented in the README.
- [x] README documents the UAC prompt, `--no-elevate`, declining the prompt, and the
      hidden-console trade-off.

**Files:** `main.py`, `config/constants.py`, `config/settings.py`,
`config/settings.example.json`, `ui/settings_tab.py`, `README.md`

---

**Part 2 — PowerShell PnP USB reset (as built)**

- [x] `pnp_instance_id: str = ""` on `DeviceConfig` (`config/devices.py`). Blank = not
      configured = USB reset skipped for that device.
- [x] **Which InstanceId.** The originally suggested query
      (`Get-PnpDevice | Where FriendlyName -like '*Android*'`) was wrong: it returns only
      Samsung `Android ADB Interface` child nodes with opaque IDs
      (`USB\VID_04E8&PID_6860&ADB\8&F6A2F79&0&0003`), dozens of stale "Unknown" ghosts, and no
      Pixels at all. The right node is the present **top-level USB device whose InstanceId ends
      with the phone's ADB serial**, e.g. `USB\VID_18D1&PID_4EE7\<serial>` (Pixel) or
      `USB\VID_04E8&PID_6860\<serial>` (Samsung composite device) — verified on 7 phones.
- [x] Device Settings dialog: "USB port reset (Windows)" section with a **"PnP Instance ID
      (USB reset)"** field and a **Detect** button that looks the ID up from the ADB serial
      (background thread, polled from the UI thread — never freezes). Detect only fills the
      field; nothing is saved until Save; a failed Detect never overwrites an existing value;
      Save rejects a malformed ID inline; Detect is disabled off Windows. The note gives a
      working PowerShell fallback with the phone's own serial pre-filled. The field is the
      source of truth; empty = off (Layer 2).
- [x] `tools/usb_pnp.py` (new, reusable): `find_instance_id`, `disable_device`,
      `enable_device`, `power_cycle_device`, `is_valid_instance_id`, `is_elevated`, plus a CLI
      (`python -m tools.usb_pnp detect|reset <adb_serial>`) for manual tests.
- [x] `DeviceManager.reset_usb_port(serial) -> bool`. Skips with a WARNING and returns False
      when: not Windows; `pnp_instance_id` blank; ID has an invalid format; process not
      elevated. Otherwise WARNING "Attempting USB port reset…", power-cycles, INFO on success,
      ERROR with the reason on failure. Carries the roadmap's comment block (why PowerShell,
      the rejected alternatives, the Linux/uhubctl path).
- [x] **Safety properties:** the InstanceId is user-entered config used by an elevated
      process, so it is never interpolated into PowerShell source — it travels in an
      **environment variable** and is format-validated (`PNP_INSTANCE_ID_PATTERN`);
      `-ErrorAction Stop` + `try/catch … exit 1` make failures non-zero exits (Disable/Enable-
      PnpDevice raise non-terminating errors by default, so a failed reset would otherwise look
      like success); **Enable is always attempted** (retried once) even if Disable failed, and
      a failure message says the device may be left disabled and gives the exact
      `Enable-PnpDevice` command; PowerShell runs with `-NoProfile -NonInteractive` and
      `CREATE_NO_WINDOW`.
- [x] Constants (`config/constants.py`): `USB_RESET_REENUM_WAIT_S = 3.0`, `USB_RESET_TIMEOUT_S =
      10.0`, `USB_RESET_ADB_REAPPEAR_TIMEOUT_S = 20.0`, `USB_RESET_MIN_INTERVAL_S = 600.0`
      (all `[TUNABLE]`) and the internal poll interval, retry count, lookup timeout, regex,
      PowerShell exe/scripts and env-var names.
- [x] **Wiring — differs from the original plan.** The roadmap put the reset inside
      `_rebuild_backend()`. That is only reached from the worker's tap-failure Level 3 (a live
      video stream but failing taps), which is **not** the path a phone dropping off ADB takes:
      scrcpy reconnect exhaustion leads to the worker's ADB-failure counter and a worker stop,
      never `_rebuild_backend`. It is wired at the **ADB failure threshold** instead, via
      `DeviceManager.recover_via_usb_reset(serial)` passed to the worker as
      `recover_via_usb_reset_fn`. `_rebuild_backend` is unchanged.
      ```
      worker: consecutive ADB failures reach adb_failure_threshold
            ↓
      recover_via_usb_reset(serial)
            ↓ skipped (worker stops as before) if: pnp_instance_id blank/invalid, not elevated,
            ↓ not Windows, or this device was already reset < USB_RESET_MIN_INTERVAL_S ago
      reset_usb_port: Disable-PnpDevice → wait 3 s → Enable-PnpDevice (retry once)
            ↓
      poll a LIVE `adb devices` for up to 20 s (abandons if the worker was stopped)
            ↓ back                                   ↓ still missing
      INFO "USB reset recovered {serial}"      ERROR — end of automated recovery,
      → _rebuild_backend → worker resumes,     worker stops as before
        failure counter reset
      ```
      ADB return is **polled**, not a fixed second sleep (phones take ~5–15 s to re-enumerate
      and re-authorize). The rate limit (a sixth safeguard beyond the plan) stops a flapping
      phone being power-cycled in a loop overnight. **Follow-up (F-1):** the same recovery is
      also tried when the worker's Level 3 scrcpy rebuild fails after repeated tap failures, and
      `recover_via_usb_reset` refuses to run for a worker that is no longer running.
- [x] Logging: WARNING when a reset is attempted, INFO when the device comes back, ERROR when
      it is still missing or the reset fails.
- [x] Verification: mocked tests for every branch of `reset_usb_port`, `recover_via_usb_reset`
      and the worker's threshold handling; real PowerShell for lookup (6/6 online phones) and
      for failure visibility / injection safety with bogus IDs; **manual hardware test passed
      2026-09-20** — `tools.usb_pnp detect` found the right InstanceId and `reset` power-cycled
      a dropped Note 20 Ultra, which re-enumerated and reappeared in the UI. The complete
      worker → threshold → recovery → rebuild path has only been exercised with mocks.

**Files:** `bot/device_manager.py`, `bot/device_worker.py`, `config/devices.py`,
`config/constants.py`, `ui/device_settings_dialog.py`, `tools/usb_pnp.py`,
`tools/__init__.py`, `README.md`

---

## Phase 8 follow-up — recovery-chain hardening ✅ Done (2026-09-20)

Branch `phase-8-followup`, done before the overnight soak. Three items from the Phase 8
check-off pass, worked one at a time with the same method: each premise checked against the
code and real adb output before anything was changed. Investigating them turned up more than
was asked; everything below was measured, not assumed.

### F-1  `_DEVICE_NOT_FOUND` text mismatch — and two more breaks in the recovery chain

**Status:** ✅ Done — three commits.

- [x] **The mismatch.** With `-s <serial>` adb prints `adb.exe: device 'X' not found` (shell) /
      `error: device 'X' not found` (get-state), never the literal `device not found` the two
      checks in `device_worker.py` looked for. New shared helper
      `tools/adb_errors.adb_output_means_device_gone(returncode, stderr)`; the wording lives in
      `ADB_DEVICE_GONE_PATTERN` (`config/constants.py`). It matches **`not found` and `offline`
      only**, requires a non-zero exit, searches stderr only (stdout is arbitrary command
      output) and needs the `adb:` / `error:` prefix so a shell command's own stderr cannot
      match. Verified against the live output for a phone that had dropped off ADB.
- [x] **The premise was only partly true.** "The counter never increments on a real drop" is
      wrong for the main path: when scrcpy's reconnect is exhausted the backend reports
      disconnected and the worker counts without the text check. Measured with the real worker
      loop and real adb wording (threshold 3, 6 loops):

      | Backend state | Before | After |
      |---|---|---|
      | S1 scrcpy disconnected | counts 1,2,3 → recovery → stop | unchanged |
      | S2 "connected", `get_frame()` None | counter stuck at 0, `launch_roblox` ×6, never stops | counts 1,2,3 → recovery, 0 relaunches |
      | S3 stale frame, nothing matches | counter 0, `launch_roblox` ×6 | counter 0 (by decision), 0 relaunches |

      A dropped phone was being read as "Roblox not running" → CRASHED → relaunch spam, and the
      counter was reset instead of incremented.
- [x] **Second break found: the tap-failure ladder never reached Level 3.** The soft-threshold
      adb reconnect reset the failure counter to 0, so with the defaults (soft 5 < hard 10) the
      counter never got past 4–5 and the scrcpy rebuild could never fire. Measured: 100
      consecutive tap failures → `adb_reconnect` ×20, rebuild ×0, worker never stopped — a
      phone with dead taps looped adb reconnects forever. The soft attempt no longer resets the
      counter; the ladder (adb reconnect at 5, rebuild at 10) now repeats while failures
      persist. **Behaviour change:** after 10 consecutive tap failures the scrcpy backend is now
      rebuilt, as the docstring and Settings tab always described. The hard threshold is
      checked first so `hard <= soft` cannot fire both actions on one failure.
- [x] **Third: USB reset on rebuild failure.** With Level 3 reachable, a failed rebuild (device
      gone from ADB) now tries USB reset recovery via the shared `_try_usb_reset_recovery`
      before the worker stops. `recover_via_usb_reset` also refuses to run when its worker is
      not running, so a phone the user just stopped is never power-cycled.
- **Deliberately not changed (decisions):** a received frame still resets the ADB-failure
      counter (S3), so a stale frame from a wedged stream is not counted — a real "not found"
      drop also kills the scrcpy socket and takes the S1 path; `device unauthorized` /
      `still connecting` are not "gone" (they need a person; a USB reset cannot fix them);
      timeouts are not "gone" (a slow phone at the 3 s foreground timeout would look dead and
      get power-cycled). Revisit if a wedged-stream case shows up in the logs.

### F-2  UI saves bypassing the lock — memory is now the single source of truth

**Status:** ✅ Done — two commits.

- [x] **Inventory of every writer of devices.json.** `crop_tool._save`, `capture_tab`
      assign / unassign (direct `save_devices`); `main.py`'s `save_devices_fn` (used by
      `main_tab` ×2 and `device_tab` ×3); `DeviceManager.persist_tap_cache`. The first three
      touch tap fields (`tap_offset_x/y`, `cached_tap_x/y`); the rest write the whole dict,
      including coordinates workers cached. Only `persist_tap_cache` took the 8-A lock.
- [x] **The bigger bug behind it.** `CropTool._save` edited a private `load_devices()` disk
      snapshot and never touched the live in-memory dict (it only received `manager`; and
      `reload_devices` is passed around but never called). Reproduced with the real `_save`:
      after a re-crop the worker kept the old assignment (stale cached coordinate, no tap
      override), and the next unrelated UI save (a card checkbox) wrote the stale memory back
      over the crop on disk, silently reverting it.
- [x] **Fix.** `save_devices()` is the only writer and takes a module-level lock itself, so no
      caller can forget it, and writes atomically (temp file in the same directory, fsync,
      `os.replace`; retried 20 × 50 ms on Windows `PermissionError`; a crash can no longer leave
      a truncated file that `load_devices()` reads as "no devices"; ~4 ms per save).
      `persist_tap_cache` saves the live dict and discards, with a WARNING, a coordinate whose
      assignment the user replaced while the worker was discovering it. `CropTool` and
      `CaptureTab` now take the app's `get_devices` / `save_devices_fn` (required — no silent
      disk-only path) and edit the live dict. Checked statically: `save_devices` is called only
      by the store itself, `main.py`'s wrapper and `persist_tap_cache`; `load_devices` only at
      startup.
- [x] **Also fixed on those lines:** the crop tool and `_assign_detector` built a fresh
      `DetectorAssignment` without `always_detect`, so every re-crop or re-assign silently reset
      it to False. It is preserved now.
- [ ] Left alone by decision: `reload_devices` in `main.py` / `ui/app.py` is dead wiring (never
      called). Removing it changes signatures for no fix; delete it in a cleanup pass.

### F-3  ADB on the Tk thread

**Status:** ✅ Done — four commits.

- [x] **Exact path.** `App._poll` (every 2 s, Tk thread) → `MainTab.refresh()` →
      `DeviceManager.get_all_status()` → `subprocess.run([adb, "devices"], timeout=10)` whenever
      the 10 s cache had expired. Measured blocking on the calling thread: ~0.1 s healthy (real
      adb here is ~20 ms), **2.0 s** for a slow adb, **10.0 s** for a hung one — i.e. the window
      froze most in exactly the state a farm is in when phones drop off USB.
- [x] **Fix.** `get_all_status` / `get_status` never run adb: they read a snapshot and, when it
      is older than `ADB_STATUS_CACHE_TTL_S`, start ONE background refresh (single-flight lock,
      daemon thread) and return the old snapshot at once. A failed query publishes an empty set
      and is retried after a TTL. Until the first refresh finishes `adb_connected` is omitted
      (the UI already defaults it to True), so there is no false "ADB Offline" flash. Tested
      with a fake adb that hangs: 200 polls, slowest 0.5 ms, exactly one subprocess, never on
      the caller's thread; and against the real phones.
- [x] **Other UI-thread ADB sites found and fixed:** the End run button
      (`manager.force_end_run` → tap, 10 s timeout) now runs on a background thread like
      Start/Stop; the Add device scan (`adb devices`) runs on a background thread with the
      button disabled meanwhile. Verified statically: the only `subprocess` calls in `ui/` are
      the two thread targets. (`capture_tab` Test and `crop_tool._capture` were already
      threaded.)
- [x] **`App._poll` no longer swallows errors** (`except Exception: pass`): the first failure of
      each distinct message is logged at WARNING with its traceback (not every 2 s), the loop
      always reschedules, and `development_mode` re-raises.

---

## Known issues / open questions

- scrcpy-server.jar must be placed at assets/scrcpy-server.jar manually (not in repo)
- assets/detectors/ folder created automatically on first crop save
- Rejoin navigation (fast path and fallback) not yet tested end-to-end on a live crash
- Detector images for rejoin states (24rolla_avatar etc.) added to capture tab but not
  yet cropped for all devices — must be done per-device before rejoin will work
- scrcpy startup race condition on Pixel 6 Pro — occasional "Failed to read device header"
  on launch; recovers on Stop All + Start; may need SCRCPY_SERVER_BIND_SETTLE_S increase
- USB reset recovery (8-H) has been run end to end on hardware only through the CLI
  (`python -m tools.usb_pnp reset <serial>`, passed 2026-09-20). The automatic path — worker hits
  the ADB failure threshold → reset → poll ADB → rebuild — is covered by mocked tests, not yet by a
  live drop.
- With `suppress_launcher_console` on (the default), a crash before logging is configured (e.g. a
  bad import at startup) is invisible in the hidden console. Untick the setting or run
  `python main.py --no-elevate` from a terminal to see it.
- The follow-up changes are verified with mocks, simulations of the real worker loop, real adb
  output and real PowerShell — but not yet by a long soak on the farm. In particular the tap-failure
  ladder now really rebuilds scrcpy after 10 consecutive failed taps (F-1), which has never run
  on hardware before, and the automatic USB-reset path is still only exercised with mocks.
- A stale frame still resets the ADB-failure counter (F-1, S3 — decided). If a wedged stream
  ever shows a phone that is gone from ADB while frames stop arriving, that case is not counted.

---

## Pending fixes

- [ ] DeviceCard pending state stuck on failed start — if worker fails to start (e.g.
      scrcpy backend error), "Starting…" label never clears because running never becomes
      True. Fix: add timeout in resync() — if pending == "Starting…" and not running and
      time since pending > ~10s, clear pending and re-enable button.

- [x] **Resolved in the Phase 8 follow-up (F-1).** `_DEVICE_NOT_FOUND` never fires — text mismatch. `_check_roblox_foreground` and
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
      `bot/actions.py` and the capture backends. Fixing this also widens the set of failure shapes
      that reach the ADB-failure counter which triggers USB reset recovery (8-H).
      *Resolved: see F-1 — `tools/adb_errors.py`, `not found` + `offline`.*

- [ ] `replace_capture_backend` clears the wrong attribute — `DeviceWorker.replace_capture_backend`
      sets `self._latest_frame = None`, but the worker reads `self._last_frame`, so the previous
      backend's last frame is not cleared after a backend swap (it is only overwritten by the next
      successful capture, and `_resolve_tap_coords` can use it in the meantime). Pre-existing; found
      during Phase 8-A. Fix: clear `_last_frame` (that attribute is never `_latest_frame` on the
      worker).

- [x] **Resolved in the Phase 8 follow-up (F-2).** UI saves are not serialized with the worker's tap-cache writes — the crop tool, capture tab and
      main tab read-modify-write devices.json without `DeviceManager._tap_cache_lock` (added in 8-A,
      which only serializes worker-vs-worker writes). Rare: it needs a UI save at the same moment as a
      first-time tap-coordinate discovery. Fix: route every devices.json write through one locked save
      path.
      *Resolved: see F-2 — one atomic, lock-protected writer; the crop tool's stale-memory overwrite was the bigger bug.*

- [x] **Resolved in the Phase 8 follow-up (F-3).** `DeviceManager.get_all_status()` runs `adb devices` (10 s timeout) on the Tk main thread. 8-B made
      it ~5× less frequent (10 s TTL), but a hung `adb` can still freeze the window for up to 10 s.
      Fix: refresh the ADB cache on a background thread and let the UI poll read only the cached value.
      *Resolved: see F-3 (plus the End run button and Add device scan, which had the same problem).*

- [ ] Dead wiring: `reload_devices` (`main.py`, `ui/app.py`) is passed around but never called. With
      memory as the source of truth (F-2) there is nothing to reload. Delete it and its parameter in a
      cleanup pass.

---

## Phase 9 — UI polish & scrcpy viewer

### 9-A  scrcpy live view button per device card

**Problem:** There is no way to visually monitor a device from within the app. Debugging
detection issues or verifying game state requires a separate terminal command.

**Design:**
- Each device card gets a "View" button that opens a scrcpy window for that device.
- Window size is controlled by `scrcpy_window_scale: float` in the settings store
  (fraction of the device's native resolution). `0.5` = half size, `0.25` = quarter.
  Translated to scrcpy's `--max-size` flag: `max_size = int(native_long_edge * scale)`.
- Window title is set to the device nickname via scrcpy's `--window-title` flag so
  multiple open windows are identifiable at a glance.
- `scrcpy_window_scale` surfaced in Settings tab under a new "Display" section.
- Button is disabled (greyed out) when the worker is not running or ADB is offline.
- scrcpy is launched as a detached subprocess — closing it does not affect the worker
  or the capture backend (the worker's scrcpy socket is a separate connection).
- Only one view window per device at a time — if the button is clicked while a window
  is already open, bring it to focus rather than opening a second one (track the
  subprocess handle on the card).

**Constants (`config/constants.py`):**
- `SCRCPY_VIEW_WINDOW_SCALE: float = 0.5`  `[TUNABLE]` — default half native resolution.
  Comment: fraction of native long-edge resolution passed to scrcpy `--max-size`.

**Settings store (`config/settings.py`, `config/settings.example.json`):**
- `scrcpy_window_scale: float = SCRCPY_VIEW_WINDOW_SCALE`

**Files:** `ui/main_tab.py` (button + subprocess handle), `config/constants.py`,
`config/settings.py`, `config/settings.example.json`, `ui/settings_tab.py`

---

### 9-B  Device card layout — rows, columns, and auto-fit window width

**Problem:** The app window launches at a fixed default size regardless of how many
devices are configured or how many columns are in use. Adjusting it manually every
session is tedious. There is no way to control the card grid shape from settings.

**Design:**

- `ui_card_columns: int` — how many cards sit side by side. Window width auto-fits to
  this value on launch and whenever the setting changes: each card has a fixed width and
  the window grows or shrinks to hold exactly `columns` of them side by side.
- `ui_card_rows: int` — how many rows of cards the visible card area shows before a
  scrollbar appears. If total cards ≤ `rows × columns`, the area is exactly tall enough
  to show all of them with no scrollbar. If total cards exceed `rows × columns`, the
  card area stays at `rows` height and a vertical scrollbar allows access to the rest.
  No cards are ever hidden.
- Both settings are spinboxes in the Settings tab under a new "Layout" section.
- Enforced bounds: columns min 1 max 4, rows min 1 max 5.
- Defaults: columns = 2, rows = 5.
- Window width and card area height are recalculated and applied whenever either setting
  is saved, and on startup.

**Constants (`config/constants.py`):**
- `UI_DEFAULT_CARD_COLUMNS: int = 2`  `[TUNABLE]`
- `UI_DEFAULT_CARD_ROWS: int = 5`     `[TUNABLE]`
- `UI_MIN_CARD_COLUMNS: int = 1`      `[INTERNAL]`
- `UI_MAX_CARD_COLUMNS: int = 4`      `[INTERNAL]`
- `UI_MIN_CARD_ROWS: int = 1`         `[INTERNAL]`
- `UI_MAX_CARD_ROWS: int = 5`         `[INTERNAL]`

**Settings store (`config/settings.py`, `config/settings.example.json`):**
- `ui_card_columns: int = UI_DEFAULT_CARD_COLUMNS`
- `ui_card_rows: int = UI_DEFAULT_CARD_ROWS`

**Files:** `ui/main_tab.py` (grid layout + scrollbar logic + width/height fit),
`config/constants.py`, `config/settings.py`, `config/settings.example.json`,
`ui/settings_tab.py`

---

## Future / maybe

- Automated tests (natural candidates: _resolve_tap_coords priority chain, rejoin state dispatch)
- Pixel 6 Pro scrcpy settle time investigation (intermittent startup failure)
- Linux USB reset via `uhubctl` (`uhubctl -l <hub_location> -p <port> -a cycle`) for the MINISFORUM
  deployment — the Sabrent HB-BU10 hub (Realtek 0bda chipset) is confirmed uhubctl-compatible. Would
  replace `DeviceManager.reset_usb_port`'s Windows PowerShell path on Linux and needs a per-device hub
  location/port setting. Not implemented until the Linux migration (see 8-H).
