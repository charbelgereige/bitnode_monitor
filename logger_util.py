#!/usr/bin/env python3
from pathlib import Path
import datetime


class Logger:
    def __init__(self, log_file: Path):
        self.log_file = log_file

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        try:
            with self.log_file.open("a") as f:
                f.write(line + "\n")
        except Exception:
            # Don't crash the monitor if logging to file fails
            pass
