#!/usr/bin/env python3
from __future__ import annotations

import time
import threading
from typing import Any, Callable, Dict, Optional

import requests


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str, logger):
        self.bot_token = bot_token
        self.chat_id = str(chat_id)
        self.logger = logger
        self.base = f"https://api.telegram.org/bot{bot_token}"
        self.session = requests.Session()

    def _post(self, method: str, payload: dict, timeout: float = 10.0) -> Optional[dict]:
        try:
            r = self.session.post(f"{self.base}/{method}", data=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.logger.log(f"[TG] {method} error: {e}")
            return None

    def send_chat_action(self, action: str = "typing") -> None:
        self._post(
            "sendChatAction",
            {"chat_id": self.chat_id, "action": action},
            timeout=8.0,
        )

    def send_text(self, text: str, disable_web_page_preview: bool = True) -> None:
        # Telegram message hard limit ~4096 chars; keep margin.
        if text is None:
            text = ""
        if len(text) > 3800:
            text = text[:3760] + "\n...[truncated]\n"
        self._post(
            "sendMessage",
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": disable_web_page_preview,
            },
            timeout=12.0,
        )


class TelegramService:
    """
    Polling-based Telegram command handler.

    callbacks: dict[str, callable]
      - status_text() -> str
      - restart_fulcrum() -> None/str
      - restart_bitcoind() -> None/str
      - check_rpc() -> str
      - datum_status() -> str
      - investigate_datum() -> str
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        logger,
        speed_chart_path=None,
        system_chart_path=None,
        callbacks: Optional[Dict[str, Callable[..., Any]]] = None,
    ):
        self.logger = logger
        self.client = TelegramClient(bot_token, chat_id, logger)
        self.speed_chart_path = speed_chart_path
        self.system_chart_path = system_chart_path
        self.callbacks = callbacks or {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._offset: Optional[int] = None

        # Polling parameters
        self._poll_timeout = 25  # seconds
        self._poll_sleep = 0.5

        self.logger.log("[TG] Telegram client initialized.")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="telegram-poll", daemon=True)
        self._thread.start()
        self.logger.log("[TG] Telegram polling thread started.")

    def stop(self) -> None:
        self._stop.set()

    def _get_updates(self) -> Optional[dict]:
        params = {"timeout": self._poll_timeout}
        if self._offset is not None:
            params["offset"] = self._offset
        try:
            r = self.client.session.get(f"{self.client.base}/getUpdates", params=params, timeout=self._poll_timeout + 5)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            self.logger.log(f"[TG] get_updates error: {e}")
            return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            data = self._get_updates()
            if data and data.get("ok") and data.get("result"):
                for upd in data["result"]:
                    try:
                        self._handle_update(upd)
                    except Exception as e:
                        self.logger.log(f"[TG] handle_update exception: {e}")
                    try:
                        self._offset = int(upd["update_id"]) + 1
                    except Exception:
                        pass
            time.sleep(self._poll_sleep)

    def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return

        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        if chat_id and chat_id != self.client.chat_id:
            # Ignore other chats
            return

        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return

        # Normalize command
        t = text.split()[0].strip()

        if t in ("/start", "/help"):
            self.client.send_text(self._help_text())
            return

        if t == "/status":
            fn = self.callbacks.get("status_text")
            if fn:
                self.client.send_text(fn())
            else:
                self.client.send_text("status_text callback not configured.")
            return

        if t == "/check_rpc":
            fn = self.callbacks.get("check_rpc")
            if fn:
                self.client.send_text(fn())
            else:
                self.client.send_text("check_rpc callback not configured.")
            return

        if t == "/restart_fulcrum":
            fn = self.callbacks.get("restart_fulcrum")
            if fn:
                out = fn()
                if isinstance(out, str) and out.strip():
                    self.client.send_text(out)
                else:
                    self.client.send_text("Requested Fulcrum restart.")
            else:
                self.client.send_text("restart_fulcrum callback not configured.")
            return

        if t == "/restart_bitcoind":
            fn = self.callbacks.get("restart_bitcoind")
            if fn:
                out = fn()
                if isinstance(out, str) and out.strip():
                    self.client.send_text(out)
                else:
                    self.client.send_text("Requested bitcoind restart.")
            else:
                self.client.send_text("restart_bitcoind callback not configured.")
            return

        # NEW: DATUM commands
        if t == "/datum":
            fn = self.callbacks.get("datum_status")
            if fn:
                self.client.send_text(fn())
            else:
                self.client.send_text("datum_status callback not configured.")
            return

        if t == "/investigate_datum":
            fn = self.callbacks.get("investigate_datum")
            if fn:
                self.client.send_chat_action("typing")
                self.client.send_text(fn(), disable_web_page_preview=True)
            else:
                self.client.send_text("investigate_datum callback not configured.")
            return

        self.client.send_text("Unknown command. Send /help for available commands.")

    def _help_text(self) -> str:
        return (
            "Bitnode Monitor Commands:\n"
            "/status - show current status\n"
            "/check_rpc - test bitcoind RPC\n"
            "/restart_fulcrum - restart fulcrum\n"
            "/restart_bitcoind - restart bitcoind\n"
            "/datum - show DATUM service status\n"
            "/investigate_datum - collect DATUM diagnostics\n"
        )
