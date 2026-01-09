#!/usr/bin/env python3
import json
import time
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BIND_HOST = "127.0.0.1"
BIND_PORT = 18888

TOKEN_FILE = Path("/etc/bitnode-control.token")
LOCAL_ENV = Path("/home/charb/fulcrum-bot/local.env")
MONITOR_SERVICE = "bitnode-monitor"

ALLOWED_MODES = {"direct", "relay", "auto"}

_last_restart_ts = 0.0

def _read_token() -> str:
    try:
        return TOKEN_FILE.read_text().strip()
    except Exception:
        return ""

def _authorized(headers) -> bool:
    want = _read_token()
    got = headers.get("X-Control-Token", "")
    return bool(want) and got == want

def _set_env_kv(path: Path, key: str, value: str) -> None:
    # Replace or append KEY=value, preserving other lines.
    lines = []
    found = False
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={value}")
                found = True
            else:
                lines.append(line)
    if not found:
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")

def _restart_monitor_rate_limited(min_interval_sec: int = 60) -> str:
    global _last_restart_ts
    now = time.time()
    if now - _last_restart_ts < min_interval_sec:
        return f"restart_skipped(rate_limit {min_interval_sec}s)"
    subprocess.check_call(["sudo", "systemctl", "restart", f"{MONITOR_SERVICE}.service"])
    _last_restart_ts = now
    return "restart_ok"

class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True})
        return self._json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        if not _authorized(self.headers):
            return self._json(403, {"ok": False, "error": "forbidden"})

        if self.path != "/mode":
            return self._json(404, {"ok": False, "error": "not_found"})

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json(400, {"ok": False, "error": "bad_json"})

        mode = str(data.get("mode", "")).strip().lower()
        ttl_sec = int(data.get("ttl_sec", 0) or 0)

        if mode not in ALLOWED_MODES:
            return self._json(400, {"ok": False, "error": "bad_mode", "allowed": sorted(ALLOWED_MODES)})

        # Apply mode
        _set_env_kv(LOCAL_ENV, "TELEGRAM_MODE", mode)

        # Optional TTL: write a one-shot expiry timestamp for the monitor to honor later (future enhancement)
        if ttl_sec > 0:
            expires = int(time.time()) + ttl_sec
            _set_env_kv(LOCAL_ENV, "TELEGRAM_MODE_EXPIRES_AT", str(expires))
        else:
            # remove expiry by setting empty (monitor can ignore)
            _set_env_kv(LOCAL_ENV, "TELEGRAM_MODE_EXPIRES_AT", "")

        restart_result = _restart_monitor_rate_limited()

        return self._json(200, {"ok": True, "mode": mode, "ttl_sec": ttl_sec, "restart": restart_result})

def main():
    httpd = HTTPServer((BIND_HOST, BIND_PORT), Handler)
    httpd.serve_forever()

if __name__ == "__main__":
    main()
