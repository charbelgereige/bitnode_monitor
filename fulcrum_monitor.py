#!/usr/bin/env python3
import sys
from pathlib import Path

from dotenv import load_dotenv

from monitor_controller import MonitorController
from logger_util import Logger


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "local.env"


def main():
    # Load local.env if present
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
    else:
        print(f"[WARN] {ENV_FILE} not found. Using defaults + hard-coded paths.")

    controller = MonitorController()
    controller.maybe_start_telegram()
    controller.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log_file = BASE_DIR / "monitor.log"
        Logger(log_file).log("Monitor interrupted by user, exiting.")
        sys.exit(0)
