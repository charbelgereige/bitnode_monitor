#!/usr/bin/env python3
import os
import re
import time
import subprocess
from typing import Optional


def _run(cmd, timeout=6):
    """
    Run a command and return (rc, stdout, stderr). Never raises.
    """
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except Exception as e:
        return 124, "", f"{type(e).__name__}: {e}"


def _truncate(s: str, max_chars: int = 3300) -> str:
    """
    Telegram-safe truncation. Keep head, append marker if needed.
    """
    if s is None:
        return ""
    if len(s) <= max_chars:
        return s
    return s[: max(0, max_chars - 40)] + "\n...[truncated]\n"


def _token_counts(text: str):
    """
    Quick token frequency for debugging signal.
    """
    rx = re.compile(
        r"(error|warn|fail|timeout|disconnect|reconnect|rpc|gbt|getblocktemplate|template|submit|stratum|socket|i/o|io error|orphan|stale|invalid|reject)"
    )
    counts = {}
    for m in rx.findall((text or "").lower()):
        counts[m] = counts.get(m, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


class DatumMonitor:
    def __init__(self, service_name: str, logger, cooldown_sec: int = 900, telegram_client=None):
        self.service_name = service_name
        self.logger = logger
        self.cooldown_sec = int(cooldown_sec)
        self.telegram_client = telegram_client
        self._last_alert_ts = 0.0

    def status_text(self) -> str:
        """
        Short status string for /datum.
        """
        host = os.uname().nodename
        rc, out, _ = _run(["/bin/systemctl", "is-active", self.service_name], timeout=3)
        active = (rc == 0 and out.strip() == "active")

        rc2, out2, _ = _run(
            ["/bin/systemctl", "show", self.service_name, "-p", "MainPID", "-p", "ActiveEnterTimestamp"],
            timeout=3,
        )
        meta = " ".join([x.strip() for x in out2.splitlines() if x.strip()])

        if active:
            return f"[{host}] ✅ DATUM active ({self.service_name}). {meta}"
        return f"[{host}] ❌ DATUM inactive ({self.service_name}). {meta}"

    def investigate_text(self) -> str:
        """
        Bounded diagnostic bundle for /investigate_datum.
        """
        host = os.uname().nodename

        _, status_out, status_err = _run(
            ["/bin/systemctl", "status", self.service_name, "-l", "--no-pager"], timeout=6
        )
        status_txt = (status_out + ("\n" + status_err if status_err else "")).strip()

        _, j_out, j_err = _run(
            ["/bin/journalctl", "-u", self.service_name, "-n", "160", "--no-pager", "-o", "short-iso"], timeout=8
        )
        journal_txt = (j_out + ("\n" + j_err if j_err else "")).strip()

        counts = _token_counts(journal_txt)
        top = ", ".join([f"{k}:{v}" for k, v in counts[:12]]) if counts else "none"

        msg = (
            f"[{host}] 🔎 DATUM investigate ({self.service_name})\n"
            f"token_counts: {top}\n\n"
            "== systemctl status ==\n"
            f"{_truncate(status_txt, 1600)}\n\n"
            "== journal (tail) ==\n"
            f"{_truncate(journal_txt, 1600)}"
        )
        return _truncate(msg, 3600)

    def watchdog_tick(self) -> None:
        """
        Minimal watchdog: alert (cooldown) if service is not active.
        """
        now = time.time()
        if (now - self._last_alert_ts) < self.cooldown_sec:
            return

        try:
            r = subprocess.run(
                ["/bin/systemctl", "is-active", self.service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            active = (r.returncode == 0 and r.stdout.strip() == "active")
        except Exception:
            active = False

        if active:
            return

        self._last_alert_ts = now
        host = os.uname().nodename
        txt = (
            f"[{host}] ⚠️ DATUM not active. Run: systemctl status {self.service_name} -l; "
            f"journalctl -u {self.service_name} -n 80 --no-pager"
        )
        self.logger.log(txt)
        if self.telegram_client:
            self.telegram_client.send_text(txt)
