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
    _ALIASES = {
        "/h": "/help",
        "/ns": "/status",
        "/ms": "/mining",
        "/ds": "/datum",
        "/id": "/investigate_datum",
        "/rpc": "/check_rpc",
        "/rf": "/restart_fulcrum",
        "/rb": "/restart_bitcoind",
    }

    _SHORTCUTS = {
        "/start": ["/status", "/mining", "/datum"],
        "/help": ["/status", "/mining", "/datum"],
        "/status": ["/mining", "/datum"],
        "/mining": ["/status"],
        "/datum": ["/investigate_datum"],
        "/investigate_datum": ["/status", "/mining"],
        "/check_rpc": ["/status"],
        "/restart_fulcrum": ["/status"],
        "/restart_bitcoind": ["/status"],
    }

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
        cmd = self._ALIASES.get(t, t)

        def _cb(name: str):
            return self.callbacks.get(name)

        def _send_cb_text(cb_name: str, missing_msg: str) -> None:
            fn = _cb(cb_name)
            if fn:
                self.client.send_text(self._with_shortcuts(fn(), cmd))
            else:
                self.client.send_text(self._with_shortcuts(missing_msg, cmd))

        def _restart(cb_name: str, missing_msg: str, ok_msg: str) -> None:
            fn = _cb(cb_name)
            if not fn:
                self.client.send_text(self._with_shortcuts(missing_msg, cmd))
                return
            out = fn()
            if isinstance(out, str) and out.strip():
                self.client.send_text(self._with_shortcuts(out, cmd))
            else:
                self.client.send_text(self._with_shortcuts(ok_msg, cmd))

        def _investigate(cb_name: str, missing_msg: str) -> None:
            fn = _cb(cb_name)
            if not fn:
                self.client.send_text(self._with_shortcuts(missing_msg, cmd))
                return
            self.client.send_chat_action("typing")
            self.client.send_text(
                self._with_shortcuts(fn(), cmd),
                disable_web_page_preview=True,
            )

        dispatch = {
            "/start": lambda: self.client.send_text(self._with_shortcuts(self._help_text(), cmd)),
            "/help": lambda: self.client.send_text(self._with_shortcuts(self._help_text(), cmd)),

            "/status": lambda: _send_cb_text("status_text", "status_text callback not configured."),
            "/check_rpc": lambda: _send_cb_text("check_rpc", "check_rpc callback not configured."),

            "/restart_fulcrum": lambda: _restart(
                "restart_fulcrum",
                "restart_fulcrum callback not configured.",
                "Requested Fulcrum restart.",
            ),
            "/restart_bitcoind": lambda: _restart(
                "restart_bitcoind",
                "restart_bitcoind callback not configured.",
                "Requested bitcoind restart.",
            ),

            "/datum": lambda: _send_cb_text("datum_status", "datum_status callback not configured."),
            "/investigate_datum": lambda: _investigate("investigate_datum", "investigate_datum callback not configured."),
            "/mining": lambda: _send_cb_text("mining_status", "mining_status callback not configured."),
        }

        handler = dispatch.get(cmd)
        if handler:
            handler()
            return

        self.client.send_text(self._with_shortcuts("Unknown command. Send /help for available commands.", cmd))

    def _help_text(self) -> str:
        return (
            "Bitnode Monitor Commands:\n"
            "/status (/ns) - show current status\n"
            "/check_rpc (/rpc) - test bitcoind RPC\n"
            "/restart_fulcrum (/rf) - restart fulcrum\n"
            "/restart_bitcoind (/rb) - restart bitcoind\n"
            "/datum (/ds) - show DATUM service status\n"
            "/investigate_datum (/id) - collect DATUM diagnostics\n"
            "/mining (/ms) - show mining job status\n"
            "/help (/h) - show available commands\n"
        )

    def _shortcuts_for(self, cmd: str):
        if not cmd:
            shortcuts = ["/help", "/status"]
        else:
            cmd = self._ALIASES.get(cmd, cmd)
            if cmd in self._SHORTCUTS:
                shortcuts = list(self._SHORTCUTS[cmd])
            else:
                shortcuts = ["/help", "/status"]

        if "/help" not in shortcuts:
            shortcuts.append("/help")

        seen = set()
        out = []
        for c in shortcuts:
            if c not in seen:
                seen.add(c)
                out.append(c)
        return out

    def _with_shortcuts(self, text: str, cmd: str) -> str:
        if text is None:
            text = ""
        shortcuts = self._shortcuts_for(cmd)
        if not shortcuts:
            return text
        return f"{text.rstrip()}\n\nShortcuts: {' '.join(shortcuts)}"

def _run_selftest() -> int:
    """
    Local, network-free self-test for TelegramService command dispatch.
    Run: python telegram_service.py --selftest
    """
    class _Logger:
        def log(self, msg: str) -> None:
            # Keep silent in selftest; uncomment for debugging.
            # print(msg)
            pass

    class _FakeClient:
        def __init__(self, chat_id: str):
            self.chat_id = str(chat_id)
            self.calls = []  # list[tuple[str, ...]]

        def send_text(self, text: str, disable_web_page_preview: bool = True) -> None:
            self.calls.append(("send_text", text, str(disable_web_page_preview)))

        def send_chat_action(self, action: str = "typing") -> None:
            self.calls.append(("send_chat_action", action))

    invoked = []

    def _cb(name):
        def _fn():
            invoked.append(name)
            if name == "restart_fulcrum":
                return ""  # should trigger default message
            if name == "restart_bitcoind":
                return "custom bitcoind restart message"
            if name == "investigate_datum":
                return "INVESTIGATE OUT"
            return "OK"
        return _fn

    callbacks = {
        "status_text": _cb("status_text"),
        "check_rpc": _cb("check_rpc"),
        "restart_fulcrum": _cb("restart_fulcrum"),
        "restart_bitcoind": _cb("restart_bitcoind"),
        "datum_status": _cb("datum_status"),
        "investigate_datum": _cb("investigate_datum"),
    }

    svc = TelegramService("DUMMY_TOKEN", "123", _Logger(), callbacks=callbacks)
    svc.client = _FakeClient("123")  # override network client

    def send(cmd: str, chat_id: str = "123"):
        upd = {"update_id": 1, "message": {"chat": {"id": chat_id}, "text": cmd}}
        svc._handle_update(upd)

    # Ignore other chats
    send("/status", chat_id="999")
    assert svc.client.calls == [], "Should ignore other chat_id"

    # /status
    send("/status")
    assert invoked[-1] == "status_text"
    assert svc.client.calls[-1][0] == "send_text"
    assert svc.client.calls[-1][1].startswith("OK")
    assert "Shortcuts:" in svc.client.calls[-1][1]

    # /datum
    send("/datum")
    assert invoked[-1] == "datum_status"
    assert svc.client.calls[-1][0] == "send_text"
    assert svc.client.calls[-1][1].startswith("OK")
    assert "Shortcuts:" in svc.client.calls[-1][1]

    # /investigate_datum: typing then message
    before = len(svc.client.calls)
    send("/investigate_datum")
    after_calls = svc.client.calls[before:]
    assert invoked[-1] == "investigate_datum"
    assert after_calls[0] == ("send_chat_action", "typing"), "Typing action should be first"
    assert after_calls[1][0] == "send_text"
    assert after_calls[1][1].startswith("INVESTIGATE OUT")
    assert "Shortcuts:" in after_calls[1][1]

    # Unknown command
    send("/does_not_exist")
    assert svc.client.calls[-1][0] == "send_text"
    assert svc.client.calls[-1][1].startswith("Unknown command. Send /help for available commands.")
    assert "Shortcuts:" in svc.client.calls[-1][1]

    return 0


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        rc = _run_selftest()
        print("SELFTEST OK" if rc == 0 else f"SELFTEST FAIL rc={rc}")
        raise SystemExit(rc)
