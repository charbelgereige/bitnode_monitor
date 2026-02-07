#!/usr/bin/env python3
import os
import re
import time
import subprocess
from datetime import datetime
from typing import Optional, Dict, Any


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
    # Regex to parse job lines like:
    # 2026-02-07 12:23:56.837 ... Updating standard stratum job for block 935399: 3.13248456 BTC, 563 txns, 298993 bytes (Sent to 1 stratum client)
    JOB_RE = re.compile(
        r"Updating (?:standard|priority) stratum job for block (\d+): ([\d.]+) BTC, (\d+) txns, (\d+) bytes \(Sent to (\d+)"
    )

    def __init__(
        self,
        service_name: str,
        logger,
        cooldown_sec: int = 900,
        no_job_sec: int = 300,
        telegram_client=None,
    ):
        self.service_name = service_name
        self.logger = logger
        self.cooldown_sec = int(cooldown_sec)
        self.no_job_sec = int(no_job_sec)
        self.telegram_client = telegram_client
        self._last_alert_ts = 0.0
        self._last_zero_client_alert_ts = 0.0
        self._last_job_ts: Optional[float] = None
        self._last_job_info: Optional[Dict[str, Any]] = None

    def parse_last_job(self) -> Optional[Dict[str, Any]]:
        """
        Parse recent journal logs for the latest job update line.
        Returns dict with block, btc, txns, bytes, clients, timestamp or None.
        """
        _, out, _ = _run(
            ["/bin/journalctl", "-u", self.service_name, "-n", "50", "--no-pager", "-o", "short-iso"],
            timeout=8,
        )
        if not out:
            return None

        # Parse lines in reverse to find most recent job
        for line in reversed(out.strip().splitlines()):
            m = self.JOB_RE.search(line)
            if m:
                # Extract timestamp from journalctl -o short-iso (first token, includes timezone)
                # Example: 2026-02-07T14:40:56+02:00
                ts_tok = line.split(None, 1)[0] if line.strip() else ""
                try:
                    ts = datetime.fromisoformat(ts_tok).timestamp()
                except Exception:
                    ts = time.time()

                return {
                    "block": int(m.group(1)),
                    "btc": float(m.group(2)),
                    "txns": int(m.group(3)),
                    "bytes": int(m.group(4)),
                    "clients": int(m.group(5)),
                    "timestamp": ts,
                }
        return None

    def mining_status_text(self) -> str:
        """
        Format mining status for /mining command.
        """
        host = os.uname().nodename
        job = self.parse_last_job()

        if not job:
            return f"[{host}] ⛏️ Mining Status\nNo recent job data found in datum-gateway logs."

        now = time.time()
        age_sec = now - job["timestamp"]
        if age_sec < 60:
            age_str = f"{int(age_sec)}s ago"
        elif age_sec < 3600:
            age_str = f"{int(age_sec / 60)}m ago"
        else:
            age_str = f"{age_sec / 3600:.1f}h ago"

        size_kb = job["bytes"] / 1024

        return (
            f"[{host}] ⛏️ Mining Status\n"
            f"Block: {job['block']} | Reward: {job['btc']:.8f} BTC\n"
            f"Txns: {job['txns']} | Size: {size_kb:.1f} KB\n"
            f"Clients: {job['clients']} | Last job: {age_str}"
        )

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
        Watchdog: alert if service inactive, no job progress, or 0 clients.
        """
        now = time.time()
        host = os.uname().nodename

        # Check 1: Service active?
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

        if not active:
            if (now - self._last_alert_ts) >= self.cooldown_sec:
                self._last_alert_ts = now
                txt = (
                    f"[{host}] ⚠️ DATUM not active. Run: systemctl status {self.service_name} -l; "
                    f"journalctl -u {self.service_name} -n 80 --no-pager"
                )
                self.logger.log(txt)
                if self.telegram_client:
                    self.telegram_client.send_text(txt)
            return  # Don't check job progress if service is down

        # Check 2: Job progress and client count
        job = self.parse_last_job()
        if job:
            self._last_job_info = job
            self._last_job_ts = job["timestamp"]

            # Alert immediately if 0 clients (with cooldown)
            if job["clients"] == 0:
                if (now - self._last_zero_client_alert_ts) >= self.cooldown_sec:
                    self._last_zero_client_alert_ts = now
                    txt = (
                        f"[{host}] ⚠️ DATUM has 0 stratum clients connected. "
                        f"Block: {job['block']}, last job: {int(now - job['timestamp'])}s ago."
                    )
                    self.logger.log(txt)
                    if self.telegram_client:
                        self.telegram_client.send_text(txt)

        # Check 3: No job progress for too long
        if self._last_job_ts is not None:
            stale_sec = now - self._last_job_ts
            if stale_sec > self.no_job_sec:
                if (now - self._last_alert_ts) >= self.cooldown_sec:
                    self._last_alert_ts = now
                    block_info = f"Last block: {self._last_job_info['block']}" if self._last_job_info else ""
                    txt = (
                        f"[{host}] ⚠️ DATUM no new jobs for {int(stale_sec)}s. {block_info}. "
                        f"Check: journalctl -u {self.service_name} -n 50 --no-pager"
                    )
                    self.logger.log(txt)
                    if self.telegram_client:
                        self.telegram_client.send_text(txt)
