"""
detection/result.py

DetectResult — the data shape returned by every detector run.
Defined here before any logic that produces or consumes it.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class DetectResult:
    """
    The result of running one detector against one captured frame.

    Args:
        detector_name : name of the detector that produced this result
        found         : True if the template was matched above threshold
        score         : confidence score of the best match (0.0 - 1.0)
        location      : (x, y) center of the match in the frame, or None if not found
    """
    detector_name: str
    found: bool
    score: float
    location: Optional[tuple[int, int]] = None
