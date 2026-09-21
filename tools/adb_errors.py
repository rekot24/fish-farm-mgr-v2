"""
tools/adb_errors.py

Recognize adb client errors that mean "this device is gone" from a failed command's exit
code and stderr. One shared definition so every caller agrees on what counts as a dropped
device; the wording lives in config/constants.py (ADB_DEVICE_GONE_PATTERN).

General enough to copy to another project.
"""

from __future__ import annotations

import re

from config.constants import ADB_DEVICE_GONE_PATTERN

_DEVICE_GONE_RE = re.compile(ADB_DEVICE_GONE_PATTERN, re.IGNORECASE)


def adb_output_means_device_gone(returncode: int | None, stderr: bytes | str | None) -> bool:
    """
    True if a finished `adb -s <serial> ...` call failed because the device is gone —
    "device '<serial>' not found" or "device offline" (see ADB_DEVICE_GONE_PATTERN).

    Only a non-zero exit is considered, and only stderr is searched: adb prints its own
    errors there, while stdout is arbitrary command output (ps, dumpsys) that could
    contain those words for unrelated reasons.

    Args:
        returncode : exit code of the adb process (0 / None -> never "gone")
        stderr     : the process's stderr, as bytes or str

    Returns:
        True only for the exact "gone" error shapes; False for success, timeouts,
        unauthorized/still-connecting, and any other failure.
    """
    if not returncode:
        return False
    if stderr is None:
        return False
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, (bytes, bytearray)) else stderr
    return bool(_DEVICE_GONE_RE.search(text))
