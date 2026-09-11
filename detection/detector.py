"""
detection/detector.py

Template matching detector engine using OpenCV TM_CCOEFF_NORMED.

Core function: find_in_frame()
  - Takes a frame (BGR numpy array) and one or more template images
  - Returns a DetectResult with found status, bbox, center, and score
  - Tries all provided templates and returns the best match

The center of the matched region is the default click target.
A per-detector click_offset in devices.json shifts it if needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from config.constants import DEFAULT_TEMPLATE_CONFIDENCE
from detection.result import DetectResult
from detection.template_bank import TemplateBank


def find_in_frame(
    frame_bgr: np.ndarray,
    templates: List[np.ndarray],
    template_paths: List[str],
    threshold: float = DEFAULT_TEMPLATE_CONFIDENCE,
    detector_name: str = "",
) -> DetectResult:
    """
    Try to find any of the given templates in the frame.

    Tries all templates and returns the best match above the threshold.
    If multiple templates match, the highest-scoring one wins.

    Args:
        frame_bgr     : current device screen as BGR numpy array
        templates     : list of template images (BGR numpy arrays) to try
        template_paths: corresponding file paths (same order as templates, for logging)
        threshold     : minimum match score to count as found (0.0 - 1.0)
        detector_name : name of this detector (used in the result)

    Returns:
        DetectResult with found=True and populated bbox/center/score if matched,
        or DetectResult with found=False if no template exceeded the threshold.
    """
    if frame_bgr is None or len(templates) == 0:
        return DetectResult.not_found(detector_name)

    best_score = -1.0
    best_bbox: Optional[Tuple[int, int, int, int]] = None
    best_path: Optional[str] = None

    for templ, path in zip(templates, template_paths):
        # Sanity check: template must fit inside the frame
        fh, fw = frame_bgr.shape[:2]
        th, tw = templ.shape[:2]
        if th > fh or tw > fw:
            continue

        try:
            result = cv2.matchTemplate(frame_bgr, templ, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            score = float(max_val)

            if score > best_score:
                best_score = score
                best_path = path
                x, y = max_loc
                best_bbox = (x, y, tw, th)

        except cv2.error:
            # Template larger than frame or other OpenCV error — skip this template
            continue

    if best_score >= threshold and best_bbox is not None:
        x, y, w, h = best_bbox
        center = (x + w // 2, y + h // 2)
        return DetectResult(
            name=detector_name,
            found=True,
            bbox=best_bbox,
            center=center,
            score=best_score,
            matched_path=best_path,
        )

    return DetectResult.not_found(detector_name)


def run_detector_by_name(
    detector_name: str,
    frame_bgr: np.ndarray,
    device_serial: str,
    device_overrides: List[str],
    bank: TemplateBank,
    threshold: float = DEFAULT_TEMPLATE_CONFIDENCE,
) -> DetectResult:
    """
    Run a named detector against a frame using the TemplateBank.

    This is the standard way workers run detectors. The bank handles
    shared vs device-specific image resolution automatically.

    Args:
        detector_name   : e.g. "auto_button_on"
        frame_bgr       : current device screen
        device_serial   : ADB serial of the device
        device_overrides: DeviceConfig.device_image_overrides
        bank            : shared TemplateBank instance
        threshold       : match confidence threshold

    Returns:
        DetectResult. Returns not_found gracefully if image is missing.
    """
    try:
        templ = bank.get(detector_name, device_serial, device_overrides)
        path = str(bank.resolve_path(detector_name, device_serial, device_overrides))
        return find_in_frame(
            frame_bgr=frame_bgr,
            templates=[templ],
            template_paths=[path],
            threshold=threshold,
            detector_name=detector_name,
        )
    except FileNotFoundError as e:
        # Image not set up yet — not a fatal error, just not found
        return DetectResult.not_found(detector_name)
    except Exception as e:
        # Unexpected error — log it but don't crash the worker
        return DetectResult.not_found(detector_name)


def run_all_detectors(
    detector_names: List[str],
    frame_bgr: np.ndarray,
    device_serial: str,
    device_overrides: List[str],
    bank: TemplateBank,
    threshold: float = DEFAULT_TEMPLATE_CONFIDENCE,
) -> dict[str, DetectResult]:
    """
    Run all detectors in the list against a single frame.

    Returns a dict of detector_name -> DetectResult.
    Every detector in detector_names will have an entry, even if not found.
    """
    results: dict[str, DetectResult] = {}
    for name in detector_names:
        results[name] = run_detector_by_name(
            detector_name=name,
            frame_bgr=frame_bgr,
            device_serial=device_serial,
            device_overrides=device_overrides,
            bank=bank,
            threshold=threshold,
        )
    return results


def find_by_path(
    frame_bgr: np.ndarray,
    image_path: str,
    bank: TemplateBank,
    threshold: float = DEFAULT_TEMPLATE_CONFIDENCE,
    detector_name: str = "",
) -> DetectResult:
    """
    Run a detector using a direct image path (not a named detector).
    Used for eaten_by_name_image matching — each support device's name
    image is stored at a known path rather than as a named detector.

    Args:
        frame_bgr    : current device screen
        image_path   : path to the template image
        bank         : TemplateBank (handles caching)
        threshold    : match confidence threshold
        detector_name: label for the result (e.g. "eaten_by:Pixel6Beta")

    Returns:
        DetectResult.
    """
    try:
        templ = bank.get_by_path(image_path)
        return find_in_frame(
            frame_bgr=frame_bgr,
            templates=[templ],
            template_paths=[image_path],
            threshold=threshold,
            detector_name=detector_name,
        )
    except FileNotFoundError:
        return DetectResult.not_found(detector_name)
    except Exception:
        return DetectResult.not_found(detector_name)
