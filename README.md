# Bitnode Monitor

A comprehensive Bitcoin/Fulcrum/Datum monitoring tool with Telegram bot integration for real-time infrastructure monitoring and alerting.

## Features

- **Bitcoin Node Monitoring**: Track bitcoind block height, sync status, and RPC latency
- **Fulcrum Indexing**: Monitor Fulcrum electrum server indexing progress and speed
- **System Metrics**: CPU, RAM, and SSD temperature monitoring with configurable alerts
- **Telegram Bot Integration**: Interactive commands for status checks and service control
- **Auto-Recovery**: Automatic service restart on detected stalls
- **Speed Tracking**: EMA-based speed calculation with historical analysis
- **Chart Generation**: Visual charts for speed trends and system telemetry
- **Service Control**: Restart bitcoind, Fulcrum, or Datum services via Telegram

## Prerequisites

- Python 3.8 or higher
- systemd-based Linux system
- bitcoind running with RPC enabled
- Fulcrum electrum server (optional)
- Datum gateway (optional)
- Telegram Bot API token
- sudo privileges for service restart functionality

## Installation

### Option 1: Using venv (Recommended)

```bash
# Clone the repository
cd bitnode_monitor

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # On Linux/Mac
# or
.\venv\Scripts\activate  # On Windows

# Install dependencies
pip install -r requirements.txt
```

### Option 2: Using Anaconda

```bash
# Create conda environment
conda create -n bitnode-monitor python=3.11

# Activate environment
conda activate bitnode-monitor

# Install dependencies
pip install -r requirements.txt
```

### Option 3: Using Docker (Recommended for Production)

```bash
# Build the Docker image
docker build -t bitnode-monitor:latest .

# Or use docker-compose
docker-compose up -d
```

## Configuration

1. Copy the example configuration file:
```bash
cp local.env.example local.env
```

2. Edit `local.env` with your settings:

```bash
# Telegram Configuration (Required)
BOT_TOKEN=your_telegram_bot_token_here
CHAT_ID=your_telegram_chat_id_here
ENABLE_TELEGRAM=1

# Bitcoin Configuration
BITCOIN_CONF=/mnt/bitcoin/bitcoind/bitcoin.conf
BITCOIND_SERVICE=bitcoind

# Fulcrum Configuration
FULCRUM_SERVICE=fulcrum

# Datum Configuration (Optional)
DATUM_SERVICE=datum-gateway

# Monitoring Intervals
CHECK_INTERVAL=120s
STALL_THRESHOLD=1800
CHART_INTERVAL=3600

# Alert Thresholds
SSD_TEMP_THRESHOLD=65
CPU_ALERT_THRESHOLD=90
RAM_ALERT_THRESHOLD=90
RPC_LATENCY_THRESHOLD=10

# Auto-Recovery
ENABLE_AUTO_RESTART=1
SPEED_WINDOW=50
```

### Getting a Telegram Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow the instructions
3. Copy the API token provided
4. Get your chat ID by messaging [@userinfobot](https://t.me/userinfobot)

## Usage

### Running Locally

```bash
# Activate your virtual environment first
source venv/bin/activate

# Run the monitor
python fulcrum_monitor.py
```

### Running with Docker

```bash
# Using docker-compose (recommended)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

### Running as a systemd Service

Create `/etc/systemd/system/bitnode-monitor.service`:

```ini
[Unit]
Description=Bitnode Monitor
After=network.target bitcoind.service fulcrum.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/bitnode_monitor
ExecStart=/path/to/bitnode_monitor/venv/bin/python fulcrum_monitor.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable bitnode-monitor
sudo systemctl start bitnode-monitor
```

## Telegram Bot Commands

Once running, you can interact with the bot via Telegram:

- `/status` or `status` - Show complete status (heights, lag, ETA, CPU/RAM)
- `/heights` or `lag` - Show block heights only
- `/speeds` - Show speed and ETA history
  - `/speeds -h 10` - Show first 10 entries
  - `/speeds -t 20` - Show last 20 entries
- `/chart` - Generate and send speed/system telemetry charts
- `/restart fulcrum` - Restart Fulcrum service
- `/restart bitcoind` - Restart bitcoind service
- `/check rpc` - Test bitcoind RPC latency
- `/help` - Show help message

## Project Structure

```
bitnode_monitor/
├── fulcrum_monitor.py          # Main entry point
├── monitor_controller.py       # Core monitoring loop
├── config.py                   # Configuration loader
├── telegram_service.py         # Telegram bot service
├── telegram_client.py          # Telegram API client
├── relay_telegram_client.py    # Relay/tunnel Telegram client
├── node_client.py              # Bitcoin RPC client
├── speed_tracker.py            # Speed calculation (EMA)
├── speed_history.py            # Historical speed analysis
├── eta_model.py                # ETA prediction model
├── status_builder.py           # Status message formatter
├── charts.py                   # Chart generation
├── chart_writer.py             # Chart file writing utilities
├── system_info.py              # System metrics collection
├── system_metrics.py           # System metrics data model
├── system_helpers.py           # System utility helpers
├── service_control.py          # systemd service control
├── bitnode_control.py          # HTTP control server
├── fulcrum_telegram_control.py # Fulcrum Telegram control commands
├── logger_util.py              # Logging utility
├── Dockerfile                  # Docker build configuration
├── docker-compose.yml          # Docker Compose orchestration
├── requirements.txt            # Python dependencies
├── pyproject.toml              # Project metadata and build config
├── local.env.example           # Example configuration template
└── local.env                   # Configuration (not in git)
```

## Monitoring Features

### Stall Detection
Automatically detects when Fulcrum indexing has stalled (no height change for > STALL_THRESHOLD seconds).

### Auto-Recovery
When enabled, automatically restarts stalled services after verifying bitcoind RPC is responsive.

### Speed Tracking
Uses Exponential Moving Average (EMA) to smooth speed calculations and provide accurate ETAs with confidence intervals.

### System Alerts
Monitors and alerts on:
- High CPU usage (>90% default)
- High RAM usage (>90% default)
- High SSD temperature (>65°C default)
- Slow RPC latency (>10s default)
- Datum service failures

## Development

### Installing Development Dependencies

```bash
pip install -e ".[dev]"
```

### Code Formatting

```bash
black *.py
```

### Type Checking

```bash
mypy fulcrum_monitor.py
```

## Troubleshooting

### Bot not responding
- Check `BOT_TOKEN` and `CHAT_ID` in `local.env`
- Verify `ENABLE_TELEGRAM=1`
- Check monitor.log for `[TG]` errors

### Service restart not working
- Ensure user has sudo privileges for systemctl
- Check `FULCRUM_SERVICE` and `BITCOIND_SERVICE` names match actual systemd services
- Review `/etc/sudoers` for NOPASSWD entries

### Charts not generating
- Verify matplotlib and numpy are installed
- Check disk space in working directory
- Review monitor.log for chart generation errors

### High memory usage
- Reduce `SPEED_WINDOW` size
- Increase `CHART_INTERVAL` to generate charts less frequently
- Consider reducing chart resolution in charts.py

## Security Considerations

- The `local.env` file contains sensitive tokens - never commit it to git
- Restrict file permissions: `chmod 600 local.env`
- Use NOPASSWD sudoers entries carefully - limit to specific services
- Consider running in a container for isolation
- Monitor the monitor.log file size - implement log rotation if needed

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## Support

For issues, questions, or contributions, please open an issue on GitHub.
