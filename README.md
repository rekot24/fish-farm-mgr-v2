# Fish Farm Manager v2

A focused Android device farm manager for the Roblox game **Be Fish** — private tank only.

Connects to Android phones via ADB and scrcpy, reads the screen each cycle to determine game state, and takes automated actions based on what it finds. Each device runs its own independent worker loop. Supports up to 10+ devices simultaneously.

Built by [Rekot24](https://github.com/Rekot24).

---

## What it does

- Keeps devices farming in a private Be Fish tank, indefinitely and automatically
- Detects game state each cycle (IN_TANK, LOBBY, CRASHED, DISCONNECTED, and more) and acts accordingly
- Recovers from crashes, disconnects, and lobby stalls automatically
- Navigates back to the private server after a crash — fast path via friend list, fallback via hamburger menu
- Persistent tap coordinate cache — learns where to tap once per session and never re-detects the same element
- Stops itself cleanly if a device drops off USB and restarts when you're ready
- Supports Windows, Linux, and macOS

## What it does NOT do

- No public server logic
- No lead/support device roles
- No health monitoring (battery/temp)
- No profile system

---

## Requirements

- Python 3.10+
- Android devices with USB debugging enabled, connected via USB
- A USB hub with individual power switches is strongly recommended for 3+ devices

**Python dependencies** (installed via pip):
```
opencv-python
numpy
Pillow
av
```

ADB and the scrcpy server jar are **bundled** — no separate installation needed.

- Windows: `tools/adb/adb.exe` is used automatically
- Linux / macOS: the system `adb` is used (install via your package manager, e.g. `sudo apt install adb`)

---

## Installation

```bash
git clone https://github.com/Rekot24/fish-farm-mgr-v2.git
cd fish-farm-mgr-v2
python -m venv venv

# Windows
venv\Scripts\activate

# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

---

## Running

```bash
python main.py
```

**Windows: expect one UAC prompt at startup.** The app relaunches itself with administrator
rights because USB port reset (the last-resort recovery for a device that drops off ADB)
requires an elevated process. Accept the prompt; the original terminal returns immediately
and the app runs as a new, elevated process. On Linux there is no prompt and no elevation.

- **`python main.py --no-elevate`** skips elevation and runs unelevated. Use it when running
  under an IDE debugger (the elevated copy is a new process the debugger is not attached to)
  or for quick UI work. Everything works except USB port reset, and a WARNING is logged.
- **Declining the UAC prompt** does the same — the app still starts unelevated, with a WARNING.
- **Hidden console window.** The elevated process opens its own console window. By default it
  is hidden (**Settings → Startup → Hide console window on launch (Windows)**; takes effect on
  next restart). While it is hidden, a crash during the earliest startup — before logging is
  configured — will not be visible. If the app never appears, untick the setting and restart,
  or run `python main.py --no-elevate` from a terminal to see the error.

---

## First-time setup

### 1 — Enable USB debugging on each device

On each Android phone: **Settings → Developer Options → USB Debugging → On**

Connect via USB and authorize the PC when prompted on the phone.

Verify each device is recognized:
```bash
adb devices
```

### 2 — Add devices

Open the app and go to **Device** tab. Add each connected device — set a nickname, model name, and the Roblox account name running on that device.

### 3 — Crop detector images

Go to the **Capture** tab. For each device, work through the detector list and crop an image for each one:

- Select the device and detector from the dropdowns
- Click **Open crop tool**
- Click **Capture frame** to grab a live screenshot
- Draw a box around the UI element
- Click **Save crop**

Core detectors needed before starting (all others are for crash recovery):

| Detector | What to crop |
|---|---|
| `in_tank` | Any distinctive element visible only when inside the tank |
| `auto_farm_on` | The auto-farm button when it is active (green) |
| `auto_farm_off` | The auto-farm button when it is inactive (red/grey) |
| `end_run_button` | The end run button |
| `lobby` | Any element visible only in the lobby |
| `roblox_home` | The Roblox app home screen icon or element |
| `disconnected` | The disconnect dialog Leave button |
| `death_screen` | The death/respawn screen |
| `net_reveal` | The net reveal animation |

Crash recovery detectors (crop after the core ones are working):

| Detector | What to crop |
|---|---|
| `24rolla_avatar` | The 24rolla friend avatar on the Roblox home screen |
| `join_button` | The Join button on the friend card |
| `hamburger_menu` | The hamburger menu icon on the home screen |
| `continue_playing_button` | The Continue Playing button in the hamburger menu |
| `befish_game_icon` | The Be Fish game icon on the Continue Playing screen |
| `servers_button` | The Servers button on the game page (after scrolling down) |
| `private_server_entry` | The private server entry in the server list |

**Tap offsets:** For detectors that require a tap (like `disconnected` Leave button), use the **Override tap point** option in the crop tool to place the amber dot on the exact tap location within the crop.

### 4 — Configure settings

Go to the **Settings** tab. Key settings:

| Setting | Default | Description |
|---|---|---|
| Double-click delay | 0.15s | Pause between the two auto-farm taps |
| Lobby stuck threshold | 60s | Time in lobby before firing an end-run tap |
| Unknown stuck threshold | 60s | Time in UNKNOWN state before force-relaunching Roblox |
| Loop interval | 5s | How often each device checks state |
| ADB failure threshold | 3 | Consecutive device-not-found failures before worker stops |
| Hide console window on launch (Windows) | On | Hides the console window of the elevated relaunch; takes effect on next restart |

Per-device intervals (auto-farm, end-run, stay-awake) are configured in each device's **Settings** button on the Main tab.

### 5 — Start workers

Go to the **Main** tab and click **Start all**, or start individual devices with their **Start** button. Workers begin detecting state and acting immediately.

---

## How the loop works

Each worker runs on its own thread and repeats every `loop_interval_s`:

1. Capture a frame from the device via scrcpy
2. Run template detectors to identify the current state
3. Dispatch to the appropriate handler — tap, swipe, launch, or wait
4. Sleep until the next cycle

State detection priority (highest to lowest):

```
DISCONNECTED → ROBLOX_HOME → FRIEND_CARD → HAMBURGER_MENU_OPEN →
CONTINUE_PLAYING_SCREEN → GAME_PAGE → GAME_PAGE_SCROLLED →
SERVER_LIST → LOBBY → AUTO_FARM_OFF → DEATH_SCREEN →
NET_REVEAL → IN_TANK → UNKNOWN
```

---

## Crash recovery flow

When the app detects Roblox has crashed or the device is on the home screen:

**Fast path** (when the main account is online and visible):
```
ROBLOX_HOME → tap 24rolla avatar → FRIEND_CARD → tap Join → IN_TANK
```

**Fallback path** (hamburger menu):
```
ROBLOX_HOME → tap hamburger menu → HAMBURGER_MENU_OPEN
→ tap Continue Playing → CONTINUE_PLAYING_SCREEN
→ tap Be Fish icon → GAME_PAGE
→ scroll down → GAME_PAGE_SCROLLED
→ tap Servers → SERVER_LIST
→ tap private server → IN_TANK
```

---

## Folder structure

```
fish-farm-mgr-v2/
  main.py                    entry point — wires everything together
  config/
    constants.py             all named constants with documentation
    paths.py                 cross-platform path resolution
    settings.py              global settings schema and loader
    devices.py               per-device config schema and loader
    settings.example.json    settings template — copy to settings.json
    devices.example.json     devices template — copy to devices.json
  bot/
    states.py                state name constants
    actions.py               ADB actions — taps, swipes, launches
    device_worker.py         per-device capture → detect → act loop
    device_manager.py        owns workers, template bank, status interface
    app_logger.py            unified logging to file and debug panel
  capture/
    base.py                  abstract capture interface
    scrcpy_socket.py         primary backend — live scrcpy stream
    adb_screencap.py         fallback backend — on-demand ADB screenshot
  detection/
    detector.py              template matching logic
    template_bank.py         image cache keyed by detector + serial
    result.py                DetectResult shape
  ui/
    app.py                   main window, tab layout
    main_tab.py              device card grid
    capture_tab.py           detector management and crop tool launcher
    settings_tab.py          global settings UI
    device_tab.py            per-device identity and interval settings
    device_settings_dialog.py per-device settings popup
  tools/
    crop_tool.py             live frame capture + box crop + tap override
  assets/
    detectors/               reference images, organized by detector name
      {detector_name}/
        {detector_name}_{serial}.png
  logs/
    app.log                  rotating session log
    errors.log               always-on critical error log
```

---

## Known issues

- scrcpy connection resets (e.g. from a device reboot mid-session) trigger automatic reconnect — if reconnect fails the worker stops itself cleanly and must be restarted manually
- Occasional scrcpy startup race condition on some Pixel devices — if a worker fails to start, click Stop All then Start All to retry
- Crash recovery navigation requires detector images to be cropped for each device — workers will log warnings if a required detector is missing

---

## Contributing

Issues and pull requests welcome. See [ROADMAP.md](ROADMAP.md) for current status and planned work.

This project follows [Rekot24/dev-standards](https://github.com/Rekot24/dev-standards).
