"""
detection/template_bank.py

TemplateBank loads and caches detection images in memory.

Resolution order for any detector + device:
  1. assets/devices/{serial}/{detector_name}.png  (device-specific override)
  2. assets/shared/{detector_name}.png            (shared fallback)

The device_image_overrides list in devices.json controls which detectors
use the per-device image. The TemplateBank enforces this automatically.

All images are cached after first load. Call clear() to force a reload
(e.g. after the Image Capture Tool saves a new image).
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
    Use clear() + reload on image updates.
    """

    def __init__(self, project_root: Path | None = None):
        """
        Args:
            project_root: root of the project (contains assets/).
                          Defaults to the parent of this file's package.
        """
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent

        self._root = project_root
        self._shared_dir = project_root / "assets" / "shared"
        self._devices_dir = project_root / "assets" / "devices"

        # Cache: (detector_name, serial_or_shared) -> np.ndarray
        self._cache: Dict[str, np.ndarray] = {}

    def get(
        self,
        detector_name: str,
        device_serial: str,
        device_overrides: List[str],
    ) -> np.ndarray:
        """
        Get the template image for a detector + device combination.

        Args:
            detector_name    : e.g. "auto_button_on"
            device_serial    : ADB serial of the device
            device_overrides : list of detector names that use device-specific images
                               (from DeviceConfig.device_image_overrides)

        Returns:
            BGR numpy array of the template image.

        Raises:
            FileNotFoundError if neither device-specific nor shared image exists.
        """
        # Determine which image to use
        use_device_specific = detector_name in device_overrides

        if use_device_specific:
            cache_key = f"{device_serial}/{detector_name}"
            if cache_key not in self._cache:
                path = self._devices_dir / device_serial / f"{detector_name}.png"
                self._cache[cache_key] = self._load(path, detector_name, device_serial)
            return self._cache[cache_key]
        else:
            cache_key = f"shared/{detector_name}"
            if cache_key not in self._cache:
                path = self._shared_dir / f"{detector_name}.png"
                self._cache[cache_key] = self._load(path, detector_name, "shared")
            return self._cache[cache_key]

    def get_by_path(self, image_path: str) -> np.ndarray:
        """
        Load a template image directly by path.
        Used for eaten_by_name_image and other path-addressed images.
        Cached by path string.
        """
        if image_path not in self._cache:
            path = Path(image_path)
            if not path.is_absolute():
                path = self._root / path
            self._cache[image_path] = self._load(path, image_path, "path")
        return self._cache[image_path]

    def invalidate(self, detector_name: str, device_serial: str | None = None) -> None:
        """
        Remove a specific entry from the cache so it reloads on next access.
        Called by the Image Capture Tool after saving a new crop.

        Args:
            detector_name : the detector whose image was updated
            device_serial : if provided, invalidate the device-specific cache entry.
                            if None, invalidate the shared cache entry.
        """
        if device_serial:
            key = f"{device_serial}/{detector_name}"
        else:
            key = f"shared/{detector_name}"
        self._cache.pop(key, None)

    def invalidate_by_path(self, image_path: str) -> None:
        """Invalidate a path-addressed cache entry."""
        self._cache.pop(image_path, None)

    def clear(self) -> None:
        """Clear the entire cache. All images reload on next access."""
        self._cache.clear()

    def resolve_path(
        self,
        detector_name: str,
        device_serial: str,
        device_overrides: List[str],
    ) -> Path:
        """
        Return the Path that would be used for a detector + device,
        without loading the image. Useful for the Image Capture Tool
        to know where to save a new crop.
        """
        if detector_name in device_overrides:
            return self._devices_dir / device_serial / f"{detector_name}.png"
        else:
            return self._shared_dir / f"{detector_name}.png"

    def exists(
        self,
        detector_name: str,
        device_serial: str,
        device_overrides: List[str],
    ) -> bool:
        """Check if the resolved image file exists on disk."""
        return self.resolve_path(detector_name, device_serial, device_overrides).exists()

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
