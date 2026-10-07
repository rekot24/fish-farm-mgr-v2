# SPEC.md — Fish Farm Manager v2

> The current milestone only, in detail. Claude Code builds from this file.
> At close-out: log the result in `ROADMAP.md`, move anything unfinished to "Issues to be addressed",
> record decisions worth keeping in `CLAUDE.md`, then reset this file to the empty template at the bottom.

**Milestone:** S1 — Headless core runs on homelab
**Status:** not started
**Last updated:** 2026-10-06

---

## Goal
Run the existing worker loop on the Ubuntu homelab server with no GUI, started by hand over SSH, driving
one real phone. The Windows Tkinter GUI keeps working exactly as it does today. This proves the shared core
(`bot/`, `capture/`, `detection/`, `config/`) runs on Linux, and it adds the second entry point that every
later server milestone (systemd service, `/status`, web portal, guest access) builds on. Nothing here is
visible to a user yet; it is the foundation.

## Out of scope (not now — parked in ROADMAP "Not now")
- FastAPI, the web portal, a `/status` endpoint, push notifications
- The systemd service (next milestone, S2)
- Guest access, Cloudflare Tunnel / Access
- Real Linux USB recovery (sysfs unbind/rebind, uhubctl) — this milestone only adds a stub
- Live video, browser control
- Any change to the Windows USB reset behaviour or retry count (separate item, see ROADMAP Issues)
- Moving the whole farm to homelab — one phone only

## Design notes
- **Core stays clean.** Nothing under `bot/`, `capture/`, `detection/`, `config/` may import `tkinter`,
  `ui`, or `tools.usb_pnp` at module level. Today the only violation is `bot/device_manager.py` line ~71
  (`from tools import usb_pnp`). Everything else is already clean (checked 2026-10-06).
- **USB recovery behind one interface, chosen by platform.** `DeviceManager` calls a small module (proposed
  name `tools/usb_recovery.py`) instead of `usb_pnp` directly. Windows implementation = the existing
  `usb_pnp` calls, unchanged. Linux implementation = reports "not supported on this platform" and returns
  failure, so the worker falls through to its existing "stop the device" behaviour. `usb_pnp` is imported
  only on Windows (lazily). Claude Code proposes the exact interface in Plan mode.
- **Second entry point `main_headless.py`.** Loads settings and devices (same loaders, same files),
  configures logging, builds `DeviceManager`, starts what the command line asks for, then waits. Nothing
  starts unless asked. Planned arguments: `--device <adb_serial>` (start one device), `--start-all`.
  No Tk, no UAC/elevation code, no `ctypes`. `main.py` is not modified.
- **Clean shutdown.** SIGINT (Ctrl+C) and SIGTERM call `manager.stop_all()`, then exit. The wait for workers
  to stop is bounded by a named constant in `config/constants.py` (tagged `[TUNABLE]`).
- **Logging.** Headless adds a stdout handler (journald-friendly: plain lines, no colour) alongside the
  existing rotating `logs/app.log` and `logs/errors.log`. Windows GUI logging is unchanged. Claude Code
  reads `bot/app_logger.py` first and proposes the smallest change.
- **Config is per machine, never synced through git.** `config/settings.json`, `config/devices.json` and
  `assets/detectors/` are gitignored. They reach homelab by the manual one-time copy below.
  `scrcpy-server.jar` is tracked in git (`tools/scrcpy/`), so `git pull` brings it.
- **adb on Linux.** `config/paths.py` already returns plain `adb` on non-Windows. The system package
  (`sudo apt install adb`) is used; the bundled Windows `adb.exe` is not.
- **Standards touched:** Layer 4 (modularity: core free of UI/OS code), Layer 7 (logging), Layer 13 (no magic
  numbers: shutdown timeout in constants), Layer 15 (CLAUDE.md "Known deviations" table created this
  milestone).

## Manual one-time steps (Joshua does these; Claude Code does not touch the server)
Placeholders: `<user>` = your homelab login. Never paste passwords or keys into chat.

**M1. Back up config on the PC first.**
HOME-PC, PowerShell, any folder. Copies the three machine-specific items to a dated folder outside the repo:
```
$d = "D:\Backups\fish-farm-mgr-v2-2026-10-06"
New-Item -ItemType Directory -Path $d -Force
Copy-Item D:\Coding\fish-farm-mgr-v2\config\devices.json, D:\Coding\fish-farm-mgr-v2\config\settings.json $d
Copy-Item D:\Coding\fish-farm-mgr-v2\assets\detectors $d -Recurse
```
Expected: the folder exists and holds two .json files and a `detectors` folder.

**M2. Copy config and detector images to homelab (after the code is pulled there).**
HOME-PC, PowerShell, any folder. Copies (does not move) the files; each machine then owns its own copy:
```
scp D:\Coding\fish-farm-mgr-v2\config\devices.json D:\Coding\fish-farm-mgr-v2\config\settings.json <user>@homelab:~/projects/fish-farm-mgr-v2/config/
scp -r D:\Coding\fish-farm-mgr-v2\assets\detectors <user>@homelab:~/projects/fish-farm-mgr-v2/assets/
```
Expected: each file listed with 100%. These files hold device serials and your private server link, so they
go by `scp` only, never git.

**M3. Pick and move ONE phone.** A phone can be driven by only one machine at a time. Unplug one phone from
the Windows hub and plug it into homelab. First, stop that device in the Windows app. Choose a Pixel if
you can (Pixels honour adb commands; a Samsung that locks cannot be unlocked remotely). Expect to accept the
"Allow USB debugging" prompt on the phone for the new computer. That account is off the farm while it is on
homelab. Plug it back into the hub when the milestone is done.

## Tasks
*Each task has a "done when" check that can be verified, not just believed.*

1. [ ] **Core import check tool.** Add `tools/check_core_imports.py`: a static script that fails if any
   module under `bot/`, `capture/`, `detection/`, `config/` imports `tkinter`, `ui`, `tools.usb_pnp`,
   `ctypes` or `winreg` at module level. Written first, so it fails now (on `device_manager.py`) and proves
   the fix in task 2.
   - Done when: it exits non-zero today, naming `bot/device_manager.py`, and exits zero after task 2.

2. [ ] **USB recovery behind a platform-chosen interface.** Windows backend wraps existing `usb_pnp` code
   unchanged; Linux backend is a stub that logs "USB reset not supported on this platform" and returns
   failure. `DeviceManager` uses the interface only.
   - Done when: `python tools/check_core_imports.py` passes on HOME-PC, and on homelab
     `python -c "import bot.device_manager, bot.device_worker, capture.scrcpy_socket"` prints nothing and
     exits 0.
   - Done when (Windows, regression): `python -m tools.usb_pnp detect <serial>` and `reset <serial>` still
     work exactly as before on a spare phone, and the GUI Device Settings "Detect" button still fills the
     PnP ID.

3. [ ] **Headless entry point `main_headless.py`** with `--device`, `--start-all`, clean SIGINT/SIGTERM
   shutdown, bounded stop wait (new constant), stdout logging.
   - Done when (homelab, SSH terminal, project folder, venv active): `python main_headless.py --device <serial>`
     logs startup, then state lines for the phone, and the process stays up.
   - Done when: Ctrl+C logs a stop, exits within the shutdown timeout, and `pgrep -af scrcpy` and
     `pgrep -af "adb.*fork"` show nothing left from this run (`adb` server itself may remain).
   - Done when: `python main_headless.py` with no arguments starts nothing and says so.

4. [ ] **Homelab prerequisites and first live run** (Joshua, with Claude Code guiding). Python venv,
   `pip install -r requirements.txt`, `sudo apt install adb`, udev rule or `plugdev` membership so your user
   can talk to the phone without sudo, manual steps M2 and M3.
   - Done when: `adb devices` on homelab lists the moved phone as `device` (not `unauthorized`/`offline`),
     and the headless run from task 3 shows the phone's state changing for 10 minutes (e.g. IN_TANK,
     auto-farm taps logged) with no ERROR lines in `logs/errors.log`.

5. [ ] **Tests.** `tools/check_core_imports.py` is the regression test for the core/UI boundary. No other
   logic is added that needs a unit test (shutdown wiring is checked live in task 3).
   - Done when: the import check passes on both machines.

6. [ ] **Windows GUI smoke test** (required for every milestone).
   - Done when (HOME-PC): the app launches, device cards show state, Start and Stop work on one device, and
     `logs/app.log` shows no new WARNING/ERROR lines compared with before the change.

7. [ ] **Close-out** — update ROADMAP (Done, Log, Issues, Not now), record decisions in CLAUDE.md, make sure
   the "Known deviations" table lists the second entry point, platform-chosen USB recovery, and stdout
   logging, then reset this file.
   - Done when: the close-out commit is reviewed by Joshua.

## Risk and rollback
- **Backup before:** step M1 above (config and detector images copied to a dated folder outside the repo).
- **What can go wrong on the Windows build:** task 2 edits `device_manager.py`, the file that runs your
  24/7 farm. Do the work on a branch (`s1-headless-core`), not `main`. Do not restart the farm app from the
  branch until the Windows smoke test passes.
- **Rollback (Windows):** HOME-PC, PowerShell, in `D:\Coding\fish-farm-mgr-v2`: `git switch main`, then restart
  the app. If a bad change was already merged: `git revert <merge-commit-hash>` and restart.
- **Rollback (homelab):** nothing runs as a service in this milestone. Ctrl+C the headless run, plug the phone
  back into the Windows hub, and restart it in the Windows app. Delete `~/projects/fish-farm-mgr-v2/config/devices.json`
  and `settings.json` if you want the server clean.
- This milestone changes no public exposure (no tunnel, ports or firewall).

## Verification checklist (run after merge — "done" means verified, not merged)
- [ ] HOME-PC: app starts, all farm devices show state, one Stop/Start cycle works.
- [ ] HOME-PC: after one hour of normal running, `logs/app.log` shows no new WARNING lines beyond what you
      normally see.
- [ ] HOME-PC: `python tools/check_core_imports.py` exits 0.
- [ ] Homelab: after `git pull` (check for local changes first and say so if any), the headless run works
      as in task 3.
- [ ] The moved phone is back on the Windows hub and running in the GUI.

## Open questions
- Which phone do you move for the test? — default: a Pixel you can spare for about an hour.
- Should `--start-all` skip devices you have disabled in the GUI, if such a flag exists in `devices.json`?
  — default: Claude Code checks `config/devices.py` and starts only devices the GUI's Start All would start.

---

<!--
EMPTY TEMPLATE FOR RESET (copy back over this file at close-out)
# SPEC.md — Fish Farm Manager v2
**Milestone:** none   **Status:** idle   **Last updated:** [date]
No active milestone. Plan the next one in chat, then write it here.
-->
