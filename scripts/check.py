#!/usr/bin/env python3
"""
Offline sanity check for fulcrum-bot.
No network calls. No systemd interaction.
"""

import subprocess
import sys

PYTHON = sys.executable

def run(cmd, label):
    print(f"[CHECK] {label}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] {label}")
        raise

def main():
    run([PYTHON, "-m", "py_compile",
         "monitor_controller.py",
         "telegram_service.py",
         "datum_monitor.py",
         "fulcrum_monitor.py"],
        "py_compile core modules")

    run([PYTHON, "telegram_service.py", "--selftest"],
        "telegram dispatcher selftest")

    run([PYTHON, "-c", "from monitor_controller import MonitorController; MonitorController(); print(ok)"],
        "monitor_controller import + init")

    print("[OK] All offline checks passed.")

if __name__ == "__main__":
    main()
