#!/usr/bin/env python3
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import Config
from logger_util import Logger
from speed_tracker import SpeedTracker


class ChartWriter:
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger

    def write_speed_chart(self, speed_tracker: SpeedTracker):
        """
        Save speed chart if we have enough samples.
        """
        if len(speed_tracker.samples) < 2:
            return
        try:
            plt.figure(figsize=(10, 4))
            plt.plot(speed_tracker.samples, marker="o", linestyle="-")
            plt.title("Fulcrum Indexing Speed (blocks/sec)")
            plt.xlabel("Sample index (last N checks)")
            plt.ylabel("blocks/sec")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(self.config.speed_chart_file)
            plt.close()
            self.logger.log(f"[CHART] Wrote speed chart to {self.config.speed_chart_file}")
        except Exception as e:
            self.logger.log(f"[ERR] Failed to write speed chart: {e}")

    def write_system_chart(self, cpu_pct: float, ram_pct: float, ssd_temp: Optional[float]):
        """
        Save basic system chart.
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
            plt.savefig(self.config.system_chart_file)
            plt.close()
            self.logger.log(f"[CHART] Wrote system chart to {self.config.system_chart_file}")
        except Exception as e:
            self.logger.log(f"[ERR] Failed to write system chart: {e}")
