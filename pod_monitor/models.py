from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from enum import Enum

class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class LogLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"
    DEBUG = "debug"

@dataclass
class LogEntry:
    timestamp: datetime
    level: LogLevel
    message: str
    pod_ip: str
    pod_name: Optional[str] = None
    source: Optional[str] = None

@dataclass
class Anomaly:
    id: str
    timestamp: datetime
    severity: Severity
    description: str
    pod_ip: str
    pod_name: Optional[str] = None
    log_context: List[str] = field(default_factory=list)
    suggestion: str = ""
    detected_by: str = "ai"  # "ai" or "rule"

@dataclass
class PodMetrics:
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    memory_limit: float = 100.0
    cpu_limit: float = 100.0
    error_rate: float = 0.0
    request_rate: float = 0.0
    active_connections: int = 0
    uptime: float = 0.0

@dataclass
class PodStatus:
    ip: str
    name: str
    namespace: str = "default"
    healthy: bool = True
    last_check: datetime = field(default_factory=datetime.now)
    logs: List[LogEntry] = field(default_factory=list)
    anomalies: List[Anomaly] = field(default_factory=list)
    metrics: PodMetrics = field(default_factory=PodMetrics)
    error_count: int = 0
    total_logs: int = 0

@dataclass
class Config:
    ssh_user: str = "root"
    ssh_password: Optional[str] = None
    ssh_key_path: Optional[str] = None
    ssh_port: int = 22
    pods: List[str] = field(default_factory=list)
    ai_enabled: bool = True
    openai_token: Optional[str] = None
    ollama_url: Optional[str] = None
    log_lines_to_fetch: int = 100
    refresh_interval: int = 10
    anomaly_threshold: int = 3