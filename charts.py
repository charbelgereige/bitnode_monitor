#!/usr/bin/env python3
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def write_speed_chart(speed_tracker, path, logger):
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
        plt.savefig(path)
        plt.close()
        logger.log(f"[CHART] Wrote speed chart to {path}")
    except Exception as e:
        logger.log(f"[ERR] Failed to write speed chart: {e}")


def write_system_chart(cpu_pct, ram_pct, ssd_temp, path, logger):
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
