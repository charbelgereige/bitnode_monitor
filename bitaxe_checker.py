#!/usr/bin/env python3
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests


@dataclass
class BitaxeSnapshot:
    ok: bool
    ts: float
    hash_rate_hs: Optional[float] = None
    shares_accepted: Optional[int] = None
    shares_rejected: Optional[int] = None
    is_using_fallback: Optional[int] = None
    primary: Optional[str] = None
    fallback: Optional[str] = None
    temp_c: Optional[float] = None
    voltage_mv: Optional[float] = None
    power_w: Optional[float] = None
    raw_error: Optional[str] = None


class BitaxeChecker:
    """
    Polls AxeOS endpoint and generates:
      - URGENT: "not mining at all" (no accepted shares for X seconds OR hashrate too low)
      - WARNING: mining on fallback (isUsingFallbackStratum == 1)
    """

    def __init__(
        self,
        base_url: str,
        logger,
        telegram_client=None,
        timeout_sec: float = 3.0,
        min_hashrate_hs: float = 50.0,   # treat below as "not mining"
        no_share_sec: int = 900,         # urgent if no accepted shares change for this long
        alert_cooldown_sec: int = 300,   # avoid spamming
    ):
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.tg = telegram_client
        self.timeout_sec = timeout_sec

        self.min_hashrate_hs = float(min_hashrate_hs)
        self.no_share_sec = int(no_share_sec)
        self.alert_cooldown_sec = int(alert_cooldown_sec)

        self._last_snapshot: Optional[BitaxeSnapshot] = None
        self._last_accept_change_ts: Optional[float] = None
        self._last_urgent_ts: float = 0.0
        self._last_fallback_ts: float = 0.0
        self._last_pool_state: Optional[int] = None  # Track previous fallback state (0=primary, 1=fallback)
        self._fallback_state_change_ts: float = 0.0  # When did we last change pool state
        self._last_daily_summary_ts: float = 0.0  # Last time we sent daily summary

        # Flapping detection: track recent state changes to detect unstable pool switching
        self._state_change_history: list = []  # List of (timestamp, state) tuples
        self._flapping_detected: bool = False
        self._flapping_alert_sent_ts: float = 0.0
        self._flap_threshold: int = 4  # Number of state changes to consider flapping
        self._flap_window_sec: int = 300  # Time window (5 minutes) to detect flapping
        self._flap_cooldown_sec: int = 3600  # Once flapping, only re-alert after 1 hour

    def _fetch(self) -> BitaxeSnapshot:
        url = f"{self.base_url}/api/system/info"
        ts = time.time()
        try:
            r = requests.get(url, timeout=self.timeout_sec)
            r.raise_for_status()
            j = r.json()

            primary = f'{j.get("stratumURL")}:{j.get("stratumPort")}'
            fallback = f'{j.get("fallbackStratumURL")}:{j.get("fallbackStratumPort")}'

            return BitaxeSnapshot(
                ok=True,
                ts=ts,
                hash_rate_hs=float(j.get("hashRate")) if j.get("hashRate") is not None else None,
                shares_accepted=int(j.get("sharesAccepted")) if j.get("sharesAccepted") is not None else None,
                shares_rejected=int(j.get("sharesRejected")) if j.get("sharesRejected") is not None else None,
                is_using_fallback=int(j.get("isUsingFallbackStratum")) if j.get("isUsingFallbackStratum") is not None else None,
                primary=primary,
                fallback=fallback,
                temp_c=float(j.get("temp")) if j.get("temp") is not None else None,
                voltage_mv=float(j.get("voltage")) if j.get("voltage") is not None else None,
                power_w=float(j.get("power")) if j.get("power") is not None else None,
            )
        except Exception as e:
            return BitaxeSnapshot(ok=False, ts=ts, raw_error=str(e))

    def _send(self, msg: str) -> None:
        self.logger.log(msg)
        if self.tg:
            try:
                self.tg.send_text(msg)
            except Exception:
                pass

    def get_pool_status_line(self) -> str:
        """
        Returns a one-line summary of current pool status.
        Example: "⛏️ Mining on PRIMARY (stratum.ocean.xyz:3334)"
        """
        if not self._last_snapshot or not self._last_snapshot.ok:
            return "⛏️ Pool: Unknown (cannot reach miner)"

        snap = self._last_snapshot
        if snap.is_using_fallback == 1:
            return f"⛏️ Mining on FALLBACK ({snap.fallback})"
        elif snap.is_using_fallback == 0:
            return f"⛏️ Mining on PRIMARY ({snap.primary})"
        else:
            return "⛏️ Pool: Unknown"

    def maybe_send_daily_summary(self) -> None:
        """
        Send a daily summary of pool status (call this once per tick).
        """
        now = time.time()
        # Send once per day (86400 seconds)
        if (now - self._last_daily_summary_ts) >= 86400:
            if self._last_snapshot and self._last_snapshot.ok:
                snap = self._last_snapshot
                pool_info = self.get_pool_status_line()

                # Calculate uptime since last state change
                if self._fallback_state_change_ts > 0:
                    state_age = now - self._fallback_state_change_ts
                    if state_age < 3600:
                        age_str = f"{int(state_age / 60)}m"
                    elif state_age < 86400:
                        age_str = f"{state_age / 3600:.1f}h"
                    else:
                        age_str = f"{state_age / 86400:.1f}d"
                    stability = f" (stable for {age_str})"
                else:
                    stability = ""

                summary = (
                    f"[BITAXE] 📊 Daily Summary\n"
                    f"{pool_info}{stability}\n"
                    f"Hashrate: {snap.hash_rate_hs:.0f}H/s\n"
                    f"Shares: {snap.shares_accepted} accepted, {snap.shares_rejected} rejected\n"
                    f"Temp: {snap.temp_c}°C | Power: {snap.power_w}W"
                )
                self._send(summary)
            self._last_daily_summary_ts = now

    def tick(self) -> Tuple[Optional[BitaxeSnapshot], Optional[str]]:
        """
        Call periodically. Returns (snapshot, alert_msg_sent_or_None)
        """
        snap = self._fetch()
        alert_msg: Optional[str] = None

        # Update "last accepted share change" timestamp
        if snap.ok and snap.shares_accepted is not None:
            if (
                self._last_snapshot
                and self._last_snapshot.ok
                and self._last_snapshot.shares_accepted is not None
                and snap.shares_accepted != self._last_snapshot.shares_accepted
            ):
                self._last_accept_change_ts = snap.ts
            elif self._last_accept_change_ts is None:
                self._last_accept_change_ts = snap.ts

        # WARNING: pool state change detection (primary ↔ fallback) with flapping detection
        if snap.ok and snap.is_using_fallback is not None:
            # Detect state changes
            if self._last_pool_state is not None and self._last_pool_state != snap.is_using_fallback:
                # State changed! Record it
                self._state_change_history.append((snap.ts, snap.is_using_fallback))
                self._fallback_state_change_ts = snap.ts

                # Clean up old history outside the flap window
                cutoff = snap.ts - self._flap_window_sec
                self._state_change_history = [(ts, state) for ts, state in self._state_change_history if ts > cutoff]

                # Check if we're flapping (multiple rapid state changes)
                if len(self._state_change_history) >= self._flap_threshold:
                    # Flapping detected!
                    if not self._flapping_detected:
                        # First time detecting flap - send alert ONCE
                        self._flapping_detected = True
                        flap_count = len(self._state_change_history)
                        window_min = self._flap_window_sec / 60
                        alert_msg = (
                            f"[BITAXE] 🔄 Pool FLAPPING detected!\n"
                            f"Switched {flap_count} times in {window_min:.0f} minutes.\n"
                            f"Primary: {snap.primary}\n"
                            f"Fallback: {snap.fallback}\n"
                            f"Currently on: {'FALLBACK' if snap.is_using_fallback == 1 else 'PRIMARY'}\n"
                            f"This usually means the primary pool is unreachable.\n"
                            f"No further alerts until pool stabilizes."
                        )
                        self._send(alert_msg)
                        self._flapping_alert_sent_ts = snap.ts
                    # Remove the hourly reminder - it's just noise
                else:
                    # Normal state change (not flapping)
                    if not self._flapping_detected:
                        # Send individual state change alert
                        if snap.is_using_fallback == 1:
                            alert_msg = (
                                f"[BITAXE] ⚠️ Switched to FALLBACK pool.\n"
                                f"Primary: {snap.primary}\n"
                                f"Fallback: {snap.fallback}\n"
                                f"Status: hr={snap.hash_rate_hs:.0f}H/s acc={snap.shares_accepted} rej={snap.shares_rejected}"
                            )
                        else:
                            alert_msg = (
                                f"[BITAXE] ✅ Restored to PRIMARY pool.\n"
                                f"Primary: {snap.primary}\n"
                                f"Status: hr={snap.hash_rate_hs:.0f}H/s acc={snap.shares_accepted} rej={snap.shares_rejected}"
                            )
                        self._send(alert_msg)

            # Check if flapping has stopped (no changes in flap window)
            if self._flapping_detected and len(self._state_change_history) < 2:
                # Stabilized! Send recovery alert
                self._flapping_detected = False
                alert_msg = (
                    f"[BITAXE] ✅ Pool STABLE - flapping resolved.\n"
                    f"Now mining on: {'FALLBACK' if snap.is_using_fallback == 1 else 'PRIMARY'}\n"
                    f"Status: hr={snap.hash_rate_hs:.0f}H/s acc={snap.shares_accepted} rej={snap.shares_rejected}"
                )
                self._send(alert_msg)
                self._state_change_history.clear()

            # Update tracked state
            self._last_pool_state = snap.is_using_fallback

        # URGENT: not mining at all
        if snap.ok:
            hr_low = (snap.hash_rate_hs is None) or (snap.hash_rate_hs < self.min_hashrate_hs)
            no_share_progress = (
                self._last_accept_change_ts is not None
                and (snap.ts - self._last_accept_change_ts) >= self.no_share_sec
            )

            if hr_low or no_share_progress:
                if (snap.ts - self._last_urgent_ts) >= self.alert_cooldown_sec:
                    reasons = []
                    if hr_low:
                        reasons.append(f"hashrate<{self.min_hashrate_hs:.0f}H/s (hr={snap.hash_rate_hs})")
                    if no_share_progress:
                        reasons.append(f"no accepted shares for ≥{self.no_share_sec}s")

                    alert_msg = (
                        f"[BITAXE] 🚨 URGENT: miner not progressing ({'; '.join(reasons)}).\n"
                        f"useFallback={snap.is_using_fallback} primary={snap.primary} fallback={snap.fallback}\n"
                        f"acc={snap.shares_accepted} rej={snap.shares_rejected} temp={snap.temp_c}C power={snap.power_w}W"
                    )
                    self._send(alert_msg)
                    self._last_urgent_ts = snap.ts
        else:
            if (snap.ts - self._last_urgent_ts) >= self.alert_cooldown_sec:
                alert_msg = f"[BITAXE] 🚨 URGENT: cannot reach AxeOS at {self.base_url} ({snap.raw_error})."
                self._send(alert_msg)
                self._last_urgent_ts = snap.ts

        self._last_snapshot = snap

        # Send daily summary if it's time
        self.maybe_send_daily_summary()

        return snap, alert_msg
