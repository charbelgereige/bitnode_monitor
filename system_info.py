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
            timeout=15,
        )
        return int(out.strip())
    except subprocess.TimeoutExpired:
        # During IBD, RPC can be slow - this is expected, don't log as error
        ibd_state = get_bitcoind_state(bitcoin_conf, logger)
        if ibd_state.get("ibd"):
            # Suppress error during IBD - just return None silently
            return None
        logger.log(f"[WARN] get_bitcoind_height timed out (not in IBD)")
        return None
    except subprocess.CalledProcessError as e:
        # RPC errors during IBD are expected when bitcoind is busy
        ibd_state = get_bitcoind_state(bitcoin_conf, logger)
        if ibd_state.get("ibd"):
            return None  # Suppress during IBD
        logger.log(f"[ERR] get_bitcoind_height failed: {e}")
        return None
    except Exception as e:
        logger.log(f"[ERR] get_bitcoind_height failed: {e}")
        return None


def get_fulcrum_height(fulcrum_service: str, logger):
    """
    Parse last 'Block height XXXX' from fulcrum journald logs.
    """
    try:
        out = subprocess.check_output(
            ["sudo", "journalctl", "-u", fulcrum_service, "--no-pager"],
            stderr=subprocess.DEVNULL,
        ).decode()
        import re
        matches = re.findall(r"Block height\s*([0-9]+)", out)
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

    Falls back to reading debug.log if RPC is unavailable.
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
        # Fallback: try to read from bitcoind debug.log
        try:
            import re
            log_path = Path("/mnt/bitcoin/bitcoind/debug.log")
            if log_path.exists():
                # Read last 500 lines
                with log_path.open() as f:
                    lines = f.readlines()[-500:]

                # Look for progress indicators
                blocks = None
                headers = None
                progress = None
                ibd = None

                for line in reversed(lines):
                    # Example: UpdateTip: new best=... height=948285
                    if "UpdateTip:" in line and "height=" in line:
                        m = re.search(r'height=(\d+)', line)
                        if m and blocks is None:
                            blocks = int(m.group(1))

                    # Example: Progress: 99.72% (headers=949342, synced to=948285)
                    if "Progress:" in line:
                        m_pct = re.search(r'Progress:\s*([0-9.]+)%', line)
                        m_headers = re.search(r'headers=(\d+)', line)
                        if m_pct:
                            progress = float(m_pct.group(1)) / 100.0
                        if m_headers:
                            headers = int(m_headers.group(1))

                    # Check for IBD completion message
                    if "Leaving InitialBlockDownload" in line:
                        ibd = False
                        break

                # If we found progress data, assume still in IBD if < 99.99%
                if progress is not None and progress < 0.9999:
                    ibd = True
                elif progress is not None:
                    ibd = False

                if blocks or headers or progress is not None:
                    logger.log(f"[INFO] Using fallback log parsing (RPC unavailable): blocks={blocks}, headers={headers}, progress={progress}")
                    return {
                        "ok": True,
                        "blocks": blocks,
                        "headers": headers,
                        "ibd": ibd,
                        "verificationprogress": progress,
                        "warnings": None,
                    }
        except Exception as log_err:
            logger.log(f"[WARN] Fallback log parsing also failed: {log_err}")

        # Both RPC and log parsing failed
        logger.log(f"[ERR] get_bitcoind_state failed: {e}")
        return {
            "ok": False,
            "blocks": None,
            "headers": None,
            "ibd": None,
            "verificationprogress": None,
            "warnings": None,
        }
