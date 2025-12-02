#!/usr/bin/env python3
import time
import threading
from pathlib import Path

from telegram_client import TelegramClient


class TelegramService:
    """
    Background Telegram listener:
      - understands natural-language-ish commands
      - calls callbacks provided by MonitorController
    """
    def __init__(self, bot_token, chat_id, logger, speed_chart_file: Path, system_chart_file: Path, callbacks):
        self.logger = logger
        self.speed_chart_file = speed_chart_file
        self.system_chart_file = system_chart_file
        self.callbacks = callbacks or {}
        self.client = None
        self.bot_token = bot_token
        self.chat_id = chat_id

    def start(self):
        if not self.bot_token or not self.chat_id:
            self.logger.log("[TG] Telegram disabled or missing BOT_TOKEN/CHAT_ID.")
            return
        self.client = TelegramClient(self.bot_token, self.chat_id, self.logger)
        self.logger.log("[TG] Telegram client initialized.")
        try:
            self.client.send_text("🚀 Bitnode monitor Telegram loop started. Type /help for commands.")
        except Exception:
            pass
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        offset = None
        while True:
            try:
                updates = self.client.get_updates(offset=offset, timeout=25)
                for u in updates:
                    offset = u["update_id"] + 1
                    msg = u.get("message") or u.get("edited_message")
                    if not msg:
                        continue
                    chat_id = msg.get("chat", {}).get("id")
                    if chat_id is None:
                        continue
                    if str(chat_id) != str(self.chat_id):
                        continue
                    text = msg.get("text")
                    if not text:
                        continue
                    self._handle_text(text)
            except Exception as e:
                self.logger.log(f"[ERR] Telegram loop error: {e}")
                time.sleep(5)

    def _handle_text(self, text: str):
        t = text.strip()
        tl = t.lower()

        # Status / lag
        if t.startswith("/status") or "status" in tl or "state" in tl or "how far" in tl:
            fn = self.callbacks.get("status_text")
            if fn:
                self.client.send_text("📊 Status:\n" + fn())
            return

        if t.startswith("/heights") or t.startswith("/lag") or "lag" in tl:
            fn = self.callbacks.get("status_text")
            if fn:
                self.client.send_text("📏 Heights/lag:\n" + fn())
            return

        # Charts
        if t.startswith("/chart") or "chart" in tl or "charts" in tl or "graph" in tl:
            sent_any = False
            if self.speed_chart_file.exists():
                self.client.send_photo(self.speed_chart_file, caption="📈 Fulcrum speed chart")
                sent_any = True
            if self.system_chart_file.exists():
                self.client.send_photo(self.system_chart_file, caption="🖥 System telemetry chart")
                sent_any = True
            if not sent_any:
                self.client.send_text("No charts yet. They are generated periodically while the monitor runs.")
            return

        # Restart fulcrum
        if (t.startswith("/restart") and "fulcrum" in tl) or ("restart" in tl and "fulcrum" in tl):
            fn = self.callbacks.get("restart_fulcrum")
            if fn:
                self.client.send_text("♻️ Restarting Fulcrum (Telegram command)...")
                fn()
            return

        # Restart bitcoind
        if (t.startswith("/restart") and "bitcoind" in tl) or ("restart" in tl and "bitcoind" in tl):
            fn = self.callbacks.get("restart_bitcoind")
            if fn:
                self.client.send_text("♻️ Restarting bitcoind (Telegram command)...")
                fn()
            return

        # Check RPC
        if t.startswith("/check") or "check rpc" in tl or "rpc" in tl:
            fn = self.callbacks.get("check_rpc")
            if fn:
                msg = fn()
                self.client.send_text(msg)
            return

        # Fallback help
        self.client.send_text(
            "🤖 Commands I understand:\n"
            "- /status, 'status', 'how far behind' → heights, lag, ETA, CPU/RAM\n"
            "- /heights, /lag → heights + lag only\n"
            "- /chart, 'charts', 'graph' → send latest charts\n"
            "- /restart fulcrum → restart Fulcrum\n"
            "- /restart bitcoind → restart bitcoind\n"
            "- /check rpc, 'check rpc' → test bitcoind RPC responsiveness\n"
        )
