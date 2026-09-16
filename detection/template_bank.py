"""
detection/template_bank.py

TemplateBank loads and caches detection images in memory.

v2 path structure:
  assets/detectors/{detector_name}/{detector_name}_{serial}.png

All images originate from a specific device capture and are named
after that device. Any device can be assigned any available image
for a given detector via devices.json detector_assignments.

The bank resolves paths based on what's assigned in detector_assignments.
If no assignment exists for a detector+device combo, raises FileNotFoundError
so the worker can skip gracefully.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np


class TemplateBank:
    """
    Loads and caches template images for template matching.

    One TemplateBank instance is shared across all workers.
    Thread-safe for reads (dict lookups after initial load).
    Call invalidate() after the crop tool saves a new image.
    """

    def __init__(self, project_root: Path | None = None):
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        self._root = project_root
        self._detectors_dir = project_root / "assets" / "detectors"

        # Cache: path_str -> np.ndarray
        self._cache: Dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    def get(
        self,
        detector_name: str,
        device_serial: str,
        detector_assignments: dict,
    ) -> np.ndarray:
        """
        Get the template image for a detector + device combination.

        Resolution order:
          1. Check detector_assignments for this device — use image_filename
             from the assignment if present.
          2. Fall back to the image named after this device's serial.
          3. Raise FileNotFoundError if nothing is found.

        Args:
            detector_name        : e.g. "in_tank"
            device_serial        : ADB serial of the device
            detector_assignments : DeviceConfig.detector_assignments dict
                                   (maps detector_name -> DetectorAssignment)

        Returns:
            BGR numpy array of the template image.

        Raises:
            FileNotFoundError if no image is configured for this detector.
        """
        path = self.resolve_path(detector_name, device_serial, detector_assignments)
        path_str = str(path)
        if path_str not in self._cache:
            self._cache[path_str] = self._load(path, detector_name, device_serial)
        return self._cache[path_str]

    def get_by_path(self, image_path: str) -> np.ndarray:
        """Load a template image directly by path. Cached by path string."""
        if image_path not in self._cache:
            path = Path(image_path)
            if not path.is_absolute():
                path = self._root / path
            self._cache[image_path] = self._load(path, image_path, "path")
        return self._cache[image_path]

    def resolve_path(
        self,
        detector_name: str,
        device_serial: str,
        detector_assignments: dict,
    ) -> Path:
        """
        Return the Path that would be used for a detector + device.

        Checks detector_assignments for an assigned image_filename first,
        then falls back to the device-serial-named file.

        Args:
            detector_name        : e.g. "friend_card"
            device_serial        : ADB serial of the device
            detector_assignments : DeviceConfig.detector_assignments dict
                                   (maps detector_name -> DetectorAssignment)
        """
        detector_dir = self._detectors_dir / detector_name

        # Use the assigned image_filename if one has been set via the UI
        assignment = detector_assignments.get(detector_name)
        if assignment is not None and assignment.image_filename:
            return detector_dir / assignment.image_filename

        # Fallback: image named after the originating device serial
        return detector_dir / f"{detector_name}_{device_serial}.png"

    def get_assigned_path(
        self,
        detector_name: str,
        assigned_filename: str,
    ) -> Path:
        """
        Return the full path for a specific assigned filename.
        Used when detector_assignments specifies a non-default image
        (e.g. device A is using device B's image for a detector).
        """
        return self._detectors_dir / detector_name / assigned_filename

    def list_available(self, detector_name: str) -> List[Path]:
        """
        List all available images for a detector across all devices.
        Used by the crop tool to show which images exist.
        """
        detector_dir = self._detectors_dir / detector_name
        if not detector_dir.exists():
            return []
        return sorted(detector_dir.glob("*.png"))

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def invalidate(self, detector_name: str, device_serial: str) -> None:
        """
        Remove a specific entry from the cache so it reloads on next access.
        Called by the crop tool after saving a new image.
        """
        path = self._detectors_dir / detector_name / f"{detector_name}_{device_serial}.png"
        self._cache.pop(str(path), None)

    def invalidate_by_path(self, image_path: str) -> None:
        """Invalidate a path-addressed cache entry."""
        self._cache.pop(image_path, None)

    def invalidate_detector(self, detector_name: str) -> None:
        """
        Remove all cached entries for a detector (any device's image).
        Called after an assignment change so the next access loads the
        correct newly-assigned file.
        """
        prefix = str(self._detectors_dir / detector_name) + "/"
        stale = [k for k in self._cache if k.startswith(prefix)]
        for k in stale:
            del self._cache[k]

    def clear(self) -> None:
        """Clear the entire cache. All images reload on next access."""
        self._cache.clear()

    def exists(self, detector_name: str, device_serial: str) -> bool:
        """Check if the default image file exists on disk for this device."""
        path = self._detectors_dir / detector_name / f"{detector_name}_{device_serial}.png"
        return path.exists()

    def exists_assigned(self, detector_name: str, assigned_filename: str) -> bool:
        """Check if a specific assigned image file exists on disk."""
        path = self._detectors_dir / detector_name / assigned_filename
        return path.exists()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self, path: Path, name: str, context: str) -> np.ndarray:
        """
        Load an image from disk as a BGR numpy array.

        Raises:
            FileNotFoundError if the file does not exist.
            RuntimeError if OpenCV fails to decode the image.
        """
        if not path.exists():
            raise FileNotFoundError(
                f"Template image not found for '{name}' ({context}): {path}"
            )
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(
                f"OpenCV failed to read template image for '{name}' ({context}): {path}"
            )
        return img
