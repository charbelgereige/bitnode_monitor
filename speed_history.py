#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import re
import subprocess
import statistics


Sample = Dict[str, str]


def _get_fulcrum_start_time(unit: str = "fulcrum") -> Optional[datetime]:
    """
    Best-effort: read journald for the last 'Started Fulcrum' line
    and parse its timestamp (no year in journalctl -> use current year).
    Returns None on failure.
    """
    try:
        out = subprocess.check_output(
            ["journalctl", "-u", unit, "--no-pager"],
            text=True,
        )
    except Exception:
        return None

    last = ""
    for line in out.splitlines():
        if "Started Fulcrum" in line:
            last = line
    if not last:
        return None

    # Typical format:
    # Dec 02 20:01:23 knots00 systemd[1]: Started Fulcrum Electrum Server.
    parts = last.split()
    if len(parts) < 3:
        return None
    month, day, time_s = parts[0], parts[1], parts[2]
    year = datetime.now().year
    try:
        return datetime.strptime(
            f"{year} {month} {day} {time_s}",
            "%Y %b %d %H:%M:%S",
        )
    except ValueError:
        return None


def load_samples_since_restart(
    log_path: Path,
    fulcrum_unit: str = "fulcrum",
) -> List[Sample]:
    """
    Parse monitor.log Heights lines, restricted to entries
    AFTER the last fulcrum.service start (if we can detect it).
    """
    samples: List[Sample] = []
    if not log_path.exists():
        return samples

    start_dt = _get_fulcrum_start_time(fulcrum_unit)

    with log_path.open() as f:
        for line in f:
            if "Heights:" not in line:
                continue

            # Timestamp "[YYYY-MM-DD HH:MM:SS]"
            ts_str = ""
            dt: Optional[datetime] = None
            if line.startswith("[") and "]" in line:
                ts_str = line.split("]", 1)[0].strip("[]")
                try:
                    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    dt = None

            # If we know fulcrum start, ignore older entries
            if start_dt and dt and dt < start_dt:
                continue

            m_btc = re.search(r"bitcoind=([0-9]+)", line)
            m_ful = re.search(r"fulcrum=([0-9]+)", line)
            m_lag = re.search(r"lag=([0-9]+) blocks", line)
            m_spd = re.search(r"speed~=([0-9.]+)", line)
            m_sig = re.search(r"σ=([0-9.]+)", line)
            m_eta = re.search(r"ETA=([0-9.]+)", line)

            samples.append(
                {
                    "timestamp": ts_str,
                    "btc": m_btc.group(1) if m_btc else "",
                    "ful": m_ful.group(1) if m_ful else "",
                    "lag": m_lag.group(1) if m_lag else "",
                    "speed": m_spd.group(1) if m_spd else "",
                    "sigma": m_sig.group(1) if m_sig else "",
                    "eta": m_eta.group(1) if m_eta else "",
                }
            )
    return samples


def _compute_eta_window(samples: List[Sample]) -> str:
    """
    Use all numeric speed samples in this run to estimate:
    - avg speed, σ
    - central ETA and an ETA window (1σ-ish) in hours/days + calendar dates.
    """
    speeds = [
        float(s["speed"])
        for s in samples
        if s.get("speed") not in ("", "N/A")
    ]
    if not speeds:
        return "No valid speed samples yet for this Fulcrum run."

    lag_str = samples[-1].get("lag", "") or "0"
    try:
        lag_blocks = int(lag_str)
    except ValueError:
        lag_blocks = 0

    avg_speed = statistics.mean(speeds)
    if len(speeds) > 1:
        stdev_speed = statistics.pstdev(speeds)
    else:
        stdev_speed = 0.0

    if avg_speed <= 0 or lag_blocks <= 0:
        return (
            f"samples={len(speeds)}, avg_speed={avg_speed:.3f} blk/s, "
            f"σ={stdev_speed:.3f}, but lag={lag_blocks} so ETA cannot be derived."
        )

    # central ETA in hours (speed is blocks/sec)
    central_h = lag_blocks / avg_speed / 3600.0

    # crude window using avg ± σ, clamped so denominator stays positive
    if stdev_speed > 0 and avg_speed > stdev_speed:
        hi_speed = avg_speed + stdev_speed  # faster
        lo_speed = max(avg_speed - stdev_speed, avg_speed * 0.25)  # slower
        low_h = lag_blocks / hi_speed / 3600.0   # optimistic (faster)
        high_h = lag_blocks / lo_speed / 3600.0  # pessimistic (slower)
    else:
        low_h = high_h = central_h

    now = datetime.now()
    central_eta_dt = now + timedelta(hours=central_h)
    low_eta_dt = now + timedelta(hours=low_h)
    high_eta_dt = now + timedelta(hours=high_h)

    def _fmt_hours_days(h: float) -> str:
        days = h / 24.0
        return f"{h:.1f} h (~{days:.1f} d)"

    return (
        f"samples used={len(speeds)}, avg_speed≈{avg_speed:.3f} blk/s (σ≈{stdev_speed:.3f}).\n"
        f"current lag≈{lag_blocks} blocks.\n"
        f"Central ETA: {_fmt_hours_days(central_h)} → ~{central_eta_dt:%Y-%m-%d %H:%M}.\n"
        f"1σ window: {_fmt_hours_days(low_h)} – {_fmt_hours_days(high_h)} "
        f"(~{low_eta_dt:%Y-%m-%d %H:%M} → ~{high_eta_dt:%Y-%m-%d %H:%M})."
    )


def build_speed_report(
    samples: List[Sample],
    mode: str = "full",
    n: Optional[int] = None,
    max_lines: int = 80,
) -> Tuple[str, List[str]]:
    """
    Prepare (summary, lines) for Telegram:
      - summary: stats + ETA window
      - lines: formatted dataset rows (head/tail/full, capped to max_lines)
    """
    if not samples:
        return ("No Heights samples in monitor.log for this Fulcrum run.", [])

    if mode not in ("full", "head", "tail"):
        mode = "full"

    if n is None or n <= 0:
        n = 10

    total = len(samples)

    if mode == "head":
        chosen = samples[:n]
    elif mode == "tail":
        chosen = samples[-n:]
    else:  # full
        chosen = samples

    truncated_note = ""
    if len(chosen) > max_lines:
        if mode == "tail":
            chosen = chosen[-max_lines:]
            truncated_note = f"(showing last {len(chosen)} of {total} samples)"
        elif mode == "head":
            chosen = chosen[:max_lines]
            truncated_note = f"(showing first {len(chosen)} of {total} samples)"
        else:  # full
            chosen = chosen[-max_lines:]
            truncated_note = f"(full series too long; showing last {len(chosen)} of {total} samples)"

    header = "timestamp  | fulcrum | lag | speed blk/s | σ | ETA h"
    rows: List[str] = [header]
    for s in chosen:
        rows.append(
            f"{s['timestamp']} | {s['ful']} | {s['lag']} | "
            f"{s['speed'] or 'N/A'} | {s['sigma'] or 'N/A'} | {s['eta'] or 'N/A'}"
        )
    if truncated_note:
        rows.append(truncated_note)

    summary = _compute_eta_window(samples)
    return summary, rows
