#!/usr/bin/env python3
"""
Status builder for Fulcrum monitor.

Instead of trusting whatever arguments callers pass,
we derive the human-readable status directly from monitor.log.
"""

from pathlib import Path


def _extract_last_matching_line(log_path, substring):
    """
    Return the last log line containing `substring`, stripped of the
    leading timestamp prefix like: "[2025-12-01 21:48:51] ".
    """
    try:
        last = None
        with log_path.open() as f:
            for line in f:
                if substring in line:
                    last = line
        if not last:
            return None

        s = last.strip()
        # If line looks like "[timestamp] rest-of-line", strip the prefix
        if "] " in s:
            parts = s.split("] ", 1)
            return parts[1]
        return s
    except FileNotFoundError:
        return None


def build_status_text(*args, **kwargs):
    """
    Build a human-readable status text for Telegram.

    We intentionally ignore positional/keyword args, because some callers
    still pass config objects instead of the actual numeric values.
    We instead read the latest information from monitor.log.
    """
    base_dir = Path(__file__).resolve().parent
    log_file = base_dir / "monitor.log"

    height_line = _extract_last_matching_line(log_file, "Heights:")
    if not height_line:
        height_line = "Heights: (no data yet)"

    # If you later want to surface alerts, you can reuse this:
    # alert_line = _extract_last_matching_line(log_file, "[ALERT]")
    alert_line = _extract_last_matching_line(log_file, "[ALERT]")

    lines = ["Status:", height_line]
    if alert_line:
        lines.append(alert_line)

    return "\n".join(lines)
