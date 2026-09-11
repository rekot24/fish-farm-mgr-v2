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
    and when it was last tested and with what result.
    """
    image_filename: Optional[str] = None   # filename within assets/detectors/{detector_name}/
    last_tested: Optional[str] = None      # ISO timestamp of last test run
    last_score: Optional[float] = None     # confidence score from last test (0.0 - 1.0)


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
            assignments_raw = entry.pop("detector_assignments", {})
            assignments = {
                name: DetectorAssignment(**vals)
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
