# Support Documentation

This file contains operational support information for the bitnode_monitor deployment.

## Production Environment

### Host Information
- **Hostname**: `knots00`
- **SSH Access**: `ssh charb@knots00`
- **Platform**: Raspberry Pi 4
- **OS**: Linux knots00 6.12.47+rpt-rpi-v8 (Debian-based, aarch64)
- **Location**: Home network

### Network Configuration
- **Bitaxe Miner IP**: `192.168.68.111`
- **Bitcoin RPC**: `127.0.0.1:8332` (local)
- **Fulcrum**: Running locally on knots00

## Service Status Checks

### Check All Services
```bash
ssh charb@knots00 "systemctl status bitcoind fulcrum datum-gateway"
```

### Individual Service Status
```bash
# Bitcoin Knots node
ssh charb@knots00 "systemctl status bitcoind"

# Fulcrum Electrum server
ssh charb@knots00 "systemctl status fulcrum"

# DATUM Gateway
ssh charb@knots00 "systemctl status datum-gateway"

# Bitnode monitor (check if running)
ssh charb@knots00 "ps aux | grep -E '(fulcrum_monitor|bitnode)' | grep -v grep"
```

### Monitor Logs
```bash
# View monitor log
ssh charb@knots00 "tail -f /home/charb/fulcrum-bot/monitor.log"

# View bitcoind logs
ssh charb@knots00 "sudo journalctl -u bitcoind -f"

# View fulcrum logs
ssh charb@knots00 "sudo journalctl -u fulcrum -f"

# View datum-gateway logs
ssh charb@knots00 "sudo journalctl -u datum-gateway -f"
```

### Bitaxe Miner

#### Check Bitaxe Status
```bash
ssh charb@knots00 "curl -s http://192.168.68.111/api/system/info | jq '{hashRate,temp,power,sharesAccepted,sharesRejected}'"
```

#### Restart Bitaxe
```bash
ssh charb@knots00 "curl -X POST http://192.168.68.111/api/system/restart"
```

#### Adjust Fan Speed
```bash
ssh charb@knots00 "curl -X PATCH http://192.168.68.111/api/system -H 'Content-Type: application/json' -d '{\"fanspeed\":80}'"
```

## Service Management

### Restart Services
```bash
# Restart bitcoind
ssh charb@knots00 "sudo systemctl restart bitcoind"

# Restart fulcrum
ssh charb@knots00 "sudo systemctl restart fulcrum"

# Restart datum-gateway
ssh charb@knots00 "sudo systemctl restart datum-gateway"

# Restart monitor (if running as systemd service)
ssh charb@knots00 "sudo systemctl restart bitnode-monitor"
```

### Service Logs with Time Range
```bash
# Last 10 minutes
ssh charb@knots00 "sudo journalctl -u bitcoind --since '10 min ago'"

# Last hour
ssh charb@knots00 "sudo journalctl -u fulcrum --since '1 hour ago'"

# Specific date
ssh charb@knots00 "sudo journalctl -u datum-gateway --since '2026-04-07 10:00:00'"
```

## Bitcoin RPC Commands

```bash
# Get blockchain info
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getblockchaininfo"

# Get block count
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getblockcount"

# Get peer info
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getpeerinfo | jq 'length'"

# Get network info
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getnetworkinfo"
```

## Troubleshooting

### Monitor Not Running
```bash
# Check if monitor process exists
ssh charb@knots00 "ps aux | grep fulcrum_monitor"

# Check monitor log for errors
ssh charb@knots00 "tail -100 /home/charb/fulcrum-bot/monitor.log | grep ERROR"

# Restart monitor manually
ssh charb@knots00 "cd /home/charb/fulcrum-bot && source venv/bin/activate && python fulcrum_monitor.py"
```

### DATUM Template Fetch Errors
The DATUM gateway occasionally shows `ERROR: Could not fetch new template from http://127.0.0.1:8332!` errors. This is usually temporary and recovers automatically. If persistent:

```bash
# Check bitcoind RPC is responsive
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getblockcount"

# Check bitcoind is not overloaded
ssh charb@knots00 "sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf getnetworkinfo"

# Restart datum-gateway if needed
ssh charb@knots00 "sudo systemctl restart datum-gateway"
```

### Fulcrum Stalled
```bash
# Check current fulcrum height vs bitcoind
ssh charb@knots00 "sudo journalctl -u fulcrum --since '5 min ago' | tail -20"

# Monitor will auto-restart if ENABLE_AUTO_RESTART=1 in local.env
# Or manually restart
ssh charb@knots00 "sudo systemctl restart fulcrum"
```

### Bitaxe Not Responding
```bash
# Check network connectivity
ssh charb@knots00 "ping -c 3 192.168.68.111"

# Check if Bitaxe web interface is up
ssh charb@knots00 "curl -I http://192.168.68.111"

# Power cycle Bitaxe if necessary (physical access required)
```

## System Health

### Check System Resources
```bash
# CPU/RAM/Disk
ssh charb@knots00 "top -bn1 | head -20"

# Disk usage
ssh charb@knots00 "df -h"

# SSD temperature
ssh charb@knots00 "sudo smartctl -A /dev/sda | grep Temperature"

# System temperature
ssh charb@knots00 "vcgencmd measure_temp"
```

## File Locations

- **Monitor Directory**: `/home/charb/fulcrum-bot/`
- **Monitor Log**: `/home/charb/fulcrum-bot/monitor.log`
- **Configuration**: `/home/charb/fulcrum-bot/local.env`
- **Bitcoin Config**: `/mnt/bitcoin/bitcoind/bitcoin.conf`
- **Fulcrum Config**: `/etc/fulcrum.conf`
- **DATUM Config**: `/etc/datum/datum_gateway_config.json`

## Deployment Process

### Deploying Code Updates

When updating code on the Pi:

```bash
# From local repository
scp "C:/Users/charb/Downloads/git/bitnode_monitor/<file>.py" charb@knots00:/home/charb/fulcrum-bot/<file>.py

# Or use git (if repository is cloned on Pi)
ssh charb@knots00 "cd /home/charb/fulcrum-bot && git pull"

# Restart the service
ssh charb@knots00 "sudo systemctl restart bitnode-monitor"

# Verify service is running
ssh charb@knots00 "systemctl status bitnode-monitor"

# Check logs for errors
ssh charb@knots00 "tail -50 /home/charb/fulcrum-bot/monitor.log"
```

### Recent Deployments

**2026-04-07**: Fixed `datum_monitor.py` missing `__init__` method
- Issue: Service was crash-looping with `TypeError: DatumMonitor() takes no arguments`
- Solution: Deployed updated `datum_monitor.py` from repository
- Result: Service now running successfully

## Current Status (as of 2026-04-07 11:41)

### Services Running
- ✅ **bitcoind**: Active (running), block height 944025
- ✅ **fulcrum**: Active (running), syncing
- ✅ **datum-gateway**: Active (running)
- ✅ **bitnode-monitor**: Active (running), PID 4455

### Configuration
- CHECK_INTERVAL: 300s (5 minutes)
- STALL_THRESHOLD: 7200s (2 hours)
- ENABLE_AUTO_RESTART: False
- Bitaxe monitoring enabled (IP: 192.168.68.102)

### Known Issues
- DATUM gateway shows intermittent template fetch errors (normal behavior, recovers automatically)
- Initial startup shows "[WARN] Could not read heights" - this is normal and clears after first check cycle
