# Multi-stage build for smaller final image
FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Final stage
FROM python:3.11-slim

# Install runtime dependencies
# - systemd tools (systemctl, journalctl)
# - bitcoin-cli (for RPC calls)
# - smartmontools (for SSD temperature monitoring)
# - procps (for system monitoring)
RUN apt-get update && apt-get install -y --no-install-recommends \
    systemd \
    systemctl \
    curl \
    procps \
    smartmontools \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set up environment
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Create app directory
WORKDIR /app

# Copy application files
COPY *.py ./
COPY local.env.example ./

# Create necessary directories
RUN mkdir -p /app/logs /app/charts

# Create non-root user for running the application
RUN useradd -m -u 1000 bitnode && \
    chown -R bitnode:bitnode /app

# Switch to non-root user
USER bitnode

# Health check
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os; os.path.exists('monitor.log') or exit(1)"

# Run the monitor
CMD ["python", "-u", "fulcrum_monitor.py"]
