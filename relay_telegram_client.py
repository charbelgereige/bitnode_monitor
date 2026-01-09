#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import requests

from logger_util import Logger


class RelayTelegramClient:
    """
    Outbound-only "Telegram" client that sends messages to a local relay
    (typically via SSH tunnel) which then forwards to Telegram.

    Supported:
      - send_text

    Not supported (yet):
      - get_updates (commands)
      - send_photo (we can add later if you want chart delivery)
    """

    def __init__(
        self,
        relay_url: str,
        token_file: str,
        logger: Logger,
        enabled: Optional[bool] = None,
    ):
        self.relay_url = relay_url.strip()
        self.token_file = Path(token_file)
        self.logger = logger
        self.enabled = bool(self.relay_url) and self.token_file.exists()
        if enabled is not None:
            self.enabled = bool(enabled) and self.enabled

        if self.enabled:
            self.logger.log(f"[TG-RELAY] Enabled relay client url={self.relay_url} token_file={self.token_file}")
        else:
            self.logger.log("[TG-RELAY] Relay disabled (missing relay_url or token file).")

    def _token(self) -> str:
        try:
            # Trim CR/LF to avoid header mismatch
            return self.token_file.read_text().strip()
        except Exception:
            return ""

    def send_text(self, msg: str) -> None:
        if not self.enabled:
            return
        token = self._token()
        if not token:
            self.logger.log("[TG-RELAY] Missing relay token.")
            return
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Relay-Token": token,
            }
            payload = {"text": msg}
            resp = requests.post(self.relay_url, headers=headers, data=json.dumps(payload), timeout=10)
            if resp.status_code != 200:
                self.logger.log(f"[TG-RELAY] send_text failed: http={resp.status_code} body={resp.text[:200]}")
        except Exception as e:
            self.logger.log(f"[TG-RELAY] send_text error: {e}")

    # Stubs to match TelegramClient interface shape used elsewhere
    def send_photo(self, path: str, caption: str = "") -> None:
        self.logger.log("[TG-RELAY] send_photo not implemented in relay mode (skipping).")

    def get_updates(self, offset=None, timeout: int = 10):
        # Inbound commands are not supported in relay mode
        return []
