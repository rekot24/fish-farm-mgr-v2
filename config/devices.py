"""
config/devices.py

Per-device configuration schema, loader, and saver.
Each device has its own DeviceConfig stored in config/devices.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Optional

from config.paths import devices_path
from config.constants import (
    AUTO_FARM_INTERVAL_S,
    END_RUN_INTERVAL_S,
    STAY_AWAKE_INTERVAL_S,
)


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

    Tap priority (in _resolve_tap_coords):
      1. tap_offset_x/y set (manual override via crop tool) → use it always
      2. cached_tap_x/y set (persisted from prior session)  → use it
      3. Neither set → run template match, persist result, use it
    """
    image_filename: Optional[str] = None
    last_tested: Optional[str] = None
    last_score: Optional[float] = None
    tap_offset_x: Optional[int] = None
    tap_offset_y: Optional[int] = None
    cached_tap_x: Optional[int] = None
    cached_tap_y: Optional[int] = None


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
    path = devices_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    output = {serial: asdict(cfg) for serial, cfg in devices.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
