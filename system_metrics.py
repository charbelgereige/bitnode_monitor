#!/usr/bin/env python3
from typing import Optional, Tuple
from pathlib import Path
import subprocess

import psutil

from logger_util import Logger


class SystemMetrics:
    def __init__(self, logger: Logger):
        self.logger = logger

    def get_cpu_ram(self) -> Tuple[Optional[float], Optional[float]]:
        try:
            cpu_pct = psutil.cpu_percent(interval=1)
            ram_pct = psutil.virtual_memory().percent
            return cpu_pct, ram_pct
        except Exception as e:
            self.logger.log(f"[ERR] psutil error: {e}")
            return None, None

    def get_ssd_temp(self) -> Optional[float]:
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
