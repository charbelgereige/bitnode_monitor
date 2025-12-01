#!/usr/bin/env python3
from __future__ import annotations

import time
from typing import Optional, List, Dict, Any

import requests

from logger_util import Logger


class TelegramClient:
    """
    Simple Telegram bot client used by the Fulcrum monitor.

    Responsibilities:
    - Send text messages
    - Send photos (charts)
    - Show 'typing...' (chat actions)
    - Poll updates for commands (used by MonitorController)
    """

    def __init__(
        self,
        token: Optional[str],
        chat_id: Optional[str],
        logger: Logger,
        enabled: Optional[bool] = None,
    ):
        self.token = token
        self.chat_id = chat_id
        self.logger = logger

        # Auto-enable if both token and chat_id are present
        if enabled is None:
            self.enabled = bool(self.token and self.chat_id)
        else:
            self.enabled = enabled and bool(self.token and self.chat_id)

        if self.enabled:
            self.logger.log("[TG] Telegram client initialized.")
        else:
            self.logger.log("[TG] Telegram disabled (missing token or chat id).")

    # ----------------------------------------------------------
    # Low-level helpers
    # ----------------------------------------------------------

    def _base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def _can_send(self) -> bool:
        return self.enabled and bool(self.token) and bool(self.chat_id)

    # ----------------------------------------------------------
    # Chat actions / typing animation
    # ----------------------------------------------------------

    def send_chat_action(self, action: str = "typing") -> None:
        """
        Send a chat action like 'typing', 'upload_photo', etc.
        Makes the bot show 'typing...' in Telegram.
        """
        if not self._can_send():
            return
        try:
            url = f"{self._base_url()}/sendChatAction"
            data = {"chat_id": self.chat_id, "action": action}
            requests.post(url, data=data, timeout=5)
        except Exception as e:
            self.logger.log(f"[TG] send_chat_action error: {e}")

    def show_typing_once(self) -> None:
        """
        Fire a single 'typing' event (Telegram shows for a short time).
        Non-blocking.
        """
        self.send_chat_action("typing")

    def show_typing_for(self, duration_sec: float = 3.0, interval: float = 2.0) -> None:
        """
        Keep sending 'typing' for up to duration_sec.
        WARNING: blocks the caller; only use for short durations.
        """
        end = time.time() + duration_sec
        while time.time() < end:
            self.send_chat_action("typing")
            time.sleep(interval)

    # ----------------------------------------------------------
    # Sending messages
    # ----------------------------------------------------------

    def send_text(self, msg: str) -> None:
        """
        Send a plain text message.

        We show a quick 'typing...' before sending so from the
        user's perspective the bot feels more responsive.
        """
        if not self._can_send():
            return
        try:
            # Show 'typing' once before sending the message
            self.show_typing_once()

            url = f"{self._base_url()}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": msg,
                
            }
            resp = requests.post(url, data=data, timeout=10)
            if resp.status_code != 200:
                self.logger.log(f"[TG] send_text failed: {resp.text}")
        except Exception as e:
            self.logger.log(f"[TG] send_text error: {e}")

    def send_photo(self, path: str, caption: str = "") -> None:
        """
        Send a PNG chart or other image.
        """
        if not self._can_send():
            return
        try:
            # Optional: also show typing before sending photos
            self.show_typing_once()

            url = f"{self._base_url()}/sendPhoto"
            with open(path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": self.chat_id, "caption": caption}
                resp = requests.post(url, data=data, files=files, timeout=20)
            if resp.status_code != 200:
                self.logger.log(f"[TG] send_photo failed: {resp.text}")
        except Exception as e:
            self.logger.log(f"[TG] send_photo error: {e}")

    # ----------------------------------------------------------
    # Polling for updates (for commands like 'status')
    # ----------------------------------------------------------

    def get_updates(
        self,
        offset: Optional[int] = None,
        timeout: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Basic long-polling getUpdates wrapper.

        MonitorController can call this in a loop and parse messages.
        """
        if not self.enabled or not self.token:
            return []

        try:
            url = f"{self._base_url()}/getUpdates"
            params: Dict[str, Any] = {
                "timeout": timeout,
            }
            if offset is not None:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=timeout + 5)
            if resp.status_code != 200:
                self.logger.log(f"[TG] get_updates failed: {resp.text}")
                return []

            data = resp.json()
            if not data.get("ok"):
                self.logger.log(f"[TG] get_updates not ok: {data}")
                return []

            return data.get("result", [])
        except Exception as e:
            self.logger.log(f"[TG] get_updates error: {e}")
            return []

