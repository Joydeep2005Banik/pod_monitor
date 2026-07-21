"""
Utility functions for Pod Monitor.
"""

import re
import json
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import hashlib

from .models import LogEntry, LogLevel, Anomaly, Severity

def generate_id() -> str:
    """Generate a unique ID."""
    return str(uuid.uuid4())[:8]

def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Parse timestamp from various formats.
    
    Supported formats:
    - 2024-01-15T14:30:25Z
    - 2024-01-15 14:30:25
    - Jan 15 14:30:25
    - 14:30:25
    """
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%b %d %H:%M:%S",
        "%b %d %H:%M:%S.%f",
        "%H:%M:%S",
        "%H:%M:%S.%f",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    
    # Try to extract timestamp with regex
    time_match = re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}', timestamp_str)
    if time_match:
        try:
            return datetime.fromisoformat(time_match.group())
        except ValueError:
            pass
    
    return None

def detect_log_level(message: str) -> LogLevel:
    """Detect log level from message content."""
    message_upper = message.upper()
    
    if "CRITICAL" in message_upper or "FATAL" in message_upper:
        return LogLevel.CRITICAL
    elif "ERROR" in message_upper or "ERR" in message_upper:
        return LogLevel.ERROR
    elif "WARN" in message_upper or "WARNING" in message_upper:
        return LogLevel.WARNING
    elif "DEBUG" in message_upper:
        return LogLevel.DEBUG
    else:
        return LogLevel.INFO

def detect_severity(level: LogLevel) -> Severity:
    """Map log level to severity."""
    severity_map = {
        LogLevel.CRITICAL: Severity.CRITICAL,
        LogLevel.ERROR: Severity.HIGH,
        LogLevel.WARNING: Severity.MEDIUM,
        LogLevel.INFO: Severity.LOW,
        LogLevel.DEBUG: Severity.LOW,
    }
    return severity_map.get(level, Severity.LOW)

def calculate_error_rate(logs: List[LogEntry]) -> float:
    """Calculate error rate as percentage."""
    if not logs:
        return 0.0
    
    error_count = sum(1 for log in logs if log.level in (LogLevel.ERROR, LogLevel.CRITICAL))
    return (error_count / len(logs)) * 100

def calculate_health_score(pod_status) -> int:
    """
    Calculate health score (0-100) for a pod.
    Higher is healthier.
    """
    if not pod_status:
        return 0
    
    score = 100
    
    # Deduct for errors
    score -= pod_status.error_count * 5
    score -= len(pod_status.anomalies) * 10
    
    # Deduct for resource usage
    score -= pod_status.metrics.cpu_usage * 0.2
    score -= pod_status.metrics.memory_usage * 0.1
    
    # Deduct for error rate
    error_rate = calculate_error_rate(pod_status.logs)
    score -= error_rate * 2
    
    # Ensure score is between 0 and 100
    return max(0, min(100, int(score)))

def get_severity_color(severity: Severity) -> str:
    """Get color code for severity level."""
    colors = {
        Severity.CRITICAL: "#ff0000",
        Severity.HIGH: "#ff6b00",
        Severity.MEDIUM: "#ffd700",
        Severity.LOW: "#00bfff",
    }
    return colors.get(severity, "#ffffff")

def get_log_level_tag(level: LogLevel) -> str:
    """Get ASCII tag for log level."""
    tags = {
        LogLevel.CRITICAL: "[CRIT]",
        LogLevel.ERROR: "[ERR]",
        LogLevel.WARNING: "[WARN]",
        LogLevel.INFO: "[INFO]",
        LogLevel.DEBUG: "[DBG]",
    }
    return tags.get(level, "[INFO]")

def truncate_message(message: str, max_length: int = 200) -> str:
    """Truncate a message if it's too long."""
    if len(message) <= max_length:
        return message
    return message[:max_length] + "..."

def extract_keywords(text: str, max_keywords: int = 5) -> List[str]:
    """Extract important keywords from text."""
    # Remove common words
    stop_words = {'the', 'a', 'an', 'of', 'for', 'on', 'at', 'to', 'in', 'and', 'or', 'but'}
    
    # Split and clean
    words = re.findall(r'\b[a-zA-Z]\w+\b', text.lower())
    
    # Count occurrences
    word_count = {}
    for word in words:
        if word not in stop_words and len(word) > 2:
            word_count[word] = word_count.get(word, 0) + 1
    
    # Sort by frequency
    sorted_words = sorted(word_count.items(), key=lambda x: x[1], reverse=True)
    
    return [word for word, _ in sorted_words[:max_keywords]]

def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"

def calculate_percentile(data: List[float], percentile: float) -> float:
    """Calculate percentile of a list of numbers."""
    if not data:
        return 0.0
    
    sorted_data = sorted(data)
    index = (percentile / 100) * (len(sorted_data) - 1)
    
    if index.is_integer():
        return sorted_data[int(index)]
    else:
        lower = sorted_data[int(index)]
        upper = sorted_data[int(index) + 1]
        fraction = index - int(index)
        return lower + (upper - lower) * fraction

def generate_report(pod_statuses: List, format: str = "text") -> str:
    """Generate a report from pod statuses."""
    if format == "json":
        return json.dumps([ps.__dict__ for ps in pod_statuses], default=str, indent=2)
    
    # Text format
    report = "=" * 60 + "\n"
    report += "POD MONITOR REPORT\n"
    report += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    report += "=" * 60 + "\n\n"
    
    for ps in pod_statuses:
        report += f"Pod: {ps.name} ({ps.ip})\n"
        report += f"Status: {'[HEALTHY]' if ps.healthy else '[UNHEALTHY]'}\n"
        report += f"Errors: {ps.error_count}\n"
        report += f"Anomalies: {len(ps.anomalies)}\n"
        report += f"CPU: {ps.metrics.cpu_usage:.1f}%\n"
        report += f"Memory: {ps.metrics.memory_usage:.1f} MiB\n"
        report += f"Health Score: {calculate_health_score(ps)}/100\n"
        report += "-" * 40 + "\n"
    
    return report

def cache_file_path(cache_dir: str, key: str) -> Path:
    """Get cache file path for a key."""
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    
    # Create hash of key
    key_hash = hashlib.md5(key.encode()).hexdigest()
    return cache_path / f"{key_hash}.cache"

def load_from_cache(cache_dir: str, key: str, max_age: int = 300) -> Optional[Any]:
    """Load data from cache if not expired."""
    cache_path = cache_file_path(cache_dir, key)
    
    if not cache_path.exists():
        return None
    
    # Check age
    age = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).seconds
    if age > max_age:
        return None
    
    try:
        with open(cache_path, 'r') as f:
            return json.load(f)
    except:
        return None

def save_to_cache(cache_dir: str, key: str, data: Any):
    """Save data to cache."""
    cache_path = cache_file_path(cache_dir, key)
    
    try:
        with open(cache_path, 'w') as f:
            json.dump(data, f, default=str)
    except:
        pass

def validate_ip(ip: str) -> bool:
    """Validate IP address format."""
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    
    parts = ip.split('.')
    for part in parts:
        if not 0 <= int(part) <= 255:
            return False
    
    return True

def validate_pod_name(name: str) -> bool:
    """Validate Kubernetes pod name format."""
    pattern = r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?$'
    return bool(re.match(pattern, name.lower()))