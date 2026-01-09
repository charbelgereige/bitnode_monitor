#!/usr/bin/env python3
"""
Enhanced status builder for Bitnode / Fulcrum monitor.
"""

from pathlib import Path
import re
import subprocess
import psutil


def _strip_prefix(line):
    """Strip leading '[timestamp] ' prefix and return (timestamp, content)."""
    if not line:
        return None, None
    s = line.strip()
    if '] ' in s:
        parts = s.split('] ', 1)
        timestamp = parts[0].replace('[', '')
        return timestamp, parts[1]
    return None, s


def _extract_last_heights_lines(log_path: Path):
    last_any = None
    last_num = None
    try:
        with log_path.open() as f:
            for line in f:
                if 'Heights:' not in line:
                    continue
                last_any = line
                has_speed = re.search(r'speed~=([0-9.]+)', line)
                has_eta   = re.search(r'ETA=([0-9.]+)',   line)
                if has_speed and has_eta:
                    last_num = line
    except FileNotFoundError:
        pass
    return last_any, last_num


def _extract_alert_lines(log_path: Path, max_lines=10):
    alerts = []
    try:
        with log_path.open() as f:
            for line in f:
                if '[ALERT]' in line:
                    ts, content = _strip_prefix(line)
                    if content:
                        alerts.append((ts, content))
    except FileNotFoundError:
        return []
    return alerts[-max_lines:]


def _get_datum_status():
    try:
        result = subprocess.run(['systemctl', 'is-active', 'datum-gateway'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=3)
        return result.stdout.strip() == 'active'
    except Exception:
        return None


def _get_ssd_temp():
    hwmon_dir = Path('/sys/class/hwmon')
    if hwmon_dir.exists():
        for hw in hwmon_dir.iterdir():
            for tfile in hw.glob('temp*_input'):
                try:
                    raw = tfile.read_text().strip()
                    return float(raw) / 1000.0
                except Exception:
                    continue
    try:
        out = subprocess.check_output(['sudo', 'smartctl', '-A', '/dev/sda'],
            stderr=subprocess.DEVNULL, timeout=5).decode()
        for line in out.splitlines():
            if 'Temperature' in line or 'Temp' in line:
                parts = line.split()
                for p in parts:
                    if p.isdigit():
                        return float(p)
    except Exception:
        pass
    return None


def _get_system_metrics():
    metrics = {}
    try:
        metrics['cpu_pct'] = psutil.cpu_percent(interval=0.3)
        metrics['ram_pct'] = psutil.virtual_memory().percent
    except Exception:
        metrics['cpu_pct'] = None
        metrics['ram_pct'] = None
    
    metrics['ssd_temp'] = _get_ssd_temp()
    
    try:
        usage = psutil.disk_usage('/mnt/bitcoin')
        metrics['disk_free'] = usage.free / (1024**3)
        metrics['disk_total'] = usage.total / (1024**3)
        metrics['disk_pct'] = usage.percent
    except Exception:
        metrics['disk_free'] = None
        metrics['disk_total'] = None
        metrics['disk_pct'] = None
    
    return metrics


def _check_active_alerts(metrics):
    active_alerts = []
    if metrics.get('cpu_pct') and metrics['cpu_pct'] > 90:
        active_alerts.append(('CPU', f"high load: {metrics['cpu_pct']:.1f}%"))
    if metrics.get('ram_pct') and metrics['ram_pct'] > 90:
        active_alerts.append(('RAM', f"high usage: {metrics['ram_pct']:.1f}%"))
    if metrics.get('ssd_temp') and metrics['ssd_temp'] > 65:
        active_alerts.append(('SSD', f"temperature high: {metrics['ssd_temp']:.1f}°C"))
    if metrics.get('disk_pct') and metrics['disk_pct'] > 90:
        active_alerts.append(('Disk', f"space low: {metrics['disk_pct']:.1f}%"))
    return active_alerts


def build_status_text(*_args, **_kwargs):
    base_dir = Path(__file__).resolve().parent
    log_file = base_dir / 'monitor.log'
    lines = ['📊 *Bitnode Status*', '']

    # Heights
    any_line, num_line = _extract_last_heights_lines(log_file)
    if num_line:
        _, height_line = _strip_prefix(num_line)
    elif any_line:
        _, height_line = _strip_prefix(any_line)
    else:
        height_line = 'Heights: (no data yet)'
    lines.append(f'⛓ {height_line}')
    lines.append('')

    # Datum status
    datum_active = _get_datum_status()
    if datum_active is True:
        lines.append('✅ Datum: Active')
    elif datum_active is False:
        lines.append('❌ Datum: Inactive')
    else:
        lines.append('⚠️ Datum: Unknown')
    lines.append('')

    # System metrics
    metrics = _get_system_metrics()
    lines.append('💻 *System Metrics:*')
    
    if metrics['cpu_pct'] is not None:
        cpu_emoji = '🔥' if metrics['cpu_pct'] > 90 else '⚠️' if metrics['cpu_pct'] > 70 else '✅'
        lines.append(f"{cpu_emoji} CPU: {metrics['cpu_pct']:.1f}%")
    
    if metrics['ram_pct'] is not None:
        ram_emoji = '🔥' if metrics['ram_pct'] > 90 else '⚠️' if metrics['ram_pct'] > 70 else '✅'
        lines.append(f"{ram_emoji} RAM: {metrics['ram_pct']:.1f}%")
    
    if metrics['ssd_temp'] is not None:
        temp_emoji = '🔥' if metrics['ssd_temp'] > 65 else '⚠️' if metrics['ssd_temp'] > 55 else '✅'
        lines.append(f"{temp_emoji} SSD: {metrics['ssd_temp']:.1f}°C")
    
    if metrics['disk_free'] is not None and metrics['disk_total'] is not None:
        disk_emoji = '🔥' if metrics['disk_pct'] > 90 else '⚠️' if metrics['disk_pct'] > 80 else '✅'
        lines.append(f"{disk_emoji} Disk: {metrics['disk_free']:.0f}GB free / {metrics['disk_total']:.0f}GB ({metrics['disk_pct']:.1f}% used)")
    
    # Alerts
    active_alerts = _check_active_alerts(metrics)
    past_alerts = _extract_alert_lines(log_file, max_lines=5)
    
    if active_alerts:
        lines.append('')
        lines.append('🚨 *ACTIVE ALERTS:*')
        for name, msg in active_alerts:
            lines.append(f'  • {name}: {msg}')
    
    if past_alerts and not active_alerts:
        lines.append('')
        lines.append('📋 *Recent Alerts (resolved):*')
        for ts, alert_text in past_alerts[-3:]:
            alert_msg = alert_text.replace('[ALERT]', '').strip()
            time_only = ts.split()[1] if len(ts.split()) > 1 else ts
            lines.append(f'  • {time_only}: {alert_msg}')

    return '\n'.join(lines)
