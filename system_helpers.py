#!/usr/bin/env python3
"""
System helpers for Fulcrum monitor: SSD temp & charts.
"""

from pathlib import Path
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def get_ssd_temp():
    """
    Try to get SSD/drive temperature.

    Strategy:
      1. smartctl -A /dev/sda  (if smartctl installed & drive supports it)
      2. /sys/class/hwmon/*/temp*_input
    """
    # smartctl
    try:
        out = subprocess.check_output(
            ["sudo", "smartctl", "-A", "/dev/sda"],
            stderr=subprocess.DEVNULL,
        ).decode()
        for line in out.splitlines():
            if "Temperature" in line or "Temp" in line:
                parts = line.split()
                # try to find an int in that line
                for p in parts:
                    if p.isdigit():
                        return float(p)
    except Exception:
        pass

    # /sys/class/hwmon fallback
    hwmon_dir = Path("/sys/class/hwmon")
    if hwmon_dir.exists():
        for hw in hwmon_dir.iterdir():
            for tfile in hw.glob("temp*_input"):
                try:
                    raw = tfile.read_text().strip()
                    val = float(raw) / 1000.0  # usually in millidegC
                    return val
                except Exception:
                    continue
    return None


def write_system_chart(cpu_pct, ram_pct, ssd_temp, out_path: Path, logger=None):
    """
    Save basic system chart (CPU/RAM/SSD temp) to out_path.
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
        plt.savefig(out_path)
        plt.close()
        if logger is not None:
            logger.log(f"[CHART] Wrote system chart to {out_path}")
    except Exception as e:
        if logger is not None:
            logger.log(f"[ERR] Failed to write system chart: {e}")
