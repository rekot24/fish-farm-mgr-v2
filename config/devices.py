"""
config/devices.py

Per-device configuration schema, loader, and saver.
Each device has its own DeviceConfig stored in config/devices.json.

Persistence model: the live in-memory dict (owned by main.py, shared by the UI, the
manager and every worker) is the SOURCE OF TRUTH; devices.json is its mirror. Every
writer edits that dict and calls save_devices() with it — nobody edits a private disk
snapshot, which would leave memory stale and let the next save overwrite the change.
save_devices() is the only function that writes the file, and it is thread-safe.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from config.paths import devices_path
from config.constants import (
    AUTO_FARM_INTERVAL_S,
    DEVICES_SAVE_RETRIES,
    DEVICES_SAVE_RETRY_DELAY_S,
    DEVICES_TMP_SUFFIX,
    END_RUN_INTERVAL_S,
    STAY_AWAKE_INTERVAL_S,
)

# Serializes every write of devices.json (UI threads and worker threads alike). Plain
# Lock: save_devices() does not nest.
_DEVICES_FILE_LOCK = threading.Lock()


@dataclass
class DetectorAssignment:
    """
    Tracks which image is assigned to a detector for this device,
    when it was last saved/tested, and tap coordinate data.

    image_filename : filename within assets/detectors/{detector_name}/
                     Named {detector_name}_{serial}.png by convention.
    last_tested    : ISO timestamp of last test run
    last_score     : confidence score from last test (0.0 - 1.0)
    tap_offset_x   : manual tap override — x offset within the crop image
                     (None = use cached or bbox center)
    tap_offset_y   : manual tap override — y offset within the crop image
    cached_tap_x   : persisted screen coordinate from first successful
                     template match. Populated automatically by the worker
                     on first hit. Cleared when a new image is assigned.
    cached_tap_y   : see cached_tap_x.
    always_detect  : when True, skip the tap cache entirely — run a live
                     template match every time and never persist the result.
                     Use for detectors whose screen position can vary between
                     cycles (e.g. avatar, game icon, servers button,
                     private server entry).

    Tap priority (in _resolve_tap_coords):
      1. tap_offset_x/y set (manual override via crop tool) → use it always
      2. cached_tap_x/y set AND always_detect is False → use cached coord
      3. Neither set (or always_detect is True) → run template match live;
         persist result only when always_detect is False
    """
    image_filename: Optional[str] = None
    last_tested: Optional[str] = None
    last_score: Optional[float] = None
    tap_offset_x: Optional[int] = None
    tap_offset_y: Optional[int] = None
    cached_tap_x: Optional[int] = None
    cached_tap_y: Optional[int] = None
    always_detect: bool = False


@dataclass
class DeviceConfig:
    """
    All configuration for a single device.
    Stored as one entry in config/devices.json, keyed by ADB serial.
    """

    serial: str = ""
    nickname: str = ""
    model: str = ""
    account: str = ""

    auto_farm_enabled: bool = True
    end_run_enabled: bool = True
    stay_awake_enabled: bool = False
    stuck_lobby_detection_enabled: bool = True

    # False = skip the 24rolla-avatar fast path and always rejoin via the hamburger
    # menu. Needed on the account that IS 24rolla, where tapping its own avatar
    # doesn't lead to a join. Per-device because the account is per-device.
    quick_join_enabled: bool = False

    # Windows PnP InstanceId of this phone's USB device (e.g.
    # USB\VID_18D1&PID_4EE7\<adb serial>), used for the last-resort USB port reset.
    # Blank = not configured: USB reset is skipped for this device. Filled in via the
    # Device Settings dialog (Detect button). See tools/usb_pnp.py.
    pnp_instance_id: str = ""

    auto_farm_interval_s: float = AUTO_FARM_INTERVAL_S
    end_run_interval_s: float = END_RUN_INTERVAL_S
    stay_awake_interval_s: float = STAY_AWAKE_INTERVAL_S

    detector_assignments: dict[str, DetectorAssignment] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_devices() -> dict[str, DeviceConfig]:
    path = devices_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        devices = {}
        for serial, entry in raw.items():
            entry = dict(entry)
            for old_field in (
                "auto_farm_tap_x", "auto_farm_tap_y",
                "end_run_tap_x", "end_run_tap_y",
                "reconnect_tap_x", "reconnect_tap_y",
                "leave_tap_x", "leave_tap_y",
            ):
                entry.pop(old_field, None)
            assignments_raw = entry.pop("detector_assignments", {})
            assignments = {
                name: DetectorAssignment(**{
                    k: v for k, v in vals.items()
                    if k in DetectorAssignment.__dataclass_fields__
                })
                for name, vals in assignments_raw.items()
            }
            devices[serial] = DeviceConfig(
                serial=serial,
                detector_assignments=assignments,
                **{k: v for k, v in entry.items() if k != "serial"},
            )
        return devices
    except Exception as e:
        print(f"[WARNING] Failed to load devices.json: {e} — starting with no devices")
        return {}


def save_devices(devices: dict[str, DeviceConfig]) -> None:
    """
    Write every device config to devices.json. Safe to call from any thread.

    Callers pass the LIVE in-memory dict (memory is the source of truth, the file is its
    mirror). Writers are serialized by _DEVICES_FILE_LOCK, and the write is atomic —
    temp file in the same directory, fsync, os.replace — so a crash or a concurrent
    reader never sees a truncated file (load_devices() would read that as "no devices").
    On Windows os.replace raises PermissionError while another process has the file open
    (editor, antivirus, backup), so it is retried briefly, then the error is raised.
    """
    path = devices_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + DEVICES_TMP_SUFFIX)
    with _DEVICES_FILE_LOCK:
        output = {serial: asdict(cfg) for serial, cfg in devices.items()}
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            for attempt in range(DEVICES_SAVE_RETRIES):
                try:
                    os.replace(tmp_path, path)
                    break
                except PermissionError:
                    if attempt == DEVICES_SAVE_RETRIES - 1:
                        raise
                    time.sleep(DEVICES_SAVE_RETRY_DELAY_S)
        finally:
            # Only still exists if the swap never happened (write or replace failed).
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
