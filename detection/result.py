"""
detection/result.py

DetectResult — the data shape returned by every detector run.
Updated to match what detector.py actually uses: name, bbox, center,
matched_path, and the not_found() classmethod.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class DetectResult:
    """
    The result of running one detector against one captured frame.

    Args:
        name         : name of the detector that produced this result
        found        : True if the template was matched above threshold
        score        : confidence score of the best match (0.0 - 1.0)
        bbox         : (x, y, w, h) bounding box of the match, or None if not found
        center       : (x, y) center of the match in the frame, or None if not found
        matched_path : path to the template image that matched, or None
    """
    name: str
    found: bool
    score: float
    bbox: Optional[Tuple[int, int, int, int]] = None
    center: Optional[Tuple[int, int]] = None
    matched_path: Optional[str] = None

    @classmethod
    def not_found(cls, detector_name: str) -> "DetectResult":
        """Convenience constructor for a non-match result."""
        return cls(name=detector_name, found=False, score=0.0)
