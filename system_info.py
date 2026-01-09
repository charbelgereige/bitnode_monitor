#!/usr/bin/env python3
import subprocess
import json
from pathlib import Path

import psutil


def parse_duration(value, default_seconds):
    """
    Parse '30', '30s', '5m', '2h' into seconds.
    """
    if not value:
        return default_seconds
    s = value.strip().lower()
    if s.endswith("s"):
        try:
            return int(s[:-1])
        except ValueError:
            return default_seconds
    if s.endswith("m"):
        try:
            return int(s[:-1]) * 60
        except ValueError:
            return default_seconds
    if s.endswith("h"):
        try:
            return int(s[:-1]) * 3600
        except ValueError:
            return default_seconds
    try:
        return int(s)
    except ValueError:
        return default_seconds


def get_bitcoind_height(bitcoin_conf: str, logger):
    try:
        out = subprocess.check_output(
            [
                "sudo", "-u", "bitcoin",
                "/usr/local/bin/bitcoin-cli",
                f"-conf={bitcoin_conf}",
                "getblockcount",
            ],
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip())
    except Exception as e:
        logger.log(f"[ERR] get_bitcoind_height failed: {e}")
        return None


def get_fulcrum_height(fulcrum_service: str, logger):
    """
    Parse last 'Processed height: XXXX' from fulcrum journald logs.
    """
    try:
        out = subprocess.check_output(
            ["sudo", "journalctl", "-u", fulcrum_service, "--no-pager"],
            stderr=subprocess.DEVNULL,
        ).decode()
        import re
        matches = re.findall(r"Processed height:\s*([0-9]+)", out)
        if matches:
            return int(matches[-1])
        return None
    except Exception as e:
        logger.log(f"[ERR] get_fulcrum_height failed: {e}")
        return None


def get_ssd_temp(logger):
    """
    Try to get SSD/drive temperature:
      1) smartctl -A /dev/sda
      2) /sys/class/hwmon/*/temp*_input
    """
    try:
        out = subprocess.check_output(
            ["sudo", "smartctl", "-A", "/dev/sda"],
            stderr=subprocess.DEVNULL,
        ).decode()
        for line in out.splitlines():
            if "Temperature" in line or "Temp" in line:
                parts = line.split()
                for p in parts:
                    if p.isdigit():
                        return float(p)
    except Exception:
        pass

    hwmon_dir = Path("/sys/class/hwmon")
    if hwmon_dir.exists():
        for hw in hwmon_dir.iterdir():
            for tfile in hw.glob("temp*_input"):
                try:
                    raw = tfile.read_text().strip()
                    val = float(raw) / 1000.0
                    return val
                except Exception:
                    continue
    return None


def get_system_stats(logger):
    """
    Return (cpu_pct, ram_pct) or (None, None) on error.
    """
    try:
        cpu_pct = psutil.cpu_percent(interval=0.3)
        ram_pct = psutil.virtual_memory().percent
        return cpu_pct, ram_pct
    except Exception as e:
        logger.log(f"[ERR] psutil error: {e}")
        return None, None


def get_bitcoind_state(bitcoin_conf: str, logger):
    """
    Return dict with bitcoind sync/verification state.
    Keys:
      ok(bool), blocks(int|None), headers(int|None),
      ibd(bool|None), verificationprogress(float|None), warnings(str|None)
    """
    try:
        out = subprocess.check_output(
            [
                "sudo", "-u", "bitcoin",
                "/usr/local/bin/bitcoin-cli",
                f"-conf={bitcoin_conf}",
                "getblockchaininfo",
            ],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        j = json.loads(out.decode("utf-8", errors="replace"))
        return {
            "ok": True,
            "blocks": int(j.get("blocks")) if j.get("blocks") is not None else None,
            "headers": int(j.get("headers")) if j.get("headers") is not None else None,
            "ibd": bool(j.get("initialblockdownload")) if j.get("initialblockdownload") is not None else None,
            "verificationprogress": float(j.get("verificationprogress")) if j.get("verificationprogress") is not None else None,
            "warnings": j.get("warnings"),
        }
    except Exception as e:
        logger.log(f"[ERR] get_bitcoind_state failed: {e}")
        return {
            "ok": False,
            "blocks": None,
            "headers": None,
            "ibd": None,
            "verificationprogress": None,
            "warnings": None,
        }
