# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Documentation Structure

For comprehensive project documentation, architecture, and development commands, see **[AGENTS.md](AGENTS.md)**.

For production environment details, SSH access, service status checks, and troubleshooting, see **[SUPPORT.md](SUPPORT.md)**.

## Claude Code Specific Notes

### Working with the Production Environment

**SSH Access**: The production Pi is accessible at `ssh charb@knots00` (NOT the aiiq-legal-00 hostname).

When checking service status or debugging issues on the production environment:
```bash
# Correct hostname
ssh charb@knots00 "systemctl status bitcoind fulcrum datum-gateway"

# Monitor logs
ssh charb@knots00 "tail -f /home/charb/fulcrum-bot/monitor.log"
```

### Common Tasks

**Checking Production Status**:
```bash
ssh charb@knots00 "ps aux | grep fulcrum_monitor"
ssh charb@knots00 "systemctl status bitcoind fulcrum datum-gateway"
```

**Viewing Logs**:
```bash
ssh charb@knots00 "tail -100 /home/charb/fulcrum-bot/monitor.log"
ssh charb@knots00 "sudo journalctl -u bitcoind -n 50"
```

**Bitcoin RPC**:
```bash
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getblockcount"
```

### File Editing Workflow

When making changes to code that needs to be deployed:
1. Edit files locally in this repository
2. Test locally if possible
3. Deploy to production via git pull or scp
4. Restart the monitor service on knots00

### Testing

Run unit tests before committing:
```bash
python -m pytest test_datum_monitor.py -v
```

### Code Style

Use black for formatting:
```bash
black *.py
```

## Quick Reference

- **Production Host**: knots00
- **Monitor Directory**: /home/charb/fulcrum-bot/
- **Monitor Log**: /home/charb/fulcrum-bot/monitor.log
- **Config File**: /home/charb/fulcrum-bot/local.env
- **Bitaxe IP**: 192.168.68.102
- **Main Branch**: main
- **Feature Branches**: feature/*
