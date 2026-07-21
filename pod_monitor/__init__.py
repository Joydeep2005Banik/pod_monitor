"""
Pod Monitor - AI-Powered CLI Monitoring Tool for Kubernetes
"""

__version__ = "1.0.0"
__author__ = "Pod Monitor Team"
__description__ = "Real-time pod monitoring with AI-powered anomaly detection"

from .monitor import PodMonitor
from .ui import PodMonitorUI
from .config import load_config, Config
from .models import (
    PodStatus, 
    Anomaly, 
    LogEntry, 
    Severity,
    LogLevel,
    PodMetrics
)

__all__ = [
    "PodMonitor",
    "PodMonitorUI", 
    "load_config",
    "Config",
    "PodStatus",
    "Anomaly",
    "LogEntry",
    "Severity",
    "LogLevel",
    "PodMetrics",
]

# Default configuration
DEFAULT_CONFIG = "config.yaml"