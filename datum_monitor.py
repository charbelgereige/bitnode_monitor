#!/usr/bin/env python3
import os
import re
import time
import subprocess
import json
import platform
from datetime import datetime
from typing import Optional, Dict, Any

from system_info import get_bitcoind_state


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


def _get_hostname():
    """
    Get hostname in a cross-platform way.
    On Linux: os.uname().nodename
    On Windows: platform.uname().node
    """
    try:
        return os.uname().nodename
    except AttributeError:
        # Windows doesn't have os.uname()
        return platform.uname().node


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
        bitcoin_conf: str = None,
    ):
        self.service_name = service_name
        self.logger = logger
        self.cooldown_sec = int(cooldown_sec)
        self.no_job_sec = int(no_job_sec)
        self.telegram_client = telegram_client
        self.bitcoin_conf = bitcoin_conf or os.getenv("BITCOIN_CONF", "/mnt/bitcoin/bitcoind/bitcoin.conf")
        self._last_alert_ts = 0.0
        self._last_zero_client_alert_ts = 0.0
        self._last_job_ts: Optional[float] = None
        self._last_job_info: Optional[Dict[str, Any]] = None
        self._ibd_cooldown_multiplier = 10  # 10x longer cooldown during IBD

    def _check_ibd_state(self) -> bool:
        """
        Check if bitcoind is in Initial Block Download (IBD) mode.
        Returns True if in IBD, False otherwise.
        Uses fallback log parsing if RPC is unavailable.
        """
        ibd_state = get_bitcoind_state(self.bitcoin_conf, self.logger)
        if ibd_state.get("ok") and ibd_state.get("ibd") is not None:
            return ibd_state["ibd"]
        # If we can't determine IBD state, assume not in IBD (conservative)
        return False

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

    def mining_status_text(self, bitaxe_checker=None) -> str:
        """
        Format mining status for /mining command.
        """
        host = _get_hostname()
        job = self.parse_last_job()

        if not job:
            base_msg = f"[{host}] ⛏️ Mining Status\nNo recent job data found in datum-gateway logs."
        else:
            now = time.time()
            age_sec = now - job["timestamp"]
            if age_sec < 60:
                age_str = f"{int(age_sec)}s ago"
            elif age_sec < 3600:
                age_str = f"{int(age_sec / 60)}m ago"
            else:
                age_str = f"{age_sec / 3600:.1f}h ago"

            size_kb = job["bytes"] / 1024

            base_msg = (
                f"[{host}] ⛏️ Mining Status\n"
                f"Block: {job['block']} | Reward: {job['btc']:.8f} BTC\n"
                f"Txns: {job['txns']} | Size: {size_kb:.1f} KB\n"
                f"Clients: {job['clients']} | Last job: {age_str}"
            )

        # Add pool status if available
        if bitaxe_checker:
            pool_status = bitaxe_checker.get_pool_status_line()
            return f"{base_msg}\n\n{pool_status}"

        return base_msg

    def status_text(self) -> str:
        """
        Short status string for /datum.
        """
        host = _get_hostname()
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
        host = _get_hostname()

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

    def check_for_template_errors(self):
        """
        Check for template fetch errors and alert if threshold exceeded.
        Only alert if we see sustained errors (10+ in last 3 minutes) to avoid
        alerting on brief swap-related hiccups.

        During IBD, template errors are expected and suppressed entirely.
        """
        # Check if in IBD - suppress template error alerts entirely during IBD
        in_ibd = self._check_ibd_state()
        if in_ibd:
            # Don't alert on template errors during IBD - they're expected
            return

        now = time.time()
        host = _get_hostname()
        _, out, _ = _run(
            ["/bin/journalctl", "-u", self.service_name, "--since", "3 minutes ago", "--no-pager"],
            timeout=8,
        )
        # Count template fetch errors
        error_count = out.count("Could not fetch new template")

        # Only alert if we have sustained errors (10+ in 3 minutes means ~2 minutes of continuous failures)
        if error_count >= 10:
            if (now - self._last_alert_ts) >= self.cooldown_sec:
                self._last_alert_ts = now
                txt = f"[{host}] ⚠️ DATUM Error: Could not fetch new block template from bitcoind ({error_count} errors in 3 min)."
                self.logger.log(txt)
                if self.telegram_client:
                    self.telegram_client.send_text(txt)

    def watchdog_tick(self) -> None:
        """
        Watchdog: alert if service inactive, no job progress, or 0 clients.
        During IBD, use longer cooldowns to reduce noise.
        """
        now = time.time()
        host = _get_hostname()

        # Check IBD state for adaptive alerting
        in_ibd = self._check_ibd_state()
        effective_cooldown = self.cooldown_sec * self._ibd_cooldown_multiplier if in_ibd else self.cooldown_sec

        self.check_for_template_errors()

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
            if (now - self._last_alert_ts) >= effective_cooldown:
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

            # Alert if 0 clients (with cooldown, extended during IBD)
            if job["clients"] == 0:
                if (now - self._last_zero_client_alert_ts) >= effective_cooldown:
                    self._last_zero_client_alert_ts = now
                    ibd_note = " (IBD in progress)" if in_ibd else ""
                    txt = (
                        f"[{host}] ⚠️ DATUM has 0 stratum clients connected{ibd_note}. "
                        f"Block: {job['block']}, last job: {int(now - job['timestamp'])}s ago."
                    )
                    self.logger.log(txt)
                    if self.telegram_client:
                        self.telegram_client.send_text(txt)

        # Check 3: No job progress for too long (with extended threshold during IBD)
        if self._last_job_ts is not None:
            stale_sec = now - self._last_job_ts
            # During IBD, use longer threshold for stale jobs (5x normal)
            effective_no_job_sec = self.no_job_sec * 5 if in_ibd else self.no_job_sec

            if stale_sec > effective_no_job_sec:
                if (now - self._last_alert_ts) >= effective_cooldown:
                    self._last_alert_ts = now
                    block_info = f"Last block: {self._last_job_info['block']}" if self._last_job_info else ""
                    ibd_note = " (IBD in progress, reduced alerting)" if in_ibd else ""
                    txt = (
                        f"[{host}] ⚠️ DATUM no new jobs for {int(stale_sec)}s{ibd_note}. {block_info}. "
                        f"Check: journalctl -u {self.service_name} -n 50 --no-pager"
                    )
                    self.logger.log(txt)
                    if self.telegram_client:
                        self.telegram_client.send_text(txt)
