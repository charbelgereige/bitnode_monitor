#!/usr/bin/env python3
import os
import time
import subprocess
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / "local.env"


# -------------------------------------------------
# local.env helpers
# -------------------------------------------------
def load_env():
    env = {}
    if not ENV_FILE.exists():
        return env
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def update_env_var(key: str, value: str):
    lines = []
    found = False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


ENV = load_env()
BOT_TOKEN = ENV.get("BOT_TOKEN")
CHAT_ID_STR = ENV.get("CHAT_ID", "0")
try:
    CHAT_ID = int(CHAT_ID_STR)
except ValueError:
    CHAT_ID = 0


# -------------------------------------------------
# Telegram helpers
# -------------------------------------------------
def send_message(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] Missing BOT_TOKEN or CHAT_ID, cannot send Telegram message.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print(f"[ERR] Telegram sendMessage failed: {e}")


# -------------------------------------------------
# Command handling
# -------------------------------------------------
def handle_command(text: str):
    text = text.strip()

    if text.startswith("/start") or text.startswith("/help"):
        send_message(
            "Fulcrum control bot.\n"
            "Commands:\n"
            "/status - show current config\n"
            "/set CHECK_INTERVAL <value>\n"
            "/set STALL_THRESHOLD <value>\n"
            "/set CHART_INTERVAL <value>\n"
            "/set AUTO_RESTART <on|off|1|0|true|false>\n"
        )
        return

    if text.startswith("/status"):
        env = load_env()
        ci = env.get("CHECK_INTERVAL", "default")
        st = env.get("STALL_THRESHOLD", "default")
        ch = env.get("CHART_INTERVAL", "default")
        ar = env.get("ENABLE_AUTO_RESTART", "0")
        send_message(
            "Current config:\n"
            f"CHECK_INTERVAL={ci}\n"
            f"STALL_THRESHOLD={st}\n"
            f"CHART_INTERVAL={ch}\n"
            f"ENABLE_AUTO_RESTART={ar}"
        )
        return

    if text.lower().startswith("/set "):
        parts = text.split()
        if len(parts) < 3:
            send_message("Usage: /set <KEY> <VALUE>")
            return

        key = parts[1].upper()
        value = parts[2]

        mapping = {
            "CHECK_INTERVAL": "CHECK_INTERVAL",
            "STALL_THRESHOLD": "STALL_THRESHOLD",
            "CHART_INTERVAL": "CHART_INTERVAL",
            "AUTO_RESTART": "ENABLE_AUTO_RESTART",
            "ENABLE_AUTO_RESTART": "ENABLE_AUTO_RESTART",
        }

        if key not in mapping:
            send_message(f"Unknown key: {key}\nAllowed: CHECK_INTERVAL, STALL_THRESHOLD, CHART_INTERVAL, AUTO_RESTART")
            return

        env_key = mapping[key]

        # Normalise AUTO_RESTART values
        if env_key == "ENABLE_AUTO_RESTART":
            vnorm = value.lower()
            if vnorm in ("1", "on", "true", "yes"):
                value = "1"
            elif vnorm in ("0", "off", "false", "no"):
                value = "0"
            else:
                send_message("AUTO_RESTART must be one of: on, off, 1, 0, true, false, yes, no")
                return

        update_env_var(env_key, value)

        # Try to restart the monitor so new config takes effect
        try:
            subprocess.check_call(["sudo", "systemctl", "restart", "bitnode-monitor.service"])
            send_message(f"Updated {env_key}={value} and restarted bitnode-monitor.service")
        except Exception as e:
            send_message(f"Updated {env_key}={value}, but failed to restart fulcrum-monitor: {e}")
        return

    # Fallback
    send_message("Unknown command. Use /help.")


# -------------------------------------------------
# Long-polling loop
# -------------------------------------------------
def main_loop():
    if not BOT_TOKEN or not CHAT_ID:
        print("[ERR] BOT_TOKEN or CHAT_ID missing in local.env. Exiting.")
        return

    send_message("🤖 Fulcrum control bot online. Send /help for commands.")

    offset = None
    while True:
        params = {"timeout": 25}
        if offset is not None:
            params["offset"] = offset

        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params=params,
                timeout=35,
            )
            data = resp.json()
        except Exception as e:
            print(f"[ERR] getUpdates failed: {e}")
            time.sleep(5)
            continue

        for upd in data.get("result", []):
            offset = upd["update_id"] + 1

            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue

            chat = msg.get("chat", {})
            cid = chat.get("id")
            if cid != CHAT_ID:
                # Ignore messages from other chats
                continue

            text = msg.get("text") or ""
            if not text:
                continue

            handle_command(text)

        # Be nice to Telegram, small pause between polls
        time.sleep(1)


if __name__ == "__main__":
    main_loop()
