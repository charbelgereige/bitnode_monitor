#!/usr/bin/env python3
"""
Status builder for Bitnode / Fulcrum monitor.

We derive the human-readable status directly from monitor.log:

- Prefer the last Heights line with numeric speed & ETA
- Fall back to the last Heights line (may have N/A)
- Optionally append the last [ALERT] line (e.g. CPU high load)
"""

from pathlib import Path
import re


def _strip_prefix(line):
    """
    Strip leading "[timestamp] " prefix if present.
    """
    if not line:
        return None
    s = line.strip()
    if "] " in s:
        _, rest = s.split("] ", 1)
        return rest
    return s


def _extract_last_heights_lines(log_path: Path):
    """
    Scan monitor.log and return:
      last_any: last line containing "Heights:"
      last_num: last line containing "Heights:" AND numeric speed & ETA
    """
    last_any = None
    last_num = None

    try:
        with log_path.open() as f:
            for line in f:
                if "Heights:" not in line:
                    continue
                last_any = line

                has_speed = re.search(r"speed~=([0-9.]+)", line)
                has_eta   = re.search(r"ETA=([0-9.]+)",   line)
                if has_speed and has_eta:
                    last_num = line
    except FileNotFoundError:
        pass

    return last_any, last_num


def _extract_last_alert_line(log_path: Path):
    """
    Return last line containing "[ALERT]" stripped of timestamp,
    or None if none found.
    """
    last = None
    try:
        with log_path.open() as f:
            for line in f:
                if "[ALERT]" in line:
                    last = line
    except FileNotFoundError:
        return None

    return _strip_prefix(last) if last else None


def build_status_text(*_args, **_kwargs):
    """
    Build a human-readable status text for Telegram.

    Priority:
      1) Last Heights line with numeric speed & ETA
      2) Else last Heights line (may have N/A)
      3) Else "Heights: (no data yet)"

    Then append last [ALERT] line if present.
    """
    base_dir = Path(__file__).resolve().parent
    log_file = base_dir / "monitor.log"

    any_line, num_line = _extract_last_heights_lines(log_file)

    if num_line:
        height_line = _strip_prefix(num_line)
    elif any_line:
        height_line = _strip_prefix(any_line)
    else:
        height_line = "Heights: (no data yet)"

    alert_line = _extract_last_alert_line(log_file)

    lines = ["Status:", height_line]
    if alert_line:
        lines.append(alert_line)

    return "\n".join(lines)
