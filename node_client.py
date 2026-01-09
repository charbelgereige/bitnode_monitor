#!/usr/bin/env python3
from typing import Optional, Tuple
import subprocess
import time
import re

from config import Config
from logger_util import Logger
from telegram_client import TelegramClient


class NodeClient:
    def __init__(self, config: Config, logger: Logger):
        self.config = config
        self.logger = logger

    def get_bitcoind_height(self) -> Optional[int]:
        try:
            out = subprocess.check_output(
                [
                    "sudo", "-u", "bitcoin",
                    "/usr/local/bin/bitcoin-cli",
                    f"-conf={self.config.bitcoin_conf}",
                    "getblockcount",
                ],
                stderr=subprocess.DEVNULL,
            )
            return int(out.strip())
        except Exception as e:
            self.logger.log(f"[ERR] get_bitcoind_height failed: {e}")
            return None

    def get_fulcrum_height(self) -> Optional[int]:
        """
        Parse last 'Block height XXXX' from fulcrum journald logs.
        """
        try:
            out = subprocess.check_output(
                ["sudo", "journalctl", "-u", self.config.fulcrum_service, "--no-pager"],
                stderr=subprocess.DEVNULL,
            ).decode()
            matches = re.findall(r"Block height\s*([0-9]+)", out)
            if matches:
                return int(matches[-1])
            return None
        except Exception as e:
            self.logger.log(f"[ERR] get_fulcrum_height failed: {e}")
            return None

    def bitcoind_quick_check(self, timeout_sec: int = 30) -> Tuple[bool, Optional[int]]:
        """
        Run a quick RPC (getblockchaininfo) and measure latency.

        Returns (ok: bool, rpc_ms: Optional[int]).
        """
        start = time.time()
        try:
            subprocess.check_output(
                [
                    "sudo", "-u", "bitcoin",
                    "/usr/local/bin/bitcoin-cli",
                    f"-conf={self.config.bitcoin_conf}",
                    "getblockchaininfo",
                ],
                stderr=subprocess.DEVNULL,
                timeout=timeout_sec,
            )
            elapsed_ms = int((time.time() - start) * 1000)
            return True, elapsed_ms
        except Exception as e:
            self.logger.log(f"[ERR] bitcoind_quick_check failed: {e}")
            return False, None

    def restart_fulcrum(self, telegram: TelegramClient):
        """
        Restart Fulcrum safely:
        - Only if ENABLE_AUTO_RESTART=1
        - Only if bitcoind responds to a quick RPC in a timely manner
        """
        if not self.config.enable_auto_restart:
            self.logger.log("[STALL] Auto-restart disabled (ENABLE_AUTO_RESTART=0). Not restarting fulcrum.")
            return

        ok, rpc_ms = self.bitcoind_quick_check()
        if not ok:
            self.logger.log("[STALL] Skipping fulcrum restart: bitcoind looks unhealthy or timed out.")
            return

        self.logger.log(f"[RECOVERY] Restarting fulcrum via systemctl... (bitcoind RPC ~{rpc_ms} ms)")
        try:
            subprocess.check_call(["sudo", "systemctl", "restart", self.config.fulcrum_service])
            self.logger.log("[RECOVERY] fulcrum restart triggered.")
            telegram.send_text("♻️ Fulcrum restart triggered by monitor.")
        except Exception as e:
            self.logger.log(f"[ERR] Failed to restart fulcrum: {e}")
