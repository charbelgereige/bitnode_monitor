#!/usr/bin/env python3
import time
import threading
from pathlib import Path

from telegram_client import TelegramClient
from speed_history import load_samples_since_restart, build_speed_report


class TelegramService:
    """
    Background Telegram listener:
      - understands natural-language-ish commands
      - calls callbacks provided by MonitorController
      - can show speed/ETA history since last fulcrum restart
    """
    def __init__(self, bot_token, chat_id, logger, speed_chart_file: Path, system_chart_file: Path, callbacks):
        self.logger = logger
        self.speed_chart_file = speed_chart_file
        self.system_chart_file = system_chart_file
        self.callbacks = callbacks or {}
        self.client = None
        self.bot_token = bot_token
        self.chat_id = chat_id
        # derive monitor.log from chart location
        self.log_file = speed_chart_file.with_name("monitor.log")

    def start(self):
        if not self.bot_token or not self.chat_id:
            self.logger.log("[TG] Telegram disabled or missing BOT_TOKEN/CHAT_ID.")
            return
        self.client = TelegramClient(self.bot_token, self.chat_id, self.logger)
        self.logger.log("[TG] Telegram client initialized.")
        try:
            self.client.send_text(
                "🚀 Bitnode monitor Telegram loop started.\n"
                "Short description: watchdog for your Raspberry Pi Bitcoin/Fulcrum stack "
                "(heights, lag, ETA, CPU/RAM, charts).\n"
                "Type /help for commands."
            )
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
                    # log incoming text
                    self.logger.log(f"[TG] ← {text}")
                    self._handle_text(text)
            except Exception as e:
                self.logger.log(f"[ERR] Telegram loop error: {e}")
                time.sleep(5)

    # ----------------------------------------------------------
    # Command routing
    # ----------------------------------------------------------

    def _handle_text(self, text: str):
        t = text.strip()
        tl = t.lower()

        # Status / lag
        if t.startswith("/status") or " status" in tl or "state" in tl or "how far" in tl:
            fn = self.callbacks.get("status_text")
            if fn:
                self.client.send_text("📊 Status:\n" + fn())
            return

        if t.startswith("/heights") or t.startswith("/lag") or " lag" in tl:
            fn = self.callbacks.get("status_text")
            if fn:
                self.client.send_text("📏 Heights/lag:\n" + fn())
            return

        # Speeds / ETA history
        if t.startswith("/speeds") or "speeds" in tl:
            mode = "full"
            n = None

            tokens = t.split()
            i = 1
            while i < len(tokens):
                tok = tokens[i]
                if tok in ("-h", "--head"):
                    mode = "head"
                    if i + 1 < len(tokens):
                        try:
                            n = int(tokens[i + 1])
                            i += 1
                        except ValueError:
                            pass
                elif tok in ("-t", "--tail"):
                    mode = "tail"
                    if i + 1 < len(tokens):
                        try:
                            n = int(tokens[i + 1])
                            i += 1
                        except ValueError:
                            pass
                i += 1

            samples = load_samples_since_restart(self.log_file)
            if not samples:
                self.client.send_text("No Heights samples found in monitor.log for this Fulcrum run yet.")
                return

            summary, lines = build_speed_report(samples, mode=mode, n=n)
            msg = "📈 Fulcrum speed/ETA history (current run):\n" + summary + "\n\n" + "\n".join(lines)
            self.client.send_text(msg)
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
        if t.startswith("/check") or "check rpc" in tl or " rpc" in tl:
            fn = self.callbacks.get("check_rpc")
            if fn:
                msg = fn()
                self.client.send_text(msg)
            return

        # Fallback help
        self.client.send_text(
            "🤖 Commands I understand:\n"
            "- /status – heights, lag, ETA, CPU/RAM\n"
            "- /heights – block heights only\n"
            "- /speeds [-h N | -t N] – speed/ETA history since last Fulcrum restart\n"
            "- /chart – send speed/system charts\n"
            "- /restart fulcrum\n"
            "- /restart bitcoind\n"
            "- /check rpc\n"
        )
