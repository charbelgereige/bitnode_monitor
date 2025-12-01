#!/usr/bin/env python3
import subprocess


def restart_fulcrum(fulcrum_service, logger, telegram=None, force=False, enable_auto_restart=False):
    """
    Restart Fulcrum via systemd, with optional Telegram notification.
    """
    if not force and not enable_auto_restart:
        logger.log("[STALL] Auto-restart disabled (ENABLE_AUTO_RESTART=0). Not restarting fulcrum.")
        if telegram:
            telegram.send_text("⚠️ Stall detected but auto-restart is disabled.")
        return
    try:
        logger.log("[RECOVERY] Restarting fulcrum via systemctl...")
        subprocess.check_call(["sudo", "systemctl", "restart", fulcrum_service])
        logger.log("[RECOVERY] fulcrum restart triggered.")
        if telegram:
            telegram.send_text("♻️ Fulcrum restart triggered.")
    except Exception as e:
        logger.log(f"[ERR] Failed to restart fulcrum: {e}")
        if telegram:
            telegram.send_text(f"❌ Failed to restart fulcrum: {e}")


def restart_bitcoind(bitcoind_service, logger, telegram=None):
    """
    Restart bitcoind via systemd, with optional Telegram notification.
    """
    try:
        logger.log("[ADMIN] Restarting bitcoind via systemctl...")
        subprocess.check_call(["sudo", "systemctl", "restart", bitcoind_service])
        logger.log("[ADMIN] bitcoind restart triggered.")
        if telegram:
            telegram.send_text("♻️ bitcoind restart triggered.")
    except Exception as e:
        logger.log(f"[ERR] Failed to restart bitcoind: {e}")
        if telegram:
            telegram.send_text(f"❌ Failed to restart bitcoind: {e}")
