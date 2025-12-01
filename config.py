#!/usr/bin/env python3
from pathlib import Path
from typing import Optional
import os

from dotenv import load_dotenv


class Config:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.env_file = base_dir / "local.env"
        self.log_file = base_dir / "monitor.log"
        self.speed_chart_file = base_dir / "speed_chart.png"
        self.system_chart_file = base_dir / "system_chart.png"

        if self.env_file.exists():
            load_dotenv(self.env_file)
        else:
            print(f"[WARN] {self.env_file} not found. Using defaults + hard-coded paths.")

        self.bot_token = os.getenv("BOT_TOKEN")
        self.chat_id = os.getenv("CHAT_ID")
        self.enable_telegram = os.getenv("ENABLE_TELEGRAM", "0") == "1"
        self.enable_auto_restart = os.getenv("ENABLE_AUTO_RESTART", "0") == "1"

        self.bitcoin_conf = os.getenv("BITCOIN_CONF", "/mnt/bitcoin/bitcoind/bitcoin.conf")
        self.fulcrum_service = os.getenv("FULCRUM_SERVICE", "fulcrum")
        self.bitcoind_service = os.getenv("BITCOIND_SERVICE", "bitcoind")

        self.check_interval = self._parse_duration(os.getenv("CHECK_INTERVAL", "120"), 120)
        self.stall_threshold = self._parse_duration(os.getenv("STALL_THRESHOLD", "1800"), 1800)
        self.speed_window = int(os.getenv("SPEED_WINDOW", "50"))

        self.ssd_temp_threshold = float(os.getenv("SSD_TEMP_THRESHOLD", "65"))
        self.cpu_alert_threshold = float(os.getenv("CPU_ALERT_THRESHOLD", "90"))
        self.ram_alert_threshold = float(os.getenv("RAM_ALERT_THRESHOLD", "90"))

        self.chart_interval = self._parse_duration(os.getenv("CHART_INTERVAL", "3600"), 3600)

        # anti-flap for recovery
        self.min_recovery_interval = 600  # 10 minutes

    @staticmethod
    def _parse_duration(value: Optional[str], default_seconds: int) -> int:
        """
        Parse strings like '30', '30s', '5m', '2h' into seconds.
        """
        if not value:
            return default_seconds
        s = value.strip().lower()
        if s.endswith("s"):
            try:
                return int(s[:-1])
            except ValueError:
                return default_seconds
        if s.endswith("m"):
            try:
                return int(s[:-1]) * 60
            except ValueError:
                return default_seconds
        if s.endswith("h"):
            try:
                return int(s[:-1]) * 3600
            except ValueError:
                return default_seconds
        try:
            return int(s)
        except ValueError:
            return default_seconds
