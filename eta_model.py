#!/usr/bin/env python3
"""
ETA model and charts for Fulcrum sync, based on regression.

We:
- Parse monitor.log "Heights:" lines to get (timestamp, fulcrum_height, lag).
- Reduce to monotonic progress samples (height strictly increases OR lag strictly decreases).
- Fit a linear regression blocks = a * t_seconds + b (numpy.polyfit, degree 1).
- Use the regression slope a as global speed (blocks / second).
- Compute central ETA and a ±20% speed window.
- Generate two Matplotlib charts:

  1) eta_history.png
     - X: hours since first sample.
     - Y: fulcrum height.
     - Scatter of samples + regression line.

  2) eta_projection.png
     - Same axes.
     - Scatter + regression line.
     - Projections to blockchain tip (central, fast, slow) plus a shaded band.
     - Horizontal line at tip height.

Return a human-readable summary text plus the PNG paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import re

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import numpy as np
except ImportError:
    np = None  # handled gracefully below


BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "monitor.log"
HISTORY_PNG = BASE_DIR / "eta_history.png"
PROJECTION_PNG = BASE_DIR / "eta_projection.png"


@dataclass
class Sample:
    timestamp: datetime
    fulcrum_height: int
    lag: int


def _parse_monitor_log() -> List[Sample]:
    """
    Parse monitor.log to extract timestamp, fulcrum height and lag
    from lines like:

    [2025-12-02 10:43:52] Heights: bitcoind=926115, fulcrum=404000,
    lag=522115 blocks, speed~=0.730 blk/s (σ=0.549), ETA=198.77 h

    We ignore speed/σ/ETA fields (we'll recompute our own).
    """
    if not LOG_PATH.exists():
        return []

    samples: List[Sample] = []
    for line in LOG_PATH.open():
        if "Heights:" not in line:
            continue

        # Timestamp: content inside the first [ ... ]
        try:
            ts_raw = line.split("]", 1)[0].strip("[]")
            ts = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue

        m_f = re.search(r"fulcrum=([0-9]+)", line)
        m_l = re.search(r"lag=([0-9]+)", line)
        if not m_f or not m_l:
            continue

        try:
            ful = int(m_f.group(1))
            lag = int(m_l.group(1))
        except ValueError:
            continue

        samples.append(Sample(timestamp=ts, fulcrum_height=ful, lag=lag))

    # Sort by time
    samples.sort(key=lambda s: s.timestamp)
    return samples


def _monotonic_progress(samples: List[Sample]) -> List[Sample]:
    """
    Reduce dataset to strictly monotonic progress points:

    Keep a sample if:
      - fulcrum_height strictly increases OR
      - lag strictly decreases

    This keeps genuine progress (e.g. each 1000-block step) and
    discards duplicate / noisy log lines.
    """
    if not samples:
        return []

    filtered: List[Sample] = []
    last_height: Optional[int] = None
    last_lag: Optional[int] = None

    for s in samples:
        if last_height is None and last_lag is None:
            filtered.append(s)
            last_height = s.fulcrum_height
            last_lag = s.lag
            continue

        if s.fulcrum_height > last_height or s.lag < last_lag:
            filtered.append(s)
            last_height = s.fulcrum_height
            last_lag = s.lag
        # else: skip

    return filtered


def _fit_regression(samples: List[Sample]) -> Tuple[float, float, List[float], List[float]]:
    """
    Fit a linear regression: blocks ≈ a * t_seconds + b

    Returns:
      (a, b, times_seconds, heights)
      - a = speed in blocks / second
      - b = intercept (blocks at t=0)
      - times_seconds = list of seconds since first sample
      - heights = list of heights
    """
    if np is None:
        raise RuntimeError("numpy is required for regression but is not installed.")

    if len(samples) < 5:
        raise RuntimeError(f"not enough progress points for regression (have {len(samples)}, need >= 5).")

    t0 = samples[0].timestamp
    times_sec = [(s.timestamp - t0).total_seconds() for s in samples]
    heights = [s.fulcrum_height for s in samples]

    # Guard: if time span is 0, regression is meaningless
    if max(times_sec) - min(times_sec) <= 0:
        raise RuntimeError("time span of samples is zero; cannot fit regression.")

    # numpy.polyfit returns coeffs highest power first: blocks = a * t + b
    a, b = np.polyfit(times_sec, heights, 1)

    if a <= 0:
        raise RuntimeError(f"regression speed non-positive (a={a:.6f}); ETA would be infinite.")

    return a, b, times_sec, heights


def _format_eta_summary(
    samples: List[Sample],
    speed: float,
    intercept: float,
) -> Tuple[str, float, float, float, float, float, float, int]:
    """
    Compute central ETA and ±20% window.

    Returns:
      summary_text, eta_seconds, eta_hours, eta_days,
      eta_fast_seconds, eta_slow_seconds, tip_height, lag_blocks
    """
    last = samples[-1]
    now_ts = last.timestamp
    lag_blocks = last.lag
    fulcrum_tip = last.fulcrum_height
    tip_height = fulcrum_tip + lag_blocks  # approximate chain tip

    if lag_blocks <= 0:
        raise RuntimeError("lag is non-positive; Fulcrum appears to be at or near tip already.")

    # Central ETA
    eta_seconds = lag_blocks / speed
    eta_hours = eta_seconds / 3600.0
    eta_days = eta_hours / 24.0

    # ±20% speed variation
    fast_speed = speed * 1.20  # 20% faster
    slow_speed = speed * 0.80  # 20% slower

    eta_fast_seconds = lag_blocks / fast_speed
    eta_slow_seconds = lag_blocks / slow_speed

    finish_central = now_ts + timedelta(seconds=eta_seconds)
    finish_fast = now_ts + timedelta(seconds=eta_fast_seconds)
    finish_slow = now_ts + timedelta(seconds=eta_slow_seconds)

    summary = (
        "📈 Fulcrum Sync ETA (regression-based)\n\n"
        f"Speed (regression): {speed:.3f} blk/s\n"
        f"Samples used: {len(samples)} progress points\n\n"
        f"Current Fulcrum height: {fulcrum_tip}\n"
        f"Current lag: {lag_blocks} blocks\n"
        f"Approx chain tip target: {tip_height}\n\n"
        f"Central ETA: {eta_hours:.1f} h ({eta_days:.2f} d)\n"
        f"Finish ≈ {finish_central:%Y-%m-%d %H:%M}\n\n"
        f"Range (±20% speed):\n"
        f"{finish_fast:%Y-%m-%d %H:%M} → {finish_slow:%Y-%m-%d %H:%M}"
    )

    return (
        summary,
        eta_seconds,
        eta_hours,
        eta_days,
        eta_fast_seconds,
        eta_slow_seconds,
        float(tip_height),
        lag_blocks,
    )


def _make_charts(
    samples: List[Sample],
    speed: float,
    intercept: float,
    times_sec: List[float],
    heights: List[float],
    eta_seconds: float,
    eta_fast_seconds: float,
    eta_slow_seconds: float,
    tip_height: float,
) -> Tuple[Path, Path]:
    """
    Build the two PNG charts:
      - eta_history.png
      - eta_projection.png
    """
    if np is None:
        # Should not happen if we got here, but be safe
        return HISTORY_PNG, PROJECTION_PNG

    t0 = samples[0].timestamp

    # Convert seconds to hours since start for X-axis
    times_hours = np.array(times_sec) / 3600.0
    heights_arr = np.array(heights, dtype=float)

    # Regression line over the observed interval
    fit_blocks = speed * np.array(times_sec) + intercept

    # -------- Chart 1: History + regression --------
    plt.figure(figsize=(10, 5))
    plt.scatter(times_hours, heights_arr, s=12, label="Observed heights")
    plt.plot(times_hours, fit_blocks, label=f"Regression (speed={speed:.3f} blk/s)")
    plt.xlabel("Hours since first sample")
    plt.ylabel("Fulcrum height")
    plt.title("Fulcrum Sync Progress vs Time (Regression Model)")
    plt.grid(True)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(HISTORY_PNG)
    plt.close()

    # -------- Chart 2: Projection with speed variation --------
    # Construct a time grid from now (last sample) into the future
    last_t_sec = times_sec[-1]
    # Make sure we extend at least to central ETA; include some padding
    max_future_sec = last_t_sec + eta_seconds
    future_t_sec = np.linspace(last_t_sec, max_future_sec, 200)
    future_hours = future_t_sec / 3600.0

    central_proj = speed * future_t_sec + intercept
    fast_speed = speed * 1.20
    slow_speed = speed * 0.80
    fast_proj = fast_speed * future_t_sec + intercept
    slow_proj = slow_speed * future_t_sec + intercept

    plt.figure(figsize=(10, 5))
    # Historical scatter and regression
    plt.scatter(times_hours, heights_arr, s=12, label="Observed heights")
    plt.plot(times_hours, fit_blocks, label=f"Regression (speed={speed:.3f} blk/s)")

    # Future projections
    plt.plot(future_hours, central_proj, linestyle="--", label="Central ETA trajectory")
    plt.fill_between(
        future_hours,
        np.minimum(fast_proj, slow_proj),
        np.maximum(fast_proj, slow_proj),
        alpha=0.25,
        label="±20% speed band",
    )

    # Blockchain tip target
    plt.axhline(y=tip_height, color="grey", linestyle=":", label="Blockchain tip target")

    plt.xlabel("Hours since first sample")
    plt.ylabel("Fulcrum height")
    plt.title("Fulcrum ETA Projection with Speed Variation (Hybrid Model C)")
    plt.grid(True)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(PROJECTION_PNG)
    plt.close()

    return HISTORY_PNG, PROJECTION_PNG


def compute_eta_and_charts() -> Tuple[str, Optional[Path], Optional[Path]]:
    """
    High-level entry point for Telegram:

    Returns:
      (summary_text, history_png_path or None, projection_png_path or None)

    On any error (no data, not enough points, regression issue, etc),
    returns a human-readable error message and (None, None).
    """
    # 1) Load & clean samples
    all_samples = _parse_monitor_log()
    if not all_samples:
        return (
            "No Heights data found in monitor.log yet. Wait for a few sync cycles.",
            None,
            None,
        )

    samples = _monotonic_progress(all_samples)
    if len(samples) < 5:
        return (
            f"Not enough progress points for a regression-based ETA yet "
            f"(have {len(samples)}, need at least 5).",
            None,
            None,
        )

    if np is None:
        return (
            "Cannot compute regression-based ETA: numpy is not installed in this environment.",
            None,
            None,
        )

    # 2) Regression
    try:
        speed, intercept, times_sec, heights = _fit_regression(samples)
    except RuntimeError as e:
        return f"Could not fit regression-based ETA: {e}", None, None

    # 3) ETA summary
    try:
        (
            summary,
            eta_seconds,
            eta_hours,
            eta_days,
            eta_fast_seconds,
            eta_slow_seconds,
            tip_height,
            lag_blocks,
        ) = _format_eta_summary(samples, speed, intercept)
    except RuntimeError as e:
        return f"Could not compute ETA: {e}", None, None

    # 4) Charts
    try:
        hist_png, proj_png = _make_charts(
            samples=samples,
            speed=speed,
            intercept=intercept,
            times_sec=times_sec,
            heights=heights,
            eta_seconds=eta_seconds,
            eta_fast_seconds=eta_fast_seconds,
            eta_slow_seconds=eta_slow_seconds,
            tip_height=tip_height,
        )
    except Exception as e:
        # If charts fail, still return ETA text
        err_txt = (
            f"{summary}\n\n"
            f"(Chart generation failed: {e})"
        )
        return err_txt, None, None

    return summary, hist_png, proj_png
