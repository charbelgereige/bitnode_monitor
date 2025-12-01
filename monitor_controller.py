#!/usr/bin/env python3
import time
import os
from pathlib import Path

from logger_util import Logger
from speed_tracker import SpeedTracker
from system_info import (
    parse_duration,
    get_bitcoind_height,
    get_fulcrum_height,
    get_system_stats,
    get_ssd_temp,
)
from charts import write_speed_chart, write_system_chart
from service_control import restart_fulcrum, restart_bitcoind
from status_builder import build_status_text
from telegram_service import TelegramService


class MonitorController:
    def __init__(self):
        base_dir = Path(__file__).resolve().parent
        self.base_dir = base_dir
        self.log_file = base_dir / "monitor.log"
        self.speed_chart_file = base_dir / "speed_chart.png"
        self.system_chart_file = base_dir / "system_chart.png"

        self.logger = Logger(self.log_file)

        # Config from env (already loaded in fulcrum_monitor.py)
        self.bitcoin_conf = os.getenv("BITCOIN_CONF", "/mnt/bitcoin/bitcoind/bitcoin.conf")
        self.fulcrum_service = os.getenv("FULCRUM_SERVICE", "fulcrum")
        self.bitcoind_service = os.getenv("BITCOIND_SERVICE", "bitcoind")

        self.check_interval = parse_duration(os.getenv("CHECK_INTERVAL", "120"), 120)
        self.stall_threshold = parse_duration(os.getenv("STALL_THRESHOLD", "1800"), 1800)
        self.speed_window = int(os.getenv("SPEED_WINDOW", "50"))

        self.ssd_temp_threshold = float(os.getenv("SSD_TEMP_THRESHOLD", "65"))
        self.cpu_alert_threshold = float(os.getenv("CPU_ALERT_THRESHOLD", "90"))
        self.ram_alert_threshold = float(os.getenv("RAM_ALERT_THRESHOLD", "90"))
        self.chart_interval = parse_duration(os.getenv("CHART_INTERVAL", "3600"), 3600)

        self.enable_auto_restart = os.getenv("ENABLE_AUTO_RESTART", "0") == "1"
        self.rpc_latency_threshold = float(os.getenv("RPC_LATENCY_THRESHOLD", "10"))  # seconds

        self.bot_token = os.getenv("BOT_TOKEN")
        self.chat_id = os.getenv("CHAT_ID")
        self.enable_telegram = os.getenv("ENABLE_TELEGRAM", "0") == "1"

        self.speed_tracker = SpeedTracker(window=self.speed_window)

        # State
        self.last_height_change_time = None
        self.last_fulcrum_height = None
        self.last_logged_height = None
        self.last_chart_time = 0
        self.last_recovery_time = 0
        self.min_recovery_interval = 600  # 10 min
        self.stall_notified = False

        # Telegram service
        self.telegram_service = None
        if self.enable_telegram and self.bot_token and self.chat_id:
            callbacks = {
                "status_text": self.get_status_text,
                "restart_fulcrum": self.restart_fulcrum_manual,
                "restart_bitcoind": self.restart_bitcoind_manual,
                "check_rpc": self.check_rpc,
            }
            self.telegram_service = TelegramService(
                self.bot_token,
                self.chat_id,
                self.logger,
                self.speed_chart_file,
                self.system_chart_file,
                callbacks,
            )

    # ----- Callbacks for Telegram -----

    def get_status_text(self):
        return build_status_text(self.bitcoin_conf, self.fulcrum_service, self.speed_tracker, self.logger)

    def restart_fulcrum_manual(self):
        restart_fulcrum(
            self.fulcrum_service,
            self.logger,
            telegram=self.telegram_service.client if self.telegram_service else None,
            force=True,
            enable_auto_restart=True,
        )

    def restart_bitcoind_manual(self):
        restart_bitcoind(
            self.bitcoind_service,
            self.logger,
            telegram=self.telegram_service.client if self.telegram_service else None,
        )

    def check_rpc(self):
        start = time.time()
        h = get_bitcoind_height(self.bitcoin_conf, self.logger)
        elapsed = time.time() - start
        if h is None:
            return "❌ bitcoind RPC failed."
        return f"✅ bitcoind RPC ok. Height={h}, latency={elapsed:.2f}s"

    # ----- Telegram startup -----

    def maybe_start_telegram(self):
        if self.telegram_service:
            self.telegram_service.start()
        else:
            self.logger.log("[MAIN] Telegram disabled or missing BOT_TOKEN/CHAT_ID.")

    # ----- Main monitor loop -----

    def run(self):
        self.logger.log("========== Fulcrum monitor starting ==========")
        self.logger.log(f"BITCOIN_CONF={self.bitcoin_conf}")
        self.logger.log(f"CHECK_INTERVAL={self.check_interval}s, STALL_THRESHOLD={self.stall_threshold}s")
        self.logger.log(
            f"SSD_TEMP_THRESHOLD={self.ssd_temp_threshold}°C, "
            f"CPU_ALERT={self.cpu_alert_threshold}%, RAM_ALERT={self.ram_alert_threshold}%"
        )
        self.logger.log(f"Charts every {self.chart_interval}s (approx).")
        self.logger.log(f"ENABLE_AUTO_RESTART={self.enable_auto_restart}, "
                        f"RPC_LATENCY_THRESHOLD={self.rpc_latency_threshold}s")

        while True:
            loop_start = time.time()

            btc_height = get_bitcoind_height(self.bitcoin_conf, self.logger)
            ful_height = get_fulcrum_height(self.fulcrum_service, self.logger)

            if btc_height is None or ful_height is None:
                self.logger.log("[WARN] Could not read heights (bitcoind or fulcrum).")
            else:
                # Only treat as new datapoint when Fulcrum height actually advances
                if self.last_fulcrum_height is None or ful_height != self.last_fulcrum_height:
                    self.speed_tracker.update(ful_height)
                    ema_speed, stdev = self.speed_tracker.get_stats()
                    lag = btc_height - ful_height

                    if ema_speed is not None and ema_speed > 0:
                        eta_sec = lag / ema_speed
                        eta_hours = eta_sec / 3600.0
                        eta_str = f"{eta_hours:.2f} h"
                    else:
                        eta_str = "N/A"
                    speed_str = f"{ema_speed:.3f}" if ema_speed is not None else "N/A"
                    stdev_str = f"{stdev:.3f}" if stdev is not None else "N/A"

                    # Only log when Fulcrum height changed (no spam on stale data)
                    if ful_height != self.last_logged_height:
                        self.logger.log(
                            f"Heights: bitcoind={btc_height}, fulcrum={ful_height}, "
                            f"lag={lag} blocks, speed~={speed_str} blk/s (σ={stdev_str}), ETA={eta_str}"
                        )
                        self.last_logged_height = ful_height

                    self.last_fulcrum_height = ful_height
                    self.last_height_change_time = loop_start
                    self.stall_notified = False

                else:
                    # Fulcrum height unchanged
                    if self.last_height_change_time is not None:
                        stalled_for = loop_start - self.last_height_change_time
                        if stalled_for > self.stall_threshold and not self.stall_notified:
                            lag = btc_height - ful_height
                            self.logger.log(
                                f"[STALL] Fulcrum height unchanged at {ful_height} for "
                                f"{stalled_for:.0f}s (> {self.stall_threshold}s). Lag={lag} blocks."
                            )
                            # Telegram notification
                            if self.telegram_service and self.telegram_service.client:
                                self.telegram_service.client.send_text(
                                    f"⚠️ Fulcrum stall suspected: height={ful_height}, "
                                    f"stalled for {stalled_for:.0f}s, lag≈{lag} blocks."
                                )

                            # Auto-restart path with bitcoind health gate
                            now = loop_start
                            if self.enable_auto_restart and (now - self.last_recovery_time > self.min_recovery_interval):
                                t0 = time.time()
                                test_height = get_bitcoind_height(self.bitcoin_conf, self.logger)
                                rpc_latency = time.time() - t0

                                if test_height is None or rpc_latency > self.rpc_latency_threshold:
                                    msg = (
                                        "[STALL] Skipping auto-restart: bitcoind RPC unhealthy or slow "
                                        f"(latency={rpc_latency:.2f}s, threshold={self.rpc_latency_threshold:.2f}s)."
                                    )
                                    self.logger.log(msg)
                                    if self.telegram_service and self.telegram_service.client:
                                        self.telegram_service.client.send_text("⚠️ " + msg)
                                else:
                                    restart_fulcrum(
                                        self.fulcrum_service,
                                        self.logger,
                                        telegram=self.telegram_service.client if self.telegram_service else None,
                                        force=False,
                                        enable_auto_restart=self.enable_auto_restart,
                                    )
                                    self.last_recovery_time = now

                            self.stall_notified = True

            # System stats
            cpu_pct, ram_pct = get_system_stats(self.logger)
            ssd_temp = get_ssd_temp(self.logger)

            if cpu_pct is not None and cpu_pct > self.cpu_alert_threshold:
                msg = f"[ALERT] CPU high load: {cpu_pct:.1f}%"
                self.logger.log(msg)
                if self.telegram_service and self.telegram_service.client:
                    self.telegram_service.client.send_text(f"🔥 {msg}")

            if ram_pct is not None and ram_pct > self.ram_alert_threshold:
                msg = f"[ALERT] RAM high usage: {ram_pct:.1f}%"
                self.logger.log(msg)
                if self.telegram_service and self.telegram_service.client:
                    self.telegram_service.client.send_text(f"💾 {msg}")

            if ssd_temp is not None and ssd_temp > self.ssd_temp_threshold:
                msg = f"[ALERT] SSD temperature high: {ssd_temp:.1f}°C"
                self.logger.log(msg)
                if self.telegram_service and self.telegram_service.client:
                    self.telegram_service.client.send_text(f"🌡 {msg}")

            # Charts
            now = time.time()
            if now - self.last_chart_time > self.chart_interval:
                if self.speed_tracker.samples:
                    write_speed_chart(self.speed_tracker, self.speed_chart_file, self.logger)
                if cpu_pct is not None and ram_pct is not None:
                    write_system_chart(cpu_pct, ram_pct, ssd_temp, self.system_chart_file, self.logger)
                self.last_chart_time = now

            # Sleep until next interval
            elapsed = time.time() - loop_start
            remaining = self.check_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
