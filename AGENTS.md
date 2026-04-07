# AI Agent Documentation

This file provides guidance for AI agents (not specific to Claude Code) working with this repository.

## Project Overview

Bitnode Monitor is a comprehensive Bitcoin infrastructure monitoring tool with Telegram bot integration. It monitors Bitcoin Core (bitcoind), Fulcrum electrum server, DATUM gateway, Bitaxe miners, and system resources (CPU/RAM/SSD temp) with real-time alerts and auto-recovery capabilities.

## Development Commands

### Environment Setup
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
.\venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install -e ".[dev]"

# Copy configuration template
cp local.env.example local.env
# Edit local.env with your BOT_TOKEN, CHAT_ID, etc.
```

### Running the Monitor
```bash
# Activate venv first
source venv/bin/activate  # or .\venv\Scripts\activate on Windows

# Run main monitor
python fulcrum_monitor.py
```

### Testing
```bash
# Run unit tests
python -m pytest test_datum_monitor.py -v

# Run with coverage
python -m pytest test_datum_monitor.py --cov=datum_monitor --cov-report=term
```

### Code Quality
```bash
# Format code
black *.py

# Type checking
mypy fulcrum_monitor.py
```

### Docker
```bash
# Build image
docker build -t bitnode-monitor:latest .

# Run with docker-compose
docker-compose up -d
docker-compose logs -f
docker-compose down
```

## Architecture

### Core Components

**Entry Point**: `fulcrum_monitor.py`
- Minimal main() that loads `local.env` and starts `MonitorController`

**Main Controller**: `monitor_controller.py`
- Central orchestration loop running every `CHECK_INTERVAL` seconds
- Coordinates all monitoring subsystems
- Manages Telegram bot lifecycle
- Handles auto-recovery logic for stalled services

**Configuration**: `config.py`
- Loads environment variables from `local.env`
- Parses duration strings (e.g., "120s", "5m", "2h")
- Provides typed configuration object

**Telegram Integration**:
- `telegram_client.py`: Low-level HTTP client for Telegram Bot API (send_text, send_photo)
- `telegram_service.py`: Polling-based command handler with command shortcuts and aliases
- `relay_telegram_client.py`: Relay/tunnel client for remote deployments

### Monitoring Subsystems

**Bitcoin Node**: `node_client.py`
- Uses `bitcoin-cli` wrapper to query bitcoind RPC
- Gets block height, peer count, sync status
- Measures RPC latency for health checks

**Fulcrum Indexing**: Scraped from `journalctl -u fulcrum`
- Extracts current height from log patterns
- Compared against bitcoind height to calculate lag

**DATUM Gateway**: `datum_monitor.py`
- Monitors DATUM mining gateway via `journalctl` logs
- Detects "no job" conditions and zero client connections
- Alert cooldown mechanism to prevent spam
- `check_for_template_errors()`: Detects template fetch failures

**Bitaxe Miner**: `bitaxe_checker.py`
- Polls Bitaxe AxeOS HTTP API at configured IP (default 192.168.68.111)
- Monitors hashrate, temperature, accepted/rejected shares
- Alerts on fallback pool usage, overheating, low hashrate

**System Metrics**: `system_info.py`, `system_metrics.py`
- CPU/RAM usage via `psutil`
- SSD temperature via `smartctl`
- Alert thresholds configurable in `local.env`

### Speed & ETA Calculations

**Speed Tracking**: `speed_tracker.py`
- Uses Exponential Moving Average (EMA) with alpha=0.2
- Maintains sliding window of recent speeds (default 50 samples)
- Calculates standard deviation for confidence intervals

**Historical Analysis**: `speed_history.py`
- Scrapes historical speeds from `monitor.log`
- Provides baseline for ETA predictions

**ETA Model**: `eta_model.py`
- Combines current speed + historical data
- Computes confidence intervals (±2 sigma)
- Formatted by `status_builder.py`

### Charting

**Chart Generation**: `charts.py`, `chart_writer.py`
- Generates speed trend and system telemetry charts
- Uses matplotlib/numpy
- Charts generated on `CHART_INTERVAL` (default 1 hour)
- Sent via Telegram when available

### Service Control

**Service Management**: `service_control.py`
- Wraps `systemctl restart <service>` for bitcoind/fulcrum/datum
- Requires sudo NOPASSWD configured for user
- Used by auto-recovery and Telegram commands

**HTTP Control Server**: `bitnode_control.py`
- Standalone HTTP server for remote control (not used in main monitor loop)

**Telegram Control Bot**: `fulcrum_telegram_control.py`
- Separate bot for updating config remotely (CHECK_INTERVAL, STALL_THRESHOLD, etc.)

## Key Design Patterns

### Alert Deduplication
DATUM and Bitaxe monitors maintain `_last_alert_ts` timestamps to prevent alert spam. Cooldown periods configured via `DATUM_COOLDOWN_SEC`, etc.

### Auto-Recovery Flow
1. Detect stall: Fulcrum height unchanged for > `STALL_THRESHOLD` seconds
2. Verify bitcoind RPC responsive: `check_rpc()` must succeed
3. Restart service: `systemctl restart fulcrum` (requires sudo NOPASSWD)
4. Anti-flap: Min 10 minutes between recovery attempts

### Telegram Command Shortcuts
Commands have aliases (`/h` → `/help`, `/ns` → `/status`) and contextual shortcuts (e.g., typing `/datum` shows `/investigate_datum` shortcut button).

### Logging
All components use `logger_util.Logger` which writes timestamped entries to `monitor.log`. Log format: `[TIMESTAMP] [TAG] message`

## Configuration (`local.env`)

Critical variables:
- `BOT_TOKEN`, `CHAT_ID`: Telegram credentials
- `ENABLE_TELEGRAM=1`: Enable bot
- `ENABLE_AUTO_RESTART=1`: Enable automatic service recovery
- `BITCOIN_CONF`: Path to bitcoin.conf (for RPC credentials)
- `FULCRUM_SERVICE`, `BITCOIND_SERVICE`, `DATUM_SERVICE`: systemd service names
- `CHECK_INTERVAL`: Main loop interval (default 120s)
- `STALL_THRESHOLD`: Seconds before declaring Fulcrum stalled (default 1800s)
- `CHART_INTERVAL`: Chart generation interval (default 3600s)
- Alert thresholds: `SSD_TEMP_THRESHOLD`, `CPU_ALERT_THRESHOLD`, `RAM_ALERT_THRESHOLD`

## Telegram Bot Commands

Main monitor bot:
- `/status` - Current heights, lag, ETA, system stats
- `/mining` - Bitaxe status (hashrate, temp, shares)
- `/datum` - DATUM service status
- `/investigate_datum` - Full diagnostics (systemctl status + journal logs)
- `/check_rpc` - Test bitcoind RPC latency
- `/restart_fulcrum`, `/restart_bitcoind` - Restart services
- `/help` - Command list

Control bot (`fulcrum_telegram_control.py`):
- `/set CHECK_INTERVAL <value>` - Update config remotely

## Testing Notes

`test_datum_monitor.py` contains unit tests for DATUM monitoring features, specifically testing the template error detection added in recent commits. Tests mock `_run()` subprocess calls and verify Telegram alerts are triggered correctly.

## Important Context

- **Bitcoin RPC**: Commands are run as `sudo -u bitcoin /usr/local/bin/bitcoin-cli -conf=/mnt/bitcoin/bitcoind/bitcoin.conf`
- **Fulcrum height scraping**: Uses regex on `journalctl -u fulcrum --since "5 min ago"` to find height in logs
- **DATUM job parsing**: Scrapes journalctl for "job_id", "prev_hash", "client count" patterns
- **Bitaxe API**: HTTP REST API at `http://{BITAXE_IP}/api/system/info` (AxeOS firmware)
- **Platform**: Designed for systemd-based Linux (Raspberry Pi 4 production environment), but core logic is cross-platform
- **Git branch strategy**: Main branch is `main`. Feature branches follow `feature/` prefix.

## Recent Changes

The most recent feature (commit `7fc4f34`) added:
1. Template error monitoring in `datum_monitor.py` via `check_for_template_errors()`
2. Unit tests in `test_datum_monitor.py` covering the new feature

## Deployment

Production runs as systemd service on Raspberry Pi 4. See README.md for systemd unit file template. Service should run after `bitcoind.service` and `fulcrum.service` in dependency order.

## Production Environment & Support

For operational support information including SSH access, service status checks, troubleshooting, and current deployment details, see **[SUPPORT.md](SUPPORT.md)**.
