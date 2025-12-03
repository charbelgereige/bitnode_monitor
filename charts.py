#!/usr/bin/env python3
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    import numpy as np
except Exception:
    np = None  # polynomial smoothing skipped if numpy missing


def _parse_speeds_from_log(log_path: Path):
    """
    Parse monitor.log and return (speeds, etas) lists from Heights lines
    that have numeric speed and ETA.
    """
    speeds = []
    etas = []

    if not log_path.exists():
        return speeds, etas

    try:
        with log_path.open() as f:
            for line in f:
                if "Heights:" not in line:
                    continue

                m_speed = re.search(r"speed~=([0-9.]+)", line)
                m_eta   = re.search(r"ETA=([0-9.]+)",   line)
                if not m_speed or not m_eta:
                    continue

                try:
                    s = float(m_speed.group(1))
                    e = float(m_eta.group(1))
                except ValueError:
                    continue

                speeds.append(s)
                etas.append(e)
    except Exception:
        # just return what we have
        pass

    return speeds, etas


def write_speed_chart(speed_tracker, path, logger):
    """
    Plot speed history with:

    - Raw speeds (from monitor.log if available, else in-memory samples)
    - EMA-smoothed curve
    - Optional polynomial fit (smooth interpolation) if numpy is available
    - Title includes last ETA from log if available
    """
    log_path = Path(path).with_name("monitor.log")
    speeds_from_log, etas = _parse_speeds_from_log(log_path)

    if speeds_from_log:
        samples = speeds_from_log
        x_label = "Sample index (log history)"
    else:
        # fallback to current process samples
        samples = list(getattr(speed_tracker, "samples", []))
        x_label = "Sample index (recent checks)"

    if len(samples) < 2:
        return

    try:
        x = list(range(len(samples)))

        # EMA smoothing
        alpha = 0.2
        ema_vals = []
        ema = samples[0]
        ema_vals.append(ema)
        for s in samples[1:]:
            ema = alpha * s + (1 - alpha) * ema
            ema_vals.append(ema)

        plt.figure(figsize=(10, 4))

        # Raw speeds
        plt.plot(x, samples, marker="o", linestyle="-", label="raw speed (blk/s)")

        # EMA curve
        if len(ema_vals) == len(samples):
            plt.plot(x, ema_vals, linestyle="-", label="EMA speed")

        # Polynomial fit / smooth curve
        if np is not None and len(samples) >= 3:
            try:
                xp = np.array(x, dtype=float)
                yp = np.array(samples, dtype=float)
                deg = 3 if len(samples) > 3 else max(1, len(samples) - 1)
                coeffs = np.polyfit(xp, yp, deg)
                xs = np.linspace(xp[0], xp[-1], len(samples) * 10)
                ys = np.polyval(coeffs, xs)
                plt.plot(xs, ys, linestyle="--", label=f"poly fit (deg {deg})")
            except Exception as e:
                logger.log(f"[CHART] poly fit failed: {e}")

        # Title with last ETA
        eta_hours = etas[-1] if etas else None
        title = "Fulcrum Indexing Speed (blocks/sec)"
        if eta_hours is not None:
            title += f"  ETA≈{eta_hours:.1f} h"
        plt.title(title)

        plt.xlabel(x_label)
        plt.ylabel("blocks/sec")
        plt.grid(True)
        plt.legend(loc="best")
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        logger.log(f"[CHART] Wrote speed chart to {path}")
    except Exception as e:
        logger.log(f"[ERR] Failed to write speed chart: {e}")


def write_system_chart(cpu_pct, ram_pct, ssd_temp, path, logger):
    """
    Basic CPU/RAM/SSD system telemetry bar chart.
    """
    try:
        labels = ["CPU %", "RAM %"]
        values = [cpu_pct, ram_pct]
        if ssd_temp is not None:
            labels.append("SSD °C")
            values.append(ssd_temp)

        plt.figure(figsize=(6, 4))
        plt.bar(labels, values)
        plt.ylim(0, max(values) + 10)
        plt.title("System Telemetry")
        plt.grid(axis="y")
        plt.tight_layout()
        plt.savefig(path)
        plt.close()
        logger.log(f"[CHART] Wrote system chart to {path}")
    except Exception as e:
        logger.log(f"[ERR] Failed to write system chart: {e}")
