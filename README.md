# Fish Farm Manager v2

A focused Android device farm manager for the Roblox game **Be Fish** — private tank only.

Connects to Android phones via ADB/scrcpy, reads the screen to determine game state, and takes automated actions based on what it finds. Each device runs its own independent worker loop.

---

## What it does

- Keeps devices farming in a private Be Fish tank, indefinitely and automatically
- Detects game state each cycle and acts accordingly
- Recovers from crashes, disconnects, and lobby stalls automatically
- Manages up to 10+ devices simultaneously

## What it does NOT do

- No public server logic
- No lead/support device roles
- No health monitoring (battery/temp)
- No profile system

---

## Folder structure

```
fish-farm-mgr-v2/
  main.py                  — entry point only, wires everything together
  config/                  — settings store, device config, constants, path resolution
  bot/                     — device workers, device manager, states, actions, logger
  detection/               — template matching, template bank, result shape
  capture/                 — scrcpy socket capture and ADB fallback
  ui/                      — display only; never writes to workers directly
  tools/                   — crop tool, coordinate finder
  assets/detectors/        — reference images organized by detector name
  logs/                    — rotating app.log and always-on errors.log
```

---

## Requirements

- Python 3.10+
- ADB installed and on PATH
- scrcpy installed and on PATH
- Android devices connected via USB

Install Python dependencies:
```
pip install -r requirements.txt
```

## Running

```
python main.py
```

---

## Dev standard

This project follows [Rekot24/dev-standards](https://github.com/Rekot24/dev-standards).
