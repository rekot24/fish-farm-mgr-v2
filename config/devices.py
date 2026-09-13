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
    when it was last saved, and any tap coordinate override.

    image_filename : filename within assets/detectors/{detector_name}/
                     Named {detector_name}_{serial}.png by convention.
    shape          : "box" or "circle" — the crop shape used when saving
    last_tested    : ISO timestamp of last test run
    last_score     : confidence score from last test (0.0 - 1.0)
    tap_offset_x   : x offset within the crop image for tap override (None = use center)
    tap_offset_y   : y offset within the crop image for tap override (None = use center)
    """
    image_filename: Optional[str] = None
    shape: str = "box"
    last_tested: Optional[str] = None
    last_score: Optional[float] = None
    tap_offset_x: Optional[int] = None
    tap_offset_y: Optional[int] = None


@dataclass
class DeviceConfig:
    """
    All configuration for a single device.
    Stored as one entry in config/devices.json, keyed by ADB serial.
    """

    # ADB serial — unique identifier, never editable by the user.
    serial: str = ""

    # Display identity — shown on the device card.
    nickname: str = ""
    model: str = ""
    account: str = ""

    # Per-device feature flags — each checked every cycle before acting.
    auto_farm_enabled: bool = True
    end_run_enabled: bool = True
    stay_awake_enabled: bool = False
    stuck_lobby_detection_enabled: bool = True

    # Timer intervals (seconds).
    auto_farm_interval_s: float = AUTO_FARM_INTERVAL_S
    end_run_interval_s: float = END_RUN_INTERVAL_S
    stay_awake_interval_s: float = STAY_AWAKE_INTERVAL_S

    # Detector image assignments — keyed by detector name.
    # Tap coordinates are derived from template match results at runtime
    # (cached per session) rather than stored as fixed pixel values.
    # Optional tap_offset_x/y in DetectorAssignment overrides center-of-bbox.
    detector_assignments: dict[str, DetectorAssignment] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Load / save
# ---------------------------------------------------------------------------

def load_devices() -> dict[str, DeviceConfig]:
    """
    Load all device configs from config/devices.json.
    Returns a dict keyed by ADB serial.
    Returns an empty dict if the file is absent or corrupt.
    """
    path = devices_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        devices = {}
        for serial, entry in raw.items():
            entry = dict(entry)
            # Strip out any legacy manual tap coordinate fields from old configs
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
    Persist all device configs to config/devices.json.
    Creates the file if it does not exist.
    """
    path = devices_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    output = {serial: asdict(cfg) for serial, cfg in devices.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
